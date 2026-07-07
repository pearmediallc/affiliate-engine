"""
Creative Team Activity — the "office" live-feed + performance ledger
====================================================================
Tracks what every persona on the creative team is doing RIGHT NOW (for the visual office-room
UI: who is working, who is queued, on which job, and how helpful the output was), plus a rolling
per-persona performance ledger (accuracy / pass-rate / avg time) for the Reports section.

In-process singleton (single worker) — snapshot() feeds the live office UI, reports() feeds the
Reports tab. Bounded history so it never grows unbounded.
"""
from __future__ import annotations

import time
import threading
from collections import deque
from typing import Optional, Any

# Fixed roster — desks in the office, in seating order. The Creative Director (leader) is first.
ROSTER = [
    {"id": "director",   "role": "Creative Director", "seat": "head",  "emoji": "🎬",
     "desc": "The smart leader — orchestrates everyone; picks references, model per beat, and marks cuts vs lip-sync."},
    {"id": "strategist", "role": "Strategist",        "seat": "left",  "emoji": "🧠",
     "desc": "Diagnoses the loser vs winner ROI data and decides the fix."},
    {"id": "scriptwriter","role": "Script Writer",    "seat": "left",  "emoji": "✍️",
     "desc": "Writes/enhances the script; keeps the offer + winning hook."},
    {"id": "scene",      "role": "Director (Scenes)", "seat": "left",  "emoji": "🎭",
     "desc": "Breaks the script into beats; assigns scene, emotion, gesture, environment."},
    {"id": "character",  "role": "Character Manager", "seat": "right", "emoji": "🧑",
     "desc": "Locks ONE consistent character reused on every beat."},
    {"id": "shots",      "role": "Shot Selector",     "seat": "right", "emoji": "🎥",
     "desc": "Picks shot type + source (real-lipsync > b-roll > i2v > AI) + model per beat."},
    {"id": "prompt",     "role": "Prompt Writer",     "seat": "right", "emoji": "📝",
     "desc": "Composes each beat's anti-slop prompt from the Prompt Reference Library."},
    {"id": "critic",     "role": "Critic",            "seat": "right", "emoji": "🔍",
     "desc": "Guards against AI-slop; rejects and revises weak beats."},
    {"id": "learner",    "role": "Learner",           "seat": "right", "emoji": "📚",
     "desc": "Feeds winning patterns back into the library after outcomes land."},
]
_ROSTER_BY_ID = {r["id"]: r for r in ROSTER}

_LOCK = threading.Lock()
# current live state per persona
_STATE: dict = {r["id"]: {"status": "idle", "job_id": None, "task": None,
                          "since": None, "last": None} for r in ROSTER}
# rolling performance ledger per persona
_LEDGER: dict = {r["id"]: {"runs": 0, "passes": 0, "revises": 0, "fails": 0,
                           "total_ms": 0, "helpful_sum": 0.0, "helpful_n": 0} for r in ROSTER}
# recent event feed (newest first) for the office ticker
_FEED: deque = deque(maxlen=200)
# queue: jobs waiting per persona (job_ids)
_QUEUE: dict = {r["id"]: [] for r in ROSTER}


def _now() -> float:
    return time.time()


def enqueue(persona: str, job_id: str, task: str = "") -> None:
    with _LOCK:
        if persona in _QUEUE and job_id not in _QUEUE[persona]:
            _QUEUE[persona].append(job_id)
        _STATE.get(persona, {})
        if persona in _STATE and _STATE[persona]["status"] == "idle":
            _STATE[persona]["status"] = "queued"
        _FEED.appendleft({"t": _now(), "persona": persona, "event": "queued",
                          "job_id": job_id, "task": task})


def start(persona: str, job_id: str, task: str = "") -> float:
    """Mark a persona as actively working on a job. Returns a start timestamp for finish()."""
    ts = _now()
    with _LOCK:
        if persona in _QUEUE and job_id in _QUEUE[persona]:
            _QUEUE[persona].remove(job_id)
        if persona in _STATE:
            _STATE[persona] = {"status": "working", "job_id": job_id, "task": task,
                               "since": ts, "last": _STATE[persona].get("last")}
        _FEED.appendleft({"t": ts, "persona": persona, "event": "start",
                          "job_id": job_id, "task": task})
    return ts


def finish(persona: str, started: float, *, ok: bool = True, revised: bool = False,
           detail: str = "", helpfulness: Optional[float] = None) -> None:
    """Mark a persona done. helpfulness in [0,1] (how useful the output was) feeds Reports."""
    ts = _now()
    ms = int((ts - (started or ts)) * 1000)
    with _LOCK:
        led = _LEDGER.get(persona)
        if led is not None:
            led["runs"] += 1
            led["total_ms"] += ms
            if not ok:
                led["fails"] += 1
            elif revised:
                led["revises"] += 1
            else:
                led["passes"] += 1
            if helpfulness is not None:
                led["helpful_sum"] += float(helpfulness)
                led["helpful_n"] += 1
        if persona in _STATE:
            still_queued = bool(_QUEUE.get(persona))
            _STATE[persona] = {"status": "queued" if still_queued else "idle",
                               "job_id": None, "task": None, "since": None,
                               "last": {"t": ts, "ms": ms, "ok": ok, "revised": revised,
                                        "detail": detail[:160]}}
        _FEED.appendleft({"t": ts, "persona": persona,
                          "event": "revise" if revised else ("done" if ok else "fail"),
                          "ms": ms, "detail": detail[:160]})


def snapshot() -> dict:
    """Live office state for the room UI: each desk's persona, status, current job/task, and feed."""
    with _LOCK:
        desks = []
        for r in ROSTER:
            st = _STATE[r["id"]]
            desks.append({**r,
                          "status": st["status"], "job_id": st["job_id"], "task": st["task"],
                          "busy_ms": int((_now() - st["since"]) * 1000) if st["since"] else 0,
                          "queued": len(_QUEUE.get(r["id"], [])),
                          "last": st["last"]})
        active_jobs = sorted({d["job_id"] for d in desks if d["job_id"]})
        return {"desks": desks, "active_jobs": active_jobs,
                "feed": list(_FEED)[:60], "ts": _now()}


def reports() -> dict:
    """Per-persona performance ledger for the Reports section."""
    with _LOCK:
        rows = []
        for r in ROSTER:
            led = _LEDGER[r["id"]]
            runs = led["runs"] or 0
            acc = round(100 * led["passes"] / runs, 1) if runs else 0.0
            helpful = round(100 * led["helpful_sum"] / led["helpful_n"], 1) if led["helpful_n"] else None
            rows.append({"id": r["id"], "role": r["role"], "emoji": r["emoji"],
                         "runs": runs, "passes": led["passes"], "revises": led["revises"],
                         "fails": led["fails"], "accuracy_pct": acc,
                         "helpfulness_pct": helpful,
                         "avg_ms": int(led["total_ms"] / runs) if runs else 0})
        return {"rows": rows, "ts": _now()}


def reset_ledger() -> None:
    with _LOCK:
        for k in _LEDGER:
            _LEDGER[k] = {"runs": 0, "passes": 0, "revises": 0, "fails": 0,
                          "total_ms": 0, "helpful_sum": 0.0, "helpful_n": 0}
