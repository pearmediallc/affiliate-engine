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
    {"id": "router",     "role": "Video Router",       "seat": "head",  "emoji": "🧭",
     "desc": "Segregates which KIND of video the request is (reference-image / UGC / UGC+B-Roll / UGC+Map) and the vertical, then locks the lane so nothing downstream re-guesses."},
    {"id": "strategist", "role": "Strategist",        "seat": "left",  "emoji": "🧠",
     "desc": "Diagnoses the loser vs winner ROI data and decides the fix."},
    {"id": "scriptwriter","role": "Copywriter",       "seat": "left",  "emoji": "✍️",
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
    {"id": "finance",    "role": "Finance",           "seat": "head",  "emoji": "💰",
     "desc": "Runs the provider/credit preflight and tracks live per-job spend by provider."},
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
    logger.info(f"[office] JOB START {job_id} · {label}")
    _persist("system", "job_start", job_id=job_id, detail=label)   # durable timeline


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
    if ok:
        logger.info(f"[office] JOB DONE {job_id}")
    else:
        logger.error(f"[office] JOB FAILED {job_id}: {(error or '')[:300]}")
    # durable job outcome (distinct event names so they never skew persona pass/fail metrics)
    _persist("system", "job_done" if ok else "job_fail", job_id=job_id, detail=(error or "")[:400], ok=ok)


def tick(job_id: str, note: str = "") -> None:
    """A coarse progress heartbeat (e.g. 'beat 2/4 generated') — updates the feed + freshness."""
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j["updated"] = _now()
            if note:
                j["feed"].appendleft({"t": _now(), "persona": "generation", "event": "progress", "detail": note[:800]})
    if note:
        logger.info(f"[office] {job_id} progress: {note[:160]}")
        _persist("generation", "progress", job_id=job_id, detail=note[:160])   # durable


def bill(job_id: str, provider: str, usd: float, note: str = "") -> None:
    """Finance running-billing feed line — per-provider spend as it lands, so the office shows live
    cost. Event name 'bill' is not counted in reports() (no pass/fail skew). Best-effort + durable."""
    line = f"💰 {provider} · ${float(usd or 0):.4f}" + (f" · {note}" if note else "")
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j["updated"] = _now()
            j["feed"].appendleft({"t": _now(), "persona": "finance", "event": "bill",
                                  "detail": line[:160], "usd": float(usd or 0), "provider": provider})
    _persist("finance", "bill", job_id=job_id, detail=line[:160])


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
    logger.info(f"[office] {job_id} {persona} START: {(task or '')[:100]}")
    _persist(persona, "start", job_id=job_id, detail=task)   # durable timeline (not counted in reports)
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
            # FULL detail on the per-employee record — this is what the office shows when you click an
            # employee, so the whole script / prompt / direction is visible (was clipped to 160 chars).
            j["personas"][persona] = {"status": "idle", "task": None, "since": None,
                                      "last": {"t": ts, "ms": ms, "ok": ok, "revised": revised,
                                               "detail": (detail or "")}}
        # Feed list keeps a generous cap (the frontend visually clamps the row; click shows full above).
        j["feed"].appendleft({"t": ts, "persona": persona, "event": event, "ms": ms,
                              "detail": (detail or "")[:800]})
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


# ── DURABLE reconstruction (Postgres) ──────────────────────────────────────────
# The room used to show ONLY in-memory jobs, so every past/completed generation's
# team work log vanished after a restart. These read the durable creative_team_events
# so the switcher lists past jobs and their desks/feed can be reconstructed on click.
def _durable_events(limit_rows: int = 600) -> list:
    """Recent events, newest first, as plain dicts (persona, event, detail, ms, job_id, at, ts)."""
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreativeTeamEvent as E
        db = SessionLocal()
        try:
            rows = (db.query(E).filter(E.job_id.isnot(None))
                      .order_by(E.created_at.desc()).limit(limit_rows).all())
            return [{"persona": e.persona, "role": e.role, "event": e.event, "task": e.task,
                     "detail": e.detail, "ms": e.ms, "job_id": e.job_id,
                     "at": e.created_at.isoformat() if e.created_at else None,
                     "ts": e.created_at.timestamp() if e.created_at else 0.0} for e in rows]
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"durable events read failed: {e}")
        return []


def _durable_jobs(limit_jobs: int = 20) -> list:
    """Reconstruct a jobs-list from the durable timeline (finished jobs only — live ones
    live in memory and take precedence in jobs_list)."""
    evs = _durable_events()
    by_job: dict = {}
    for e in evs:   # newest-first
        jid = e["job_id"]
        g = by_job.setdefault(jid, {"job_id": jid, "label": jid, "status": "done",
                                    "updated": e["ts"], "error": ""})
        if e["event"] == "job_start" and e.get("detail"):
            g["label"] = e["detail"]
        elif e["event"] == "job_fail":
            g["status"] = "failed"; g["error"] = (e.get("detail") or "")[:400]
        # first (newest) occurrence sets updated; keep the max
        g["updated"] = max(g["updated"], e["ts"])
    out = [{**g, "progress": 100, "eta_sec": 0, "elapsed_sec": 0, "working": [], "durable": True}
           for g in by_job.values()]
    out.sort(key=lambda x: -x["updated"])
    return out[:limit_jobs]


def _durable_room(job_id: str) -> Optional[dict]:
    """Rebuild ONE past job's desks + feed + status from the durable timeline, so clicking a
    finished job in the switcher shows exactly what every persona did."""
    evs = [e for e in _durable_events(1000) if e["job_id"] == job_id]
    if not evs:
        return None
    evs_old_first = list(reversed(evs))
    label, status, error = job_id, "done", ""
    last_by_persona: dict = {}
    for e in evs_old_first:
        if e["event"] == "job_start" and e.get("detail"):
            label = e["detail"]
        elif e["event"] == "job_fail":
            status = "failed"; error = (e.get("detail") or "")[:400]
        if e["persona"] in _ROSTER_BY_ID and e["event"] in ("done", "fail", "revise"):
            last_by_persona[e["persona"]] = (e.get("detail") or e.get("task") or "")[:200]
    feed = [{"t": e["ts"], "persona": e["persona"], "event": e["event"],
             "detail": (e.get("detail") or e.get("task") or "")[:200], "ms": e.get("ms")}
            for e in evs][:60]
    return {"label": label, "status": status, "error": error,
            "last_by_persona": last_by_persona, "feed": feed}


def jobs_list() -> list:
    with _LOCK:
        out = []
        seen = set()
        for jid in list(_JOB_ORDER):
            j = _JOBS.get(jid)
            if not j:
                continue
            seen.add(jid)
            out.append({"job_id": jid, "label": j["label"], "status": j["status"],
                        "progress": _progress(j), "eta_sec": _eta(j), "error": j.get("error", ""),
                        "elapsed_sec": int(_now() - j["started"]), "updated": j["updated"],
                        "working": [p for p, st in j["personas"].items() if st["status"] == "working"]})
    # merge in past jobs the memory no longer holds (survives restarts/deploys)
    for dj in _durable_jobs():
        if dj["job_id"] not in seen:
            out.append(dj)
            seen.add(dj["job_id"])
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
        if j:
            desks = []
            for r in ROSTER:
                st = j["personas"][r["id"]]
                desks.append({**r, "status": st["status"],
                              "job_id": job_id if st["status"] == "working" else None,
                              "task": st["task"],
                              "busy_ms": int((_now() - st["since"]) * 1000) if st["since"] else 0,
                              "queued": 0, "last": st["last"]})
            return {"job_id": job_id, "label": j["label"],
                    "status": j["status"], "error": j.get("error", ""),
                    "progress": _progress(j), "eta_sec": _eta(j),
                    "elapsed_sec": int(_now() - j["started"]),
                    "desks": desks, "feed": list(j["feed"])[:60],
                    "active_jobs": [x["job_id"] for x in jl if x["status"] == "running"],
                    "jobs": jl, "ts": _now()}
    # not in memory → reconstruct from the durable timeline (a past/completed job)
    room = _durable_room(job_id) if job_id else None
    desks = []
    for r in ROSTER:
        last = (room["last_by_persona"].get(r["id"]) if room else None)
        desks.append({**r, "status": "idle", "job_id": None, "task": None,
                      "busy_ms": 0, "queued": 0, "last": last})
    return {"job_id": job_id, "label": (room["label"] if room else None),
            "status": (room["status"] if room else "idle"), "error": (room["error"] if room else ""),
            "progress": (100 if room else 0), "eta_sec": 0, "elapsed_sec": 0,
            "desks": desks, "feed": (room["feed"] if room else []),
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
