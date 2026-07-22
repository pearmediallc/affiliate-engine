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
SPECIFICITY (this is what makes it convert — never be vague): use REAL, concrete specifics relevant to the vertical — real dollar amounts/results, quantified time ("two minutes", "20 seconds"), real places/names, life or seasonal triggers, and relatable archetypes ("my dad", "my neighbor Linda"). Vague = dead.
HOOK PATTERNS (pick one; vary across variations): personal story; direct question to the viewer; shared frustration; neighbor / social-proof reveal; targeted "this is for you if..." statement.
CTA: direct + imperative; restate the speed and the benefit; end on reassurance (no obligation / no catch).
AVOID (kills conversion): vague claims with no numbers; corporate jargon; making it sound slow or complicated; a generic impersonal ad voice; listing product features instead of the viewer's benefit; ignoring the obvious objection."""

# Vertical-specific NEED/offer — distilled from that vertical's own scripts. Craft (above) is added on top.
VERTICAL_NEED = {
    "home insurance": """HOME-INSURANCE NEED + OFFER (layer this onto the craft):
PAIN: Homeowners feel overcharged and powerless as rates climb every year and loyalty goes unrewarded.
DESIRE: financial relief + peace of mind with the SAME coverage.
MECHANISM: a quick online comparison — enter zip, compare quotes, find a lower rate.
SIGNATURE SPECIFICS: real dollar swings ("$289/mo down to $62/mo"); "same / comparable coverage"; "your zip code"; seasonal/life triggers ("after hail season", "mortgage went up", "fixed income", "a neighbor mentioned it"); homeowner archetypes ("my dad in San Antonio").""",
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
                f"its core pain, state its offer/mechanism plainly, and use real specifics that fit "
                f"{vertical} (real numbers, places, and relatable people for this audience).")
    return CRAFT_DNA
