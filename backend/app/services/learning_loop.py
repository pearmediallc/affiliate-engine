"""
Learning loop — the part that makes the engine improve instead of repeating itself.

Karpathy's three parts:
  • STATE     : log_decision() writes one CreativeDecision row per creative.
  • VERIFIER  : ROI (from the ad platform) is the objective metric — set by attach_roi().
  • LOOP      : voice_scores()/character_scores() rank options by the ROI they actually earned,
                so casting/voice picks bend toward winners over time.

Ranking is pure arithmetic (a Wilson lower bound on win-rate) — NO LLM in this path, so it cannot
hallucinate a preference. Cold start returns nothing, so today's behavior is unchanged until data
exists. The brain reads these AGGREGATES, never raw rows, so nothing bloats a prompt.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

_WIN_ROI = 1.0   # ROI ≥ 1.0 = a winning creative


def log_decision(db, **kw) -> None:
    """Append one decision. Never raises into the render path."""
    try:
        from ..models.creative_team import CreativeDecision
        db.add(CreativeDecision(**{k: v for k, v in kw.items() if v is not None or k in ("qc_passed", "captions")}))
        db.commit()
    except Exception as e:
        logger.warning(f"[learn] log_decision failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def attach_roi(db, creative_ref: str, roi: float) -> int:
    """Stitch platform ROI back onto the decision(s) for a delivered creative."""
    try:
        from ..models.creative_team import CreativeDecision
        from datetime import datetime
        rows = db.query(CreativeDecision).filter(CreativeDecision.creative_ref == creative_ref).all()
        for r in rows:
            r.roi = roi
            r.roi_updated_at = datetime.utcnow()
        db.commit()
        return len(rows)
    except Exception as e:
        logger.warning(f"[learn] attach_roi failed: {e}")
        return 0


def _wilson(wins: int, n: int) -> float:
    """Lower bound of a 95% CI on win-rate. One lucky win on n=1 scores low; a steady 8/10 scores
    high. This is what stops a single fluke from hijacking the ranking."""
    if n == 0:
        return 0.0
    z = 1.96
    p = wins / n
    return (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def _rank(db, column, vertical: Optional[str]) -> dict:
    """{value: {n, wins, score}} for a decision column, over creatives that HAVE an ROI yet."""
    from ..models.creative_team import CreativeDecision
    q = db.query(CreativeDecision).filter(CreativeDecision.roi.isnot(None))
    if vertical:
        q = q.filter(CreativeDecision.vertical == vertical)
    agg: dict = {}
    for r in q.all():
        v = getattr(r, column)
        if not v:
            continue
        a = agg.setdefault(v, {"n": 0, "wins": 0})
        a["n"] += 1
        a["wins"] += 1 if (r.roi or 0) >= _WIN_ROI else 0
    for v, a in agg.items():
        a["score"] = round(_wilson(a["wins"], a["n"]), 4)
    return agg


def voice_scores(db, vertical: Optional[str] = None) -> dict:
    """{voice_id: score} — how well each voice has performed. Empty until ROI exists."""
    return {v: a["score"] for v, a in _rank(db, "voice_id", vertical).items()}


def character_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank(db, "character_key", vertical).items()}


def model_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank(db, "video_model", vertical).items()}


def summary(db, vertical: Optional[str] = None) -> dict:
    """What the brain reads — small aggregates, not history."""
    return {
        "voices": _rank(db, "voice_id", vertical),
        "characters": _rank(db, "character_key", vertical),
        "models": _rank(db, "video_model", vertical),
    }
