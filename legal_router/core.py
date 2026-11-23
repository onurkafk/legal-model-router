"""Legal Model Router: read a legal request, pick the model, call it. One OpenRouter key.

    classify(request)  -> Work     what the work is (one decision-model call, about $0.0001)
    route(work)        -> Route    which model does it, from the Vals Legal Index table
    complete(messages) -> answer   both, then the call to that model

Every OpenRouter call, the classifier's included, is restricted to zero-data-retention
endpoints and denies prompt collection. The routing table and questions ship inside the package
(legal_router/data/), generated from config/ by scripts/build_routing_table.py.
"""
import json
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import httpx

OPENROUTER = "https://openrouter.ai/api"
# Zero data retention on every call; no prompt collection.
ZDR = {"zdr": True, "data_collection": "deny"}
# The worker call also refuses silent parameter dropping and provider fallback, so the model is
# called exactly the way its benchmark score was earned.
WORKER_PROVIDER = {**ZDR, "require_parameters": True, "allow_fallbacks": False}
MODELS = ("legal-router/auto", "legal-router/best")
CONFIG = Path.home() / ".legal-router" / "config.json"
# The classifier sees this much of each end of a long request; the worker always gets all of it.
# Measured on long requests: the instruction is at one end, the middle is the pasted document.
ENVELOPE_CHARS = 4000

DATA = files("legal_router").joinpath("data")
TABLE: dict = json.loads(DATA.joinpath("routing-table.json").read_text())
QUESTIONS: dict = json.loads(DATA.joinpath("questions.json").read_text())["questions"]
CLASSIFIERS: dict[str, str] = TABLE["classifiers"]          # short name -> OpenRouter id
DEFAULT_CLASSIFIER: str = TABLE["default_classifier"]


class RouterError(Exception):
    pass


def _saved() -> dict:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def api_key(key: str | None = None) -> str:
    """The OpenRouter key: argument, then OPENROUTER_API_KEY, then `legal-router init`'s file."""
    key = key or os.environ.get("OPENROUTER_API_KEY") or _saved().get("openrouter_api_key")
    if not key:
        raise RouterError("No OpenRouter key. Run `legal-router init` or set OPENROUTER_API_KEY.")
    return key


def resolve_classifier(name: str | None = None) -> str:
    """The decision model's short name: argument, then LEGAL_ROUTER_CLASSIFIER, then the saved choice, then
    the default. Only measured models are accepted (see config/routing-policy.yaml)."""
    env = os.environ.get("LEGAL_ROUTER_CLASSIFIER", "")
    env = "" if env.startswith("${") else env     # a plugin setting left empty arrives unexpanded
    name = name or env or _saved().get("classifier") or DEFAULT_CLASSIFIER
    if name not in CLASSIFIERS:
        raise RouterError(f"Unknown decision model {name!r}. Choose one of: {', '.join(CLASSIFIERS)}.")
    return name


def save_config(**values: str) -> Path:
    """Write the key and/or decision model to ~/.legal-router/config.json, readable only by the user."""
    config = {**_saved(), **{k: v for k, v in values.items() if v}}
    CONFIG.parent.mkdir(mode=0o700, exist_ok=True)
    CONFIG.touch(mode=0o600, exist_ok=True)
    CONFIG.chmod(0o600)
    CONFIG.write_text(json.dumps(config))
    return CONFIG


def as_messages(request: str | list[dict]) -> list[dict]:
    return [{"role": "user", "content": request}] if isinstance(request, str) else request


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def envelope(text: str, side: int = ENVELOPE_CHARS) -> str:
    if len(text) <= 2 * side + 200:
        return text
    return (text[:side] + f"\n\n[... {len(text) - 2 * side:,} characters of the request omitted ...]\n\n"
            + text[-side:])


def state(messages: list[dict]) -> dict:
    """What the classifier is shown: the user's own words, in order, both ends of a long request."""
    turns = [t for t in (_text(m.get("content")) for m in messages if m.get("role") == "user") if t]
    return {"instructions": envelope("\n\n".join(turns))}


@dataclass(frozen=True)
class Work:
    """What the request is, as the decision model read it."""
    work_type: str                 # research_or_advice | new_drafting | document_work | not_legal_work
    work_type_probabilities: dict
    standard_form: float           # P(the draft is a standard form); read only for new drafting
    section: str                   # finer kind of work: data_extraction, translation, contract_work, ...
    section_confidence: float
    practice_area: str
    line: str                      # the Vals Legal Index line the practice area belongs to
    classifier: str = DEFAULT_CLASSIFIER   # the decision model that read it

    def p(self, option: str) -> float:
        return self.work_type_probabilities.get(option, 0.0)


@dataclass(frozen=True)
class Route:
    model: str                     # the OpenRouter id that does the work
    effort: str | None             # the reasoning effort its Vals score was earned at
    pick: str                      # best | efficient | economy | escalated
    line: str
    why: str
    work: Work | None = field(default=None, compare=False)
    reason: str = ""               # the rule's one-line reason, for footers and headers

    def public(self) -> dict:
        return {"model": self.model, "pick": self.pick, "line": self.line, "reason": self.reason, "why": self.why,
                "classifier": self.work.classifier if self.work else None}


def classify(request: str | list[dict], *, classifier: str | None = None, key: str | None = None,
             client: httpx.Client | None = None) -> Work | None:
    """One decision-model call. None if it cannot answer; the router then takes the safe route."""
    name = resolve_classifier(classifier)
    body = {"model": CLASSIFIERS[name], "state": state(as_messages(request)), "questions": QUESTIONS, "provider": ZDR}
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10))
    try:
        r = client.post(f"{OPENROUTER}/alpha/decisions", json=body,
                        headers={"Authorization": f"Bearer {api_key(key)}"})
        if r.status_code != 200:
            return None
        a = r.json()["answers"]
        top = lambda q: (a[q]["choice"], float(a[q]["probabilities"].get(a[q]["choice"], 0.0)))  # noqa: E731
        section, section_p = top("section")
        area = a["practice_area"]["choice"]
        return Work(work_type=a["work_type"]["choice"], work_type_probabilities=a["work_type"]["probabilities"],
                    standard_form=float(a["drafting_complexity"]["probabilities"].get("standard_form", 0.0)),
                    section=section, section_confidence=section_p, practice_area=area,
                    line=TABLE["line_of_practice_area"].get(area, "overall"), classifier=name)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return None
    finally:
        if own:
            client.close()


def _holds(cond: dict, work: Work | None, sent_back: bool) -> bool:
    for k, v in cond.items():
        if k == "sent_back":
            ok = sent_back == v
        elif k == "classifier":
            ok = (work is None) == (v == "unavailable")
        elif work is None:
            return False
        elif k == "section_confidence_below":
            ok = work.section_confidence < v
        elif k == "work_type":
            ok = work.work_type == v
        elif k == "research_or_drafting_at_least":
            ok = work.p("research_or_advice") + work.p("new_drafting") >= v
        elif k == "section":
            ok = work.section in (v if isinstance(v, list) else [v])
        elif k == "drafting_complexity":
            ok = v == "standard_form" and work.standard_form >= cond["probability_at_least"]
        elif k == "probability_at_least":
            continue
        else:
            raise RouterError(f"unknown rule condition {k!r} in the routing table")
        if not ok:
            return False
    return True


def route(work: Work | None, *, sent_back: bool = False, best: bool = False, table: dict = TABLE) -> Route:
    """The first rule in the table that matches picks the tier; the request's line picks the model."""
    for rule in table["rules"]:
        if _holds(rule["when"], work, sent_back) and not (rule.get("unless") and _holds(rule["unless"], work, sent_back)):
            pick = rule["pick"]
            if best and pick in ("efficient", "economy"):
                pick = "best"
            line = rule.get("row") or (work.line if work else "overall")
            chosen = table["rows"][line][pick]["model"]
            return Route(model=chosen, effort=table["models"][chosen]["effort"], pick=pick, line=line,
                         why=rule["why"], work=work, reason=rule.get("short", ""))
    raise RouterError("no routing rule matched; the table must end with a catch-all rule")


def check_table(table: dict = TABLE) -> None:
    """Fail at import, not on a live request, if the table names a condition this code cannot read."""
    probe = Work("document_work", {"document_work": 1.0}, 0.0, "other", 1.0, "other", "overall")
    for rule in table["rules"]:
        for cond in (rule["when"], rule.get("unless") or {}):
            _holds(cond, probe, False)
    if table["rules"][-1]["when"]:
        raise RouterError("the last rule must be the catch-all")


check_table()


def request_body(messages: list[dict], r: Route, params: dict) -> dict:
    """The caller's request, unchanged except for the model, its benchmarked effort and ZDR."""
    body = {**params, "messages": messages, "model": r.model, "provider": WORKER_PROVIDER}
    if r.effort:
        body["reasoning"] = {"effort": r.effort}
    return body


def complete(request: str | list[dict], *, sent_back: bool = False, best: bool = False,
             classifier: str | None = None, key: str | None = None, **params) -> tuple[dict, Route]:
    """Classify, route and call. Returns OpenRouter's chat-completion response and the route taken.

    A send-back goes to the escalation model whatever the work is, so it is not classified again.
    """
    messages = as_messages(request)
    with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as client:
        work = None if sent_back else classify(messages, classifier=classifier, key=key, client=client)
        r = route(work, sent_back=sent_back, best=best)
        body = request_body(messages, r, params)
        for attempt in range(2):     # one retry, only for an empty reply that used no tokens (a provider hiccup)
            resp = client.post(f"{OPENROUTER}/v1/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {api_key(key)}"})
            if resp.status_code != 200:
                raise RouterError(f"OpenRouter refused the call to {r.model} ({resp.status_code}): {resp.text[:300]}")
            out = resp.json()
            if answer_text(out) or (out.get("usage") or {}).get("completion_tokens"):
                break
    check_answer(out, r)
    return out, r


def answer_text(resp: dict) -> str:
    return ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def check_answer(resp: dict, r: Route) -> None:
    """An empty answer is an error, never a result: say why instead of handing back nothing."""
    if answer_text(resp):
        return
    choice = (resp.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise RouterError(f"{r.model} spent its whole output budget reasoning (effort {r.effort}) and wrote no "
                          "answer. Raise max_tokens or leave it unset.")
    raise RouterError(f"{r.model} returned an empty answer (finish reason {choice.get('finish_reason')!r}). "
                      "Try again; the provider may be busy.")
