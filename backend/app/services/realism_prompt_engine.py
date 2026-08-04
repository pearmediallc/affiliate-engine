"""
Realism Prompt Engine
=====================
Turns creative intent into a BELIEVABLE (anti-slop) video-generation prompt, formatted for the
chosen model. This is the piece that separates real-looking AI video from plastic slop.

Disciplines encoded (from Runway/Kling/Veo guides + our own home-insurance UGC recipe):
  • Front-loading order: CAMERA → SUBJECT → ENVIRONMENT → LIGHTING (models weight first tokens).
  • ONE continuous physical action per clip — never "then/after that" (temporal confusion).
  • Consumer-camera imperfection (handheld, autofocus hunting, exposure pumping, compression,
    sensor noise, faded colors, no stabilization, no cinematic grade) — realism, not polish.
  • Candid/documentary feel, dense authentic environment detail, realistic skin, minimal makeup.
  • CONSISTENT entity — the exact same character/wardrobe description reused on every clip.
  • Ambient audio only (no music/narration) unless overridden.
  • Per-model dialect: Seedance uses @Image1/@Video1 mentions; Veo/Runway front-load camera;
    Kling wants a single action.

Deterministic assembly (no LLM dependency for structure) so it's reliable + testable; an optional
LLM polish can tighten wording but never change the discipline.
"""
from typing import Optional

# The anti-slop realism layer — appended for the "realistic" style. This is the core of what
# makes generated footage read as a real phone/camcorder capture instead of an AI render.
REALISM_LAYER = (
    # Pin the CAPTURE DEVICE to a modern iPhone so quality reads CONSISTENT across every render
    # (instead of a vague 'consumer phone/camcorder' that drifted between renders).
    "Shot on an iPhone 15 Pro front camera (natural iPhone color science, ~4K sharpness downscaled): "
    "handheld shake, natural autofocus hunting, exposure pumping between sun and shade, slight lens "
    "breathing, mild rolling shutter, subtle digital compression artifacts, light sensor noise, "
    "faded colors and soft contrast. No stabilization, no cinematic camera moves, no modern color "
    "grading. Candid documentary realism, natural imperfect off-center framing, believable "
    "unscripted body language, realistic skin texture with pores, minimal makeup."
)

STYLE_LAYERS = {
    "realistic": REALISM_LAYER,
    "animated": (
        "Pixar/Disney 3D animated style: stylized character with soft subsurface-scattering skin, "
        "expressive eyes, clean CGI render, soft cinematic lighting. Keep all motion and lip-sync "
        "intact (video-to-video style transfer, strength ~75%)."
    ),
    "cinematic": (
        "Clean cinematic look: smooth camera, shallow depth of field, controlled key + rim lighting, "
        "gentle color grade."
    ),
}

# audio guidance per style
AUDIO_LAYER = "Ambient/diegetic sound only — no music, no narration, no sound design."


def split_into_clips(script: str, max_words: int = 30) -> list:
    """Split a script into ~<=12s chunks on SENTENCE/action boundaries (one action per clip).
    Never splits mid-action; keeps each chunk a single continuous beat."""
    import re
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", (script or "").strip()) if s.strip()]
    clips, cur, n = [], [], 0
    for s in sents:
        w = len(s.split())
        if cur and n + w > max_words:
            clips.append(" ".join(cur)); cur, n = [], 0
        cur.append(s); n += w
    if cur:
        clips.append(" ".join(cur))
    return clips or ([script.strip()] if script and script.strip() else [])


def _mentions(model: str, n_images: int, has_video: bool) -> str:
    """Per-model reference mentions. Seedance references assets as @Image1/@Video1 in the prompt."""
    m = (model or "").lower()
    out = ""
    if "seedance" in m:
        if has_video:
            out += " @Video1"
        for i in range(n_images):
            out += f" @Image{i + 1}"
    return out


# ── Emotion → PHYSICAL, on-camera cue ─────────────────────────────────────────
# The Director writes an abstract emotion per beat (e.g. "frustration"). Handed to a video model as
# the bare adjective it reads FLAT; handed the full ad copy it reads STAGED/exaggerated. So we render
# the FEELING as a visible face/body direction (brows, jaw, mouth, shoulders) instead.
_EMOTION_CUES = {
    "frustrat":   "brows drawn together, jaw tight, tense mouth",
    "anger":      "brows lowered and pulled in, jaw set, lips pressed",
    "angry":      "brows lowered and pulled in, jaw set, lips pressed",
    "worr":       "brows raised and knitted, faint forehead tension, uneasy mouth",
    "anxi":       "brows raised and knitted, faint forehead tension, uneasy mouth",
    "stress":     "brows knitted, tight jaw, pressed lips",
    "fear":       "widened eyes, raised brows, breath held",
    "scared":     "widened eyes, raised brows, breath held",
    "sad":        "inner brows lifted, downturned mouth, heavy eyes",
    "relief":     "shoulders drop, soft exhale, easing smile",
    "reliev":     "shoulders drop, soft exhale, easing smile",
    "happy":      "genuine crow's-feet smile, lifted cheeks, bright eyes",
    "happ":       "genuine crow's-feet smile, lifted cheeks, bright eyes",
    "joy":        "genuine crow's-feet smile, lifted cheeks, bright eyes",
    "excit":      "wide bright eyes, animated open smile, lively brows",
    "surpris":    "raised brows, widened eyes, parted lips",
    "confiden":   "steady level gaze, relaxed set jaw, slight assured smile",
    "hope":       "soft lifted brows, gentle forward lean, warming smile",
    "sincere":    "soft steady eye contact, relaxed brow, gentle honest mouth",
    "warm":       "soft eyes, easy natural smile, relaxed face",
    "calm":       "relaxed brow, even gaze, unhurried soft mouth",
    "relaxed":    "relaxed brow, even gaze, unhurried soft mouth",
    "serious":    "level focused gaze, settled brow, composed mouth",
    "empath":     "softened brows, understanding eyes, gentle mouth",
    "reassur":    "soft eyes, calm nod, gentle steady smile",
}
_NEUTRAL_CUE = "relaxed natural expression, soft steady eye contact"
# intensity words in the emotion string scale how much tension/wrinkling shows, so lines that don't
# call for it stay relaxed (no permanent "angry" wrinkles on a calm sentence).
_STRONG_WORDS = ("very", "intense", "strong", "deep", "extreme", "overwhelm",
                 "furious", "terrified", "ecstatic", "desperate", "raw")
_MILD_WORDS = ("slight", "mild", "faint", "subtle", "gentle", "soft", "little", "hint")


def _emotion_cue(emotion: str = "", gesture: str = "") -> str:
    """Render a beat's abstract emotion as a VISIBLE, physical on-camera direction (brows/jaw/mouth/
    shoulders) plus any directed gesture. Never emits the bare adjective (reads flat) or the ad copy
    (reads staged). Intensity words scale added tension/wrinkles so it only shows when the line calls
    for it. Empty emotion → a neutral relaxed cue."""
    e = (emotion or "").strip().lower()
    cue = _NEUTRAL_CUE
    if e:
        cue = next((v for k, v in _EMOTION_CUES.items() if k in e), None) or _NEUTRAL_CUE
    if e and any(w in e for w in _STRONG_WORDS):
        cue += ", visible muscle tension and fine expression lines"
    elif e and any(w in e for w in _MILD_WORDS):
        cue += ", understated and barely-there"
    g = (gesture or "").strip()
    if g:
        cue += f"; {g}"
    return cue


def build_prompt(
    *,
    model: str,
    action: str,                       # the ONE continuous action for this clip
    request_type: str = "ugc",         # ugc | testimonial | broll | product | cinematic | animated | map | image | fast_cuts
    entity_desc: str = "",             # locked character/subject description (reused every clip)
    environment: str = "",             # dense authentic setting detail
    camera: Optional[str] = None,      # override; else the request-type profile's camera
    lighting: Optional[str] = None,    # override; else the profile's lighting
    line: Optional[str] = None,        # exact spoken line (for lip-sync)
    emotion: str = "",                 # the beat's abstract emotion (rendered as a physical face cue)
    gesture: str = "",                 # one natural directed gesture for the beat
    vertical: str = "",
    n_reference_images: int = 0,
    has_reference_video: bool = False,
    audio: bool = True,
    omit_spoken_line: bool = False,    # t2v per-clip path appends its OWN authoritative SPOKEN LINE, so
                                       # skip rendering 'They say exactly: "…"' here (avoids two conflicting
                                       # speech instructions). Avatar/other callers keep the line (default).
) -> str:
    """Compose a front-loaded, one-action prompt for THIS request type by pulling the matching
    STYLE PROFILE + rules from the Prompt Reference Library (not a hardcoded single style)."""
    from . import prompt_reference_library as lib
    ref = lib.retrieve(request_type, model)
    prof = ref["profile"]
    cam = camera or prof.get("camera", "vertical 9:16")
    lit = lighting or prof.get("lighting", "natural light")

    parts = []
    parts.append(f"Camera: {cam}.")                                   # 1) front-loaded camera
    if entity_desc:                                                    # 2) locked subject
        parts.append(f"Subject: {entity_desc}. Keep identical face, hair and wardrobe throughout.")
    if environment:                                                    # 3) environment
        parts.append(f"Environment: {environment}.")
    parts.append(f"Lighting: {lit}.")                                 # 4) lighting
    parts.append(f"Action (one continuous motion, no cuts): {action.strip()}.")   # 5) one action
    if line and not omit_spoken_line:
        parts.append(f'They say exactly: "{line.strip()}" with matching lip movement, '
                     f'{_emotion_cue(emotion, gesture)}.')
    parts.append(prof["look"])                                        # 6) request-type aesthetic (anti-slop)
    # NOTE: appending REALISM_LAYER here was tried and REVERTED — doubling the distortion terms on top
    # of prof["look"] pushed the model to over-distort (warped/animated faces). prof["look"] alone.
    if ref["exemplars"]:                                              # 7) reference patterns for this type
        parts.append("Follow these proven patterns: " + " ".join(ref["exemplars"]))
    if audio and prof.get("audio"):                                  # 8) audio guidance
        parts.append(f"Audio: {prof['audio']}.")
    parts.append("No on-screen text/captions/subtitles/watermarks — clean footage (captions added later).")
    prompt = " ".join(parts)
    if ref["model_rule"]:
        prompt += " " + ref["model_rule"]
    prompt += _mentions(model, n_reference_images, has_reference_video)
    # Model-aware cap: Seedance/Kie ingest long detailed prompts well (per our team's skill), so don't
    # slice off the rich craft detail at 1900; models with real limits keep the tighter cap.
    _m = (model or "").lower()
    _cap = 6000 if ("seedance" in _m or "kie" in _m or "veo" in _m) else 1900
    return prompt[:_cap]


def build_winner_clone_prompt(
    *, model: str, offer_desc: str, winner_hook: str = "", entity_desc: str = "",
    vertical: str = "", n_reference_images: int = 0, request_type: str = "ugc",
) -> str:
    """Prompt for cloning a proven winner's structure onto THIS offer (reference-to-video)."""
    action = (
        f"recreate the hook, pacing and shot structure of the proven winning ad in @Video1, "
        f"but for this offer: {offer_desc[:200]}. "
        + (f'Open on the winning hook angle: "{winner_hook[:100]}". ' if winner_hook else "")
        + "The subject is already speaking energetically from the first frame — no intro or silent lead-in"
    )
    return build_prompt(
        model=model, action=action, request_type=request_type, entity_desc=entity_desc,
        environment="authentic lived-in real-world setting for the offer",
        vertical=vertical, n_reference_images=n_reference_images, has_reference_video=True,
    )
