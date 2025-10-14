# analyze.py — FastAPI router that performs Step 4 end-to-end
from __future__ import annotations

import json
from typing import Dict, Any, List

import httpx
from fastapi import APIRouter, HTTPException

from .step4 import (
    load_transcript_json,
    to_segments,
    to_paragraphs,
    build_summary_and_actions,
    jump_link,
)

router = APIRouter()


def my_generate(prompt: str) -> str:
    """
    Plug your LLM call here and return a *JSON string* with keys:
      { "summary": str,
        "highlights": [{"title": str, "start_ms": int, "end_ms": int, "quote": str}],
        "action_items": [{"title": str, "owner": str|null, "due_date": str|null,
                          "confidence": float, "evidence_ms": int}] }
    Keep this dependency isolated so you can change models freely.
    """
    # Minimal, valid fallback for demos:
    return json.dumps({"summary": "", "highlights": [], "action_items": []})


@router.post("/analyze")
async def analyze(payload: Dict[str, Any]):
    """
    Request body:
      {
        "transcript_url": "https://<short-lived-url-from-media_shortcuts>",
        "base_play_url": "https://yourapp.example/play?bot_id=...",   // optional; used for jump links
        "slack_webhook_url": null | "https://hooks.slack.com/services/..."  // optional
      }

    Response body:
      {
        "paragraphs": [...],     // trimmed for payload size
        "summary": "...",
        "highlights": [...],
        "action_items": [...]
      }
    """
    # Validate input
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    transcript_url = payload.get("transcript_url")
    if not transcript_url or not isinstance(transcript_url, str):
        raise HTTPException(status_code=400, detail="Missing required field: transcript_url")

    base_play_url = payload.get("base_play_url") or ""
    slack_webhook_url = payload.get("slack_webhook_url")

    # Load + normalize transcript
    try:
        tj = await load_transcript_json(transcript_url)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to load transcript: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error loading transcript: {e}") from e

    segs = to_segments(tj)
    paras = to_paragraphs(segs)

    # Summarize + extract actions (LLM-agnostic hook)
    result = build_summary_and_actions(paras, generate=my_generate)

    summary: str = result.get("summary") or ""
    highlights: List[Dict[str, Any]] = result.get("highlights") or []
    action_items: List[Dict[str, Any]] = result.get("action_items") or []

    # Optional: post a concise Slack digest with jump links
    if slack_webhook_url:
        blocks: List[Dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Meeting summary*"}}
        ]
        # Include top 5 highlights with timestamped jump links if base_play_url was provided
        top = highlights[:5]
        for h in top:
            title = (h.get("title") or "").strip()
            start_ms = int(h.get("start_ms") or 0)
            link_text = "jump"
            if base_play_url:
                link = jump_link(base_play_url, start_ms)
                text_line = f"• {title} — <{link}|{link_text}>"
            else:
                # No player URL; still show the timestamp (mm:ss) for context
                mm = max(0, start_ms // 1000) // 60
                ss = max(0, start_ms // 1000) % 60
                text_line = f"• {title} — {mm:02d}:{ss:02d}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text_line}})

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                await http.post(slack_webhook_url, json={"blocks": blocks})
        except Exception:
            # Best-effort: don't fail the request if Slack is unreachable
            pass

    # Return trimmed payload for UI consumption
    return {
        "paragraphs": paras[:200],  # trim for payload size; adjust to your needs
        "summary": summary,
        "highlights": highlights,
        "action_items": action_items,
    }
