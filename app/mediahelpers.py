# app/mediahelpers.py — media shortcut parsing and optional explicit artifact fetch

from typing import Any, Dict, List, Optional, Tuple
import httpx
import os

RECALL_REGION = os.getenv("RECALL_REGION", "us-east-1")
API           = f"https://{RECALL_REGION}.recall.ai/api/v1"
KEY           = os.getenv("RECALL_API_KEY", "")
H             = {"Authorization": f"Token {KEY}", "Content-Type": "application/json"}

# These URLs are short-lived; store IDs, not links.
def extract_media_shortcuts(bot_json: Dict[str, Any]) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    for rec in bot_json.get("recordings") or []:
        shortcuts = rec.get("media_shortcuts") or {}

        def url(key: str) -> Optional[str]:
            node = shortcuts.get(key) or {}
            data = node.get("data") or {}
            return data.get("download_url")

        out.append({
            "recording_id":     rec.get("id"),
            "transcript_url":   url("transcript"),
            "video_mixed_url":  url("video_mixed"),
            "audio_mixed_url":  url("audio_mixed"),
        })
    return out

async def extract_audio_separate_id(bot_json: dict) -> Optional[str]:
    for rec in bot_json.get("recordings") or []:
        for key in ("audio_separate", "audio_separate_mp3", "audio_separate_raw"):
            obj = rec.get(key)
            if obj and obj.get("id"):
                return obj["id"]
    return None

async def get_audio_separate_download_url(audio_separate_id: str) -> Tuple[Optional[str], Optional[str]]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API}/audio_separate/{audio_separate_id}/", headers=H)
        r.raise_for_status()
        data = r.json()
        d = data.get("data") or {}
        return d.get("download_url"), d.get("format")
