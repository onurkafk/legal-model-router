"""`legal-router mcp`: the router as one MCP tool over stdio, for Claude Code and other MCP clients.

No MCP library: the protocol needed here is three JSON-RPC methods (initialize, tools/list,
tools/call), newline-delimited on stdin/stdout.
"""
import json
import sys

from .core import RouterError, complete

TOOL = {
    "name": "legal_router",
    "description": (
        "Do a piece of legal work on the model best suited to it, chosen by the Legal Model Router from the Vals "
        "Legal Index: legal research and advice, drafting (contracts, letters, filings), and work on documents "
        "(review, markup, extraction, summary, translation). Put the whole task in `task`, including any text the "
        "work is on. Show the answer to the user as returned. If the user says the answer is not good enough, "
        "call again with the same task, sent_back=true and their comment."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The legal task, with all the text it needs."},
            "sent_back": {"type": "boolean", "description": "True when the user rejected the previous answer."},
            "comment": {"type": "string", "description": "What the user said was wrong, on a send-back."},
            "best": {"type": "boolean", "description": "True to skip the cheaper tiers."},
        },
        "required": ["task"],
    },
}


def run_tool(args: dict) -> str:
    messages = [{"role": "user", "content": args["task"]}]
    if args.get("sent_back") and args.get("comment"):
        messages.append({"role": "user", "content": "The previous answer was not good enough: " + args["comment"]})
    resp, r = complete(messages, sent_back=bool(args.get("sent_back")), best=bool(args.get("best")))
    answer = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return (f"{answer}\n\n— Legal Model Router: {r.model} ({r.pick}, {r.line.replace('_', ' ')}). "
            f"Why: {r.reason or r.why}")


def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                      # a notification: nothing to answer
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "legal-router", "version": "0.3.0"}}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}}
        try:
            result = {"content": [{"type": "text", "text": run_tool(params.get("arguments") or {})}]}
        except (RouterError, KeyError) as e:
            result = {"content": [{"type": "text", "text": f"Legal Model Router: {e}"}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
