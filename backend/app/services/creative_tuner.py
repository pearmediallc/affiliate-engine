"""
Gated self-correction for the creative brains.

This is the analytical layer on top of learning_loop's per-brain labels. For each brain it:
  1. takes every labelled CreativeDecision for that brain (the anti-noise labels),
  2. splits them deterministically into TRAIN / HOLDOUT (md5(id) % 5 == 0 → holdout; the SAME
     split learning_service already uses — reused, not reinvented),
  3. mines a candidate rule set (preferred / avoided option values) from TRAIN ONLY,
  4. KEEPS it only if holdout agreement strictly improves over the rules currently serving,
  5. writes exactly one LearningEvent(brain=...) per keep/reject (the audit changelog),
  6. recomputes a measured promotion state: a brain may ASSERT its rules automatically only
     after clearing the bar (>=0.85 holdout agreement over >=50 holdout labels, 2 cycles in a
     row); below the bar the rules are stored but only SUGGEST.

"Making a change to the system" here means changing these GOVERNED RULES (data the engine
reads), never source code — and only through the holdout gate. Everything is wrapped so it can
never raise into the render/generation path. Cold start (no data) touches nothing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_

from .learning_service import is_holdout, _PROMOTION_AGREEMENT_BAR, _PROMOTION_MIN_HOLDOUT
from .learning_loop import BRAIN_COLUMN, _brain_label, _wilson

logger = logging.getLogger(__name__)

MIN_N = 8            # cold-start floor: an option needs >= MIN_N TRAIN labels before it can be a rule
_PREFER_BAR = 0.60   # wilson lower bound at/above which a value is "preferred"
_AVOID_BAR = 0.40    # wilson lower bound at/below which a value is "avoided"

# The brains this tuner governs. pacing is excluded (no rankable column — see learning_loop).
TUNABLE_BRAINS = [b for b in BRAIN_COLUMN.keys()]


def _labelled_rows(db, brain: str, vertical: Optional[str]) -> list:
    """(value, label, id) for every CreativeDecision that carries a label for THIS brain."""
    from ..models.creative_team import CreativeDecision
    col = BRAIN_COLUMN.get(brain)
    if not col:
        return []
    q = db.query(CreativeDecision).filter(
        or_(CreativeDecision.roi.isnot(None), CreativeDecision.human_verdict.isnot(None)))
    if vertical:
        q = q.filter(CreativeDecision.vertical == vertical)
    out = []
    for r in q.all():
        val = getattr(r, col, None)
        lab = _brain_label(r, brain)
        if not val or lab is None:
            continue
        out.append((val, lab, r.id))
    return out


def _mine_rules(train: list) -> dict:
    """Candidate governed rules from TRAIN ONLY. Wilson lower bound stops one fluke win from
    minting a 'preferred'. Only options with >= MIN_N samples can become a rule (cold-start floor)."""
    agg: dict = {}
    for val, lab, _id in train:
        a = agg.setdefault(val, {"n": 0, "wins": 0})
        a["n"] += 1
        a["wins"] += lab
    preferred, avoided = {}, []
    for val, a in agg.items():
        if a["n"] < MIN_N:
            continue
        score = round(_wilson(a["wins"], a["n"]), 4)
        if score >= _PREFER_BAR:
            preferred[val] = score
        elif score <= _AVOID_BAR:
            avoided.append(val)
    return {"preferred": preferred, "avoided": avoided}


def _agreement(rules: dict, holdout: list) -> float:
    """Fraction of holdout decisions the rules predict correctly, over the decisions the rules
    make a call on. A rule set overfit to TRAIN-only values fires on nothing in holdout → 0."""
    if not rules:
        return 0.0
    preferred = set((rules.get("preferred") or {}).keys())
    avoided = set(rules.get("avoided") or [])
    called = correct = 0
    for val, lab, _id in holdout:
        if val in preferred:
            pred = 1
        elif val in avoided:
            pred = 0
        else:
            continue
        called += 1
        if pred == lab:
            correct += 1
    return round(correct / called, 4) if called else 0.0


def _option_stats(rows: list) -> dict:
    """Per-option {n, wins, win_rate, wilson} over the given (val, lab, id) rows — the numbers the
    admin sees behind a proposed preferred/avoided call."""
    agg: dict = {}
    for val, lab, _id in rows:
        a = agg.setdefault(val, {"n": 0, "wins": 0})
        a["n"] += 1
        a["wins"] += lab
    for val, a in agg.items():
        a["win_rate"] = round(a["wins"] / a["n"], 4) if a["n"] else None
        a["wilson"] = round(_wilson(a["wins"], a["n"]), 4)
    return agg


def _trigger_creatives(db, brain: str, vertical: Optional[str], candidate: dict, limit: int = 8) -> list:
    """The specific videos that drove the pattern — each with its feedback, blame, ROI and a
    best-effort thumbnail path, so the admin can SEE why. Read-only; never raises."""
    try:
        import json
        from ..models.creative_team import CreativeDecision
        from .learning_loop import _brain_label
        from sqlalchemy import or_
        col = BRAIN_COLUMN.get(brain)
        if not col:
            return []
        watched = set((candidate.get("preferred") or {}).keys()) | set(candidate.get("avoided") or [])
        if not watched:
            return []
        q = db.query(CreativeDecision).filter(
            or_(CreativeDecision.roi.isnot(None), CreativeDecision.human_verdict.isnot(None)))
        if vertical:
            q = q.filter(CreativeDecision.vertical == vertical)
        q = q.order_by(CreativeDecision.created_at.desc())
        out = []
        for r in q.all():
            val = getattr(r, col, None)
            if not val or val not in watched:
                continue
            lab = _brain_label(r, brain)
            if lab is None:
                continue
            try:
                blamed = json.loads(r.blamed_brains) if isinstance(r.blamed_brains, str) else (r.blamed_brains or None)
            except Exception:
                blamed = None
            out.append({
                "creative_ref": r.creative_ref, "request_id": r.request_id,
                "option_value": val, "outcome": ("win" if lab == 1 else "loss"),
                "human_verdict": r.human_verdict, "feedback": r.human_reason,
                "blamed_brains": blamed, "roi": r.roi,
                "thumb_url": (f"/api/v1/regen/thumb?key={r.creative_ref}" if r.creative_ref else None),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        logger.warning(f"[tuner] trigger_creatives {brain} failed: {e}")
        return []


def _pattern_summary(brain: str, vertical: Optional[str], candidate: dict, stats: dict) -> str:
    """Plain-language 'what it noticed'."""
    pref = list((candidate.get("preferred") or {}).keys())
    av = list(candidate.get("avoided") or [])
    def _wl(v):
        a = stats.get(v) or {}
        return f"{v} ({a.get('wins', 0)}/{a.get('n', 0)})"
    parts = []
    if pref:
        parts.append("winners " + ", ".join(_wl(v) for v in pref[:5]))
    if av:
        parts.append("losers " + ", ".join(_wl(v) for v in av[:5]))
    body = "; ".join(parts) or "no strong option split"
    return f"[{brain}/{vertical or 'all'}] {body}."


def _upsert_proposal(db, brain, vertical, candidate, before, after, holdout_labels,
                     promotion_metrics, all_rows, train, holdout):
    """Create (or refresh) the single pending_admin RuleProposal for this (brain, vertical) with a
    COMPLETE evidence bundle. Idempotent: a nightly re-run refreshes the existing pending proposal
    rather than spawning duplicates. Returns the proposal id, or None."""
    from ..models.learning import RuleProposal
    stats = _option_stats(all_rows)
    watched = set((candidate.get("preferred") or {}).keys()) | set(candidate.get("avoided") or [])
    bundle = {
        "brain": brain,
        "vertical": vertical or "all",
        "created_at": datetime.utcnow().isoformat(),
        "pattern_summary": _pattern_summary(brain, vertical, candidate, stats),
        "reasoning": {
            "train_n": len(train), "holdout_n": len(holdout),
            "agreement_before": before, "agreement_after": after,
            "options": {v: stats.get(v) for v in watched},
        },
        "proposed_change": {"preferred": dict(candidate.get("preferred") or {}),
                            "avoided": list(candidate.get("avoided") or [])},
        "trigger_creatives": _trigger_creatives(db, brain, vertical, candidate),
        "promotion_state": promotion_metrics,
    }
    existing = db.query(RuleProposal).filter(
        RuleProposal.brain == brain,
        RuleProposal.vertical == (vertical or None),
        RuleProposal.status == "pending_admin").first()
    if existing:
        existing.agreement_before = before
        existing.agreement_after = after
        existing.detail_json = bundle
        return existing.id
    prop = RuleProposal(id=str(uuid.uuid4()), brain=brain, vertical=(vertical or None),
                        status="pending_admin", agreement_before=before, agreement_after=after,
                        detail_json=bundle)
    db.add(prop)
    return prop.id


def tune_brain(db: Session, brain: str, vertical: Optional[str] = None) -> dict:
    """Run the gate for one brain. Never raises — returns a status dict.

    ADMIN-APPROVAL GATE: this NEVER changes engine behavior. A holdout-improving candidate for a
    PROMOTED brain becomes a pending_admin RuleProposal (evidence bundle for the admin) — it does
    NOT write/activate a CreativeBrainRule. `agreement_before` is measured against the ACTIVE
    (admin-approved) rules the engine actually serves, so an un-approved candidate never counts as
    'in production'. Below-promotion brains tune+log+gather evidence but raise NO proposal."""
    try:
        from ..models.learning import CreativeBrainRule, LearningEvent
        rows = _labelled_rows(db, brain, vertical)
        train = [x for x in rows if not is_holdout(x[2])]
        holdout = [x for x in rows if is_holdout(x[2])]
        if not train or not holdout:
            return {"brain": brain, "vertical": vertical, "status": "insufficient_data",
                    "labelled": len(rows)}

        candidate = _mine_rules(train)

        rule_row = db.query(CreativeBrainRule).filter(
            CreativeBrainRule.brain == brain,
            CreativeBrainRule.vertical == (vertical or None)).first()
        # The rules the ENGINE actually serves = only an ACTIVE (admin-approved) rule. An unapproved
        # rule_row is inert, so 'before' is 0 until an admin approves — the candidate is judged
        # against real production behavior, never against a proposal.
        active_rules = (rule_row.rules_json if (rule_row and rule_row.active and rule_row.rules_json) else {}) or {}

        before = _agreement(active_rules, holdout)
        after = _agreement(candidate, holdout)
        improving = after > before
        holdout_labels = len(holdout)
        live_agreement = after if improving else before

        prev_metrics = (rule_row.promotion_metrics if rule_row else None) or {}
        prev_live = prev_metrics.get("live_agreement")
        consecutive_high = (live_agreement >= _PROMOTION_AGREEMENT_BAR
                            and prev_live is not None and prev_live >= _PROMOTION_AGREEMENT_BAR)
        promoted = (live_agreement >= _PROMOTION_AGREEMENT_BAR
                    and holdout_labels >= _PROMOTION_MIN_HOLDOUT and consecutive_high)
        promotion_metrics = {
            "live_agreement": live_agreement, "holdout_labels": holdout_labels,
            "agreement_threshold": _PROMOTION_AGREEMENT_BAR, "min_holdout_labels": _PROMOTION_MIN_HOLDOUT,
            "consecutive_high_cycles": consecutive_high, "prev_live_agreement": prev_live,
        }

        # Persist METRICS only — NEVER touch `active` or overwrite an approved rule's rules_json.
        # (Activation happens exclusively in the admin-approve endpoint.)
        if not rule_row:
            rule_row = CreativeBrainRule(id=str(uuid.uuid4()), brain=brain, vertical=(vertical or None))
            db.add(rule_row)
        rule_row.promoted = promoted
        rule_row.promotion_metrics = promotion_metrics
        rule_row.last_analyzed_at = datetime.utcnow()

        candidate_has_content = bool((candidate.get("preferred") or {}) or (candidate.get("avoided") or []))
        proposal_id = None
        if promoted and improving and candidate_has_content:
            proposal_id = _upsert_proposal(db, brain, vertical, candidate, before, after,
                                           holdout_labels, promotion_metrics, rows, train, holdout)

        n_pref = len(candidate.get("preferred") or {})
        n_av = len(candidate.get("avoided") or [])
        if proposal_id:
            summary = (f"[{brain}/{vertical or 'all'}] PROPOSED to admin ({n_pref} preferred, {n_av} avoided): "
                       f"holdout agreement {before:.2f} → {after:.2f} over {holdout_labels} labels "
                       f"[pending_admin — engine unchanged until approved].")
        elif improving and candidate_has_content:
            summary = (f"[{brain}/{vertical or 'all'}] candidate improves ({before:.2f} → {after:.2f}) but brain "
                       f"not promoted yet — still gathering proof; no proposal raised.")
        else:
            summary = (f"[{brain}/{vertical or 'all'}] no improving candidate: holdout agreement "
                       f"{before:.2f} vs candidate {after:.2f}; engine unchanged.")

        db.add(LearningEvent(
            id=str(uuid.uuid4()), vertical=(vertical or "all"), brain=brain, summary=summary,
            agreement_before=before, agreement_after=after,
            detail_json={"improving": improving, "promoted": promoted, "holdout_labels": holdout_labels,
                         "live_agreement": live_agreement, "proposal_id": proposal_id,
                         "candidate_preferred": n_pref, "candidate_avoided": n_av}))
        db.commit()
        return {"brain": brain, "vertical": vertical, "status": "analyzed", "improving": improving,
                "promoted": promoted, "proposal_id": proposal_id,
                "proposal_created": bool(proposal_id),
                "agreement_before": before, "agreement_after": after,
                "holdout_agreement": live_agreement, "holdout_labels": holdout_labels}
    except Exception as e:
        logger.warning(f"[tuner] tune_brain {brain}/{vertical} failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return {"brain": brain, "vertical": vertical, "status": "error", "error": str(e)[:200]}


def run_all(db: Session, verticals: Optional[list] = None) -> list:
    """Manual/nightly entry point: run every brain tuner once. `verticals` defaults to [None]
    (global). Never raises."""
    targets = verticals if verticals else [None]
    results = []
    for v in targets:
        for brain in TUNABLE_BRAINS:
            results.append(tune_brain(db, brain, v))
    return results


def governed_scores(db, brain: str, vertical: Optional[str] = None) -> dict:
    """{value: score} the engine may ASSERT — non-empty ONLY when an admin has APPROVED this
    brain's rule (row.active). Promotion alone is NOT enough: a promoted-but-unapproved brain
    returns {} here, so the engine behaves exactly as today until an admin approves. Cold start
    also returns {}. THIS is where 'engine reads only an ACTIVE rule' is enforced. Wrapped so it
    can never raise into generation."""
    try:
        from ..models.learning import CreativeBrainRule
        row = (db.query(CreativeBrainRule)
                 .filter(CreativeBrainRule.brain == brain,
                         CreativeBrainRule.vertical == (vertical or None)).first())
        if not row and vertical:                      # fall back to global rules
            row = (db.query(CreativeBrainRule)
                     .filter(CreativeBrainRule.brain == brain,
                             CreativeBrainRule.vertical.is_(None)).first())
        if not row or not row.active or not row.rules_json:
            return {}
        return dict((row.rules_json.get("preferred") or {}))
    except Exception:
        return {}


def governed_preference(db, brain: str, vertical: Optional[str] = None) -> Optional[str]:
    """The single top APPROVED preferred value for a brain (or None when no active rule / cold
    start). The pick sites for script_write / caption_place / caption_remove / footage_cast read
    this to bias a DEFAULT choice; None → the engine keeps its exact current behavior. Never raises."""
    try:
        scores = governed_scores(db, brain, vertical)
        if not scores:
            return None
        return max(scores.items(), key=lambda kv: kv[1])[0]
    except Exception:
        return None
