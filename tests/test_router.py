"""Legal Model Router package: routing rules, ZDR on every call, server, MCP. Offline."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from legal_router import core
from legal_router.core import Work, classify, route
from legal_router.mcp import handle
from legal_router.server import create_app

T = core.TABLE


def work(work_type="document_work", p=None, standard=0.0, section="document_review", conf=0.95,
         area="corporate_ma"):
    return Work(work_type, p or {work_type: 1.0}, standard, section, conf, area,
                T["line_of_practice_area"][area])


def test_sent_back_goes_to_opus_5_5():
    assert route(work(), sent_back=True).model == "anthropic/claude-opus-5.5"
    assert route(None, sent_back=True).model == "anthropic/claude-opus-5.5"


def test_classifier_down_or_unsure_takes_the_overall_best():
    for r in (route(None), route(work(conf=0.5))):
        assert (r.pick, r.line) == ("best", "overall") and r.model == "google/gemini-4-neon"


def test_bespoke_drafting_goes_to_opus_and_standard_forms_do_not():
    bespoke = work("new_drafting", {"new_drafting": 0.9}, standard=0.1, section="contract_work")
    standard = work("new_drafting", {"new_drafting": 0.9}, standard=0.9, section="contract_work")
    assert route(bespoke).model == "anthropic/claude-opus-5.5"
    assert route(standard).pick == "efficient"


def test_research_goes_to_best_on_its_line_even_when_not_the_top_answer():
    r = route(work("document_work", {"document_work": 0.6, "research_or_advice": 0.35}, area="real_estate"))
    assert (r.pick, r.line) == ("best", "real_estate") and r.model == T["rows"]["real_estate"]["best"]["model"]


def test_extraction_is_economy_and_best_lifts_it():
    w = work(section="data_extraction", area="employment_labor")
    assert route(w).pick == "economy"
    assert route(w, best=True).pick == "best"


def test_admin_is_economy_on_the_overall_row():
    r = route(work("not_legal_work", section="other"))
    assert (r.pick, r.line) == ("economy", "overall")


def test_unknown_rule_condition_fails_loudly():
    bad = {**T, "rules": [{"when": {"mood": "happy"}, "pick": "best", "why": ""}]}
    with pytest.raises(core.RouterError):
        route(work(), table=bad)


def fake_openrouter(seen):
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((req.url.path, body))
        if req.url.path.endswith("/alpha/decisions"):
            a = {q: {"choice": next(iter(v["criteria"])), "probabilities": {next(iter(v["criteria"])): 1.0}}
                 for q, v in body["questions"].items()}
            a["work_type"] = {"choice": "research_or_advice", "probabilities": {"research_or_advice": 0.9}}
            a["section"] = {"choice": "legal_research", "probabilities": {"legal_research": 0.9}}
            a["practice_area"] = {"choice": "employment_labor", "probabilities": {"employment_labor": 0.9}}
            return httpx.Response(200, json={"answers": a})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
    return handler


def test_classify_sends_zdr_and_reads_the_answers():
    seen = []
    with httpx.Client(transport=httpx.MockTransport(fake_openrouter(seen))) as c:
        w = classify("Is this non-compete enforceable?", key="k", client=c)
    assert w.work_type == "research_or_advice" and w.line == "labor_employment"
    assert seen[0][1]["provider"]["zdr"] is True and seen[0][1]["provider"]["data_collection"] == "deny"
    assert seen[0][1]["model"] == core.CLASSIFIERS[core.DEFAULT_CLASSIFIER] and w.classifier == core.DEFAULT_CLASSIFIER


def test_classifier_failure_is_none_not_an_exception():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as c:
        assert classify("x", key="k", client=c) is None


def test_server_forwards_with_zdr_effort_and_names_the_model(monkeypatch):
    seen = []
    real = httpx.Client
    monkeypatch.setattr(core.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake_openrouter(seen))))
    app = create_app(client=httpx.AsyncClient(transport=httpx.MockTransport(fake_openrouter(seen))), key="k")
    r = TestClient(app).post("/v1/chat/completions", json={
        "model": "legal-router/auto", "messages": [{"role": "user", "content": "Is this enforceable?"}], "temperature": 0.2})
    assert r.status_code == 200 and r.headers["X-Legal-Router-Pick"] == "best"
    path, sent = seen[-1]
    assert path.endswith("/v1/chat/completions")
    assert sent["provider"] == core.WORKER_PROVIDER and sent["provider"]["zdr"] is True
    assert sent["model"] == r.headers["X-Legal-Router-Model"] and sent["temperature"] == 0.2
    assert "legal_router" not in sent


def test_server_send_back_skips_the_classifier():
    seen = []
    app = create_app(client=httpx.AsyncClient(transport=httpx.MockTransport(fake_openrouter(seen))), key="k")
    r = TestClient(app).post("/v1/chat/completions", json={
        "model": "legal-router/auto", "legal_router": {"sent_back": True},
        "messages": [{"role": "user", "content": "draft it"}, {"role": "user", "content": "not good enough"}]})
    assert r.headers["X-Legal-Router-Model"] == "anthropic/claude-opus-5.5"
    assert [p for p, _ in seen] == ["/api/v1/chat/completions"]


def test_server_refuses_other_model_names():
    app = create_app(client=httpx.AsyncClient(transport=httpx.MockTransport(fake_openrouter([]))), key="k")
    assert TestClient(app).post("/v1/chat/completions", json={"model": "gpt-4", "messages": []}).status_code == 400


def test_mcp_lists_one_tool_and_answers_initialize():
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["legal_router"]
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_package_ships_the_current_table_and_questions():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert core.TABLE == json.loads((root / "config/routing-table.json").read_text())
    assert core.QUESTIONS == json.loads((root / "config/questions.json").read_text())["questions"]
    assert (root / "skills/legal-router/SKILL.md").read_text() == (root / "legal_router/skill.md").read_text()


def test_standard_form_score_does_not_demote_research():
    """drafting_complexity is asked on every request; it may only matter for new drafting."""
    w = work("research_or_advice", {"research_or_advice": 0.9}, standard=0.95, section="legal_research")
    assert route(w).pick == "best"
