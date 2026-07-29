"""
Script DNA — distilled from the team's REAL proven scripts. Two layers:

  • CRAFT_DNA — the UNIVERSAL converting craft/tone (personal-story hooks, real specifics,
    conversational peer voice, objection handling, direct CTA). This is transferable to ANY vertical,
    so it's applied to EVERY script request. Distilled from the home-insurance corpus, but the *craft*
    it captures is not HI-specific.
  • VERTICAL_NEED — the vertical-SPECIFIC pain + offer mechanism + signature specifics. Only verticals
    with a real distilled corpus have one (home insurance today). A vertical without one still gets the
    full craft, plus a directive to adapt it to that vertical's own pain/offer.

Add a new vertical's NEED by distilling its scripts; the craft layer already covers it.
"""

# Universal — the CRAFT the proven scripts share, applied to every script regardless of vertical.
CRAFT_DNA = """SCRIPT CRAFT (how our proven scripts convert — apply to EVERY script, any vertical):
TONE: Conversational, authentic, peer-to-peer. Open on a personal anecdote of frustration or surprise. Empowering + lightly urgent — "don't make my mistake / you're not alone." Never corporate, stiff, or salesy.
STRUCTURE (beats): 1) personal/relatable hook (a short story) -> 2) name the problem plainly -> 3) the simple fix / offer mechanism -> 4) show it's fast + easy -> 5) concrete proof (REAL numbers, a specific result) -> 6) direct CTA -> 7) reassurance (removes the obvious objection).
SPECIFICITY (this is what makes it convert — never be vague): be concrete, but ONLY with specifics the user actually gave (their offer, their numbers, their story). NEVER FABRICATE: do not invent a person's name, a city/state, a company, or a dollar amount the user did not provide — invented specifics are false claims, not craft. When the user gave no number or name, stay truthful and generic ("save on your rate", "in a couple of minutes", "a friend told me") rather than making one up. Quantified time is fine when generic ("two minutes"). Vague waffle is dead; so is fabrication.
HOOK PATTERNS (pick one; vary across variations): personal story; direct question to the viewer; shared frustration; social-proof reveal (do NOT name a specific person unless the user provided one — use "a friend"/"someone I know"); targeted "this is for you if..." statement.
CTA: direct + imperative; restate the speed and the benefit; end on reassurance (no obligation / no catch).
AVOID (kills conversion): vague claims with no numbers; corporate jargon; making it sound slow or complicated; a generic impersonal ad voice; listing product features instead of the viewer's benefit; ignoring the obvious objection.
VARIETY (mandatory — this is a STYLE GUIDE, not a template): vary the hook, the opening line, the story, the specifics, and the sentence structure on EVERY script — never reuse a fixed opening or a canned template sentence. Two scripts for the same offer must read like they were written by different people, not minor edits of each other."""

# Vertical-specific NEED/offer — distilled from that vertical's own scripts. Craft (above) is added on top.
VERTICAL_NEED = {
    "home insurance": """HOME-INSURANCE NEED + OFFER (layer this onto the craft — a STYLE GUIDE, NOT a script to copy):
PAIN: Homeowners feel overcharged and powerless as rates climb every year and loyalty goes unrewarded.
DESIRE: financial relief + peace of mind with the SAME coverage.
MECHANISM: a quick online comparison — enter zip, compare quotes, find a lower rate.
VARY EVERY TIME (critical): do NOT return the same script twice. "My bill jumped again / a friend mentioned checking rates / it took two minutes / same coverage / enter your zip" is ONE possible take — NOT THE script. Reusing that opening or sequence verbatim is the defect we are fixing. Change the hook, the story, the trigger, the specifics, and the phrasing on every script.
ROTATE (draw from these as PATTERNS, never the same combo twice, never all at once): triggers ("after hail season", "my escrow went up", "on a fixed income", "renewal-letter sticker shock", a claim near a neighbor); proof framings ("comparable coverage", "kept my same deductible", "hundreds less" — only if truthful, never an invented figure); social proof ("a friend", "my neighbor", "someone at work") — only when truthful and never a named/located person the user didn't provide.""",
}


def style_guide(vertical: str) -> str:
    """Return the DNA to inject for a script in this vertical: ALWAYS the universal craft, PLUS the
    vertical-specific need if we have one — otherwise a directive to adapt the craft to this vertical's
    own pain/offer. Never empty, so every script (any vertical) carries the proven converting craft."""
    key = (vertical or "").strip().lower().replace("-", " ").replace("_", " ")
    need = None
    for k, v in VERTICAL_NEED.items():
        if k == key:
            need = v
            break
    if need:
        return CRAFT_DNA + "\n" + need
    if key and key != "general":
        return (CRAFT_DNA + f"\nVERTICAL: {vertical}. Apply the craft above to THIS vertical — open on "
                f"its core pain, state its offer/mechanism plainly. Use specifics that fit {vertical} "
                f"ONLY when the user provided them; never invent numbers, names, or places.")
    return CRAFT_DNA
