"""
Creative Playbook — the brain's COMPLETE knowledge of what it can make, which path to use, and
what resources each path needs. The Creative Director consults this before every job so it never
picks a path we can't execute or a resource we don't have (a wrong pick wastes credits + burns
credibility). This is the single editable source of truth; the Learner may append to it.

Three questions the Playbook answers for any request:
  1. WHAT style/variation is being asked for?           → VARIATION_STYLES
  2. WHICH engine/path produces it (and at what cost)?  → ENGINES
  3. WHAT resources does that path need?                → RESOURCES
Plus the hard POLICY every choice must respect, and route() which turns intent → a concrete plan.
"""
from __future__ import annotations
from typing import Optional

# ── 0. PROJECT MISSION — why this engine exists (the brain reasons WITH this, not generically) ──
MISSION = (
    "You are the creative brain of ORBIT — the in-house creative-regeneration engine for a "
    "direct-response AFFILIATE media buyer running home_insurance, bizop and refinance offers. "
    "PURPOSE: take a LOSING ad and regenerate a WINNER — keep the offer, fix only the lagging "
    "metric — by reusing our OWN proven assets: real avatars (our Top-Avatar library, casting: "
    "45-55 woman preferred, else a tasteful younger female), proven scripts (the script_database), "
    "state maps, and vertical b-rolls. Mirror how our human editors actually work: pick a real "
    "reference character → a timeframe-based script → ElevenLabs voice → lip-sync → minor touchups — "
    "but automated. NON-NEGOTIABLES: it must look REAL (anti-slop, one consistent character, no "
    "stray captions, hook in 2s); it must be CHEAP (480p, prefer avatar-lipsync, avoid Veo for bulk, "
    "no wasted retries) because we win on ROI (offer-CR%, EPC by state tier, $500 min spend to judge); "
    "and it must be ACCURATE — a wrong engine/asset/casting choice wastes credits and burns "
    "credibility, so consult the Playbook + Lessons and never invent a path we can't run."
)

# ── 1. Every generation / variation STYLE we can produce ──────────────────────
# cost: $ (cheap) → $$$$ (expensive). engine → key in ENGINES. resources → keys in RESOURCES.
VARIATION_STYLES = {
    "avatar_lipsync": {
        "what": "A locked real avatar (from the library) re-voiced with TTS and lip-synced to a script.",
        "engine": "avatar_lipsync", "resources": ["asset_avatars", "script_database", "tts", "asset_maps", "asset_brolls"],
        "cost": "$", "identity": "exact", "when": "talking-head variation of an existing character — the DEFAULT for cheap, on-brand UGC."},
    "full_ad": {
        "what": "Full ~30-45s ad rebuilt from a loser: script → beats → per-beat clips → stitch → captions.",
        "engine": "seedance", "resources": ["winner_library", "asset_maps", "asset_brolls"],
        "cost": "$$$", "identity": "anchored", "when": "rebuild a losing creative end-to-end when no reusable avatar fits."},
    "generate_prompt": {
        "what": "Direct prompt (+optional reference image/video) → video (Studio).",
        "engine": "seedance", "resources": ["asset_library"], "cost": "$$",
        "when": "user gives a prompt/reference and wants a net-new clip."},
    "remix": {
        "what": "Any library/winner clip + an instruction → a variation (reference-to-video).",
        "engine": "seedance", "resources": ["asset_library", "winner_library"], "cost": "$$",
        "when": "'make the hook better / use this style / mash these up' on an existing clip."},
    "create_from_assets": {
        "what": "User's scenic images + a script → narrated, stitched, captioned video.",
        "engine": "image_to_video", "resources": ["tts"], "cost": "$$",
        "when": "user supplies their own images + script."},
    "map_ugc": {
        "what": "Talking-head + a state-map insert on the geo beat.",
        "engine": "avatar_lipsync", "resources": ["asset_avatars", "asset_maps", "tts"], "cost": "$",
        "when": "the script references a specific state/region."},
    "multi_state_batch": {
        "what": "One character, N state variations (script + state map swapped per state).",
        "engine": "avatar_lipsync", "resources": ["asset_avatars", "asset_maps", "script_database", "tts"],
        "cost": "$ x N", "when": "'make this for all 50 states'."},
    "hook_change": {"what": "Swap only the first 2s hook on real footage.", "engine": "seedance",
        "resources": ["winner_library"], "cost": "$", "when": "hook_rate is the lagging metric."},
    "caption_change": {"what": "Overlay a new CTA caption on the original.", "engine": "ffmpeg",
        "resources": [], "cost": "$", "when": "lift CTR with a sharper on-screen CTA."},
    "reclean": {"what": "Remaster/clean the original (no new generation).", "engine": "ffmpeg",
        "resources": [], "cost": "$", "when": "minor fix / cleanup."},
    "script_rewrite": {"what": "Rewrite the script + re-voice over original visuals.", "engine": "tts",
        "resources": ["script_database", "tts"], "cost": "$", "when": "message/offer clarity fix."},
    "broll": {"what": "Topic-matched b-roll clip + caption.", "engine": "seedance",
        "resources": ["asset_brolls", "winner_library"], "cost": "$$", "when": "supporting/proof insert."},
    "veo_long": {"what": "Long/continuous video via Veo native extend (up to 148s).", "engine": "veo_extend",
        "resources": [], "cost": "$$$$", "when": "ONLY when long continuous motion is required — expensive."},
    "image": {"what": "Static image creative.", "engine": "image_gen", "resources": [], "cost": "$",
        "when": "image ad; judged on CTR + CPC only."},
    "image_voiceover": {"what": "Image(s) + voiceover.", "engine": "image_to_video",
        "resources": ["tts"], "cost": "$$", "when": "image ad with narration."},
}

# ── 2. Engines / paths, capabilities, cost, provider, status ──────────────────
ENGINES = {
    "avatar_lipsync": {"desc": "Real avatar clip + TTS audio → re-lipsynced talking video.",
        "provider": "latentsync|sync.so|infinitalk", "cost": "$", "identity": "exact",
        "status": "planned", "caps": "matches audio length exactly; keeps the real person",
        "best_for": ["talking-head variation", "same character across many states"]},
    "seedance": {"desc": "ByteDance Seedance 2.0 (Kie) — reference-to-video + image-to-video.",
        "provider": "kie", "cost": "$$", "status": "live", "caps": "4-15s/clip; stitch clips for longer; refs: image+video+audio",
        "best_for": ["net-new talking/scene from prompt+refs", "winner-clone", "remix"]},
    "veo_extend": {"desc": "Google Veo 3.1 base clip + native +7s extends.", "provider": "google",
        "cost": "$$$$", "status": "live", "caps": "up to ~148s; ~$6-11 per 15s — EXPENSIVE",
        "best_for": ["long continuous / cinematic extend"], "avoid": "bulk / cost-sensitive runs"},
    "image_to_video": {"desc": "Animate a still image into motion.", "provider": "veo3-kie|kling|higgsfield",
        "cost": "$$", "status": "live", "best_for": ["scenic image → clip"]},
    "image_gen": {"desc": "Generate a static image.", "provider": "flux|gemini", "cost": "$", "status": "live"},
    "tts": {"desc": "Text-to-speech voice.", "provider": "openai(cheap default)|elevenlabs(premium)",
        "cost": "~$0.01-0.30", "status": "live"},
    "lip_sync": {"desc": "Image/video + audio → talking video.", "provider": "latentsync|sync.so|infinitalk|higgsfield",
        "cost": "$", "status": "partial (image lip-sync live; video re-lipsync = build)"},
    "ffmpeg": {"desc": "Transcode / stitch / caption / trim — no model cost.", "cost": "$0", "status": "live"},
}

# ── 3. Resources the brain can draw on (how to fetch each) ────────────────────
RESOURCES = {
    "asset_library": {"what": "Tagged reference clips (avatars/maps/brolls/hooks/voices).",
        "query": "GET /assets?kind=&usable_as=&age_band=&gender=&state_code=&vertical="},
    "asset_avatars": {"what": "Lip-sync-ready avatars, filter by age_band/gender/face_score.",
        "query": "GET /assets?kind=avatar&usable_as=avatar_lipsync&age_band=&gender="},
    "asset_maps": {"what": "State map clips.", "query": "GET /assets?kind=map&state_code="},
    "asset_brolls": {"what": "B-roll by vertical.", "query": "GET /assets?kind=broll&vertical="},
    "script_database": {"what": "Proven scripts (serials + state variants + tree, approved/tested).",
        "query": "script_database table (vertical, state_code, approved)"},
    "winner_library": {"what": "Competitor winners (scraper).", "query": "GET /winners?vertical="},
    "tts": {"what": "Voices (OpenAI default / ElevenLabs premium)."},
}

# ── Hard POLICY — every choice must respect these (money + credibility) ────────
POLICY = {
    "casting": "Prefer a 45-55 woman (man acceptable); if younger, a female with balanced, tasteful presence. Keep ONE identity across a set.",
    "cost": "480p by default. Single clip unless a longer duration is explicitly requested. Prefer avatar_lipsync (cheapest, exact identity) over Seedance for talking variations. NEVER use Veo for bulk. Retry a clip only on a real Critic-flagged defect.",
    "quality": "No on-screen text/captions unless asked. Hook in the first 2 seconds, no silent lead-in. Anti-slop realism. Consistent character/wardrobe across clips.",
    "judging": "$500 minimum spend before judging. ROI (not ROAS); offer-CR% is the CPC judge; EPC tiered (TX/CO=6, else 3.5); hook > hold; image = CTR+CPC only.",
    "never": "Never pick an engine marked status!=live for actual generation. Never exceed the requested/available resources. Never bypass the office (every job is planned + audited).",
}


# ── Editors' UGC style REFERENCE (patterns distilled from the team's working doc) ──
# These are ADAPTIVE patterns, not fixed copy. Always fill them with the ACTUAL vertical,
# offer, value and details from the request — never reproduce any example's specifics
# (state, dollar amounts, exact CTA wording) verbatim.
EDITOR_PLAYBOOK = (
    "EDITORS' UGC STYLE REFERENCE (patterns to adapt to THIS request's vertical/offer/value — "
    "never copy the illustrative specifics):\n"
    "- SCRIPT ARC (shape, not script): Hook → Problem → Realization → Solution (quick, low-effort "
    "action) → Result (a concrete, believable outcome for THIS offer) → CTA (one clear next step "
    "for THIS funnel). First-person, spoken, one idea per sentence.\n"
    "- PERFORMER STYLES to choose from: fast-talking woman in a living room (rapid, hand gestures, "
    "room echo, selfie phone); casual man walking outdoors (handheld bounce, grainy); two-person "
    "kitchen conversation (warm indoor light). Pick one that fits the avatar and stay consistent.\n"
    "- HOOK PATTERNS: relatable pattern-interrupt in the first line tailored to the audience; "
    "slip-and-catch; news-anchor format; neighbor-story with b-roll beats. (Write the actual line "
    "from the request, don't reuse an example.)\n"
    "- AUTHENTICITY MARKERS (the core strategy): raw, no grading/filter, imperfect framing, autofocus "
    "breathing, natural skin texture, slight handheld shake, mild compression/grain, real ambience.\n"
    "- HARD NEGATIVES: NO subtitles/captions/on-screen text; no plastic AI skin, no robotic lip-sync, "
    "no polished commercial look, no distorted hands, no frozen expressions."
)


# ── Cost discipline the brain must obey (so we out-produce humans WITHOUT burning money) ──
COST_MODEL = (
    "COST DISCIPLINE — pick the cheapest path that meets the quality bar:\n"
    "- REUSE our own tagged footage + regenerate script/voice/lip-sync BY DEFAULT (~$0.03–0.10 each). "
    "Only generate net-new video when no suitable asset exists (~25% of volume). New-video costs "
    "(Kie Seedance 480p official): ~$0.86/15s WITH an image/video input vs ~$1.43 text→video — so "
    "prefer image→video (with-input) mode, and cheaper fal models (Wan ~$0.07/s, Kling) when quality allows.\n"
    "- Lip-sync routing: BULK → Replicate LatentSync (~$0.09) / Wav2Lip (~$0.03) — cheapest at volume; "
    "PREMIUM/hero only → sync.so (~$0.70). NEVER Veo for bulk ($6–11).\n"
    "- Voice: OpenAI/Deepgram (pennies) before ElevenLabs. Captions: ffmpeg ASS (free) before VEED.\n"
    "- 480p default; single clip unless a longer duration is explicitly required; retry a clip ONLY on a "
    "real Critic-flagged defect (never speculative re-renders).\n"
    "- Respect the engine's concurrency cap + monthly budget ceiling; ~$0.50/creative all-in is the target."
)


# ── US direct-response affiliate VERTICAL knowledge (audience · pain · angle · offer · compliance · hook) ──
# The brain reads the matching brief so scripts speak the vertical's real language and stay compliant.
VERTICALS = {
    "home_insurance": "US homeowners (often 45-65, TX/FL/CO high-cost states). Pain: premiums rising yearly with no claims. Angle: compare/switch to cut the bill; 'you're overpaying'. Offer: free rate comparison by zip (lead gen, CPC/EPC). Hook: 'If you own a home in [state] and your insurance keeps going up…'. Compliance: no guaranteed-savings claims, no fake carrier logos, savings are 'may/could'.",
    "auto_insurance": "US drivers (25-65). Pain: rates jump despite clean record. Angle: 2-min quote comparison, drivers switching save. Offer: free auto quote by zip/age. Hook: 'Drivers in [state] are switching and saving…'. Compliance: 'may save', no guaranteed rates, no impersonating GEICO/Progressive.",
    "health_insurance": "US 18-64 uninsured/underinsured, ACA-eligible. Pain: can't afford coverage. Angle: subsidies/credits many qualify for; check eligibility. Offer: ACA subsidy/plan finder (lead). Hook: 'You may qualify for a $0 health plan…'. Compliance: NOT govt-affiliated, 'may qualify', no ACA/gov logos, licensed-agent disclaimers.",
    "medicare": "US seniors 65+ (and turning 65). Pain: confusing Advantage/Supplement choices, missing benefits. Angle: extra benefits (dental/vision/OTC/flex card) they may be leaving on the table. Offer: free plan review by a licensed agent. Hook: 'Seniors on Medicare may qualify for extra benefits…'. Compliance: NOT Medicare/CMS, 'may be eligible', TPMO disclaimers, no scare tactics.",
    "life_insurance": "US 45-75, final-expense/burial focus. Pain: leaving family with funeral costs. Angle: affordable coverage, no-exam, locks in rate. Offer: free quote (lead). Hook: 'Cover your final expenses for about a dollar a day…'. Compliance: 'rates vary', no guaranteed acceptance unless true, no fear-mongering.",
    "refinance": "US homeowners with a mortgage. Pain: high rate/payment, want cash-out or lower payment. Angle: check today's rate, could lower payment. Offer: free refi quote by zip (lead). Hook: 'Homeowners are lowering their payment by…'. Compliance: 'may qualify', APR/NMLS where required, no guaranteed rates.",
    "personal_loans": "US adults needing cash (debt, emergency). Pain: high-interest debt, need funds fast. Angle: check your rate, no impact to score. Offer: loan/rate marketplace (lead). Hook: 'See your personal loan rate in 60 seconds — won't hurt your credit'. Compliance: 'checking rate is a soft pull', representative APR, no guaranteed approval.",
    "debt_relief": "US adults with $10k+ unsecured debt. Pain: drowning in credit-card debt. Angle: programs to reduce/consolidate what you owe. Offer: free debt assessment (lead). Hook: 'If you owe over $10,000 in credit cards…'. Compliance: not credit repair, results vary, no 'erase your debt' guarantees.",
    "solar": "US homeowners (sunny/high-utility states). Pain: rising electric bills. Angle: incentives/programs may cover install; slash the bill. Offer: free solar savings estimate by zip (lead). Hook: 'Homeowners in [state] are getting solar for little to nothing…'. Compliance: incentives vary by eligibility, no guaranteed 'free', no fake govt-program claims.",
    "bizop": "US 25-55 seeking income/work-from-home. Pain: paycheck-to-paycheck, want extra/replacement income. Angle: simple system, real people making money from home, low start. Offer: free training/webinar or app signup. Hook: 'This stay-at-home mom makes $___/week doing…'. Compliance: income disclaimers ('results not typical'), no get-rich-quick guarantees, no fake testimonials.",
    "credit_repair": "US adults with poor credit. Pain: denied for loans/apartments. Angle: dispute errors, raise your score. Offer: free credit consultation (lead). Hook: 'Boost your credit score by removing errors…'. Compliance: results vary, cannot remove accurate items, CROA disclaimers.",
    "auto_warranty": "US owners of older/out-of-warranty cars. Pain: costly repairs after factory warranty ends. Angle: protect against big repair bills. Offer: free vehicle protection quote. Hook: 'If your car is out of warranty, one repair could cost…'. Compliance: it's a service contract not insurance, not the manufacturer, coverage varies.",
}


# ── Camera-movement prompt reference (from aicameramovements.com) — the Shot Selector / Prompt
# Writer pulls the exact phrasing for a shot when a movement suits the beat. Reference, not default. ──
CAMERA_MOVES = {
    "static": "locked-off static shot. hold one fixed camera position for the full clip.",
    "pan right": "pan right. rotate the camera horizontally left→right from one fixed point.",
    "pan left": "pan left. rotate the camera horizontally right→left from one fixed point.",
    "whip pan": "whip pan. rotate rapidly from the current direction toward a new target.",
    "tilt up": "tilt up. rotate the camera upward from one fixed point.",
    "tilt down": "tilt down. rotate the camera downward from one fixed point.",
    "slow zoom in": "slow zoom in. slowly increase focal length toward a tighter frame.",
    "slow zoom out": "slow zoom out. slowly decrease focal length toward a wider frame.",
    "crash zoom": "crash zoom. snap the lens rapidly toward the main visual target.",
    "dolly in": "dolly in. move the camera physically forward toward the subject.",
    "dolly out": "dolly out. move the camera physically backward away from the subject.",
    "tracking": "tracking shot. move through the scene with the main subject.",
    "follow (OTS)": "follow shot from behind. move behind the subject at shoulder height.",
    "reverse tracking (walk-and-talk)": "reverse tracking shot. move backward in front of the walking subject.",
    "side tracking": "side tracking shot. move parallel beside the subject.",
    "truck": "truck left/right. move the camera physically sideways on a straight horizontal path.",
    "pedestal": "pedestal up/down. move the whole camera vertically in a straight line.",
    "arc": "arc left/right. move on a shallow curved path around the subject.",
    "orbit": "orbit clockwise/counter-clockwise. circle the subject at a consistent radius.",
    "handheld": "handheld shot. camera at operator height with natural body movement (UGC feel).",
    "snorricam": "body-mounted Snorricam. camera fixed relative to the subject's face/torso.",
    "crane": "crane up/down. travel smoothly through open space vertically.",
    "drone push in": "drone push in. fly smoothly forward through open space toward the subject.",
    "drone pull back": "drone pull back. fly smoothly backward away from the subject.",
    "aerial": "helicopter-style aerial. move from high altitude along a broad gradual flight path.",
    "FPV": "first-person view. move forward at eye height from the character's perspective.",
    "push past": "push past. move forward past a visible foreground object/edge into the space beyond.",
}


def camera_reference() -> str:
    """Camera-movement vocabulary the brain can apply when a shot calls for motion (else keep it
    steady/handheld for UGC authenticity). Reference — use only when it fits the beat."""
    picks = ["handheld", "slow zoom in", "dolly in", "tracking", "orbit", "arc", "crane", "drone push in", "FPV", "static"]
    lines = "; ".join(f"{k} → {CAMERA_MOVES[k]}" for k in picks if k in CAMERA_MOVES)
    return ("CAMERA-MOVEMENT REFERENCE (apply only when a move suits the beat; default to steady/handheld "
            f"for UGC authenticity): {lines}")


def vertical_brief(vertical: str) -> str:
    """The researched context line for a vertical (audience/angle/offer/compliance) — the brain uses
    it so scripts speak the vertical's real DR language and stay compliant. Falls back gracefully."""
    v = _slug_vertical(vertical)
    ctx = VERTICALS.get(v)
    if not ctx:
        return (f"VERTICAL: {vertical or 'direct-response'} — write a benefit-led, first-person DR ad; "
                "make claims soft ('may/could'), no guarantees, no impersonating brands/gov, add income/results disclaimers if relevant.")
    return f"VERTICAL CONTEXT ({v}): {ctx}"


def _slug_vertical(v: str) -> str:
    s = (v or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"homeowners_insurance": "home_insurance", "home_ins": "home_insurance",
               "aca": "health_insurance", "obamacare": "health_insurance",
               "final_expense": "life_insurance", "burial": "life_insurance",
               "mortgage": "refinance", "refi": "refinance", "loans": "personal_loans",
               "make_money_online": "bizop", "work_from_home": "bizop", "mmo": "bizop"}
    return aliases.get(s, s)


def _norm(request_type: str) -> str:
    rt = (request_type or "").strip().lower().replace(" ", "_").replace("/", "_").replace("-", "_")
    alias = {
        "full_ad": "full_ad", "avatar_ugc": "avatar_lipsync", "avatar": "avatar_lipsync",
        "ugc": "avatar_lipsync", "map___ugc": "map_ugc", "map_+_ugc": "map_ugc", "map_ugc": "map_ugc",
        "generate_video": "generate_prompt", "generate": "generate_prompt", "remix": "remix",
        "create_from_assets": "create_from_assets", "hook_change_only": "hook_change",
        "caption_change_only": "caption_change", "reclean_minor_mod": "reclean", "script": "script_rewrite",
        "broll": "broll", "stock_video": "broll", "image": "image", "image___voiceover": "image_voiceover",
        "image_+_voiceover": "image_voiceover", "veo": "veo_long", "special_request": "generate_prompt",
    }
    return alias.get(rt, rt if rt in VARIATION_STYLES else "generate_prompt")


def route(*, request_type: str = "", vertical: str = "", has_real_character: bool = False,
          needs_talking: bool = True, needs_state: bool = False, has_winner_video: bool = False,
          duration: int = 15, prefer_cheap: bool = True, engine_hint: str = "") -> dict:
    """Turn an intent into a CONCRETE, executable plan. Deterministic so it can't hallucinate a path
    we don't have. Returns {style, engine, resources, resolution, voice, notes, cost, confidence}."""
    style = _norm(request_type)
    spec = dict(VARIATION_STYLES.get(style, VARIATION_STYLES["generate_prompt"]))
    engine = spec["engine"]

    # honor an explicit engine hint if it's live
    if engine_hint:
        eh = engine_hint.lower()
        if "veo" in eh:
            engine, style = "veo_extend", "veo_long"
        elif "seedance" in eh:
            engine = "seedance"

    # cost-aware substitution: a talking variation with a real avatar available → avatar_lipsync (cheapest)
    if needs_talking and has_real_character and engine == "seedance" and prefer_cheap and engine_hint == "":
        engine, style = "avatar_lipsync", "avatar_lipsync"

    resources = list(spec.get("resources", []))
    if needs_state and "asset_maps" not in resources:
        resources.append("asset_maps")

    notes = []
    if engine == "avatar_lipsync" and ENGINES["avatar_lipsync"]["status"] != "live":
        notes.append("avatar_lipsync path is not yet wired → falling back to Seedance reference-to-video for now.")
        engine = "seedance"
    if engine == "veo_extend":
        notes.append("Veo is expensive ($$$$) — only for long continuous motion; avoid for bulk.")

    return {
        "style": style, "engine": engine, "resources": resources,
        "resolution": "480p" if prefer_cheap else "720p",
        "voice": "openai" if prefer_cheap else "elevenlabs",
        "cost": spec.get("cost", "$$"),
        "casting": POLICY["casting"],
        "notes": " ".join(notes), "confidence": 0.9 if style in VARIATION_STYLES else 0.5,
    }


def summary_for_prompt() -> str:
    """A compact playbook the Creative Director reads each run so it knows EVERY path + rule."""
    styles = ", ".join(sorted(VARIATION_STYLES.keys()))
    live = ", ".join(k for k, v in ENGINES.items() if v.get("status") == "live")
    return (
        MISSION + "\n\n"
        "CREATIVE PLAYBOOK (choose only from these; never invent a path):\n"
        f"- Styles you can make: {styles}.\n"
        f"- LIVE engines: {live}. avatar_lipsync is preferred for talking variations (cheapest, exact "
        "identity) — fall back to Seedance if unavailable. Veo is $$$$ (long-form only, avoid bulk).\n"
        f"- Resources: tagged asset library (avatars by age/gender/face, maps by state, brolls by "
        "vertical, voices), script_database, winner_library.\n"
        f"- POLICY: {POLICY['casting']} {POLICY['cost']} {POLICY['quality']}\n\n"
        + EDITOR_PLAYBOOK + "\n\n" + COST_MODEL + "\n\n" + camera_reference()
    )


def describe() -> dict:
    """Full playbook (for the UI / an endpoint) so the office can show what the brain knows."""
    return {"styles": VARIATION_STYLES, "engines": ENGINES, "resources": RESOURCES, "policy": POLICY,
            "verticals": VERTICALS, "camera_moves": CAMERA_MOVES}
