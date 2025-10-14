# app/step4.py — helpers for Step 4 (load, flatten, paragraphs, summarize, search, Slack)

import httpx, json, subprocess
from pathlib import Path
from typing import Any, Dict, List, Callable, Tuple, Optional
from collections import defaultdict

# PII note: transcripts may contain PII. Redact before logging externally.

async def load_transcript_json(url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(url)
        r.raise_for_status()
        return r.json()

def to_segments(transcript_json: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Flatten Recall.ai transcript JSON to:
      [{"speaker": str|None, "start_ms": int, "end_ms": int, "text": str}, ...]
    Expected input shape (per Recall.ai):
      [ { "participant": {...}, "words": [ { "text": str, "start_timestamp": {"relative": sec}, "end_timestamp": {"relative": sec} }, ... ] }, ... ]
    """
    segs: List[Dict[str, Any]] = []
    for entry in transcript_json:
        participant = entry.get("participant") or {}
        words = entry.get("words") or []
        if not words:
            continue
        start = int((words[0]["start_timestamp"]["relative"]) * 1000)
        end   = int((words[-1]["end_timestamp"]["relative"]) * 1000)
        text  = " ".join((w.get("text","").strip() for w in words)).strip()
        segs.append({
            "speaker": participant.get("name"),
            "start_ms": start,
            "end_ms": end,
            "text": text
        })
    return [s for s in segs if s["text"]]

def to_paragraphs(segments: List[Dict[str, Any]], gap_ms: int = 1200) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cur: Dict[str, Any] | None = None
    for s in sorted(segments, key=lambda x: x["start_ms"]):
        new_block = (cur is None or s.get("speaker") != cur.get("speaker") or s["start_ms"] - cur["end_ms"] > gap_ms)
        if new_block:
            if cur: out.append(cur)
            cur = dict(s)
        else:
            cur["end_ms"] = max(cur["end_ms"], s["end_ms"])
            cur["text"]   = (cur["text"] + " " + s["text"]).strip()
    if cur: out.append(cur)
    return out

def build_summary_and_actions(
    paragraphs: List[Dict[str, Any]],
    generate: Callable[[str], str],
    max_chars: int = 15000
) -> Dict[str, Any]:
    def fmt_time(ms: int) -> str:
        s = max(0, ms // 1000); return f"{s//60:02d}:{s%60:02d}"
    lines = []
    for p in paragraphs:
        speaker = p.get("speaker") or "Speaker"
        ts = fmt_time(p.get("start_ms", 0))
        lines.append(f"[{ts}] {speaker}: {p['text']}")
    text = "\n".join(lines)[:max_chars]

    prompt = f"""
You are turning a meeting transcript into structured, linkable notes.
Return STRICT JSON with keys: summary, highlights[], action_items[].
- highlights[]: title, start_ms, end_ms, quote
- action_items[]: title, owner (email or null), due_date (YYYY-MM-DD or null), confidence (0..1), evidence_ms
Only use information present in the transcript below.

Transcript:
{text}
""".strip()

    raw = generate(prompt)
    try:
        data = json.loads(raw)
        data.setdefault("summary",""); data.setdefault("highlights",[]); data.setdefault("action_items",[])
        return data
    except Exception:
        return {"summary": "", "highlights": [], "action_items": []}

def search_paragraphs(paragraphs: List[Dict[str, Any]], query: str, limit: int = 5
) -> List[Tuple[Dict[str, Any], int]]:
    q = query.lower().strip()
    scored: List[Tuple[Dict[str, Any], int]] = []
    for p in paragraphs:
        score = p["text"].lower().count(q)
        if score: scored.append((p, score))
    scored.sort(key=lambda t: (-t[1], t[0]["start_ms"]))
    return scored[:limit]

def jump_link(base_play_url: str, start_ms: int) -> str:
    sec = max(0, start_ms // 1000)
    sep = "&" if "?" in base_play_url else "?"
    return f"{base_play_url}{sep}t={sec}"

# Optional enrichment
async def load_events_json(url: str):
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(url)
        r.raise_for_status()
        return r.json()

def enrich_paragraphs_with_events(paragraphs, events):
    for p in paragraphs:
        start, end = p.get("start_ms", 0), p.get("end_ms", 0)
        p["events"] = [e for e in events if start <= e.get("ts_ms", 0) <= end]

def compute_speaker_stats(paragraphs, events=None):
    segs = defaultdict(list); on = {}
    for e in (events or []):
        who = (e.get("participant") or {}).get("name") or "Speaker"
        if e.get("type") == "speech_on": on[who] = e.get("ts_ms", 0)
        elif e.get("type") == "speech_off" and who in on:
            segs[who].append((on.pop(who), e.get("ts_ms", 0)))
    if not segs:
        for p in paragraphs:
            who = p.get("speaker") or "Speaker"
            segs[who].append((p.get("start_ms", 0), p.get("end_ms", 0)))
    return {
        spk: {"talk_time_ms": sum(b - a for a, b in segs[spk]), "turns": len(segs[spk])}
        for spk in segs
    }

def thumbnail_at(video_path: str, ms: int, out_dir: str):
    out = Path(out_dir) / f"thumb_{ms}.jpg"
    ss = f"{ms/1000:.3f}"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", ss, "-i", video_path,
         "-frames:v", "1", "-vf", "scale=480:-1", str(out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return str(out)
