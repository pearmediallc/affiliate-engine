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
    "Shot on a consumer phone/DV camcorder: handheld shake, natural autofocus hunting, exposure "
    "pumping between sun and shade, slight lens breathing, mild rolling shutter, subtle digital "
    "compression artifacts, light sensor noise, faded colors and soft contrast. No stabilization, "
    "no cinematic camera moves, no modern color grading. Candid documentary realism, natural "
    "imperfect off-center framing, believable unscripted body language, realistic skin texture "
    "with pores, minimal makeup."
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
    vertical: str = "",
    n_reference_images: int = 0,
    has_reference_video: bool = False,
    audio: bool = True,
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
    if line:
        parts.append(f'They say exactly: "{line.strip()}" with matching lip movement and natural expression.')
    parts.append(prof["look"])                                        # 6) request-type aesthetic (anti-slop)
    if ref["exemplars"]:                                              # 7) reference patterns for this type
        parts.append("Follow these proven patterns: " + " ".join(ref["exemplars"]))
    if audio and prof.get("audio"):                                  # 8) audio guidance
        parts.append(f"Audio: {prof['audio']}.")
    parts.append("No on-screen text/captions/subtitles/watermarks — clean footage (captions added later).")
    prompt = " ".join(parts)
    if ref["model_rule"]:
        prompt += " " + ref["model_rule"]
    prompt += _mentions(model, n_reference_images, has_reference_video)
    return prompt[:1900]


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
