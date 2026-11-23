"""An OpenAI-compatible endpoint on the user's own machine: `legal-router serve`.

Send `model: "legal-router/auto"` (or `legal-router/best` to skip the cheaper tiers). To send an
answer back, repeat the conversation with the lawyer's comment as the last user message and add
`"legal_router": {"sent_back": true}`; the work goes to the escalation model. The response headers
name the model that did the work.
"""
import json

import httpx
from fastapi import FastAPI, Request
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response, StreamingResponse

from .core import MODELS, OPENROUTER, RouterError, api_key, classify, request_body, resolve_classifier, route

MAX_BODY = 4 * 1024 * 1024


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "legal_router_error"}}, status)


def create_app(client: httpx.AsyncClient | None = None, key: str | None = None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    upstream = client or httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10))

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "legal-router"} for m in MODELS]}

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return error(413, "Request is larger than 4 MiB")
        try:
            body = json.loads(raw)
        except ValueError:
            return error(400, "Expected a JSON request")
        if not isinstance(body, dict) or body.get("model") not in MODELS or not isinstance(body.get("messages"), list):
            return error(400, f"Send `model` as one of {', '.join(MODELS)} and a `messages` list")
        ours = body.pop("legal_router", None) or {}
        sent_back = bool(ours.get("sent_back")) if isinstance(ours, dict) else False
        best = body.pop("model") == "legal-router/best"
        messages = body.pop("messages")
        try:
            token = api_key(key)
        except RouterError as e:
            return error(401, str(e))
        try:
            resolve_classifier()
        except RouterError as e:
            return error(500, str(e))
        work = None if sent_back else await run_in_threadpool(classify, messages, key=token)
        r = route(work, sent_back=sent_back, best=best)
        headers = {"X-Legal-Router-Model": r.model, "X-Legal-Router-Pick": r.pick, "X-Legal-Router-Line": r.line,
                   "Cache-Control": "no-store"}
        if r.reason:
            headers["X-Legal-Router-Reason"] = r.reason
        if work:
            headers["X-Legal-Router-Classifier"] = work.classifier
        req = upstream.build_request("POST", f"{OPENROUTER}/v1/chat/completions", json=request_body(messages, r, body),
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            resp = await upstream.send(req, stream=True)
        except httpx.HTTPError as e:
            return error(502, f"Could not reach OpenRouter: {type(e).__name__}")
        if resp.status_code != 200 or not body.get("stream"):
            content = await resp.aread()
            await resp.aclose()
            return Response(content, resp.status_code, media_type="application/json", headers=headers)
        return StreamingResponse(resp.aiter_bytes(), media_type="text/event-stream", headers=headers,
                                 background=BackgroundTask(resp.aclose))

    return app
