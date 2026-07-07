"""
Creative Metrics — how we judge a creative (home-insurance affiliate rules)
==========================================================================
Encodes the judging model from the media team, so both the eval loop and the outcome grader
speak the same language. Editable constants (no logic changes needed to tune thresholds).

Rules captured (from the team head):
  • $500 minimum spend before ANY metric is trustworthy.
  • Judge order: Profit → RPL → State → Offer CR → CPC (per state/tier) → EPC (tiered) → hook>hold.
  • Offer CR (percentage) ≥ 30 is the ultimate judge of a creative's CPC.
      – EXCEPTION: if LP-CTR drops, CPC can't be judged (downstream LP issue, NOT the creative).
  • Offer CR difference < 30 → it's a DELIVERY problem (character / voice / lip-sync not landing).
  • EPC (percentage) is tiered: tier-1 states need ≥ 6; lower-tier states profitable at ≥ 3.5.
  • CPC < 1 AND CTR > 3 → Advantage+ placement is sending junk audience (diagnostic, not a win).
  • If CPC is under control, CPM basically doesn't matter.
  • Creative fatigue at 4–6 weeks → regenerate.
  • Payout ≥ $50 → separate logs.
  • Image creatives are judged ONLY on CTR + CPC.
  • Character casting: 45+ woman preferred (man ok); if younger, always woman with some sensuality.

Metric unit conventions (per the team): CR and EPC are PERCENTAGES (e.g. 30 means 30, not 0.30).
hook_rate / hold_rate / ctr may arrive as ratios (0.32) — helpers normalize to percent.
"""
from __future__ import annotations

from typing import Optional

# ── tunable constants ─────────────────────────────────────────────────────────
MIN_SPEND = 500.0                 # $ minimum before judging anything
OFFER_CR_JUDGE = 30.0             # % — CR ≥ this validates CPC; CR diff < this = delivery fault
EPC_TARGET_TIER1 = 6.0           # % — tier-1 states
EPC_TARGET_OTHER = 3.5           # % — lower-tier states
CPC_JUNK = 1.0                    # $ — with high CTR, signals Advantage+ junk audience
CTR_JUNK = 3.0                    # % — paired with low CPC → junk audience
FATIGUE_WEEKS = (4, 6)           # creative fatigue window
HIGH_PAYOUT = 50.0               # $ — offers at/above this get separate logs

# Tier-1 home-insurance affiliate states: high premiums / catastrophe exposure / high payout /
# heavy shopping intent. Editable — the team can move states between tiers.
STATE_TIER1 = {
    "TX", "CO", "FL", "CA", "GA", "AZ", "LA", "OK", "NC", "SC",
}
_ABBR = {  # a few full-name → abbr conveniences (extend as needed)
    "texas": "TX", "colorado": "CO", "florida": "FL", "california": "CA", "georgia": "GA",
    "arizona": "AZ", "louisiana": "LA", "oklahoma": "OK", "north carolina": "NC", "south carolina": "SC",
}


def _norm_state(state: str) -> str:
    s = (state or "").strip()
    if len(s) == 2:
        return s.upper()
    return _ABBR.get(s.lower(), s.upper()[:2])


def tier_of(state: str) -> int:
    return 1 if _norm_state(state) in STATE_TIER1 else 2


def epc_target(state: str) -> float:
    return EPC_TARGET_TIER1 if tier_of(state) == 1 else EPC_TARGET_OTHER


def as_pct(v: Optional[float]) -> Optional[float]:
    """Normalize a rate to a percentage: 0.32 → 32, 32 → 32, None → None."""
    if v is None:
        return None
    return v * 100 if -1.0 <= v <= 1.0 else v


def roi_pct(revenue: Optional[float], spend: Optional[float]) -> Optional[float]:
    """ROI as a percentage = (revenue - spend) / spend * 100. (Not ROAS.)"""
    if not spend:
        return None
    return (float(revenue or 0) - float(spend)) / float(spend) * 100.0


def eligible(spend: Optional[float]) -> bool:
    return float(spend or 0) >= MIN_SPEND


def judge_creative(m: dict, *, is_image: bool = False) -> dict:
    """Judge one creative's metrics against the team model. `m` may contain:
    spend, revenue, offer_cr, offer_cr_baseline, epc, cpc, ctr, lp_ctr, lp_ctr_baseline,
    hook_rate, hold_rate, state, payout, age_weeks. Returns a structured verdict."""
    spend = float(m.get("spend") or 0)
    state = m.get("state", "")
    verdict: dict = {"eligible": eligible(spend), "state": _norm_state(state), "tier": tier_of(state),
                     "notes": [], "faults": [], "diagnostics": []}
    if not verdict["eligible"]:
        verdict["notes"].append(f"Under ${MIN_SPEND:.0f} spend — not judgeable yet ({spend:.0f}).")
        return verdict

    roi = roi_pct(m.get("revenue"), spend)
    verdict["roi_pct"] = roi
    verdict["profitable"] = (roi is not None and roi > 0)

    # Image creatives → only CTR + CPC matter.
    if is_image:
        verdict["scope"] = "image (CTR + CPC only)"
        verdict["ctr_pct"] = as_pct(m.get("ctr"))
        verdict["cpc"] = m.get("cpc")
        _placement_check(m, verdict)
        return verdict

    # Offer CR is the ultimate judge of CPC — UNLESS LP-CTR dropped (then CPC isn't judgeable).
    lp_ctr = as_pct(m.get("lp_ctr")); lp_base = as_pct(m.get("lp_ctr_baseline"))
    lp_dropped = (lp_ctr is not None and lp_base is not None and lp_ctr < lp_base)
    cr = as_pct(m.get("offer_cr")); cr_base = as_pct(m.get("offer_cr_baseline"))
    verdict["offer_cr_pct"] = cr

    if lp_dropped:
        verdict["notes"].append("LP-CTR dropped → CPC not judgeable; issue is the landing page, "
                                "NOT the creative. No persona penalized.")
        verdict["cpc_judgeable"] = False
    else:
        verdict["cpc_judgeable"] = True
        if cr is not None:
            if cr >= OFFER_CR_JUDGE:
                verdict["notes"].append(f"Offer CR {cr:.0f}% ≥ {OFFER_CR_JUDGE:.0f}% → CPC is valid.")
            else:
                # CR difference below threshold → DELIVERY fault (character / voice / lip-sync).
                diff = (cr - cr_base) if cr_base is not None else cr
                if diff < OFFER_CR_JUDGE:
                    verdict["notes"].append(f"Offer CR low ({cr:.0f}%) → delivery problem "
                                            "(character/voice/lip-sync not landing).")
                    verdict["faults"].append({"reason": "low_offer_cr_delivery",
                                              "personas": ["character", "shots", "scriptwriter"]})

    # EPC vs tiered target.
    epc = as_pct(m.get("epc"))
    if epc is not None:
        tgt = epc_target(state)
        verdict["epc_pct"] = epc; verdict["epc_target"] = tgt
        verdict["epc_ok"] = epc >= tgt
        verdict["notes"].append(f"EPC {epc:.1f} vs tier-{verdict['tier']} target {tgt} → "
                                + ("ok" if epc >= tgt else "below target"))

    # hook > hold priority.
    hook = as_pct(m.get("hook_rate")); hold = as_pct(m.get("hold_rate"))
    if hook is not None:
        verdict["hook_pct"] = hook; verdict["hold_pct"] = hold
        if hook < 25:  # weak hook is a script/direction problem
            verdict["faults"].append({"reason": "weak_hook", "personas": ["scriptwriter", "scene", "director"]})
            verdict["notes"].append(f"Weak hook ({hook:.0f}%) → hook is worth more than hold; fix the first 2s.")

    # payout log flag + fatigue.
    if float(m.get("payout") or 0) >= HIGH_PAYOUT:
        verdict["diagnostics"].append(f"High payout (≥${HIGH_PAYOUT:.0f}) → separate log.")
    wk = m.get("age_weeks")
    if wk is not None and wk >= FATIGUE_WEEKS[0]:
        verdict["fatigued"] = True
        verdict["diagnostics"].append(f"Creative is {wk}wk old (fatigue at {FATIGUE_WEEKS[0]}–{FATIGUE_WEEKS[1]}wk) → regenerate.")

    _placement_check(m, verdict)
    return verdict


def _placement_check(m: dict, verdict: dict) -> None:
    cpc = m.get("cpc"); ctr = as_pct(m.get("ctr"))
    if cpc is not None and ctr is not None and float(cpc) < CPC_JUNK and ctr > CTR_JUNK:
        verdict["diagnostics"].append(
            f"CPC ${float(cpc):.2f} < ${CPC_JUNK} with CTR {ctr:.1f}% > {CTR_JUNK}% → "
            "Advantage+ placement likely sending junk audience (not a creative win).")


# Character casting guidance for the Character Manager persona (from the team).
CHARACTER_CASTING = (
    "Casting rules: prefer a 45+ woman (a man is acceptable too). If a younger character is used, "
    "it must be a woman with some tasteful sensuality. Real, ordinary, un-retouched — never model-like."
)
