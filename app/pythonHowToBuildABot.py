# app/pythonHowToBuildABot.py

import os, json, base64
from collections import defaultdict

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn
from starlette.websockets import WebSocketDisconnect, WebSocketState

# Config (use env in prod; hardcode for PoC if needed)
RECALL_REGION = os.getenv("RECALL_REGION", "us-east-1")
API = f"https://{RECALL_REGION}.recall.ai/api/v1"
KEY = os.getenv("RECALL_API_KEY", "MY_BACKUP_HERE")  # for PoC only; use env in prod
NGROK_BASE = os.getenv("NGROK_BASE", "BACKUP_NGROK_URL")
WS_TOKEN = os.getenv("WS_TOKEN", "BACKUP_TOKEN")  # demo only

H = {"Authorization": f"Token {KEY}", "Content-Type": "application/json"}

audio_count = defaultdict(int)
video_count = defaultdict(int)

app = FastAPI()
http: httpx.AsyncClient | None = None

def log(*args):
    print(*args, flush=True)

@app.on_event("startup")
async def _startup():
    global http
    http = httpx.AsyncClient(timeout=30)

@app.on_event("shutdown")
async def _shutdown():
    global http
    if http:
        await http.aclose()
        http = None

def b64_to_bytes(b64: str) -> bytes:
    return base64.b64decode(b64)

# Webhook (transcript + participant events)
@app.post("/wh")
async def wh(req: Request):
    try:
        p = await req.json()
    except Exception:
        raw = await req.body()
        log("[wh] non-JSON payload:", raw[:200])
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)

    ev  = p.get("event") or p.get("type", "")
    dat = p.get("data") or p.get("payload") or {}
    dd  = dat.get("data") or {}

    ts_abs = (dd.get("timestamp") or {}).get("absolute")
    who = None
    if isinstance(dd.get("participant"), dict):
        who = dd["participant"].get("name") or dd["participant"].get("id")

    if ev == "transcript.data":
        words = dd.get("words") or []
        text  = " ".join((w.get("text","") for w in words)) or dd.get("text","") or ""
        log(f"[wh] transcript.data ts={ts_abs} speaker={who} text={text}")

    elif ev.startswith("participant_events."):
        # Compact, informative single-line print for all participant events
        # Full details are kept (truncated) for quick debugging.
        details = json.dumps(dd, separators=(",", ":"), ensure_ascii=False)
        if len(details) > 500:
            details = details[:500] + "…"
        log(f"[wh] {ev} ts={ts_abs} who={who} details={details}")

    elif ev == "bot.status_change":
        code = dd.get("code")
        log(f"[wh] bot.status_change ts={ts_abs} code={code}")
        # if code == "bot.done": artifacts are ready via /retrieve

    else:
        s = json.dumps(p, separators=(",", ":"), ensure_ascii=False)
        log("[wh] event:", ev, "| payload:", (s[:800] + "…") if len(s) > 800 else s)

    # Ack fast; do work in background worker
    return JSONResponse({"ok": True})

# WebSocket receiver
@app.websocket("/ws/rt")
async def ws_rt(ws: WebSocket):
    if ws.query_params.get("token") != WS_TOKEN:
        await ws.close(code=1008)
        return

    await ws.accept()
    log("[ws] connected", ws.client)
    try:
        while True:
            # bail early if the client already closed
            if ws.client_state == WebSocketState.DISCONNECTED:
                break

            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                # first close frame seen -> exit cleanly
                break

            if msg.get("type") == "websocket.disconnect":
                break

            payload = None
            if msg.get("text") is not None:
                payload = msg["text"]
            elif msg.get("bytes") is not None:
                try:
                    payload = msg["bytes"].decode("utf-8", errors="replace")
                except Exception:
                    payload = None

            if not payload:
                # don't loop back into receive() after a close frame
                log("[ws] non-text frame or empty")
                continue

            try:
                e = json.loads(payload)
            except Exception:
                log("[ws] bad-json:", (payload[:200] + "…") if isinstance(payload, str) and len(payload) > 200 else payload)
                continue

            ev = e.get("event")
            d  = e.get("data") or {}
            dd = d.get("data") or {}
            ts = (dd.get("timestamp") or {}).get("absolute")
            buf = dd.get("buffer")

            if ev == "audio_mixed_raw.data" and buf:
                n = len(base64.b64decode(buf))
                dur_ms = n // 32
                log(f"[ws] audio {dur_ms}ms {n/1024:.1f}KB ts={ts}")

            elif ev == "video_separate_png.data" and buf:
                raw = base64.b64decode(buf)
                dims = "?"
                if raw[:8] == b'\x89PNG\r\n\x1a\n' and raw[12:16] == b'IHDR':
                    w = int.from_bytes(raw[16:20], 'big'); h = int.from_bytes(raw[20:24], 'big')
                    dims = f"{w}x{h}"
                p = dd.get("participant") or {}
                log(f"[ws] png {dims} {len(raw)/1024:.1f}KB {p.get('id')}:{p.get('name')} ts={ts}")

            elif ev == "video_separate_h264.data" and buf:
                n = len(base64.b64decode(buf))
                p = dd.get("participant") or {}
                log(f"[ws] h264 {n/1024:.1f}KB {p.get('id')}:{p.get('name')} ts={ts}")

            elif ev == "transcript.data":
                words = dd.get("words") or []
                text  = " ".join((w.get("text","") for w in words)) or dd.get("text","")
                who   = (dd.get("participant") or {}).get("name")
                log(f"[ws] transcript {who}: {text}")

            else:
                log("[ws] event", ev)
    finally:
        log("[ws] disconnected")


# Create bot (register webhook + optional WS + optional PNG/H264)
@app.post("/start")
async def start(payload: dict):
    assert http is not None, "HTTP client not initialized"

    meeting_url    = payload["meeting_url"]
    display_name   = payload.get("display_name", "Recall Bot")
    platform       = payload.get("platform")
    meeting_pw     = payload.get("meeting_password")
    ws_url         = payload.get("ws_url")  # e.g., f"{NGROK_BASE}/ws/rt?token={WS_TOKEN}"
    realtime_video = payload.get("realtime_video")      # None | "png" | "h264"

    endpoints = [{
        "type": "webhook",
        "url": f"{NGROK_BASE}/wh",
        "events": [
            "transcript.data",
            "participant_events.join","participant_events.leave","participant_events.update",
            "participant_events.speech_on","participant_events.speech_off",
            "participant_events.webcam_on","participant_events.webcam_off",
            "participant_events.screenshare_on","participant_events.screenshare_off",
            "participant_events.chat_message"
        ],
    }]

    if ws_url:
        ws_events = ["audio_mixed_raw.data"]
        if realtime_video == "png":  ws_events.append("video_separate_png.data")
        if realtime_video == "h264": ws_events.append("video_separate_h264.data")
        endpoints.append({"type": "websocket", "url": ws_url, "events": ws_events})

    recording_config = {
        "transcript": {"provider": {"recallai_streaming": {
            "language_code": "en", "filter_profanity": False, "mode": "prioritize_low_latency"
        }}},
        "participant_events": {},
        "meeting_metadata": {},
        "start_recording_on": payload.get("start_recording_on", "participant_join"),
        "realtime_endpoints": endpoints,
        "audio_mixed_raw": {},
    }

    # PNG only — add variant to be safe (helps separate video reliability)
    if realtime_video == "png":
        recording_config.update({
            "video_separate_png": {},
            "video_mixed_layout": "gallery_view_v2",
            "variant": {"zoom": "web_4_core", "google_meet": "web_4_core", "microsoft_teams": "web_4_core"}
        })
    elif realtime_video == "h264":
        recording_config.update({
            "video_separate_h264": {},
            "video_mixed_layout": "gallery_view_v2",
            "variant": {"zoom": "web_4_core", "google_meet": "web_4_core", "microsoft_teams": "web_4_core"}
        })

    body = {"meeting_url": meeting_url, "bot_name": display_name, "recording_config": recording_config}
    if platform:   body["platform"] = platform
    if meeting_pw: body["meeting_password"] = meeting_pw

    # Helpful to confirm subscriptions quickly
    log("[start] recording_config =", json.dumps(recording_config, separators=(",", ":"), ensure_ascii=False)[:2000])

    try:
        r = await http.post(f"{API}/bot", headers=H, json=body)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            {"ok": False, "status": e.response.status_code, "url": str(e.request.url), "body": e.response.text},
            status_code=502
        )

    bot = r.json()
    bot_id = bot.get("id") or bot.get("bot_id") or bot.get("uuid") or (bot.get("data") or {}).get("id")
    return {"bot_id": bot_id, "webhook": f"{NGROK_BASE}/wh", "websocket": ws_url or None, "video": realtime_video or "none"}

# Retrieve artifacts
@app.get("/retrieve/{bot_id}")
async def retrieve(bot_id: str):
    assert http is not None, "HTTP client not initialized"
    r = await http.get(f"{API}/bot/{bot_id}", headers=H)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    log("[boot] NGROK_BASE =", NGROK_BASE, "| WS_TOKEN set:", bool(WS_TOKEN))
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
