"""
Creative Team Activity — per-job office rooms + live progress + DURABLE audit ledger
====================================================================================
Three concerns, cleanly separated:
  • PER-JOB LIVE ROOMS (in-memory): every job gets its OWN independent set of desks + feed +
    progress, keyed by job_id. Concurrent jobs never garble each other — each is its own team room
    you can switch between. Ephemeral/per-worker (fine; it's "now").
  • PROGRESS + ETA: time-based estimate per job (begin_job sets an expected duration; progress and
    ETA are derived from elapsed vs expected, refined as we learn the beat/segment count).
  • DURABLE AUDIT (Postgres, creative_team_events): every completed step/eval/coaching/reward row —
    permanent, per-job drillable (audit(job_id)), consistent across workers.

reports()/get_coaching()/audit() read Postgres. jobs_list()/snapshot(job_id) drive the live UI.
All DB writes are best-effort — the live view keeps working if the DB is briefly down.
"""
from __future__ import annotations

import time
import logging
import threading
from collections import deque
from typing import Optional, Any

logger = logging.getLogger(__name__)

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

FAULT_PENALTY = 8.0
REWARD_GAIN = 2.0

_LOCK = threading.RLock()   # reentrant: snapshot() calls jobs_list() under the same lock

# ── per-job live rooms ─────────────────────────────────────────────────────────
_JOBS: dict = {}              # job_id -> room dict
_JOB_ORDER: deque = deque(maxlen=60)   # recent job_ids, newest first

# per-persona rolling ledger (in-memory fallback; DURABLE source is Postgres)
_LEDGER: dict = {r["id"]: {"runs": 0, "passes": 0, "revises": 0, "fails": 0, "total_ms": 0,
                           "helpful_sum": 0.0, "helpful_n": 0, "accountability": 100.0, "faults": 0}
                 for r in ROSTER}
_COACHING: dict = {r["id"]: deque(maxlen=8) for r in ROSTER}


def _now() -> float:
    return time.time()


def _blank_personas() -> dict:
    return {r["id"]: {"status": "idle", "task": None, "since": None, "last": None} for r in ROSTER}


def _job(job_id: str, label: str = "", expected_sec: float = 120.0) -> dict:
    """Get-or-create a job room (holds _LOCK via caller)."""
    j = _JOBS.get(job_id)
    if j is None:
        j = {"label": label or job_id, "status": "running", "started": _now(), "updated": _now(),
             "expected_sec": max(15.0, expected_sec), "personas": _blank_personas(),
             "feed": deque(maxlen=120)}
        _JOBS[job_id] = j
        _JOB_ORDER.appendleft(job_id)
        # bound memory: drop the oldest room if we exceed the deque
        if len(_JOBS) > 70:
            for old in list(_JOBS.keys()):
                if old not in _JOB_ORDER:
                    _JOBS.pop(old, None)
    return j


# ── lifecycle ──────────────────────────────────────────────────────────────────
def begin_job(job_id: str, label: str = "", expected_sec: float = 120.0) -> None:
    with _LOCK:
        j = _job(job_id, label, expected_sec)
        if label:
            j["label"] = label
        j["status"] = "running"


def set_expected_sec(job_id: str, expected_sec: float) -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j["expected_sec"] = max(15.0, float(expected_sec))


def end_job(job_id: str, ok: bool = True, error: str = "") -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j["status"] = "done" if ok else "failed"
            j["error"] = (error or "")[:400]
            j["updated"] = _now()
            if not ok and error:
                j["feed"].appendleft({"t": _now(), "persona": "system", "event": "fail", "detail": error[:200]})


def tick(job_id: str, note: str = "") -> None:
    """A coarse progress heartbeat (e.g. 'beat 2/4 generated') — updates the feed + freshness."""
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j["updated"] = _now()
            if note:
                j["feed"].appendleft({"t": _now(), "persona": "generation", "event": "progress", "detail": note[:160]})


# ── per-persona step events ────────────────────────────────────────────────────
def start(persona: str, job_id: str, task: str = "") -> float:
    ts = _now()
    with _LOCK:
        j = _job(job_id)
        j["updated"] = ts
        if persona in j["personas"]:
            j["personas"][persona] = {"status": "working", "task": task, "since": ts,
                                      "last": j["personas"][persona].get("last")}
        j["feed"].appendleft({"t": ts, "persona": persona, "event": "start", "task": task})
    return ts


def finish(persona: str, job_id: str, started: float, *, ok: bool = True, revised: bool = False,
           detail: str = "", helpfulness: Optional[float] = None) -> None:
    ts = _now()
    ms = int((ts - (started or ts)) * 1000)
    event = "revise" if revised else ("done" if ok else "fail")
    with _LOCK:
        j = _job(job_id)
        j["updated"] = ts
        if persona in j["personas"]:
            j["personas"][persona] = {"status": "idle", "task": None, "since": None,
                                      "last": {"t": ts, "ms": ms, "ok": ok, "revised": revised, "detail": detail[:160]}}
        j["feed"].appendleft({"t": ts, "persona": persona, "event": event, "ms": ms, "detail": detail[:160]})
        led = _LEDGER.get(persona)
        if led is not None:
            led["runs"] += 1; led["total_ms"] += ms
            led["fails" if not ok else ("revises" if revised else "passes")] += 1
            if helpfulness is not None:
                led["helpful_sum"] += float(helpfulness); led["helpful_n"] += 1
    _persist(persona, event, job_id=job_id, detail=detail, ms=ms, ok=ok, revised=revised, helpfulness=helpfulness)


def coach(persona: str, note: str, *, penalty: float = FAULT_PENALTY, job_id: Optional[str] = None) -> None:
    """Corrective 'one-on-one': durable + live-feed + in-memory accountability dock."""
    if persona not in _COACHING or not (note or "").strip():
        return
    note = note.strip()
    with _LOCK:
        _COACHING[persona].appendleft(note)
        led = _LEDGER.get(persona)
        if led is not None:
            led["faults"] += 1
            led["accountability"] = max(0.0, led["accountability"] - penalty)
        if job_id and job_id in _JOBS:
            _JOBS[job_id]["feed"].appendleft({"t": _now(), "persona": persona, "event": "coached", "detail": note[:160]})
    _persist(persona, "coached", job_id=job_id, detail=note)


def reward(persona: str, *, gain: float = REWARD_GAIN, job_id: Optional[str] = None) -> None:
    with _LOCK:
        led = _LEDGER.get(persona)
        if led is not None:
            led["accountability"] = min(100.0, led["accountability"] + gain)
    _persist(persona, "reward", job_id=job_id)


# ── progress / ETA ─────────────────────────────────────────────────────────────
def _progress(j: dict) -> int:
    if j["status"] == "done":
        return 100
    if j["status"] == "failed":
        return 100
    elapsed = _now() - j["started"]
    return int(min(98, max(1, round(elapsed / max(1.0, j["expected_sec"]) * 100))))


def _eta(j: dict) -> Optional[int]:
    if j["status"] in ("done", "failed"):
        return 0
    return int(max(0, j["expected_sec"] - (_now() - j["started"])))


def jobs_list() -> list:
    with _LOCK:
        out = []
        for jid in list(_JOB_ORDER):
            j = _JOBS.get(jid)
            if not j:
                continue
            out.append({"job_id": jid, "label": j["label"], "status": j["status"],
                        "progress": _progress(j), "eta_sec": _eta(j), "error": j.get("error", ""),
                        "elapsed_sec": int(_now() - j["started"]), "updated": j["updated"],
                        "working": [p for p, st in j["personas"].items() if st["status"] == "working"]})
        out.sort(key=lambda x: (x["status"] != "running", -x["updated"]))
        return out


def snapshot(job_id: Optional[str] = None) -> dict:
    """Live state for ONE job's room. If job_id omitted, picks the most recent running job."""
    with _LOCK:
        jl = jobs_list()
        if not job_id:
            running = [x["job_id"] for x in jl if x["status"] == "running"]
            job_id = running[0] if running else (jl[0]["job_id"] if jl else None)
        j = _JOBS.get(job_id) if job_id else None
        desks = []
        for r in ROSTER:
            st = (j["personas"][r["id"]] if j else {"status": "idle", "task": None, "since": None, "last": None})
            desks.append({**r, "status": st["status"],
                          "job_id": job_id if st["status"] == "working" else None,
                          "task": st["task"],
                          "busy_ms": int((_now() - st["since"]) * 1000) if st["since"] else 0,
                          "queued": 0, "last": st["last"]})
        return {"job_id": job_id, "label": (j["label"] if j else None),
                "status": (j["status"] if j else "idle"), "error": (j.get("error", "") if j else ""),
                "progress": (_progress(j) if j else 0), "eta_sec": (_eta(j) if j else None),
                "elapsed_sec": (int(_now() - j["started"]) if j else 0),
                "desks": desks, "feed": (list(j["feed"])[:60] if j else []),
                "active_jobs": [x["job_id"] for x in jl if x["status"] == "running"],
                "jobs": jl, "ts": _now()}


# ── DURABLE audit (Postgres) ───────────────────────────────────────────────────
def _persist(persona: str, event: str, *, job_id: Optional[str] = None, detail: str = "",
             ms: Optional[int] = None, ok: Optional[bool] = None, revised: Optional[bool] = None,
             helpfulness: Optional[float] = None) -> None:
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent
        db = SessionLocal()
        try:
            db.add(CreativeTeamEvent(
                job_id=job_id, persona=persona, role=(_ROSTER_BY_ID.get(persona, {}) or {}).get("role"),
                event=event, detail=(detail or "")[:2000], ms=ms, ok=ok, revised=revised, helpfulness=helpfulness))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"creative_team audit persist failed ({event}/{persona}): {e}")


def get_coaching(persona: str) -> list:
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent
        db = SessionLocal()
        try:
            rows = (db.query(CreativeTeamEvent.detail)
                      .filter(CreativeTeamEvent.persona == persona, CreativeTeamEvent.event == "coached")
                      .order_by(CreativeTeamEvent.created_at.desc()).limit(8).all())
            notes = [r[0] for r in rows if r[0]]
            if notes:
                return notes
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"get_coaching DB read failed: {e}")
    with _LOCK:
        return list(_COACHING.get(persona, []))


def _reports_from_memory() -> dict:
    with _LOCK:
        rows = []
        for r in ROSTER:
            led = _LEDGER[r["id"]]; runs = led["runs"] or 0
            rows.append({"id": r["id"], "role": r["role"], "emoji": r["emoji"],
                         "runs": runs, "passes": led["passes"], "revises": led["revises"], "fails": led["fails"],
                         "accuracy_pct": round(100 * led["passes"] / runs, 1) if runs else 0.0,
                         "helpfulness_pct": round(100 * led["helpful_sum"] / led["helpful_n"], 1) if led["helpful_n"] else None,
                         "accountability_pct": round(led["accountability"], 1), "attributed_faults": led["faults"],
                         "coaching": list(_COACHING.get(r["id"], []))[:3],
                         "avg_ms": int(led["total_ms"] / runs) if runs else 0})
        return {"rows": rows, "ts": _now(), "source": "memory"}


def reports() -> dict:
    try:
        from sqlalchemy import func, case
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent as E
        db = SessionLocal()
        try:
            agg = {}
            q = (db.query(E.persona,
                          func.sum(case((E.event == "done", 1), else_=0)).label("passes"),
                          func.sum(case((E.event == "revise", 1), else_=0)).label("revises"),
                          func.sum(case((E.event == "fail", 1), else_=0)).label("fails"),
                          func.sum(case((E.event == "coached", 1), else_=0)).label("faults"),
                          func.sum(case((E.event == "reward", 1), else_=0)).label("rewards"),
                          func.avg(case((E.event.in_(("done", "revise", "fail")), E.ms))).label("avg_ms"),
                          func.avg(E.helpfulness).label("helpful"))
                   .group_by(E.persona))
            for row in q.all():
                agg[row.persona] = row
            coaching = {}
            for r in ROSTER:
                notes = (db.query(E.detail).filter(E.persona == r["id"], E.event == "coached")
                           .order_by(E.created_at.desc()).limit(3).all())
                coaching[r["id"]] = [n[0] for n in notes if n[0]]
            rows = []
            for r in ROSTER:
                a = agg.get(r["id"])
                passes = int(a.passes or 0) if a else 0; revises = int(a.revises or 0) if a else 0
                fails = int(a.fails or 0) if a else 0; faults = int(a.faults or 0) if a else 0
                rewards = int(a.rewards or 0) if a else 0; runs = passes + revises + fails
                rows.append({"id": r["id"], "role": r["role"], "emoji": r["emoji"],
                             "runs": runs, "passes": passes, "revises": revises, "fails": fails,
                             "accuracy_pct": round(100 * passes / runs, 1) if runs else 0.0,
                             "helpfulness_pct": round(100 * float(a.helpful), 1) if (a and a.helpful is not None) else None,
                             "accountability_pct": round(max(0.0, min(100.0, 100.0 - FAULT_PENALTY * faults + REWARD_GAIN * rewards)), 1),
                             "attributed_faults": faults, "coaching": coaching.get(r["id"], []),
                             "avg_ms": int(a.avg_ms) if (a and a.avg_ms is not None) else 0})
            return {"rows": rows, "ts": _now(), "source": "db"}
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"reports DB aggregation failed, using memory: {e}")
        return _reports_from_memory()


def audit(job_id: Optional[str] = None, persona: Optional[str] = None, limit: int = 300) -> dict:
    try:
        from ..models.creative_team import CreativeTeamEvent as E
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            q = db.query(E)
            if job_id:
                q = q.filter(E.job_id == job_id)
            if persona:
                q = q.filter(E.persona == persona)
            rows = q.order_by(E.created_at.asc()).limit(min(limit, 1000)).all()
            events = [{"persona": e.persona, "role": e.role, "event": e.event, "task": e.task,
                       "detail": e.detail, "ms": e.ms, "ok": e.ok, "revised": e.revised,
                       "helpfulness": e.helpfulness, "job_id": e.job_id,
                       "at": e.created_at.isoformat() if e.created_at else None} for e in rows]
            return {"job_id": job_id, "persona": persona, "count": len(events), "events": events}
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"audit DB read failed: {e}")
        return {"job_id": job_id, "persona": persona, "count": 0, "events": [], "error": str(e)}


def reset_ledger() -> None:
    with _LOCK:
        for k in _LEDGER:
            _LEDGER[k] = {"runs": 0, "passes": 0, "revises": 0, "fails": 0, "total_ms": 0,
                          "helpful_sum": 0.0, "helpful_n": 0, "accountability": 100.0, "faults": 0}
            _COACHING[k].clear()
