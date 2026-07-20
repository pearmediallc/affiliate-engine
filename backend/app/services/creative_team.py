"""
Internal Creative Team
======================
A knowledge-driven multi-agent "creative team" that turns a regeneration request (a losing
ad + its ROI data + winner references) into an executable SHOT PLAN — the same way our human
editing team works, but automated. It is NOT a hardcoded style loop: every creative decision
is reasoned per request, and every prompt is composed from the Prompt Reference Library
(prompt_reference_library.py) via the Realism Prompt Engine (realism_prompt_engine.py).

Roles (each a focused step; run in sequence, state passed forward):
  1. Strategist        — diagnose loser vs winner data; decide the fix (angle, what to KEEP vs change).
  2. Script Writer     — write/enhance the script (keep the offer + winning hook; fix the lagging beat).
  3. Director          — break the script into timed beats; assign scene, emotion, gesture, environment.
  4. Character Manager — lock ONE consistent character/entity descriptor reused on every beat.
  5. Shot Selector     — per beat choose shot type + source strategy (real-lipsync > real-broll >
                         image-to-video > AI scene) + request_type + model (capability-routed).
  6. Prompt Writer     — deterministic: compose each beat's prompt from the reference library.
  7. Critic            — judge each prompt for slop risk; return concrete fixes (loop until clean).
  8. Learner           — after outcomes land, append winning patterns back into the library.

The orchestrator run_creative_team() returns a CreativePlan the composer executes. Every LLM
step degrades gracefully to a deterministic heuristic if no GEMINI_API_KEY, so the plan always
builds.
"""
from __future__ import annotations

import json
import base64
import logging
from typing import Optional, Any

import httpx

import os
import asyncio

from ..config import settings
from . import prompt_reference_library as lib
from . import realism_prompt_engine as rpe
from . import creative_team_activity as act
from . import creative_metrics as cm

logger = logging.getLogger(__name__)

_GEMINI_MODEL = getattr(settings, "gemini_model", None) or "gemini-2.5-flash"

# Eval self-learning loop knobs (bounded to protect generation credits).
EVAL_PASS_THRESHOLD = float(os.getenv("EVAL_PASS_THRESHOLD", "7"))   # 0-10; below → coach + retry
MAX_BEAT_RETRIES = int(os.getenv("EVAL_MAX_RETRIES", "1"))           # extra attempts per beat


def _coach_pre(persona: str) -> str:
    """Injected 'one-on-one' preamble: the corrections this persona earned on past reviews, so it
    stops repeating the mistake (the self-improvement half of the loop)."""
    notes = act.get_coaching(persona)
    if not notes:
        return ""
    return ("COACHING — apply these corrections from prior reviews so you don't repeat them:\n- "
            + "\n- ".join(notes[:4]) + "\n\n")


# ── shared LLM plumbing ───────────────────────────────────────────────────────
# Observability: track how often we're silently falling back to heuristics (invisible degradation
# is dangerous — if Gemini fails often, ads quietly go generic). Exposed via llm_health().
_LLM_STATS = {"calls": 0, "ok": 0, "fallback": 0, "no_key": 0}


def llm_health() -> dict:
    s = dict(_LLM_STATS)
    s["fallback_rate"] = round(s["fallback"] / s["calls"], 3) if s["calls"] else 0.0
    return s


async def _read_frame_b64(fp: str) -> Optional[dict]:
    def _rd():
        with open(fp, "rb") as f:
            return base64.b64encode(f.read()).decode()
    try:
        import asyncio
        data = await asyncio.to_thread(_rd)   # don't block the event loop on disk I/O
        return {"inline_data": {"mime_type": "image/jpeg", "data": data}}
    except Exception:
        return None


async def _gemini_json(prompt: str, *, temperature: float = 0.4,
                       frames: Optional[list] = None, _retry: bool = True) -> Optional[dict]:
    """One strict-JSON call to Gemini (text, or text+frames for the vision Critic). Retries ONCE on
    failure with a valid-JSON nudge before returning None (so callers drop to heuristics). Tracks a
    fallback rate so degradation is observable, not invisible."""
    _LLM_STATS["calls"] += 1
    if not settings.gemini_api_key:
        _LLM_STATS["no_key"] += 1
        _LLM_STATS["fallback"] += 1
        return None
    parts: list = [{"text": prompt}]
    for fp in (frames or []):
        part = await _read_frame_b64(fp)
        if part:
            parts.append(part)
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_GEMINI_MODEL}:generateContent?key={settings.gemini_api_key}")
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        out = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
        _LLM_STATS["ok"] += 1
        return out
    except Exception as e:
        if _retry:
            logger.warning(f"creative_team LLM call failed ({e}); retrying once")
            _LLM_STATS["calls"] -= 1   # the retry re-counts the call
            return await _gemini_json(prompt + "\n\nReturn ONLY valid JSON matching the requested shape.",
                                      temperature=temperature, frames=frames, _retry=False)
        logger.warning(f"creative_team LLM call failed twice ({e}); using heuristic fallback")
        _LLM_STATS["fallback"] += 1
        return None


# ── Typed contracts + validation + sanitization ───────────────────────────────
# TypedDicts document each role's promised shape. They are plain dicts at runtime, so existing
# `.get()`/`[]` access (here and in the composer) keeps working — but static tooling now sees types.
try:
    from typing import TypedDict, List
    class Beat(TypedDict, total=False):
        i: int; line: str; emotion: str; gesture: str; environment: str; action: str
        request_type: str; shot_type: str; source_strategy: str; technique: str
        planned_technique: str; section: str; capability: str; model: str; prompt: str
    class Strategy(TypedDict, total=False):
        diagnosis: str; lagging_metric: str; angle: str; keep: list; change: list; fix: str
    class Plan(TypedDict, total=False):
        plan: dict; strategy: Strategy; script: str; entity_desc: str
        beats: "List[Beat]"; critique: list; request_type: str
except Exception:   # pragma: no cover — typing shim for very old runtimes
    Beat = Strategy = Plan = dict  # type: ignore

# Truncation limits (named, so they're consistent + tunable — no more scattered magic numbers).
MAX_TRANSCRIPT = 1200      # loser/original transcript chars fed to a prompt
MAX_WINNER_TX = 1200       # winner transcript chars (was inconsistently 900 vs 1200)
MAX_HOOK = 300
MAX_OFFER = 300
MAX_PROMPT = 1900          # provider prompt hard cap

# crude prompt-injection guard: transcripts/scripts can come from uploads, so strip the common
# "ignore your instructions" style overrides before they reach an LLM prompt.
import re as _re
_INJECT = _re.compile(r"(?i)\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b"
                      r".{0,30}\b(instructions?|prompts?|rules?)\b")


def _sanitize(text: str, limit: int = MAX_TRANSCRIPT) -> str:
    """Neutralize obvious prompt-injection and bound length for any user/transcript text."""
    if not text:
        return ""
    t = _INJECT.sub("[redacted]", str(text))
    t = t.replace("```", "'''")           # don't let content break out of fenced context
    return t[:limit]


_TYPE_DEFAULTS = {str: "", list: [], dict: {}, int: 0, float: 0.0, bool: False}


def _coerce(data, spec: dict) -> dict:
    """Validate/coerce an LLM dict to an expected {field: type} shape with safe defaults, so a
    malformed LLM response (e.g. `approach` as a list) becomes a typed default instead of a runtime
    crash downstream. Returns {} inputs as all-defaults."""
    data = data if isinstance(data, dict) else {}
    out = {}
    for field, typ in spec.items():
        v = data.get(field)
        if isinstance(v, typ) and not (typ is str and not isinstance(v, str)):
            out[field] = v
        elif v is not None and typ is str:
            out[field] = " ".join(map(str, v)) if isinstance(v, list) else str(v)  # salvage list→str
        else:
            out[field] = _TYPE_DEFAULTS.get(typ, None)
    return out


# ── 0. Creative Director (the smart leader) ───────────────────────────────────
async def creative_director(*, offer_desc: str, vertical: str, request_type: str,
                            model: str, winner_hook: str = "", winner_transcript: str = "",
                            available_references: Optional[dict] = None,
                            has_real_character: bool = False,
                            has_winner_video: bool = False) -> dict:
    """The leader. Sets the MASTER PLAN the rest of the team executes: the creative approach,
    which references to use where, the model routing intent, and — crucially — WHERE in the
    timeline we lip-sync a real character vs hard-cut to b-roll/map/product inserts.
    Returns {approach, reference_plan, model_intent, structure, notes, route}. `route` is the concrete
    Playbook decision (style/engine/resources) so nothing bypasses what we can actually execute."""
    from . import creative_playbook as pb
    from . import creative_learning as learn
    refs = available_references or {}
    # deterministic route from the Playbook (never picks a path/engine we can't run) + learned avoids
    plan_route = pb.route(request_type=request_type, vertical=vertical,
                          has_real_character=has_real_character, has_winner_video=has_winner_video,
                          needs_talking=True, engine_hint=("" if (model or "").lower() in ("", "auto") else model))
    avoid = learn.learned_engine_avoid(style=plan_route["style"], vertical=vertical)
    if plan_route["engine"] in avoid:
        plan_route["notes"] = (plan_route.get("notes", "") + f" (learned: avoid {plan_route['engine']} for {plan_route['style']})").strip()
    playbook = pb.summary_for_prompt()
    lessons = learn.lessons_for_prompt(style=plan_route["style"], vertical=vertical)
    prompt = f"""{playbook}\n\n{lessons}\n\nYou are the Creative Director — the leader of a direct-response video team. You
decide the whole plan and delegate. Be concrete about REFERENCES, MODEL, and where we LIP-SYNC a
talking person vs HARD-CUT to an insert (b-roll / map / product).

OFFER: {offer_desc}
VERTICAL: {vertical}
REQUEST TYPE: {request_type}
PREFERRED MODEL (or 'Auto'): {model}
WINNING HOOK: {winner_hook[:300]}
WINNER STRUCTURE (reference): {winner_transcript[:900]}
AVAILABLE REFERENCES: {json.dumps(refs)[:600]}
HAVE REAL CHARACTER FOOTAGE: {has_real_character}   HAVE WINNER VIDEO: {has_winner_video}

Return STRICT JSON:
{{"approach": "one-line creative direction for the whole ad",
  "reference_plan": "which references to use and where (hook, body, proof, CTA)",
  "model_intent": "which model/capability per section and why (respect the preferred model)",
  "structure": [
    {{"section": "hook|body|proof|cta", "beat_kind": "talking_head|broll|map|product|image",
      "technique": "lipsync|hard_cut|overlay|insert", "note": "what happens here"}} ],
  "notes": "risks or must-keeps"}}"""
    out = await _gemini_json(prompt, temperature=0.4)
    if out:
        out["route"] = plan_route
        return out
    # heuristic master plan: real character → lipsync body with b-roll inserts; else winner-clone
    technique = "lipsync" if has_real_character else ("hard_cut" if has_winner_video else "lipsync")
    return {
        "route": plan_route,
        "approach": f"Hook fast on the winning angle, then deliver the offer with a real talking person and cut to relevant inserts.",
        "reference_plan": ("Open on the winning hook; use the real character for spoken beats; "
                           "cut to b-roll/map inserts on proof points; clean CTA card." if has_real_character
                           else "Clone the proven winner structure for this offer."),
        "model_intent": f"Use {model} for talking beats; capability-route inserts to a b-roll-capable model.",
        "structure": [
            {"section": "hook", "beat_kind": "talking_head", "technique": technique, "note": "hook in 2s"},
            {"section": "body", "beat_kind": "talking_head", "technique": "lipsync", "note": "deliver the offer"},
            {"section": "proof", "beat_kind": "broll", "technique": "hard_cut", "note": "supporting insert"},
            {"section": "cta", "beat_kind": "talking_head", "technique": "lipsync", "note": "clean CTA"},
        ],
        "notes": "Keep the offer intact; anti-slop realism throughout.",
    }


# ── 1. Strategist ─────────────────────────────────────────────────────────────
async def strategist(*, offer_desc: str, vertical: str, request_type: str,
                     loser_transcript: str = "", loser_metrics: Optional[dict] = None,
                     winner_hook: str = "", winner_transcript: str = "") -> dict:
    """Diagnose the loser against winner references + ROI data, decide the fix.
    Returns {diagnosis, fix, angle, keep, change, lagging_metric}."""
    metrics = loser_metrics or {}
    prompt = f"""{_coach_pre('strategist')}You are the Strategist on a direct-response creative team. Diagnose why this ad
underperformed and decide the SMALLEST high-leverage fix. Keep the offer and what already works.

OFFER: {offer_desc}
VERTICAL: {vertical}
REQUEST TYPE: {request_type}
LOSER TRANSCRIPT: {loser_transcript[:1200]}
LOSER METRICS (lower = worse): {json.dumps(metrics)[:500]}
PROVEN WINNER HOOK: {winner_hook[:300]}
WINNER TRANSCRIPT (reference structure): {winner_transcript[:1200]}

Return STRICT JSON:
{{"diagnosis": "one sentence: what is dragging performance",
  "lagging_metric": "hook_rate | hold_rate | ctr | cvr | roas | unknown",
  "angle": "the new creative angle in one line (keep the offer)",
  "keep": ["what to preserve from the loser/winner"],
  "change": ["specific changes to make"],
  "fix": "one-line directive for the Script Writer"}}"""
    out = await _gemini_json(prompt, temperature=0.3)
    if out:
        return out
    # metric-aware heuristic fallback: read loser_metrics to pick the ACTUAL lagging metric via the
    # domain model, so a down-LLM diagnosis still differs per creative instead of always "weak hook".
    return _strategist_heuristic(offer_desc, winner_hook, metrics)


def _has_real_metrics(metrics: Optional[dict]) -> bool:
    """True only when the input is backed by a REAL creative with REAL spend from the DB.
    A fresh Studio-generated script carries no spend → False → no past-performance verdict."""
    if not metrics:
        return False
    try:
        return float(metrics.get("spend") or 0) > 0
    except (TypeError, ValueError):
        return False


def _forward_heuristic(offer_desc: str, winner_hook: str) -> dict:
    """Ungrounded input (fresh script, NO metrics, NO real creative): forward-looking BEST-PRACTICE
    guidance — never a verdict on past performance. Used when the LLM is unavailable."""
    return {"diagnosis": "New script — no performance history yet; guidance below is forward-looking best practice.",
            "lagging_metric": "unknown",
            "angle": f"Lead with the single strongest proof/payoff of: {offer_desc[:120]}",
            "keep": ["the offer", "the winning hook angle" if winner_hook else "the core message"],
            "change": ["open on the payoff in the first 2s", "one idea per sentence", "end on a clean CTA"],
            "fix": f"To maximize this, hook on the payoff in 2s and keep the offer intact. {('Use hook: ' + winner_hook) if winner_hook else ''}".strip()}


def _strategist_heuristic(offer_desc: str, winner_hook: str, metrics: dict) -> dict:
    """Deterministic diagnosis from real metrics (used when the LLM is unavailable)."""
    v = cm.judge_creative(metrics) if metrics.get("spend") else {}
    faults = v.get("faults") or []
    if any(f.get("reason") == "low_offer_cr_delivery" for f in faults):
        return {"diagnosis": "Offer CR is low — the delivery (character/voice/lip-sync) isn't landing.",
                "lagging_metric": "offer_cr", "angle": f"Re-cast the delivery for: {offer_desc[:120]}",
                "keep": ["the offer", "the winning hook angle" if winner_hook else "the core message"],
                "change": ["stronger, more relatable on-camera delivery", "clearer read of the CTA"],
                "fix": "Rebuild delivery: warmer, credible talent; keep the offer + script intact."}
    hook = cm.as_pct(metrics.get("hook_rate"))
    if hook is not None and hook < 25:
        return {"diagnosis": f"Weak hook ({hook:.0f}%) — viewers scroll before the offer lands.",
                "lagging_metric": "hook_rate", "angle": f"Lead with the strongest proof of: {offer_desc[:120]}",
                "keep": ["the offer", "the winning hook angle" if winner_hook else "the core message"],
                "change": ["stronger first-2-seconds hook", "tighter pacing"],
                "fix": f"Rewrite the opening to hook in 2s; keep the offer intact. {('Use hook: ' + winner_hook) if winner_hook else ''}".strip()}
    hold = cm.as_pct(metrics.get("hold_rate"))
    if hold is not None and hold < 30:
        return {"diagnosis": f"Body drags (hold {hold:.0f}%) — viewers drop mid-video.",
                "lagging_metric": "hold_rate", "angle": f"Tighten the middle for: {offer_desc[:120]}",
                "keep": ["the offer", "the hook"], "change": ["cut drag", "front-load value"],
                "fix": "Tighten the body: remove filler, front-load the payoff; keep the offer."}
    return {"diagnosis": "Conversion lags despite ok engagement — sharpen offer clarity + CTA.",
            "lagging_metric": v.get("faults") and "offer_cr" or "roas",
            "angle": f"Sharpen the offer + CTA for: {offer_desc[:120]}",
            "keep": ["the offer", "the hook"], "change": ["sharper CTA", "clearer offer framing"],
            "fix": "Sharpen the CTA and offer clarity; keep the winning structure."}


# ── 2. Script Writer ──────────────────────────────────────────────────────────
async def script_writer(*, offer_desc: str, vertical: str, strategy: dict,
                        loser_transcript: str = "", winner_hook: str = "",
                        winner_transcript: str = "") -> str:
    """Write/enhance the spoken script per the Strategist's fix. Keep the offer; open on the
    winning hook. Returns plain script text (spoken lines only, no stage directions)."""
    prompt = f"""{_coach_pre('scriptwriter')}You are the Script Writer on a direct-response creative team. Write a tight,
natural spoken script (first-person, conversational, no stage directions, no on-screen text
markers) for a short vertical ad.

OFFER (must stay intact): {offer_desc}
VERTICAL: {vertical}
STRATEGIST FIX: {strategy.get('fix','')}
ANGLE: {strategy.get('angle','')}
KEEP: {json.dumps(strategy.get('keep', []))}
CHANGE: {json.dumps(strategy.get('change', []))}
WINNING HOOK to open on: {winner_hook[:300]}
LOSER SCRIPT (to enhance, not copy): {loser_transcript[:1200]}
WINNER SCRIPT (proven structure to echo): {winner_transcript[:1200]}

Rules: hook in the first sentence; one clear idea per sentence; end on a clean CTA. 40-90 words.
Return STRICT JSON: {{"script": "the spoken script as plain sentences"}}"""
    out = await _gemini_json(prompt, temperature=0.6)
    if out and out.get("script"):
        return str(out["script"]).strip()
    return _script_heuristic(offer_desc, loser_transcript, winner_hook)


def _script_heuristic(offer_desc: str, loser_transcript: str, winner_hook: str) -> str:
    base = (loser_transcript or offer_desc).strip()
    opener = (winner_hook.strip() + " ") if winner_hook else ""
    return f"{opener}{base}"[:600]


_STRATEGY_SPEC = {"diagnosis": str, "lagging_metric": str, "angle": str,
                  "keep": list, "change": list, "fix": str}


async def strategize_and_write(*, offer_desc: str, vertical: str, request_type: str,
                               loser_transcript: str = "", loser_metrics: Optional[dict] = None,
                               winner_hook: str = "", winner_transcript: str = "",
                               variation_directive: str = "") -> tuple:
    """MERGED Strategist + Script Writer in ONE round-trip (diagnosis + script together) — halves
    latency/cost vs two sequential calls. Returns (strategy: Strategy, script: str). Falls back to
    the two deterministic heuristics if the LLM is unavailable."""
    from . import creative_playbook as pb
    from . import creative_learning as learn
    metrics = loser_metrics or {}
    grounded = _has_real_metrics(metrics)
    # GROUNDING GUARD: only diagnose PAST performance when a real creative with real spend is behind
    # the input. A fresh Studio-generated script has no metrics/no prior ad — inventing "the original
    # failed because… / low engagement" would be a hallucinated verdict, so we switch to forward-
    # looking best-practice guidance instead (never a verdict on performance that never happened).
    if grounded:
        task_instr = ("First DIAGNOSE why this ad underperformed (GROUND every claim in the LOSER "
                      "METRICS below — cite the actual lagging number, use ROI not ROAS) and pick "
                      "the smallest high-leverage fix, THEN write the new spoken script implementing it.")
        diag_hint = "one sentence grounded in the real metrics: what is dragging performance"
    else:
        task_instr = ("This is a NEW script with NO performance history — there is NO prior ad, NO "
                      "metrics, NO spend behind it. Do NOT critique past performance and do NOT claim "
                      "anything 'failed', had 'low engagement', or a 'weak hook that didn't grab' — "
                      "there is zero data to support that. Instead give FORWARD-LOOKING best-practice "
                      "guidance to maximize this script, THEN write the improved script.")
        diag_hint = ("forward-looking opportunity, NOT a verdict on past performance "
                     "(e.g. 'To maximize this, open on the payoff…')")
    prompt = f"""{pb.MISSION}

{pb.vertical_brief(vertical)}

{learn.lessons_for_prompt(vertical=vertical)}

{_coach_pre('strategist')}{_coach_pre('scriptwriter')}You are the Strategist AND the Script
Writer on THIS project (above). {task_instr} Keep the offer intact.

OFFER: {_sanitize(offer_desc, MAX_OFFER)}
VERTICAL: {vertical}   REQUEST TYPE: {request_type}
{("REAL LOSER METRICS (from live data, lower=worse): " + json.dumps(metrics)[:500]) if grounded else "PERFORMANCE DATA: none — this is a fresh script with no metrics."}
{"LOSER TRANSCRIPT" if grounded else "SOURCE SCRIPT (draft to improve, not a past ad)"}: {_sanitize(loser_transcript, MAX_TRANSCRIPT)}
WINNING HOOK to open on: {_sanitize(winner_hook, MAX_HOOK)}
WINNER SCRIPT (proven structure): {_sanitize(winner_transcript, MAX_WINNER_TX)}
{(_sanitize(variation_directive, 400) + chr(10)) if variation_directive else ""}
Script rules: hook in the first sentence; one idea per sentence; clean CTA; 40-90 words; first-person;
no stage directions or on-screen-text markers.
Return STRICT JSON: {{"diagnosis": "{diag_hint}", "lagging_metric": "hook_rate|hold_rate|offer_cr|ctr|roas|unknown",
  "angle": "...", "keep": ["..."], "change": ["..."], "fix": "one-line directive",
  "script": "the spoken script as plain sentences"}}"""
    out = await _gemini_json(prompt, temperature=0.5)
    if out and out.get("script"):
        strategy = _coerce(out, _STRATEGY_SPEC)
        return strategy, str(out.get("script")).strip()
    # fallback: metric-grounded diagnosis when we have real metrics, else forward-looking guidance
    strategy = (_strategist_heuristic(offer_desc, winner_hook, metrics) if grounded
                else _forward_heuristic(offer_desc, winner_hook))
    return strategy, _script_heuristic(offer_desc, loser_transcript, winner_hook)


# ── 3. Director (scene / emotion / gesture per beat) ──────────────────────────
async def director(*, script: str, request_type: str, vertical: str) -> list:
    """Break the script into timed beats and direct each: scene, emotion, gesture, environment,
    and the ONE continuous action. Returns list of beat dicts."""
    clips = rpe.split_into_clips(script, max_words=30)
    prompt = f"""{_coach_pre('scene')}You are the Director on a creative team. For each spoken beat below, direct the
performance for a realistic vertical ad. ONE continuous physical action per beat (never sequence
two actions). Emotions and gestures must feel candid, not staged.

REQUEST TYPE: {request_type}   VERTICAL: {vertical}
BEATS (in order):
{json.dumps([{"i": i, "line": c} for i, c in enumerate(clips)])}

Return STRICT JSON: {{"beats": [
  {{"i": 0, "emotion": "...", "gesture": "one natural gesture", "environment": "dense authentic setting detail",
    "action": "the ONE continuous action for this beat"}} ]}}
One object per input beat, same order."""
    out = await _gemini_json(prompt, temperature=0.5)
    directed = (out or {}).get("beats") if out else None
    beats = []
    for i, line in enumerate(clips):
        d = next((b for b in directed if b.get("i") == i), {}) if directed else {}
        beats.append({
            "i": i,
            "line": line,
            "emotion": d.get("emotion", "sincere, relaxed"),
            "gesture": d.get("gesture", "a small natural hand gesture"),
            "environment": d.get("environment", "authentic lived-in interior with real clutter"),
            "action": d.get("action", "the speaker talks directly to camera with a natural gesture"),
        })
    return beats


# ── 4. Character Manager (consistent identity) ────────────────────────────────
async def character_manager(*, request_type: str, vertical: str,
                            avatar_hint: Optional[dict] = None,
                            entity_desc: str = "") -> str:
    """Lock ONE character descriptor reused across every beat (identity consistency).
    If an entity_desc is already supplied (e.g. from a real Top-Avatar reference), keep it."""
    if entity_desc:
        return entity_desc
    hint = avatar_hint or {}
    if hint:
        age = hint.get("age", "45+"); gender = hint.get("gender", "woman"); region = hint.get("region", "American")
        return (f"a real, ordinary {region} {gender} aged {age}, natural un-retouched skin with pores, "
                f"minimal makeup, everyday casual clothes, believable candid demeanor")
    prompt = f"""{_coach_pre('character')}You are the Character Manager. Describe ONE believable, ordinary
real person to be the consistent on-camera talent for a {vertical} {request_type} ad. Anti-slop: no
model looks, natural skin, everyday clothes. {cm.CHARACTER_CASTING}
Return STRICT JSON: {{"entity_desc": "one vivid sentence"}}"""
    out = await _gemini_json(prompt, temperature=0.5)
    if out and out.get("entity_desc"):
        return str(out["entity_desc"]).strip()
    # casting rule fallback: default to a real 45+ woman (per the team's casting guidance)
    return ("a real, ordinary American woman aged 45+, natural un-retouched skin with visible "
            "pores, minimal makeup, everyday casual clothes, relaxed candid demeanor")


# ── 5. Shot Selector (source strategy + model per beat) ───────────────────────
# realism hierarchy: real-footage lip-sync > real b-roll > image-to-video > AI scene (no face) > AI human
def shot_selector(*, beats: list, request_type: str, model: str,
                  has_real_character: bool, has_winner_video: bool) -> list:
    """Per beat pick shot_type, source_strategy, request_type and capability-routed model.
    Deterministic (fast, testable) — encodes the realism hierarchy, no LLM needed."""
    from .multi_provider_video import MultiProviderVideoService as MPV
    rt = lib._norm(request_type)
    out = []
    for b in beats:
        line = b.get("line", "")
        # b-roll / map / product / animated types keep their type; talking types default to the person
        if rt in ("broll", "map", "product", "image", "cinematic"):
            beat_rt = rt
            if has_real_character and rt == "broll":
                strategy, cap = "real_broll_recut", "b_roll"
            else:
                strategy, cap = "ai_scene_no_face", "b_roll"
            shot = rt
        else:  # ugc / testimonial / fast_cuts → a talking human
            beat_rt = rt
            shot = "talking_head"
            if has_real_character:
                strategy, cap = "real_footage_lipsync", "talking_head"
            elif has_winner_video:
                strategy, cap = "winner_clone", "reference_to_video"
            else:
                strategy, cap = "ai_human_antislop", "talking_head"
        chosen = MPV.route_capability(cap, model)
        # technique is DERIVED from the chosen source strategy — single source of truth, so it can
        # never contradict source_strategy (talking strategies → lipsync; inserts/clones → hard_cut).
        technique = _TECHNIQUE_BY_STRATEGY.get(strategy, "lipsync")
        out.append({**b, "request_type": beat_rt, "shot_type": shot,
                    "source_strategy": strategy, "technique": technique,
                    "capability": cap, "model": chosen})
    return out


# maps each source strategy to its ONE technique (keeps technique/source_strategy consistent)
_TECHNIQUE_BY_STRATEGY = {
    "real_footage_lipsync": "lipsync",
    "ai_human_antislop": "lipsync",
    "winner_clone": "hard_cut",
    "real_broll_recut": "hard_cut",
    "ai_scene_no_face": "insert",
}


# ── 6. Prompt Writer (deterministic composition from the library) ─────────────
def prompt_writer(*, beats: list, entity_desc: str, vertical: str,
                  n_reference_images: int = 0, has_reference_video: bool = False) -> list:
    """Compose each beat's final prompt from the Prompt Reference Library via the realism engine.
    No hardcoded style string — the request_type selects the reference DNA."""
    for b in beats:
        b["prompt"] = rpe.build_prompt(
            model=b["model"],
            action=b.get("action", "the speaker talks directly to camera with a natural gesture"),
            request_type=b.get("request_type", "ugc"),
            entity_desc=entity_desc if b.get("shot_type") == "talking_head" else "",
            environment=b.get("environment", ""),
            line=b.get("line") if b.get("shot_type") == "talking_head" else None,
            vertical=vertical,
            n_reference_images=n_reference_images,
            has_reference_video=has_reference_video,
        )
    return beats


# ── 7. Critic (slop-risk judgment; optional vision QA) ────────────────────────
async def critic(*, beats: list, frames_by_beat: Optional[dict] = None) -> list:
    """PURE (no mutation): judge each beat's prompt (and, if provided, a generated frame) for slop
    risk. Returns list of {i, verdict: pass|revise, issues, revised_prompt}. Apply the fixes with
    apply_revisions() — separating judgment from mutation keeps this testable."""
    verdicts = []
    for b in beats:
        frames = (frames_by_beat or {}).get(b["i"])
        prompt = f"""You are the Critic — the guardrail against AI-slop. Judge this ad beat.
Slop signals: plastic/waxy skin, dead eyes, over-smooth render, sterile fake interiors, warped
hands/text, stabilized-gimbal look on a supposed phone video, generic stock feel, on-screen text.

REQUEST TYPE: {b.get('request_type')}   SHOT: {b.get('shot_type')}
PROMPT: {b.get('prompt','')[:1500]}
{'A generated frame is attached — inspect it for the slop signals above.' if frames else 'No frame yet — judge the PROMPT for slop risk and missing anti-slop cues.'}

Return STRICT JSON: {{"verdict": "pass" | "revise", "issues": ["..."],
  "revised_prompt": "only if revise: a corrected prompt string, else empty"}}"""
        out = await _gemini_json(prompt, temperature=0.2, frames=frames)
        v = _coerce(out, {"verdict": str, "issues": list, "revised_prompt": str})
        v["i"] = b["i"]
        v["verdict"] = v["verdict"] or "pass"
        verdicts.append(v)
    return verdicts


def apply_revisions(beats: list, verdicts: list) -> int:
    """SIDE-EFFECTING counterpart to critic(): apply each 'revise' verdict's corrected prompt onto
    its beat. Returns how many beats were revised. Separated from critic() so judgment is pure."""
    by_i = {b.get("i"): b for b in beats}
    n = 0
    for v in verdicts:
        if v.get("verdict") == "revise" and v.get("revised_prompt"):
            b = by_i.get(v.get("i"))
            if b is not None:
                b["prompt"] = v["revised_prompt"][:MAX_PROMPT]
                n += 1
    return n


# ── 8. Learner (grow the library from outcomes) ───────────────────────────────
def learner(*, request_type: str, winning_prompt_pattern: str) -> None:
    """After a regenerated ad wins, distill its prompt into a reusable pattern and append it to
    the Prompt Reference Library so future prompts inherit what worked (closed learning loop)."""
    if winning_prompt_pattern and winning_prompt_pattern.strip():
        lib.add_exemplar(request_type, winning_prompt_pattern.strip())


# ── Eval self-learning loop (vision QA → fault attribution → coaching → retry) ─
_FAULT_PERSONAS = {"character", "shots", "prompt", "scriptwriter", "scene", "editor", "director"}


async def evaluate_clip(frame_paths: list, beat: dict) -> dict:
    """Vision-QA a GENERATED clip's frame(s): score realism, lip-sync, captions, and attribute any
    failure to the responsible persona(s). This is what lets the team grade its OWN output and learn.
    Returns {overall, realism, lipsync, captions, issues, fault_personas}. Degrades to a pass if no
    vision available (never blocks generation)."""
    is_talking = beat.get("shot_type") == "talking_head"
    prompt = f"""You are the Critic doing VISUAL QA on a generated ad clip. Inspect the attached
frame(s) hard for AI-slop and defects.

Beat intent: shot={beat.get('shot_type')}, line spoken={'yes' if is_talking else 'no'}.
Score 0-10 (10 = flawless, real):
- realism: plastic/waxy skin, dead eyes, over-smooth, fake sterile interior, warped hands/text → low
- lipsync: {'do the lips match a person speaking?' if is_talking else 'n/a — no talking, score 10'}
- captions: garbled/duplicated/baked-in wrong text on screen → low (clean/none → high)

Attribute EACH problem to the responsible role, choosing from:
  character (wrong/plastic person or casting), shots (wrong technique/lip-sync/model),
  prompt (prompt lacked anti-slop cues), scriptwriter (bad line), scene (bad direction),
  editor (caption/stitch defect).

Return STRICT JSON: {{"realism": <0-10>, "lipsync": <0-10>, "captions": <0-10>,
  "overall": <0-10>, "issues": ["short concrete defect"], "fault_personas": ["character", ...]}}"""
    out = await _gemini_json(prompt, temperature=0.2, frames=frame_paths)
    if not out:
        return {"overall": 10, "realism": 10, "lipsync": 10, "captions": 10, "issues": [], "fault_personas": []}
    out["fault_personas"] = [p for p in (out.get("fault_personas") or []) if p in _FAULT_PERSONAS]
    return out


def revised_prompt(prompt: str, issues: list) -> str:
    """PURE: fold concrete eval issues into a prompt as an explicit correction line (testable)."""
    if not issues:
        return prompt or ""
    fix = " CORRECTION (fix these on this attempt): " + "; ".join(issues[:4]) + "."
    return ((prompt or "") + fix)[:MAX_PROMPT]


def coach_from_eval(beat: dict, ev: dict, job_id: Optional[str] = None) -> None:
    """Turn a failed eval into ACTION: dock + coach each faulted persona (the one-on-one), and fold
    the concrete corrections into this beat's prompt so the retry is actually better. (Uses the pure
    revised_prompt() for the prompt rewrite so that half is unit-testable.)"""
    issues = ev.get("issues") or []
    note = "; ".join(issues)[:200] or "output scored below the quality bar — tighten realism/delivery."
    for p in (ev.get("fault_personas") or []):
        act.coach(p, note, job_id=job_id)
    if issues:
        beat["prompt"] = revised_prompt(beat.get("prompt", ""), issues)
        # SELF-LEARNING: a Critic rejection is a wrongdoing → record it + the corrective rule
        try:
            from . import creative_learning as learn
            learn.record_lesson("quality", trigger=f"beat scored {ev.get('overall')}/10",
                                reason="; ".join(issues)[:200],
                                rule="Pre-empt in the prompt: " + "; ".join(issues[:3]),
                                job_id=job_id)
        except Exception:
            pass


def eval_passed(ev: dict) -> bool:
    return float(ev.get("overall", 10)) >= EVAL_PASS_THRESHOLD


# ── Orchestrator ──────────────────────────────────────────────────────────────
async def _run(persona: str, job_id: str, task: str, coro, *, helpfulness=None):
    """Instrument one persona step: mark working → run → record time/outcome for the office feed."""
    ts = act.start(persona, job_id, task)
    try:
        result = await coro
        h = helpfulness(result) if callable(helpfulness) else helpfulness
        act.finish(persona, job_id, ts, ok=True, detail=task, helpfulness=h)
        return result
    except Exception as e:
        act.finish(persona, job_id, ts, ok=False, detail=f"{task}: {e}")
        raise


async def run_creative_team(
    *,
    offer_desc: str,
    job_id: str = "job",
    vertical: str = "",
    request_type: str = "ugc",
    model: str = "seedance-2",
    loser_transcript: str = "",
    loser_metrics: Optional[dict] = None,
    winner_hook: str = "",
    winner_transcript: str = "",
    entity_desc: str = "",
    avatar_hint: Optional[dict] = None,
    available_references: Optional[dict] = None,
    has_real_character: bool = False,
    has_winner_video: bool = False,
    n_reference_images: int = 0,
    has_reference_video: bool = False,
    run_critic: bool = True,
) -> dict:
    """Run the full team (led by the Creative Director) and return an executable CreativePlan:
    {plan, strategy, script, entity_desc, beats:[...], critique}. Every step reports live to the
    office activity feed under job_id.

    NOTE: this orchestrator produces the PLAN (incl. prompt-only critique). The per-beat
    self-learning eval loop (evaluate_clip → coach_from_eval → bounded retry) runs in the COMPOSER
    (routes/regen.py `_gen_beat_with_eval`) once each beat's clip is generated — that's where the
    "grade its own output and coach" feature is wired, since it needs the rendered pixels."""
    # ensure this job has a room (idempotent — the recipe usually begins it with a better label)
    act.begin_job(job_id, label=job_id, expected_sec=60)

    # 0) The leader sets the master plan first.
    plan = await _run("director", job_id, "orchestrating the master plan",
                      creative_director(
                          offer_desc=offer_desc, vertical=vertical, request_type=request_type,
                          model=model, winner_hook=winner_hook, winner_transcript=winner_transcript,
                          available_references=available_references,
                          has_real_character=has_real_character, has_winner_video=has_winner_video),
                      helpfulness=lambda p: 1.0 if p.get("structure") else 0.5)

    # 1+2) Strategist + Script Writer share ONE round-trip (merged), reported as both personas.
    ts_s = act.start("strategist", job_id, "diagnosing loser vs winner")
    ts_w = act.start("scriptwriter", job_id, "writing the script")
    strategy, script = await strategize_and_write(
        offer_desc=offer_desc, vertical=vertical, request_type=request_type,
        loser_transcript=loser_transcript, loser_metrics=loser_metrics,
        winner_hook=winner_hook, winner_transcript=winner_transcript)
    act.finish("strategist", job_id, ts_s, ok=True, detail=strategy.get("diagnosis", "diagnosed"),
               helpfulness=1.0 if strategy.get("fix") else 0.5)
    act.finish("scriptwriter", job_id, ts_w, ok=True, detail="script written",
               helpfulness=min(1.0, len((script or "").split()) / 60))

    # 3+4) Director (needs the script) and Character Manager (independent) run CONCURRENTLY.
    beats, character = await asyncio.gather(
        _run("scene", job_id, "breaking script into beats",
             director(script=script, request_type=request_type, vertical=vertical),
             helpfulness=lambda b: 1.0 if b else 0.0),
        _run("character", job_id, "locking the character",
             character_manager(request_type=request_type, vertical=vertical,
                               avatar_hint=avatar_hint, entity_desc=entity_desc),
             helpfulness=lambda c: 1.0 if c else 0.0),
    )

    # 5) Shot Selector: technique derived from source_strategy; leader's structure only annotates.
    ts = act.start("shots", job_id, "selecting shots + models")
    beats = shot_selector(beats=beats, request_type=request_type, model=model,
                          has_real_character=has_real_character, has_winner_video=has_winner_video)
    _apply_director_structure(beats, plan.get("structure") or [])
    act.finish("shots", job_id, ts, ok=True, detail="shots + models chosen",
               helpfulness=1.0 if beats else 0.0)

    # 6) Prompt Writer: compose anti-slop prompts from the reference library.
    ts = act.start("prompt", job_id, "composing anti-slop prompts")
    beats = prompt_writer(beats=beats, entity_desc=character, vertical=vertical,
                          n_reference_images=n_reference_images, has_reference_video=has_reference_video)
    act.finish("prompt", job_id, ts, ok=True, detail=f"{len(beats)} prompts composed",
               helpfulness=1.0 if beats else 0.0)

    # 7) Critic: PURE judgment, then apply_revisions mutates (separation of concerns).
    critique = []
    if run_critic:
        ts = act.start("critic", job_id, "judging beats for slop")
        critique = await critic(beats=beats)  # prompt-only QA; vision QA runs post-generation
        revised = apply_revisions(beats, critique)
        act.finish("critic", job_id, ts, ok=True, revised=bool(revised),
                   detail=f"{revised}/{len(critique)} beats revised",
                   helpfulness=1.0 - (revised / len(critique)) if critique else 1.0)

    return {"plan": plan, "strategy": strategy, "script": script, "entity_desc": character,
            "beats": beats, "critique": critique, "request_type": lib._norm(request_type)}


def _apply_director_structure(beats: list, structure: list) -> None:
    """Annotate each beat with the SECTION it falls in (hook/body/proof/cta) and record the leader's
    intended technique as `planned_technique`. It does NOT overwrite `technique` — that is derived
    from source_strategy in shot_selector (single source of truth) so the two can't contradict."""
    if not structure or not beats:
        return
    n = len(beats); S = len(structure)
    for i, b in enumerate(beats):
        # linear interpolation that ANCHORS endpoints: first beat → first section (hook),
        # last beat → last section (cta); middles distribute. (Avoids the last beat never
        # reaching the CTA section when n < S.)
        idx = 0 if n == 1 else round(i * (S - 1) / (n - 1))
        sec = structure[min(idx, S - 1)]
        b["section"] = sec.get("section", "")
        b["planned_technique"] = sec.get("technique", "")   # leader's intent (for reporting/QA)
