"""
Vertical style-DNA — the tone, need, and requirements distilled from the team's REAL proven scripts,
so new scripts carry the same converting qualities instead of vague generic copy. This is the DNA,
NOT the scripts: a writer follows it to produce fresh scripts, never to copy the originals. Refresh
by re-distilling a vertical's scripts from the script database when the winning style shifts.
"""

# Distilled from all of the Home-Insurance team's proven scripts (personal-story UGC, Texas-heavy).
HOME_INSURANCE_DNA = """HOME-INSURANCE SCRIPT DNA — match this converting style; do NOT copy the source scripts.
TONE: Conversational, authentic, peer-to-peer. Open on a personal anecdote of frustration or surprise. Empowering + lightly urgent — "don't make my mistake / you're not alone." Never corporate or salesy.
NEED IT TAPS: Homeowners feel overcharged and powerless as rates climb every year and loyalty goes unrewarded. The desire is financial relief + peace of mind with the SAME coverage. The mechanism is a quick online comparison — enter zip, compare quotes, find a lower rate.
STRUCTURE (beats most scripts follow): 1) personal/relatable hook (a short story) -> 2) name the problem (rising bill, loyalty punished) -> 3) the simple online fix (compare quotes) -> 4) show it's fast/easy ("two minutes", "enter your zip") -> 5) concrete savings proof (real dollar numbers, "same coverage") -> 6) direct CTA -> 7) reassurance (no agent, no calls, no commitment).
SPECIFICITY (use concretely): real dollar amounts (e.g. "$289/mo down to $62/mo"); quantify time ("two minutes", "20 seconds"); real places (Texas, San Antonio, "your zip code"); life/season triggers ("after hail season", "mortgage went up", "fixed income", "a neighbor mentioned it"); "same / comparable coverage"; relatable archetypes ("my dad", "my neighbor Linda").
HOOK PATTERNS (pick one, vary across variations): personal story; direct question ("when did you last actually compare your rate?"); shared frustration ("that bill just keeps getting bigger"); neighbor / social-proof reveal; targeted statement ("Texas homeowners who pay their bills on time...").
CTA STYLE: direct + imperative — "Tap below", "Enter your [state] zip code", "See what rates come up for your home." Restate the speed and the benefit, and end on reassurance (no obligation, no spam).
AVOID (these make it vague / non-converting): vague savings or process with no numbers; corporate jargon; making it sound slow or complicated; a generic impersonal ad voice; selling the tool's features instead of the homeowner's benefit; ignoring objections (spam calls, commitment, losing coverage)."""

_DNA = {
    "home insurance": HOME_INSURANCE_DNA,
}


def style_guide(vertical: str) -> str:
    """Distilled style-DNA block for a vertical, or '' if none defined. Case/spacing/underscore
    tolerant. The Script Writer injects this so scripts match the vertical's proven converting DNA."""
    key = (vertical or "").strip().lower().replace("-", " ").replace("_", " ")
    for k, v in _DNA.items():
        if k.replace("_", " ") == key:
            return v
    return ""
