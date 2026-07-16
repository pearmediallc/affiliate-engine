"""
Feedback attribution — the anti-noise core of the creative learning loop.

Before this module a human 'regenerated'/'rejected' verdict marked the WHOLE creative a
loss and copied the reason onto every decision, so voice/character/script/model were ALL
penalized even when only one was actually wrong. That is training noise: it teaches the
ranker to avoid a perfectly good voice because the CAPTION was bad.

`attribute()` reads the free-text feedback and returns ONLY the brains the feedback
actually blames, drawn from a FIXED enum. Everything NOT named stays UNLABELED (never
penalized). When nothing is clearly blamed it returns an EMPTY list — an ambiguous
complaint ("make it better") trains NO brain, it only counts as a creative-level stat.

Deterministic keyword matching (no LLM in this path, so it cannot hallucinate a blame).
An LLM pass is possible later but MUST be constrained to this same enum and MUST return
empty when unsure; it is intentionally NOT wired here so the signal stays reproducible.
"""
from __future__ import annotations

import re

# The only brains that can ever be blamed. Anything outside this set is impossible to emit.
BRAINS = (
    "voice_cast",       # who/how the voice sounds
    "script_write",     # the words / copy / hook
    "caption_place",    # our caption style / placement / timing
    "caption_remove",   # a leftover caption/watermark from the donor footage
    "footage_cast",     # wrong person / face / clip
    "pacing",           # too long / short / slow / fast
    "lipsync",          # mouth / lips out of sync
)

# A donor-caption complaint is MORE specific than a generic caption complaint. Matched first,
# and when it fires we do NOT also blame caption_place (they are different fixes).
_REMOVE = re.compile(
    r"\b(old caption|old subtitle|original caption|previous caption|donor caption|leftover|"
    r"still see|still show|double caption|two captions|watermark|logo|burned[- ]in)\b")

# brain -> keyword regex. Conservative on purpose: a word must clearly point at ONE brain.
_PATTERNS = [
    ("voice_cast", re.compile(
        r"\b(voice|older|younger|too young|too old|age|male|female|man|woman|guy|lady|"
        r"accent|sounds?|sound|tone|narrat|speaker|robotic|monotone|delivery)\b")),
    ("script_write", re.compile(
        r"\b(script|copy|wording|word choice|rewrite|re-write|punchier|punchy|hook|"
        r"message|messaging|the line|cta|call to action|what (?:it|she|he) says|dialog|dialogue)\b")),
    ("footage_cast", re.compile(
        r"\b(wrong person|wrong face|wrong clip|different person|not the right (?:person|clip|face)|"
        r"other actor|wrong character)\b")),
    ("pacing", re.compile(
        r"\b(too long|too short|too slow|too fast|slow|drags|rushed|pacing|the pace|duration|length)\b")),
    ("lipsync", re.compile(
        r"\b(mouth|lips|lip[- ]?sync|out of sync|not in sync|sync(?:ing)?)\b")),
    # caption_place is checked LAST and only when caption_remove did not fire (see attribute()).
    ("caption_place", re.compile(
        r"\b(caption|subtitle|text overlay|on[- ]screen text|overlap|caption timing|captions?)\b")),
]


def attribute(feedback: str) -> list:
    """free-text feedback → the set of blamed brains (subset of BRAINS).

    Returns [] when the feedback names no brain (ambiguous) — that is a deliberate signal:
    the caller must train NO brain on an unattributed complaint. Never raises.
    """
    try:
        t = (feedback or "").strip().lower()
        if not t:
            return []
        remove_hit = bool(_REMOVE.search(t))
        blamed = []
        if remove_hit:
            blamed.append("caption_remove")
        for brain, pat in _PATTERNS:
            # a donor-caption complaint is not ALSO a caption-style complaint
            if brain == "caption_place" and remove_hit:
                continue
            if pat.search(t):
                blamed.append(brain)
        # dedup, preserve order, keep only real brains
        return [b for b in dict.fromkeys(blamed) if b in BRAINS]
    except Exception:
        return []
