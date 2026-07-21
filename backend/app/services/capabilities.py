"""
Provider/model capability matrix — the SINGLE, declared source of truth for what each video model
can actually do AS THIS CODE INVOKES IT. Routing then decides on REQUIREMENTS (does this request need
audio? a given mode?), not just availability + cost. Before this, "which model produces audio" lived
only in a comment, so the t2v fallback happily routed to a silent model when the audio-capable one was
down. Declaring capabilities as DATA makes that mistake structurally impossible.

IMPORTANT — capability is about the ENDPOINT WE CALL, not the model's marketing:
  • fal-seedance uses fal's seedance-v1-LITE endpoint → SILENT, even though Seedance 2.0 elsewhere
    has native audio. kie-seedance calls Kie's Seedance-2 endpoint WITH generate_audio → audible.
  • kling-v3 / wan-2.2 / hailuo-02 / luma-ray-2 / seedance-2 are invoked here through Higgsfield's
    image→video (DOP) path → SILENT, regardless of a given model's standalone audio feature.
Verified audio flags (provider docs, 2026): Google Veo 3.1 = native 48kHz audio; Kie Seedance-2 =
native audio; Hailuo 02 / Wan / Runway Gen-4 / Luma Ray-2 = silent.

Fields per provider:
  audio   — produces a native/spoken audio track (True) or silent video (False) ON OUR CALL PATH
  modes   — generation modes we use it for: t2v (text→video), i2v (image→video), ref2v (reference set)
  max_sec — max clip seconds per single call
"""

VIDEO_CAPS = {
    # ── audio-capable (native sound + dialogue) ──────────────────────────────────
    "kie-seedance": {"audio": True,  "modes": {"t2v", "i2v", "ref2v"}, "max_sec": 15},
    "kie-veo":      {"audio": True,  "modes": {"t2v", "i2v"},          "max_sec": 8},   # Veo 3.1 via Kie
    "veo-3.1":      {"audio": True,  "modes": {"t2v", "i2v"},          "max_sec": 8},   # Veo via MultiProvider/Google
    "veo-3.1-fast": {"audio": True,  "modes": {"t2v", "i2v"},          "max_sec": 8},

    # ── silent (video only — sound must be muxed/added) ──────────────────────────
    "fal-seedance": {"audio": False, "modes": {"t2v", "i2v"}, "max_sec": 10},   # fal seedance-v1-lite endpoint
    "fal-kling":    {"audio": False, "modes": {"t2v", "i2v"}, "max_sec": 10},   # fal kling v2.1
    "fal-wan":      {"audio": False, "modes": {"t2v"},        "max_sec": 5},
    "higgsfield-v1":{"audio": False, "modes": {"i2v"},        "max_sec": 8},
    "kling-v3":     {"audio": False, "modes": {"i2v"},        "max_sec": 10},   # invoked via Higgsfield DOP i2v
    "wan-2.2":      {"audio": False, "modes": {"i2v"},        "max_sec": 6},
    "hailuo-02":    {"audio": False, "modes": {"i2v"},        "max_sec": 6},
    "luma-ray-2":   {"audio": False, "modes": {"i2v"},        "max_sec": 5},
    "seedance-2":   {"audio": False, "modes": {"ref2v", "i2v"}, "max_sec": 10}, # via Higgsfield DOP (silent path)
    "runway-gen4":  {"audio": False, "modes": {"i2v", "t2v"}, "max_sec": 10},
}


def known(provider: str) -> bool:
    """Is this provider declared in the matrix? Used to WARN when a configured provider is missing —
    an undeclared provider would otherwise fail-open through every requirement check (a stale-matrix
    footgun). Warn, don't block: a new model should still run, just visibly-unverified."""
    return provider in VIDEO_CAPS


def provides_audio(provider: str) -> bool:
    """True only if this provider is DECLARED to produce a native audio track on our call path."""
    return bool(VIDEO_CAPS.get(provider, {}).get("audio"))


def audio_capable(providers: list) -> list:
    """Subset of `providers` (order preserved) that produce native audio."""
    return [p for p in providers if provides_audio(p)]


def satisfies(provider: str, *, needs_audio: bool = False, mode: str = None) -> bool:
    """Does this provider's DECLARED capability meet the hard requirements? Undeclared providers
    fail-OPEN (returned True) so a brand-new model isn't silently dropped before its caps are added
    — but a KNOWN model that can't do what's asked (fal-wan + audio) is correctly rejected. Pair with
    known()/a startup check so the fail-open is visible, not silent."""
    caps = VIDEO_CAPS.get(provider)
    if caps is None:
        return True
    if needs_audio and not caps.get("audio"):
        return False
    if mode and caps.get("modes") and mode not in caps["modes"]:
        return False
    return True


def filter_by_requirements(providers: list, *, needs_audio: bool = False, mode: str = None) -> list:
    """Keep only providers whose capabilities satisfy the hard requirements, preserving order."""
    return [p for p in providers if satisfies(p, needs_audio=needs_audio, mode=mode)]
