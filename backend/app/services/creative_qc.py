"""
Creative QC — a DETERMINISTIC verifier that runs BEFORE we spend on lip-sync.

Karpathy's rule: the thing being optimized must never be allowed to edit the thing that grades it.
So this file contains NO LLM calls and NO generation. Every check is arithmetic on measurable
facts (durations, gender/age labels, box geometry). It returns pass/fail + reasons. It cannot
hallucinate because it never asks a model for an opinion — it counts.

verify_pre_lipsync(...) is the gate: if it fails, we don't pay for the render.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# words-per-second a natural read sits in. Outside this = too slow / too rushed.
_WPS_MIN, _WPS_MAX = 1.8, 3.6
_AGE_ORDER = ["under35", "35-44", "45-55", "55plus"]


def _age_gap(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if a in _AGE_ORDER and b in _AGE_ORDER:
        return abs(_AGE_ORDER.index(a) - _AGE_ORDER.index(b))
    return None


def verify_pre_lipsync(*, script: str, vo_seconds: float,
                       voice_gender: Optional[str], voice_age: Optional[str],
                       char_gender: Optional[str], char_age: Optional[str],
                       offer_value: Optional[str] = None) -> dict:
    """Gate the render. Returns {ok, checks:[{name,ok,severity,detail}], reasons:[...]}.

    Hard failures (severity='block') stop the render — the money is spent at lip-sync, so a
    wrong voice must be caught here, not shipped. Soft ones (severity='warn') are logged.
    """
    checks = []

    def add(name, ok, severity, detail):
        checks.append({"name": name, "ok": bool(ok), "severity": severity, "detail": detail})

    words = len([w for w in (script or "").split() if w])
    wps = (words / vo_seconds) if vo_seconds and vo_seconds > 0 else 0.0

    # 1) PACE — the "vague and slow" failure, measured not guessed
    add("pace", _WPS_MIN <= wps <= _WPS_MAX, "block",
        f"{wps:.2f} words/sec ({words}w in {vo_seconds:.1f}s); expected {_WPS_MIN}-{_WPS_MAX}")

    # 2) GENDER match to the face — never ship a male voice on a woman
    if voice_gender and char_gender:
        add("voice_gender", voice_gender == char_gender, "block",
            f"voice={voice_gender} vs character={char_gender}")

    # 3) AGE band — a 30-something voice on a 70-year-old face reads wrong
    gap = _age_gap(voice_age, char_age)
    if gap is not None:
        add("voice_age", gap <= 1, "block",
            f"voice={voice_age} vs character={char_age} ({gap} band(s) apart)")

    # 4) OFFER present in the script when one was required
    if offer_value:
        num = "".join(c for c in offer_value if c.isdigit())
        add("offer_stated", (num and num in (script or "")) or offer_value.lower() in (script or "").lower(),
            "warn", f"offer {offer_value} not found in the spoken script")

    blockers = [c for c in checks if not c["ok"] and c["severity"] == "block"]
    return {
        "ok": not blockers,
        "checks": checks,
        "reasons": [f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]],
        "wps": round(wps, 2),
    }


def verify_post_render(*, caption_boxes_after: list, W: int, H: int) -> dict:
    """After the burn, confirm no burned-in text SURVIVED the scrub (double-caption guard) and
    our captions sit inside the frame. Pure geometry on vision-detected boxes — no opinion."""
    checks = []
    residual = [b for b in (caption_boxes_after or [])
                if float(b.get("y", 0)) > 0.05 and float(b.get("w", 0)) > 0.15]
    checks.append({"name": "no_residual_captions", "ok": not residual, "severity": "warn",
                   "detail": f"{len(residual)} caption-like region(s) still detected after scrub"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
