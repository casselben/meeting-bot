# meeting-bot

Minimal FastAPI server that creates a Recall.ai meeting bot, streams realtime data (webhook + optional websocket), and retrieves artifacts for downstream analysis.

## What you can do

* Spin up a tiny FastAPI server that can **join a meeting (Zoom / Google Meet / Microsoft Teams)** via Recall.ai

* Stream events/media to your app via webhook events (transcripts, participant events, etc.)

* Retrieve artifacts (transcripts, audio, video) for analysis (audio and video (PNG or H.264))

* Stream data to the meeting from your app

* Normalize, summarize, and enrich meeting data (extract media artifact links, compute speaker stats, generate thumbnails, and optionally post structured Slack digests with jump links)

## Demo Video: 
[Demo Video](https://www.loom.com/share/97b8b466ea2f49dea75f03f0182efc80)

> TL;DR
>
> ```bash
> # 1) Start the API server (FastAPI via Uvicorn)
> uvicorn server:app --host 0.0.0.0 --port 8000
>
> # 2) Expose it publicly so Recall.ai can reach your webhooks / websockets
> ngrok http --domain=ngrok-static-domain 8000
>
> # 3) Start a meeting bot
> curl -X POST 'http://localhost:8000/start' >   -H 'Content-Type: application/json' >   --data-raw '{
>     "meeting_url": "meeting_url_here",
>     "display_name": "Bot Name",
>     "platform": "platform_name",
>     "ws_url": "ws_url_token",
>     "realtime_video": "png"
>   }'
>
> # 4) Retrieve bot/artifacts later
> curl -sS http://localhost:8000/retrieve/BOT_ID_HERE | jq .
> ```
>
> If you use `jq`, you’ll get nicely formatted JSON. Install it via your package manager if you don’t have it.

---

## Table of Contents

- [What this repo does](#what-this-repo-does)
- [Architecture overview](#architecture-overview)
- [Repo layout](#repo-layout)
- [Requirements](#requirements)
- [Configuration & environment](#configuration--environment)
- [Quick start](#quick-start)
- [Endpoints](#endpoints)
  - [`POST /start`](#post-start)
  - [`GET /retrieve/{bot_id}`](#get-retrievebot_id)
  - [`POST /wh` (webhook)](#post-wh-webhook)
  - [`WS /ws/rt` (websocket)](#ws-wsrt-websocket)
  - [`POST /api/analyze`](#post-apianalyze)
- [How it works (request flow)](#how-it-works-request-flow)
- [Realtime options (audio/video)](#realtime-options-audiovideo)
- [Artifacts & analysis helpers](#artifacts--analysis-helpers)
- [Local development](#local-development)
- [Troubleshooting](#troubleshooting)
- [Security & production notes](#security--production-notes)
- [License](#license)

---

## What this repo does

This sample app demonstrates how to:

- **Start a meeting bot** and join it to a Zoom / Google Meet / Microsoft Teams meeting.
- **Receive webhook events** (transcripts, participant join/leave, speech on/off, webcam/screenshare on/off, chat messages).
- **Receive websocket streams** for **mixed audio** and **realtime video** (PNG or H.264), plus transcript events.
- **Retrieve artifacts** (transcript, audio, video) for offline processing.
- **Run simple analysis** of transcripts into paragraphs, summaries, highlights, and action items via a pluggable LLM hook.
- **(Optional extension)**: *Realtime media ingress* (sending audio/video **into** the meeting). This is not implemented in the sample code but the server layout anticipates it; add your own endpoint/worker if your plan supports ingress.

> Note: If you only need webhooks (transcripts + events) you can omit the websocket configuration entirely. If you want realtime audio/video frames, enable the websocket endpoint and choose PNG or H.264 frames as described below.

---

## Architecture overview

```
Client ↔ (ngrok) ↔ FastAPI server
                ├─ POST /start        → Recall.ai: create bot + subscribe endpoints
                ├─ POST /wh           ← Webhooks (transcripts & participant events)
                ├─ WS   /ws/rt        ← Realtime streams (audio_mixed_raw, video PNG/H264, transcript)
                ├─ GET  /retrieve/{id}→ Recall.ai: fetch artifacts/recording metadata
                └─ POST /api/analyze  → Local Step 4: normalize, summarize, extract actions
```

---

## Repo layout

```
.
├─ server.py                         # Entrypoint (imports `app` and mounts /api router)
├─ app/
│  ├─ pythonHowToBuildABot.py       # FastAPI app: /start, /wh, /ws/rt, /retrieve/{bot_id}
│  ├─ analyze.py                    # Router mounted at /api/analyze (Step 4 pipeline)
│  ├─ step4.py                      # Normalize transcript → segments → paragraphs; summarize/search
│  └─ mediahelpers.py               # Helpers to parse artifact shortcuts; audio_separate helpers
└─ .venv/                           # (optional) your local virtualenv
```

---

## Requirements

- **Python 3.10+**
- **Pip** + **virtualenv** (recommended)
- **ngrok** (or any public reverse proxy) to receive webhooks/websocket events
- A **Recall.ai API key** with access to your target platform(s)
- (Optional) **jq** for pretty-printing JSON at the CLI

Python dependencies (install via `pip`):

- `fastapi`, `uvicorn`, `httpx`, `starlette`

If you have a `requirements.txt`, do:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip3 install -r requirements.txt
```

Otherwise:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install fastapi uvicorn httpx starlette
```

---

## Configuration & environment

The server reads the following environment variables (with safe defaults for local dev):

- `RECALL_REGION` — default: `us-east-1`
- `RECALL_API_KEY` — **required** for real calls (sample uses a placeholder for PoC)
- `NGROK_BASE` — your public base URL, e.g. `https://your-domain.ngrok.app`
- `WS_TOKEN` — shared token required by `WS /ws/rt` (e.g., `?token=XYZ`)

Export them in your shell (examples):

```bash
export RECALL_REGION=us-east-1
export RECALL_API_KEY=YOUR_API_KEY
export NGROK_BASE=https://ngrok-static-domain
export WS_TOKEN=dev-secret
```

> **Important**: `NGROK_BASE` must match the public hostname created by ngrok and **must be HTTPS**. For websockets, ngrok will accept `wss://` at the same hostname.

---

## Quick start

1) **Start the server**

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

2) **Expose it publicly** (so Recall.ai can call your webhooks/websockets)

```bash
ngrok http --domain=ngrok-static-domain-here 8000
```

3) **Start a bot** (replace placeholders)

```bash
curl -X POST 'http://localhost:8000/start'   -H 'Content-Type: application/json'   --data-raw '{
    "meeting_url": "MEETING_URL_HERE",
    "display_name": "BOT_NAME_HERE",
    "platform": "PLATFORM_NAME",
    "ws_url": "WS_URL_TOKEN",
    "realtime_video": "png"
  }'
```

- `meeting_url` — full meeting URL for Zoom/Google Meet/Microsoft Teams
- `platform` — optional; if omitted, Recall.ai auto-detects from the URL
- `ws_url` — optional; set to your `wss://` URL (usually your ngrok base + `/ws/rt?token=...`)
- `realtime_video` — optional; `"png"` or `"h264"` (omit for audio-only)

**Example `ws_url`:**

```
wss://ngrok-static-domain/ws/rt?token=dev-secret
```

4) **Retrieve bot / artifacts**

```bash
curl -sS http://localhost:8000/retrieve/BOT_ID_HERE | jq .
```

You’ll see the Recall.ai bot object including `recordings` and `media_shortcuts` (short‑lived URLs).

---

## Endpoints

### `POST /start`

Creates a Recall.ai bot and subscribes your **webhook** and optional **websocket** endpoints.

**Request body**

```json
{
  "meeting_url": "MEETING_URL_HERE", // e.g. https://meet.google.com/abc-defg-hij
  "display_name": "BOT_NAME_HERE",
  "platform": "PLATFORM_NAME_HERE",
  "meeting_password": null,
  "ws_url": "wss://ngrok-static-domain/ws/rt?token=dev-secret",
  "realtime_video": "png",
  "start_recording_on": "participant_join"
}
```

- `realtime_video`: `"png"` or `"h264"` to enable realtime video frames over WS.
- Without `ws_url`, only webhooks (e.g., `transcript.data`) are enabled.

**Response body**

```json
{
  "bot_id": "b_123...",
  "webhook": "https://ngrok-static-domain/wh",
  "websocket": "wss://ngrok-static-domain/ws/rt?token=dev-secret",
  "video": "png"
}
```

---

### `GET /retrieve/{bot_id}`

Fetches the up-to-date Recall.ai bot object. Use this to find artifacts/recordings and derive download URLs via helpers.

```bash
curl -sS http://localhost:8000/retrieve/BOT_ID_HERE | jq .
```

The structure includes `recordings[]` and per-recording `media_shortcuts` (short‑lived `download_url`s). See `app/mediahelpers.py` for programmatic extraction.

---

### `POST /wh` (webhook)

Recall.ai will POST transcript and participant events to this endpoint.

- **Transcript** events: `transcript.data` — includes `words[]` with timestamps
- **Participant** events: `participant_events.join|leave|update|speech_on|speech_off|webcam_on|webcam_off|screenshare_on|screenshare_off|chat_message`
- **Status** events: `bot.status_change` (e.g., `bot.done` indicates artifacts are ready)

The handler logs compact, single-line entries for quick inspection and returns `{"ok": true}` quickly. Do heavy work in background tasks.

---

### `WS /ws/rt` (websocket)

Accepts connections only when `?token=WS_TOKEN` matches your environment variable. Streams may include:

- `audio_mixed_raw.data` — base64 PCM chunks; server logs duration/byte size
- `video_separate_png.data` — base64 PNG frames (one per participant), logs inferred dimensions
- `video_separate_h264.data` — base64 H.264 chunks (one per participant)
- `transcript.data` — same schema as webhooks, just delivered over WS

The code shows how to parse JSON frames, decode buffers, and print meaningful logs.

---

### `POST /api/analyze`

End-to-end **Step 4**: fetch transcript JSON → normalize → summarize → (optionally) post a Slack digest.

**Request body**

```json
{
  "transcript_url": "https://short-lived-url/transcript.json",
  "base_play_url": "https://yourapp.example/play?bot_id=...",
  "slack_webhook_url": null
}
```

**Response body**

```json
{
  "paragraphs": [ { "speaker": "Alice", "start_ms": 12345, "end_ms": 15678, "text": "..." }, ... ],
  "summary": "...",
  "highlights": [ { "title": "...", "start_ms": 12345, "end_ms": 15678, "quote": "..." } ],
  "action_items": [ { "title": "...", "owner": null, "due_date": null, "confidence": 0.8, "evidence_ms": 12345 } ]
}
```

> The actual LLM call is abstracted behind `my_generate()` and currently returns an empty JSON scaffold so the route always succeeds. Plug in your model/provider and return a JSON **string**.

---

## How it works (request flow)

1. **You POST `/start`** with meeting details.  
2. Server calls **Recall.ai** to create the bot and subscribe to your **webhook** and (optionally) **websocket** endpoints.
3. As the meeting runs:
   - Recall.ai sends **webhooks** to `/wh` for transcripts and participant events.
   - Recall.ai streams **realtime audio/video** to your `/ws/rt` (if configured).
4. After the meeting (or on `bot.done`), call **`/retrieve/{bot_id}`** to get recordings and **short‑lived** artifact URLs.
5. Feed the transcript URL to **`/api/analyze`** to normalize/summarize and (optionally) post a Slack digest with jump links.

---

## Realtime options (audio/video)

When you include `ws_url` in `/start`, the server enables:

- Always: `audio_mixed_raw` (mixed PCM over WS)
- Optionally: `video_separate_png` (easier to debug) **or** `video_separate_h264` (more compact / production‑friendly)
- The sample sets `video_mixed_layout = "gallery_view_v2"` and chooses a **web_4_core** variant to maximize video reliability across platforms.

Choose one video mode at a time with `realtime_video: "png"` or `"h264"`.

---

## Artifacts & analysis helpers

`app/mediahelpers.py` exposes convenient utilities to extract media download links from the `bot` object returned by `/retrieve/{bot_id}`:

- `extract_media_shortcuts(bot_json)` — returns transcript/audio/video **download URLs** per recording (remember: **short‑lived**).
- `extract_audio_separate_id(bot_json)` → `get_audio_separate_download_url(id)` — resolve per‑speaker audio downloads when available.

`app/step4.py` includes helpers to:

- `to_segments()` → `to_paragraphs()` — normalize Recall.ai transcript JSON
- `build_summary_and_actions()` — LLM‑driven JSON output (summary, highlights, action items)
- `search_paragraphs()` — naive keyword search
- `thumbnail_at()` — sample `ffmpeg` call to pull a frame from mixed video

---

## Local development

Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn httpx starlette
```

Run the server:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Expose it:

```bash
ngrok http --domain=ngrok-static-domain 8000
```

Start a bot (replace placeholders) and watch your server logs for `[/wh]` and `[ws]` lines.

---

## Troubleshooting

- **401/403 from Recall.ai**: Check `RECALL_API_KEY`, `RECALL_REGION`.
- **Webhook not firing**: Verify your `NGROK_BASE` matches the ngrok hostname and is reachable (HTTPS). Check that `/wh` is publicly accessible.
- **Websocket not connecting**: Ensure your client uses `wss://` and appends `?token=WS_TOKEN`. Check that ngrok supports websockets on your domain.
- **No video frames**: You likely omitted `realtime_video` or `ws_url`. Use `"png"` first to debug, then switch to `"h264"`.
- **Short‑lived URLs expired**: Call `/retrieve/{bot_id}` again to refresh artifact shortcut links.
- **Large payloads**: Keep heavy processing out of the webhook handler; offload to workers/queues.
- **CORS**: This server is designed primarily for server-to-server calls. Add CORS middleware if you’re calling directly from a browser app.

---

## Security & production notes

- **NEVER** hardcode production API keys. Use environment variables or a secret manager.
- Protect `/ws/rt` with a **strong token**, rotate regularly, and prefer IP allowlists on your edge when possible.
- Webhooks should be **idempotent** and fast; queue work elsewhere.
- Consider **signature verification** and **replay protection** for webhooks.
- Store **IDs, not URLs** — artifact links are short‑lived by design.
- Ensure any logs or exports **redact PII** present in transcripts.
- Add observability (structured logs, metrics, tracing) for production use.

---

## License

MIT (or your preferred license). Update this section before open‑sourcing.
