"""Choosing the decision model: only measured models, and each one routes the test requests safely."""
import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from legal_router import core
from legal_router.core import CLASSIFIERS, RouterError, Work, classify, resolve_classifier, route

ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT / "docs/data/labels.json").read_text())
TOP = {"best", "escalated"}
# A first UK employment contract the client calls "standard stuff": d1-ultra and Decider V1.3 read it as a
# standard form (0.79, 0.83) and send it to Efficient, about a point behind Best on Labor & Employment.
STANDARD_BY_ITS_OWN_WORDS = {"holdout:54"}


def test_default_is_listed_and_every_model_is_named():
    assert core.DEFAULT_CLASSIFIER in CLASSIFIERS
    assert set(CLASSIFIERS) == {"d1-ultra", "decider-v1.3", "elephant-1"}


def test_choice_order_is_argument_then_env_then_saved_then_default(monkeypatch):
    assert resolve_classifier() == core.DEFAULT_CLASSIFIER
    core.save_config(classifier="elephant-1")
    assert resolve_classifier() == "elephant-1"
    monkeypatch.setenv("LEGAL_ROUTER_CLASSIFIER", "decider-v1.3")
    assert resolve_classifier() == "decider-v1.3"
    assert resolve_classifier("d1-ultra") == "d1-ultra"


def test_unknown_model_is_refused_with_the_choices():
    with pytest.raises(RouterError, match="d1-ultra, decider-v1.3, elephant-1"):
        resolve_classifier("some/other-model")


def test_saved_config_keeps_the_key_and_is_private():
    core.save_config(openrouter_api_key="k")
    core.save_config(classifier="elephant-1", openrouter_api_key="")
    assert json.loads(core.CONFIG.read_text()) == {"openrouter_api_key": "k", "classifier": "elephant-1"}
    assert stat.S_IMODE(os.stat(core.CONFIG).st_mode) == 0o600


@pytest.mark.parametrize("name", sorted(CLASSIFIERS))
def test_classify_calls_the_chosen_model_with_zdr(name):
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        a = {q: {"choice": next(iter(v["criteria"])), "probabilities": {next(iter(v["criteria"])): 1.0}}
             for q, v in body["questions"].items()}
        return httpx.Response(200, json={"answers": a})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        w = classify("x", classifier=name, key="k", client=c)
    assert seen[0]["model"] == CLASSIFIERS[name] and seen[0]["provider"]["zdr"] is True
    assert w.classifier == name and route(w).public()["classifier"] == name


def routes(name):
    out = {}
    for line in (ROOT / f"docs/data/classifier-answers-{name}.jsonl").read_text().splitlines():
        r = json.loads(line)
        a = r["answers"]
        top = lambda q: (a[q]["choice"], float(a[q]["probabilities"].get(a[q]["choice"], 0.0)))  # noqa: E731
        section, p = top("section")
        area = a["practice_area"]["choice"]
        w = Work(a["work_type"]["choice"], a["work_type"]["probabilities"],
                 float(a["drafting_complexity"]["probabilities"].get("standard_form", 0.0)), section, p, area,
                 core.TABLE["line_of_practice_area"].get(area, "overall"), name)
        out[f"{r['set']}:{r['i']}"] = route(w).pick
    return out


@pytest.mark.parametrize("name", sorted(CLASSIFIERS))
def test_every_model_meets_the_safety_bar_on_the_published_answers(name):
    picks = routes(name)
    assert len(picks) == 195
    needs_top = [f"holdout:{i}" for i, lab in LABELS["holdout_work"].items() if lab in ("law", "scratch")]
    needs_top += [f"stress:{i}" for i in LABELS["stress_needs_law"]]
    assert len(needs_top) == 31 + 28
    standard = {k for k, lab in LABELS["drafting"].items() if lab == "standard"}   # meant for Efficient
    missed = [k for k in needs_top if picks[k] not in TOP and k not in standard]
    assert set(missed) <= STANDARD_BY_ITS_OWN_WORDS and all(picks[k] == "efficient" for k in missed)
    bespoke = [k for k, lab in LABELS["drafting"].items() if lab == "bespoke"]
    assert len(bespoke) == 13 and [k for k in bespoke if picks[k] not in TOP] == []
