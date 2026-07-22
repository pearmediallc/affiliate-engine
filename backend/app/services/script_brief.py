"""
Creative brief factors — the inputs that separate a SUPERB converting script from a vague one. When a
Studio user is vague ("give me a home insurance script"), the router asks for the missing factors
FIRST (with concrete options), then writes a superior script. Every option here is a REAL type /
demographic the system actually supports — not invented — so the answers map straight onto generation
(video type → recipe, audience → voice/avatar casting, geo → state map, etc.).
"""

# Real creative formats the engine produces (from the recipe set + the request types used in prod).
VIDEO_TYPES = {
    "UGC": "talking-head — a real person speaks to camera (most common, highest converting)",
    "B-Roll": "scenic / product footage with a voiceover, no talking head",
    "MAP": "US state-map creative — great for geo offers targeted by state",
    "Avatar": "an AI / library avatar lip-syncing the script",
    "Image": "a single still image / poster ad",
}

AGE_BANDS = ["under 35", "35-44", "45-55", "55+"]

SETTINGS = ["kitchen / home", "driving / in-car", "living room / couch", "front porch / outdoors",
            "office / desk", "walk-and-talk / on the street"]

ANGLES = ["personal story", "direct question to the viewer", "neighbor / social proof",
          "\"this is for you if…\" targeted", "shocking stat / number"]

TONES = ["warm & empathetic", "urgent & direct", "bold & confident", "casual & relatable"]

LENGTHS = ["15s (~40 words)", "30s (~75 words)", "45s (~110 words)"]

# The ORDERED factor checklist the flow gathers. `options=None` → an open specifics answer.
# Structured as data so a future chips/selects UI can render it directly; today it drives the router's
# question text. `key` maps to the generation param it feeds.
FACTORS = [
    {"key": "video_type", "q": "What format do you want?", "options": list(VIDEO_TYPES.keys())},
    {"key": "audience",   "q": "Target audience / age range?", "options": AGE_BANDS},
    {"key": "setting",    "q": "Where's the scene set?", "options": SETTINGS},
    {"key": "angle",      "q": "Hook / angle?", "options": ANGLES},
    {"key": "offer",      "q": "The exact offer + any real numbers to feature (savings, price, result)?", "options": None},
    {"key": "geo",        "q": "Any specific state(s) to target? (especially for MAP / geo offers)", "options": None},
    {"key": "tone",       "q": "Tone?", "options": TONES},
    {"key": "length",     "q": "How long?", "options": LENGTHS},
]


def factors_json() -> list:
    """The factor set as data — for a structured (chips/selects) follow-up UI."""
    return FACTORS


def checklist_text() -> str:
    """Compact factor checklist for the router prompt: the model asks for whichever factors the user
    hasn't already given, using THESE exact options, as a tight numbered list."""
    lines = ["CREATIVE BRIEF FACTORS — a superb script needs these. Ask for the ones the user hasn't "
             "already specified (use the given options; don't re-ask what they've told you); keep it a "
             "tight numbered list:"]
    for f in FACTORS:
        opts = (" — options: " + ", ".join(f["options"])) if f.get("options") else " — (open: specifics)"
        lines.append(f"• {f['q']}{opts}")
    return "\n".join(lines)
