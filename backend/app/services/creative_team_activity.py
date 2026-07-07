"""
Creative Team Activity — the "office" live-feed + DURABLE performance/audit ledger
=================================================================================
Two layers:
  • LIVE (in-memory): who is working RIGHT NOW / queued — powers the office desks. Ephemeral,
    per-worker, rebuilt continuously; losing it on restart is fine (it's "now").
  • DURABLE (Postgres, creative_team_events): every completed step, eval, coaching and reward is
    written as a row. This is the permanent audit trail — survives restarts/deploys, is drillable
    per job (audit(job_id)), and (being in the shared DB) is consistent across workers.

reports()/get_coaching()/audit() read from Postgres so history + accountability + coaching persist.
snapshot() stays in-memory for live speed. DB writes are best-effort — if the DB is briefly down,
the live view still works and nothing crashes.
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

_LOCK = threading.Lock()
# current live state per persona
_STATE: dict = {r["id"]: {"status": "idle", "job_id": None, "task": None,
                          "since": None, "last": None} for r in ROSTER}
# rolling performance ledger per persona
_LEDGER: dict = {r["id"]: {"runs": 0, "passes": 0, "revises": 0, "fails": 0,
                           "total_ms": 0, "helpful_sum": 0.0, "helpful_n": 0,
                           # accountability: starts perfect, drops on attributed faults, recovers on clean passes
                           "accountability": 100.0, "faults": 0} for r in ROSTER}
# coaching notes per persona (the "one-on-one" — injected into that persona's next prompt)
_COACHING: dict = {r["id"]: deque(maxlen=8) for r in ROSTER}
# recent event feed (newest first) for the office ticker
_FEED: deque = deque(maxlen=200)
# queue: jobs waiting per persona (job_ids)
_QUEUE: dict = {r["id"]: [] for r in ROSTER}


# accountability tuning (kept as constants so DB-derived score matches the intent)
FAULT_PENALTY = 8.0
REWARD_GAIN = 2.0


def _persist(persona: str, event: str, *, job_id: Optional[str] = None, task: str = "",
             detail: str = "", ms: Optional[int] = None, ok: Optional[bool] = None,
             revised: Optional[bool] = None, helpfulness: Optional[float] = None) -> None:
    """Best-effort write of ONE durable audit row to Postgres. Never raises to the caller."""
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent
        db = SessionLocal()
        try:
            db.add(CreativeTeamEvent(
                job_id=job_id, persona=persona, role=(_ROSTER_BY_ID.get(persona, {}) or {}).get("role"),
                event=event, task=(task or "")[:2000], detail=(detail or "")[:2000],
                ms=ms, ok=ok, revised=revised, helpfulness=helpfulness))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"creative_team audit persist failed ({event}/{persona}): {e}")


def coach(persona: str, note: str, *, penalty: float = FAULT_PENALTY, job_id: Optional[str] = None) -> None:
    """Record a corrective 'one-on-one' for a persona after a fault: persist it (durable), keep it
    in the live feed, and dock the in-memory accountability. The DURABLE score is derived from the
    persisted 'coached'/'reward' rows in reports()."""
    if persona not in _COACHING or not (note or "").strip():
        return
    note = note.strip()
    with _LOCK:
        _COACHING[persona].appendleft(note)
        led = _LEDGER.get(persona)
        if led is not None:
            led["faults"] += 1
            led["accountability"] = max(0.0, led["accountability"] - penalty)
        _FEED.appendleft({"t": _now(), "persona": persona, "event": "coached", "detail": note[:160]})
    _persist(persona, "coached", job_id=job_id, detail=note)


def reward(persona: str, *, gain: float = REWARD_GAIN, job_id: Optional[str] = None) -> None:
    """A clean pass nudges accountability back up (teams improve as they stop making the mistake)."""
    with _LOCK:
        led = _LEDGER.get(persona)
        if led is not None:
            led["accountability"] = min(100.0, led["accountability"] + gain)
    _persist(persona, "reward", job_id=job_id)


def get_coaching(persona: str) -> list:
    """Latest coaching notes for a persona — from the DURABLE store so coaching survives restarts
    and is shared across workers. Falls back to the in-memory deque if the DB is unavailable."""
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
        jid = (_STATE.get(persona) or {}).get("job_id")   # capture before we reset to idle
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
        event = "revise" if revised else ("done" if ok else "fail")
        _FEED.appendleft({"t": ts, "persona": persona, "event": event, "ms": ms, "detail": detail[:160]})
    # DURABLE: record the completed step (outside the lock — no DB I/O while holding it)
    _persist(persona, event, job_id=jid, detail=detail, ms=ms,
             ok=ok, revised=revised, helpfulness=helpfulness)


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


def _reports_from_memory() -> dict:
    with _LOCK:
        rows = []
        for r in ROSTER:
            led = _LEDGER[r["id"]]
            runs = led["runs"] or 0
            acc = round(100 * led["passes"] / runs, 1) if runs else 0.0
            helpful = round(100 * led["helpful_sum"] / led["helpful_n"], 1) if led["helpful_n"] else None
            rows.append({"id": r["id"], "role": r["role"], "emoji": r["emoji"],
                         "runs": runs, "passes": led["passes"], "revises": led["revises"],
                         "fails": led["fails"], "accuracy_pct": acc, "helpfulness_pct": helpful,
                         "accountability_pct": round(led["accountability"], 1),
                         "attributed_faults": led["faults"],
                         "coaching": list(_COACHING.get(r["id"], []))[:3],
                         "avg_ms": int(led["total_ms"] / runs) if runs else 0})
        return {"rows": rows, "ts": _now(), "source": "memory"}


def reports() -> dict:
    """Per-persona performance ledger — aggregated from the DURABLE Postgres audit so it survives
    restarts and is consistent across workers. Falls back to the in-memory ledger if the DB is down."""
    try:
        from sqlalchemy import func, case
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent as E
        db = SessionLocal()
        try:
            agg = dict()
            q = (db.query(
                    E.persona,
                    func.count().label("total"),
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
            # latest coaching per persona (small N of personas → one query each is fine)
            coaching = {}
            for r in ROSTER:
                notes = (db.query(E.detail).filter(E.persona == r["id"], E.event == "coached")
                           .order_by(E.created_at.desc()).limit(3).all())
                coaching[r["id"]] = [n[0] for n in notes if n[0]]

            rows = []
            for r in ROSTER:
                a = agg.get(r["id"])
                passes = int(a.passes or 0) if a else 0
                revises = int(a.revises or 0) if a else 0
                fails = int(a.fails or 0) if a else 0
                faults = int(a.faults or 0) if a else 0
                rewards = int(a.rewards or 0) if a else 0
                runs = passes + revises + fails
                acc = round(100 * passes / runs, 1) if runs else 0.0
                accountability = max(0.0, min(100.0, 100.0 - FAULT_PENALTY * faults + REWARD_GAIN * rewards))
                rows.append({"id": r["id"], "role": r["role"], "emoji": r["emoji"],
                             "runs": runs, "passes": passes, "revises": revises, "fails": fails,
                             "accuracy_pct": acc,
                             "helpfulness_pct": round(100 * float(a.helpful), 1) if (a and a.helpful is not None) else None,
                             "accountability_pct": round(accountability, 1),
                             "attributed_faults": faults, "coaching": coaching.get(r["id"], []),
                             "avg_ms": int(a.avg_ms) if (a and a.avg_ms is not None) else 0})
            return {"rows": rows, "ts": _now(), "source": "db"}
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"reports DB aggregation failed, using memory: {e}")
        return _reports_from_memory()


def audit(job_id: Optional[str] = None, persona: Optional[str] = None, limit: int = 300) -> dict:
    """DURABLE per-task / per-persona drill-down: every recorded step for a job (or persona), in
    order. This is the permanent record — 'show me everything the team did for job X'."""
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
            _LEDGER[k] = {"runs": 0, "passes": 0, "revises": 0, "fails": 0,
                          "total_ms": 0, "helpful_sum": 0.0, "helpful_n": 0,
                          "accountability": 100.0, "faults": 0}
            _COACHING[k].clear()
