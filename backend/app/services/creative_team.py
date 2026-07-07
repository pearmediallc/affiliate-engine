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

from ..config import settings
from . import prompt_reference_library as lib
from . import realism_prompt_engine as rpe
from . import creative_team_activity as act

logger = logging.getLogger(__name__)

_GEMINI_MODEL = getattr(settings, "gemini_model", None) or "gemini-2.5-flash"


# ── shared LLM plumbing ───────────────────────────────────────────────────────
async def _gemini_json(prompt: str, *, temperature: float = 0.4,
                       frames: Optional[list] = None) -> Optional[dict]:
    """One strict-JSON call to Gemini (text, or text+frames for the vision Critic).
    Returns None on any failure so callers fall back to deterministic heuristics."""
    if not settings.gemini_api_key:
        return None
    parts: list = [{"text": prompt}]
    for fp in (frames or []):
        try:
            with open(fp, "rb") as f:
                parts.append({"inline_data": {"mime_type": "image/jpeg",
                                              "data": base64.b64encode(f.read()).decode()}})
        except Exception:
            pass
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{_GEMINI_MODEL}:generateContent?key={settings.gemini_api_key}")
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(url, json=body)
            r.raise_for_status()
            data = r.json()
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        logger.warning(f"creative_team LLM call failed ({e}); using heuristic fallback")
        return None


# ── 0. Creative Director (the smart leader) ───────────────────────────────────
async def creative_director(*, offer_desc: str, vertical: str, request_type: str,
                            model: str, winner_hook: str = "", winner_transcript: str = "",
                            available_references: Optional[dict] = None,
                            has_real_character: bool = False,
                            has_winner_video: bool = False) -> dict:
    """The leader. Sets the MASTER PLAN the rest of the team executes: the creative approach,
    which references to use where, the model routing intent, and — crucially — WHERE in the
    timeline we lip-sync a real character vs hard-cut to b-roll/map/product inserts.
    Returns {approach, reference_plan, model_intent, structure:[{beat_kind, technique}], notes}."""
    refs = available_references or {}
    prompt = f"""You are the Creative Director — the leader of a direct-response video team. You
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
        return out
    # heuristic master plan: real character → lipsync body with b-roll inserts; else winner-clone
    technique = "lipsync" if has_real_character else ("hard_cut" if has_winner_video else "lipsync")
    return {
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
    prompt = f"""You are the Strategist on a direct-response creative team. Diagnose why this ad
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
    # heuristic fallback: assume weak hook (most common failure)
    return {
        "diagnosis": "Weak opening hook — viewers scroll before the offer lands.",
        "lagging_metric": "hook_rate",
        "angle": f"Lead with the strongest proof point of the offer: {offer_desc[:120]}",
        "keep": ["the offer", "the winning hook angle" if winner_hook else "the core message"],
        "change": ["stronger first-2-seconds hook", "tighter pacing"],
        "fix": f"Rewrite the opening to hook in 2s; keep the offer intact. {('Use hook: ' + winner_hook) if winner_hook else ''}".strip(),
    }


# ── 2. Script Writer ──────────────────────────────────────────────────────────
async def script_writer(*, offer_desc: str, vertical: str, strategy: dict,
                        loser_transcript: str = "", winner_hook: str = "",
                        winner_transcript: str = "") -> str:
    """Write/enhance the spoken script per the Strategist's fix. Keep the offer; open on the
    winning hook. Returns plain script text (spoken lines only, no stage directions)."""
    prompt = f"""You are the Script Writer on a direct-response creative team. Write a tight,
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
    # fallback: enhance loser opening with winner hook, keep offer + CTA
    base = (loser_transcript or offer_desc).strip()
    opener = (winner_hook.strip() + " ") if winner_hook else ""
    return f"{opener}{base}"[:600]


# ── 3. Director (scene / emotion / gesture per beat) ──────────────────────────
async def director(*, script: str, request_type: str, vertical: str) -> list:
    """Break the script into timed beats and direct each: scene, emotion, gesture, environment,
    and the ONE continuous action. Returns list of beat dicts."""
    clips = rpe.split_into_clips(script, max_words=30)
    prompt = f"""You are the Director on a creative team. For each spoken beat below, direct the
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
        age = hint.get("age", "35-45"); gender = hint.get("gender", "person"); region = hint.get("region", "American")
        return (f"a real, ordinary {region} {gender} aged {age}, natural un-retouched skin with pores, "
                f"minimal makeup, everyday casual clothes, believable candid demeanor")
    prompt = f"""You are the Character Manager. Describe ONE believable, ordinary real person to be
the consistent on-camera talent for a {vertical} {request_type} ad. Anti-slop: no model looks,
natural skin, everyday clothes. Return STRICT JSON: {{"entity_desc": "one vivid sentence"}}"""
    out = await _gemini_json(prompt, temperature=0.5)
    if out and out.get("entity_desc"):
        return str(out["entity_desc"]).strip()
    return ("a real, ordinary middle-aged American person, natural un-retouched skin with visible "
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
        out.append({**b, "request_type": beat_rt, "shot_type": shot,
                    "source_strategy": strategy, "capability": cap, "model": chosen})
    return out


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
    """Judge each beat's prompt (and, if provided, a generated frame) for slop risk.
    Returns list of {i, verdict: pass|revise, issues, revised_prompt?}. Frames enable true QA."""
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
        if not out:
            verdicts.append({"i": b["i"], "verdict": "pass", "issues": [], "revised_prompt": ""})
            continue
        v = {"i": b["i"], "verdict": out.get("verdict", "pass"),
             "issues": out.get("issues", []), "revised_prompt": out.get("revised_prompt", "")}
        if v["verdict"] == "revise" and v["revised_prompt"]:
            b["prompt"] = v["revised_prompt"][:1900]  # apply the fix in place
        verdicts.append(v)
    return verdicts


# ── 8. Learner (grow the library from outcomes) ───────────────────────────────
def learner(*, request_type: str, winning_prompt_pattern: str) -> None:
    """After a regenerated ad wins, distill its prompt into a reusable pattern and append it to
    the Prompt Reference Library so future prompts inherit what worked (closed learning loop)."""
    if winning_prompt_pattern and winning_prompt_pattern.strip():
        lib.add_exemplar(request_type, winning_prompt_pattern.strip())


# ── Orchestrator ──────────────────────────────────────────────────────────────
async def _run(persona: str, job_id: str, task: str, coro, *, helpfulness=None):
    """Instrument one persona step: mark working → run → record time/outcome for the office feed."""
    ts = act.start(persona, job_id, task)
    try:
        result = await coro
        h = helpfulness(result) if callable(helpfulness) else helpfulness
        act.finish(persona, ts, ok=True, detail=task, helpfulness=h)
        return result
    except Exception as e:
        act.finish(persona, ts, ok=False, detail=f"{task}: {e}")
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
    office activity feed under job_id."""
    # queue the whole team for this job so the office shows them lined up
    for r in act.ROSTER:
        act.enqueue(r["id"], job_id, "creative regeneration")

    # 0) The leader sets the master plan first.
    plan = await _run("director", job_id, "orchestrating the master plan",
                      creative_director(
                          offer_desc=offer_desc, vertical=vertical, request_type=request_type,
                          model=model, winner_hook=winner_hook, winner_transcript=winner_transcript,
                          available_references=available_references,
                          has_real_character=has_real_character, has_winner_video=has_winner_video),
                      helpfulness=lambda p: 1.0 if p.get("structure") else 0.5)

    strategy = await _run("strategist", job_id, "diagnosing loser vs winner",
                          strategist(offer_desc=offer_desc, vertical=vertical, request_type=request_type,
                                     loser_transcript=loser_transcript, loser_metrics=loser_metrics,
                                     winner_hook=winner_hook, winner_transcript=winner_transcript),
                          helpfulness=lambda s: 1.0 if s.get("fix") else 0.5)

    script = await _run("scriptwriter", job_id, "writing the script",
                        script_writer(offer_desc=offer_desc, vertical=vertical, strategy=strategy,
                                      loser_transcript=loser_transcript, winner_hook=winner_hook,
                                      winner_transcript=winner_transcript),
                        helpfulness=lambda s: min(1.0, len((s or '').split()) / 60))

    beats = await _run("scene", job_id, "breaking script into beats",
                       director(script=script, request_type=request_type, vertical=vertical),
                       helpfulness=lambda b: 1.0 if b else 0.0)

    character = await _run("character", job_id, "locking the character",
                           character_manager(request_type=request_type, vertical=vertical,
                                             avatar_hint=avatar_hint, entity_desc=entity_desc),
                           helpfulness=lambda c: 1.0 if c else 0.0)

    # Shot Selector honors the leader's technique markers (lipsync vs hard-cut) where present.
    ts = act.start("shots", job_id, "selecting shots + models")
    beats = shot_selector(beats=beats, request_type=request_type, model=model,
                          has_real_character=has_real_character, has_winner_video=has_winner_video)
    _apply_director_structure(beats, plan.get("structure") or [])
    act.finish("shots", ts, ok=True, detail="shots + models chosen",
               helpfulness=1.0 if beats else 0.0)

    ts = act.start("prompt", job_id, "composing anti-slop prompts")
    beats = prompt_writer(beats=beats, entity_desc=character, vertical=vertical,
                          n_reference_images=n_reference_images, has_reference_video=has_reference_video)
    act.finish("prompt", ts, ok=True, detail=f"{len(beats)} prompts composed",
               helpfulness=1.0 if beats else 0.0)

    critique = []
    if run_critic:
        ts = act.start("critic", job_id, "judging beats for slop")
        critique = await critic(beats=beats)  # prompt-only QA; vision QA runs post-generation
        revised = sum(1 for c in critique if c.get("verdict") == "revise")
        act.finish("critic", ts, ok=True, revised=bool(revised),
                   detail=f"{revised}/{len(critique)} beats revised",
                   helpfulness=1.0 - (revised / len(critique)) if critique else 1.0)

    return {"plan": plan, "strategy": strategy, "script": script, "entity_desc": character,
            "beats": beats, "critique": critique, "request_type": lib._norm(request_type)}


def _apply_director_structure(beats: list, structure: list) -> None:
    """Overlay the leader's per-section technique (lipsync/hard_cut/insert) onto the beats so
    downstream generation knows where to lip-sync a real person vs hard-cut to an insert."""
    if not structure or not beats:
        return
    n = len(beats)
    for i, b in enumerate(beats):
        # map beat index onto the section it falls in (proportional)
        sec = structure[min(int(i * len(structure) / n), len(structure) - 1)]
        b["technique"] = sec.get("technique", b.get("technique", "lipsync"))
        b["section"] = sec.get("section", "")
