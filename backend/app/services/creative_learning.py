"""
Creative Learning — the self-learning failure memory (the outer/bilevel loop).
Every failure or wrongdoing (a job that failed, a Critic rejection, a wrong/forced path, a cost
overrun) is recorded here with WHY it happened and the corrective RULE. Deduped by signature so a
repeat just increments `hits`. The brain reads applicable lessons before every job and folds them
into its plan, so the same mistake never recurs. Nothing is hardcoded-final: the seed Playbook is
the base, these lessons are the living, growing layer on top. All DB ops best-effort.
"""
from __future__ import annotations
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _sig(scope: str, rule: str, style: str = "") -> str:
    return hashlib.sha1(f"{scope}|{style}|{(rule or '').lower().strip()[:120]}".encode()).hexdigest()[:20]


def record_lesson(scope: str, *, trigger: str = "", reason: str = "", rule: str = "",
                  style: str = "", engine: str = "", vertical: str = "", job_id: str = "") -> None:
    """Log a failure + its corrective rule. Repeats increment hits instead of duplicating."""
    if not (rule or reason or trigger):
        return
    try:
        from ..database import SessionLocal
        from ..models.creative_team import CreativeLesson
        sig = _sig(scope, rule or reason, style)
        db = SessionLocal()
        try:
            row = db.query(CreativeLesson).filter(CreativeLesson.sig == sig).first()
            if row:
                row.hits = (row.hits or 1) + 1
                row.active = True
                if trigger and not row.trigger:
                    row.trigger = trigger[:1000]
            else:
                db.add(CreativeLesson(
                    sig=sig, scope=scope, style=style or None, engine=engine or None,
                    vertical=vertical or None, trigger=(trigger or "")[:1000],
                    reason=(reason or "")[:1000], rule=(rule or "")[:1000], job_id=job_id or None))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"record_lesson failed: {e}")


def get_lessons(*, scope: str = "", style: str = "", vertical: str = "", limit: int = 10) -> list:
    """Applicable lessons for the brain to obey — most-repeated first (biggest recurring pains)."""
    try:
        from sqlalchemy import or_
        from ..database import SessionLocal
        from ..models.creative_team import CreativeLesson as L
        db = SessionLocal()
        try:
            q = db.query(L).filter(L.active == True)  # noqa: E712
            if scope:
                q = q.filter(L.scope == scope)
            if style:
                q = q.filter(or_(L.style == style, L.style.is_(None)))
            if vertical:
                q = q.filter(or_(L.vertical == vertical, L.vertical.is_(None)))
            rows = q.order_by(L.hits.desc(), L.updated_at.desc()).limit(limit).all()
            return [{"scope": r.scope, "style": r.style, "engine": r.engine, "vertical": r.vertical,
                     "reason": r.reason, "rule": r.rule, "hits": r.hits} for r in rows]
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"get_lessons failed: {e}")
        return []


def lessons_for_prompt(style: str = "", vertical: str = "") -> str:
    """Compact 'lessons learned' block injected into the brain's reasoning so it avoids past mistakes."""
    ls = get_lessons(style=style, vertical=vertical, limit=8)
    if not ls:
        return ""
    lines = [f"- ({l['scope']}) {l['rule']}" + (f"  [seen {l['hits']}x]" if (l['hits'] or 0) > 1 else "")
             for l in ls if l.get("rule")]
    return ("LESSONS LEARNED — you MUST obey these to avoid repeating past failures:\n" + "\n".join(lines)) if lines else ""


def learned_engine_avoid(style: str = "", vertical: str = "") -> set:
    """Engines that have repeatedly failed for this style/vertical → the router avoids them."""
    avoid = set()
    for l in get_lessons(scope="engine", style=style, vertical=vertical, limit=20):
        if l.get("engine") and (l.get("hits") or 0) >= 2:
            avoid.add(l["engine"])
    return avoid
