"""legal-router: init | serve | mcp | route | doctor"""
import argparse
import getpass
import json
import os
import sys

import httpx

from .core import (CLASSIFIERS, DEFAULT_CLASSIFIER, OPENROUTER, TABLE, RouterError, api_key, classify,
                   resolve_classifier, route, save_config)

USAGE = f"""legal-router init               save your OpenRouter key and decision model (~/.legal-router/config.json, yours only)
legal-router serve [--port N]   OpenAI-compatible endpoint at http://127.0.0.1:8404/v1
legal-router mcp                the router as an MCP tool, for any MCP client
legal-router claude             add /legal-router to Claude Code (personal skill + MCP tool)
legal-router route "<task>"     show which model would do a task (one classifier call, ~$0.0001)
legal-router doctor             check the key, the decision model and zero data retention

  --classifier NAME             the decision model for this run: {', '.join(CLASSIFIERS)}"""


def doctor() -> int:
    ok = True
    try:
        key = api_key()
        print("key: found")
    except RouterError as e:
        print(f"key: {e}")
        return 1
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{OPENROUTER}/v1/key", headers={"Authorization": f"Bearer {key}"})
        print(f"key: {'valid' if r.status_code == 200 else f'rejected ({r.status_code})'}")
        ok &= r.status_code == 200
        zdr = c.get(f"{OPENROUTER}/v1/endpoints/zdr").json()
        zdr = {e["model_id"] for e in zdr.get("data", zdr)}
    name = resolve_classifier()
    print(f"decision model: {name} ({CLASSIFIERS[name]})")
    for m in sorted({*TABLE["models"], CLASSIFIERS[name]}):
        has = m in zdr
        ok &= has
        print(f"zero data retention: {'yes' if has else 'NO '}  {m}")
    work = classify("Is a five-year non-compete enforceable in California?", key=key)
    print(f"decision model: {'answers' if work else 'NO ANSWER'}" + (f" ({work.work_type}, {work.line})" if work else ""))
    ok &= work is not None
    print("ready" if ok else "not ready")
    return 0 if ok else 1


def init() -> int:
    key = getpass.getpass("OpenRouter API key (Enter keeps the saved one): ").strip()
    names = ", ".join(CLASSIFIERS)
    name = input(f"Decision model [{DEFAULT_CLASSIFIER}] ({names}): ").strip() or DEFAULT_CLASSIFIER
    path = save_config(openrouter_api_key=key, classifier=resolve_classifier(name))
    print(f"saved to {path}")
    return doctor()


def add_to_claude_code() -> int:
    """A personal skill gives the bare `/legal-router` (plugin skills are namespaced) plus the MCP tool."""
    import shutil
    import subprocess
    from importlib.resources import files
    from pathlib import Path
    if not shutil.which("claude"):
        print("Claude Code (`claude`) is not on PATH")
        return 1
    skill = Path.home() / ".claude" / "skills" / "legal-router" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(files("legal_router").joinpath("skill.md").read_text())
    print(f"skill: {skill}")
    exe = shutil.which("legal-router") or "legal-router"
    r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "legal-router", "--", exe, "mcp"])
    if r.returncode == 0:
        print("Done. In Claude Code: /legal-router <your legal task>")
    return r.returncode


def main() -> None:
    p = argparse.ArgumentParser(prog="legal-router", usage=USAGE)
    p.add_argument("command", choices=["init", "serve", "mcp", "route", "doctor", "claude"])
    p.add_argument("task", nargs="?")
    p.add_argument("--port", type=int, default=8404)
    p.add_argument("--classifier")
    a = p.parse_args()
    try:
        if a.classifier:   # checked here, then read by every part of the router
            os.environ["LEGAL_ROUTER_CLASSIFIER"] = resolve_classifier(a.classifier)
        resolve_classifier()
        run(p, a)
    except RouterError as e:
        p.exit(2, f"legal-router: {e}\n")


def run(p: argparse.ArgumentParser, a: argparse.Namespace) -> None:
    if a.command == "init":
        sys.exit(init())
    if a.command == "doctor":
        sys.exit(doctor())
    if a.command == "claude":
        sys.exit(add_to_claude_code())
    if a.command == "mcp":
        from .mcp import main as mcp
        mcp()
    elif a.command == "serve":
        import uvicorn
        from .server import create_app
        print(f"Legal Model Router on http://127.0.0.1:{a.port}/v1  (models: legal-router/auto, legal-router/best; "
              f"decision model: {resolve_classifier()})")
        uvicorn.run(create_app(), host="127.0.0.1", port=a.port, access_log=False)
    elif a.command == "route":
        if not a.task:
            p.error("route needs a task in quotes")
        work = classify(a.task)
        print(json.dumps({**route(work).public(), "work": work and work.__dict__}, indent=1))
