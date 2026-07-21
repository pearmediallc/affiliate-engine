"""
Provider/model capability matrix — the SINGLE, declared source of truth for what each video model
can actually do. Routing then decides on REQUIREMENTS (does this request need audio? a given mode?
a duration?), not just availability + cost. Before this, "which model produces audio" lived only in
a code comment, so the t2v fallback happily routed to a silent model when the audio-capable one was
down. Declaring capabilities as DATA makes that mistake structurally impossible: a model that can't
meet a hard requirement is filtered out of the candidate set before it's ever tried.

Fields per provider:
  audio   — produces a native/spoken audio track (True) or silent video (False)
  modes   — generation modes it supports: t2v (text→video), i2v (image→video), ref2v (reference set)
  max_sec — max clip seconds per single call
  res     — resolutions it can render
Override nothing here at runtime — this is reference data; keep it matched to the provider pages.
"""

VIDEO_CAPS = {
    # Kie Seedance is the ONLY t2v lane with native audio (its full reference set: image+video+audio).
    "kie-seedance": {"audio": True,  "modes": {"t2v", "i2v", "ref2v"}, "max_sec": 15, "res": {"480p", "720p", "1080p"}},
    # fal lanes are the cheap credits-out fallback — they render SILENT video (no native audio).
    "fal-seedance": {"audio": False, "modes": {"t2v", "i2v"}, "max_sec": 10, "res": {"480p", "720p"}},
    "fal-kling":    {"audio": False, "modes": {"t2v", "i2v"}, "max_sec": 10, "res": {"480p", "720p"}},
    "fal-wan":      {"audio": False, "modes": {"t2v"},        "max_sec": 5,  "res": {"480p", "720p"}},
}


def provides_audio(provider: str) -> bool:
    """True only if this provider is DECLARED to produce a native audio track."""
    return bool(VIDEO_CAPS.get(provider, {}).get("audio"))


def audio_capable(providers: list) -> list:
    """Subset of `providers` (order preserved) that produce native audio."""
    return [p for p in providers if provides_audio(p)]


def satisfies(provider: str, *, needs_audio: bool = False, mode: str = None) -> bool:
    """Does this provider's DECLARED capability meet the hard requirements? Undeclared providers
    fail-OPEN (returned True) so a brand-new model isn't silently dropped before its caps are added
    — but a KNOWN model that can't do what's asked (fal-wan + audio) is correctly rejected."""
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
