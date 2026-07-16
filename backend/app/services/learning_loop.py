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


def record_verdict(db, creative_ref: str, verdict: str, reason: str = "") -> int:
    """The human's decision as a label (used wherever ROI is absent).

    ANTI-NOISE: a 'regenerated'/'rejected' verdict is NOT a blanket loss for the whole
    creative. We interpret the reason into the specific brains it blames and store that set
    in `blamed_brains`; per-brain labelling (below) then makes it a loss ONLY for those
    brains — every other brain stays UNLABELED. An ambiguous reason attributes NOTHING
    ('[]'), so it trains no brain and only counts as a creative-level stat. 'accepted' clears
    blamed_brains (a win for every brain). Enums normalized on write."""
    try:
        import json
        from ..models.creative_team import CreativeDecision
        from .feedback_attribution import attribute
        from datetime import datetime
        verdict = (verdict or "").strip().lower()
        blamed_json = None
        if verdict in ("regenerated", "rejected"):
            blamed_json = json.dumps(attribute(reason))   # [] when nothing is clearly blamed
        rows = db.query(CreativeDecision).filter(CreativeDecision.creative_ref == creative_ref).all()
        for r in rows:
            r.human_verdict = verdict
            r.human_reason = (reason or "")[:500]
            r.blamed_brains = blamed_json      # None for 'accepted' → win for all brains
            r.verdict_at = datetime.utcnow()
        db.commit()
        return len(rows)
    except Exception as e:
        logger.warning(f"[learn] record_verdict failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def _label(r) -> Optional[int]:
    """The training label for one decision, best-signal-first:
       real ROI if we have it, else the human verdict. None = no signal yet (ignored)."""
    if r.roi is not None:
        return 1 if r.roi >= _WIN_ROI else 0
    if r.human_verdict:
        return 1 if r.human_verdict == "accepted" else 0
    return None


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


# brain -> the CreativeDecision column that brain's choice lives in. pacing is intentionally
# absent: there is no discrete, recoverable 'pacing option' at log time (it's a per-read tempo
# nudge), so pacing is attribution-only — it can be blamed but never ranked.
BRAIN_COLUMN = {
    "voice_cast": "voice_id",
    "footage_cast": "character_key",
    "script_write": "script_mode",
    "caption_place": "caption_method",
    "caption_remove": "caption_removal_method",
    "lipsync": "lipsync_provider",
}


def _blamed(r) -> Optional[set]:
    """The blamed-brain set for a row, or None if attribution was never computed.
    None (accepted / ROI-only / legacy) and '[]' (ambiguous) are DIFFERENT: see _brain_label."""
    raw = getattr(r, "blamed_brains", None)
    if raw is None:
        return None
    try:
        import json
        v = json.loads(raw) if isinstance(raw, str) else raw
        return set(v or [])
    except Exception:
        return None


def _brain_label(r, brain: str) -> Optional[int]:
    """The training label for ONE brain on ONE creative. This is where the anti-noise rules live.
       1 = win, 0 = loss, None = no signal for THIS brain (excluded from that brain's ranking).

       Rule 4  ROI present → holistic, overrides the human verdict, labels EVERY brain.
       Rule 3  'accepted'  → win for EVERY brain (nothing was wrong).
       Rule 1  'regenerated'/'rejected' → loss ONLY for brains named by the interpreter.
       Rule 2  ambiguous ('[]') → trains NO brain. Legacy rows (no attribution) also train no
               brain — an un-attributed human loss must never penalize a specific brain."""
    if r.roi is not None:
        return 1 if r.roi >= _WIN_ROI else 0
    v = r.human_verdict
    if not v:
        return None
    if v == "accepted":
        return 1
    blamed = _blamed(r)          # regenerated / rejected
    if not blamed:               # None (legacy) or empty (ambiguous)
        return None
    return 0 if brain in blamed else None


def _rank_brain(db, brain: str, vertical: Optional[str], column: Optional[str] = None) -> dict:
    """{value: {n, wins, score, signal}} for one brain, labelled the anti-noise way. `column`
    overrides the mapping (used for video_model, which has no attribution brain and so only ever
    wins from ROI/accepted — never a human loss)."""
    col = column or BRAIN_COLUMN.get(brain)
    if not col:
        return {}
    from ..models.creative_team import CreativeDecision
    from sqlalchemy import or_
    q = db.query(CreativeDecision).filter(
        or_(CreativeDecision.roi.isnot(None), CreativeDecision.human_verdict.isnot(None)))
    if vertical:
        q = q.filter(CreativeDecision.vertical == vertical)
    agg: dict = {}
    for r in q.all():
        v = getattr(r, col, None)
        lab = _brain_label(r, brain)
        if not v or lab is None:
            continue
        a = agg.setdefault(v, {"n": 0, "wins": 0, "roi_n": 0})
        a["n"] += 1
        a["wins"] += lab
        if r.roi is not None:
            a["roi_n"] += 1
    for v, a in agg.items():
        a["score"] = round(_wilson(a["wins"], a["n"]), 4)
        a["signal"] = "roi" if a["roi_n"] == a["n"] else ("mixed" if a["roi_n"] else "human")
    return agg


def voice_scores(db, vertical: Optional[str] = None) -> dict:
    """{voice_id: score} — how well each voice has performed. Empty until ROI exists."""
    return {v: a["score"] for v, a in _rank_brain(db, "voice_cast", vertical).items()}


def character_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank_brain(db, "footage_cast", vertical).items()}


def model_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank_brain(db, "video_model", vertical, column="video_model").items()}


def script_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank_brain(db, "script_write", vertical).items()}


def caption_scores(db, vertical: Optional[str] = None) -> dict:
    return {v: a["score"] for v, a in _rank_brain(db, "caption_place", vertical).items()}


def creative_aggregate(db, vertical: Optional[str] = None) -> dict:
    """Creative-LEVEL stats (not per-brain): every labelled creative counts here, including the
    ambiguous 'make it better' verdicts that train no brain. This is where rule 2's excluded
    signal still lands."""
    from ..models.creative_team import CreativeDecision
    from sqlalchemy import or_
    q = db.query(CreativeDecision).filter(
        or_(CreativeDecision.roi.isnot(None), CreativeDecision.human_verdict.isnot(None)))
    if vertical:
        q = q.filter(CreativeDecision.vertical == vertical)
    n = wins = 0
    for r in q.all():
        lab = _label(r)
        if lab is None:
            continue
        n += 1
        wins += lab
    return {"n": n, "wins": wins, "win_rate": round(wins / n, 4) if n else None}


def summary(db, vertical: Optional[str] = None) -> dict:
    """What the brain reads — small per-brain aggregates, not history."""
    return {
        "voices": _rank_brain(db, "voice_cast", vertical),
        "characters": _rank_brain(db, "footage_cast", vertical),
        "models": _rank_brain(db, "video_model", vertical, column="video_model"),
        "scripts": _rank_brain(db, "script_write", vertical),
        "captions": _rank_brain(db, "caption_place", vertical),
        "caption_removal": _rank_brain(db, "caption_remove", vertical),
        "creative": creative_aggregate(db, vertical),
    }


def decisions_for_job(db, request_id: str) -> list:
    """What the Learner recorded for ONE job (request_id) — the per-job learning signal:
    the QC gate result, the ROI once the platform reports it, and the human's verdict, plus
    the casting/voice/model choices those outcomes attach to. Read-only; never raises."""
    try:
        from ..models.creative_team import CreativeDecision
        rows = (db.query(CreativeDecision)
                  .filter(CreativeDecision.request_id == request_id)
                  .order_by(CreativeDecision.created_at.asc()).all())
        out = []
        for r in rows:
            label = _label(r)   # 1 = win, 0 = loss, None = no outcome yet
            out.append({
                "creative_ref": r.creative_ref, "vertical": r.vertical,
                "qc_passed": r.qc_passed, "qc_reasons": r.qc_reasons,
                "roi": r.roi, "roi_updated_at": r.roi_updated_at.isoformat() if r.roi_updated_at else None,
                "human_verdict": r.human_verdict, "human_reason": r.human_reason,
                "verdict_at": r.verdict_at.isoformat() if r.verdict_at else None,
                "outcome": ("win" if label == 1 else "loss" if label == 0 else "pending"),
                "voice_id": r.voice_id, "voice_provider": r.voice_provider, "voice_cloned": r.voice_cloned,
                "character_key": r.character_key, "character_gender": r.character_gender,
                "character_age": r.character_age, "video_model": r.video_model,
                "cost_usd": r.cost_usd,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out
    except Exception as e:
        logger.warning(f"[learn] decisions_for_job failed: {e}")
        return []
