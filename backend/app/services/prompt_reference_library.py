"""
Prompt Reference Library
========================
The knowledge base the creative team draws on — so prompts are COMPOSED from references
per request type + model, not stamped from one hardcoded style (which produces uniform slop).

Contents (all editable data, meant to be Langfuse-versioned + grown by the Learner):
  • GLOBAL_RULES     — apply to every prompt (front-loading order, one continuous action,
                       no temporal words, no on-screen text, consistent entity).
  • STYLE_PROFILES   — one per REQUEST TYPE (ugc, testimonial, product, cinematic, animated,
                       broll, map, image, app_demo, fast_cuts). Each = guidance + keywords, NOT
                       a single fixed string. Different requests pull different profiles.
  • MODEL_RULES      — per-model dialect (Seedance @refs, Veo/Runway front-load, Kling one-action).
  • EXEMPLARS        — reference prompt PATTERNS (seeded from our editor docs + public prompt
                       guides, expressed as principles). The Learner appends winning ones.

retrieve(request_type, model) returns the bundle the Prompt Writer agent composes from.
add_exemplar()/dump() let the Learner + an admin grow it without code changes.
"""
from typing import Optional

GLOBAL_RULES = [
    "Front-load the prompt: CAMERA movement first, then SUBJECT, then ENVIRONMENT, then LIGHTING.",
    "Describe ONE continuous physical action per clip — never use 'then', 'after that', or multiple sequential actions (temporal confusion breaks video models).",
    "Keep the SUBJECT identity/wardrobe identical across every clip (consistency).",
    "No on-screen text, captions, subtitles or watermarks — captions are added afterward.",
    "Prefer believable imperfection over polish; specificity over generic description.",
]

# Per-request-type STYLE PROFILES. `look` = the aesthetic layer; `camera`/`lighting` = defaults;
# `audio` = sound guidance. These are the anti-slop DNA per type — not one recipe for everything.
STYLE_PROFILES = {
    "ugc": {
        "look": ("Shot on a consumer phone/DV camcorder: handheld shake, autofocus hunting, exposure "
                 "pumping between sun and shade, lens breathing, mild rolling shutter, compression "
                 "artifacts, light sensor noise, faded colors, soft contrast. No stabilization, no "
                 "cinematic moves, no modern grade. Candid documentary realism, imperfect off-center "
                 "framing, believable unscripted body language, realistic skin texture, minimal makeup."),
        "camera": "handheld selfie-style vertical 9:16",
        "lighting": "available natural light, uneven",
        "audio": "ambient/diegetic only — no music, no narration, no sound design",
    },
    "testimonial": {
        "look": ("Authentic first-person testimonial. Real person talking directly to camera at home, "
                 "natural micro-expressions, small honest pauses, phone-camera realism, no studio polish."),
        "camera": "handheld eye-level selfie vertical 9:16",
        "lighting": "soft window light",
        "audio": "the speaker's own voice, natural room tone",
    },
    "broll": {
        "look": ("Real-world b-roll, no faces to camera. Concrete lived-in detail, natural motion, "
                 "phone-shot realism; NOT a stock-generic clean plate."),
        "camera": "slow handheld push-in or pan, vertical 9:16",
        "lighting": "natural available light",
        "audio": "ambient only",
    },
    "product": {
        "look": ("Clean product-focused shot; the real product in a believable real setting (kitchen "
                 "counter, desk, hands). Crisp but not sterile; keep any real product text/branding."),
        "camera": "slow macro slide / gentle orbit, vertical 9:16",
        "lighting": "soft key + subtle rim",
        "audio": "ambient only",
    },
    "cinematic": {
        "look": "Cinematic commercial: shallow depth of field, controlled key + rim lighting, gentle color grade, deliberate composition.",
        "camera": "smooth dolly/crane, vertical 9:16",
        "lighting": "cinematic key + rim + practicals",
        "audio": "atmospheric bed",
    },
    "animated": {
        "look": ("Pixar/Disney 3D animated style: stylized character, soft subsurface-scattering skin, "
                 "expressive eyes, clean CGI render. For video-to-video keep all motion + lip-sync intact (strength ~75%)."),
        "camera": "animation-native framing, vertical 9:16",
        "lighting": "soft stylized 3D lighting",
        "audio": "as source",
    },
    "map": {
        "look": "Clean animated geographic map, smooth zoom to the target state highlighted, minimal, caption-free.",
        "camera": "smooth map zoom/pan, vertical 9:16",
        "lighting": "flat map render",
        "audio": "none",
    },
    "image": {
        "look": "Photorealistic still, authentic real-world detail, natural lighting, not over-retouched.",
        "camera": "vertical 9:16 still",
        "lighting": "natural",
        "audio": "none",
    },
    "fast_cuts": {
        "look": "High-energy social edit; fast 0.5–1.5s beats; punchy, real footage feel.",
        "camera": "handheld, quick reframes, vertical 9:16",
        "lighting": "natural",
        "audio": "ambient",
    },
}

# aliases: map EVERY variation-type + file-request type we actually make to a style profile,
# so each video type pulls the right references (not one hardcoded style).
_ALIAS = {
    # variation types (Variation Studio)
    "full ad": "ugc",
    "hook change only": "ugc",
    "caption change only": "ugc",        # overlay on real footage
    "reclean/minor mod": "ugc",          # remaster of real footage
    "script": "testimonial",
    "broll": "broll",
    "stock video": "broll",
    "avatar/ugc": "ugc",
    "avatar variation": "ugc",
    "ugc": "ugc",
    "map + ugc": "ugc",                   # talking-head + map insert (composer adds the map beat)
    "map": "map",
    "image": "image",
    "image + voiceover": "image",
    "special request": "ugc",            # interpreter re-routes; safe default
    # common file-request phrasings
    "b-roll": "broll", "b roll": "broll", "minor modification": "ugc",
    "product": "product", "product demo": "product", "app demo": "product",
    "cinematic": "cinematic", "commercial": "cinematic",
    "animated": "animated", "animation": "animated", "cartoon": "animated",
    "testimonial": "testimonial", "review": "testimonial",
    "fast cuts": "fast_cuts", "viral": "fast_cuts",
}

MODEL_RULES = {
    "seedance": "Reference assets are @-mentioned in the prompt: @Image1/@Image2 for identity/product, @Video1 for motion. Put mentions at the end.",
    "veo": "Front-load the camera movement; single continuous action; concise.",
    "kling": "One physical action only; describe a single seamless motion (match-cut on action if transitioning).",
    "runway": "Camera movement first, then subject, environment, lighting; motion-focused verbs.",
    "higgsfield": "Concise scene + subject; strong single motion; works from a still (image-to-video).",
}

# Seeded exemplar PATTERNS (principles distilled from our editor docs + public prompt guides).
# Not verbatim third-party text — reusable structures the Prompt Writer can imitate. Learner appends.
EXEMPLARS = [
    {"type": "ugc", "pattern": "Timed micro-beats (0-2s adjust/settle, 2-6s core line with one gesture, "
     "6-10s CTA glance) with a specific candid action per beat and dense environmental detail."},
    {"type": "ugc", "pattern": "Inject ONE natural gesture tied to a script line (e.g. hand-to-mouth throat "
     "clear on a transition) — described as a single continuous motion."},
    {"type": "map", "pattern": "Smooth zoom from continent to the highlighted target state, clean labels, no overlay text."},
    {"type": "product", "pattern": "Real hands interacting with the real product in a lived-in setting; keep product branding legible."},
    {"type": "animated", "pattern": "Video-to-video style transfer to Pixar 3D; preserve motion + lip-sync; ~75% style strength."},
]


def _norm(request_type: str) -> str:
    rt = (request_type or "ugc").strip().lower()
    rt = _ALIAS.get(rt, rt)
    return rt if rt in STYLE_PROFILES else "ugc"


def _model_family(model: str) -> str:
    m = (model or "").lower()
    for fam in ("seedance", "veo", "kling", "runway", "higgsfield"):
        if fam in m:
            return fam
    return "seedance"


def retrieve(request_type: str, model: str = "", max_exemplars: int = 3) -> dict:
    """Return the reference bundle for a request: {request_type, profile, global_rules,
    model_rule, exemplars}. The Prompt Writer composes from this — no hardcoded single style."""
    rt = _norm(request_type)
    fam = _model_family(model)
    ex = [e["pattern"] for e in EXEMPLARS if e["type"] == rt][:max_exemplars]
    return {
        "request_type": rt,
        "profile": STYLE_PROFILES[rt],
        "global_rules": GLOBAL_RULES,
        "model_rule": MODEL_RULES.get(fam, ""),
        "exemplars": ex,
    }


def add_exemplar(request_type: str, pattern: str) -> None:
    """Learner/admin grows the library at runtime (persist to DB/Langfuse in production)."""
    rt = _norm(request_type)
    if pattern and pattern.strip():
        EXEMPLARS.append({"type": rt, "pattern": pattern.strip()})


def request_types() -> list:
    return list(STYLE_PROFILES.keys())
