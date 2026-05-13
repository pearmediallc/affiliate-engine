"""
Storyboard service — takes a campaign brief + script and produces a
structured shot list via Gemini.

Each shot in the list specifies:
  sequence_num, shot_type, duration, prompt, character_id (optional),
  setting_id (optional), model_id (recommended), b_roll_query (for stock fallback)

Shot types: hero | spokesperson | b_roll | transition
"""
import json
import logging
from typing import Optional
from ..config import settings
from .pricing import Pricing
from .multi_provider_video import MultiProviderVideoService

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a professional ad creative director.
You produce storyboard shot lists for short-form video ads (15-60 seconds).
Each shot must have exactly these JSON fields:
  sequence_num: int (1-based)
  shot_type: "hero" | "spokesperson" | "b_roll" | "transition"
  duration: int (seconds, 4-8)
  description: str (what happens on screen)
  prompt: str (video generation prompt — cinematic, specific, vivid)
  b_roll_query: str (fallback stock footage search query if AI gen fails)
  character_ref: bool (true if this shot needs a character)
  setting_ref: bool (true if this shot needs a setting reference)
  narration_text: str (what the voiceover says during this shot, or "")
  on_screen_text: str (caption/lower-third text to burn in, or "")
  model_hint: "hero" | "spokesperson" | "b_roll" | "transition"

Return ONLY a JSON array of shot objects. No explanation, no markdown fences."""

_USER_TEMPLATE = """
Brief:
- Vertical: {vertical}
- Offer: {offer}
- Hook style: {hook_style}
- Ad arc: {ad_arc}
- Visual rhythm: {visual_rhythm}
- Color palette: {color_palette}
- CTA style: {cta_style}
- Target duration: {duration}s

Script:
{script}

Characters available: {characters}
Settings available: {settings}
Key insights from reference: {key_insights}

Produce a shot list for a {duration}-second ad that matches this brief.
Keep total duration at exactly {duration}s.
"""


def _call_gemini(prompt: str, system: str) -> str:
    from google import genai
    from google.genai import types as gtypes

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    return response.text


def _parse_shot_list(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "shots" in data:
            return data["shots"]
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except Exception:
                pass
    return []


class StoryboardService:
    """Generate a storyboard (shot list) from a campaign brief and script."""

    @staticmethod
    def generate(
        brief: dict,
        script: str,
        characters: list[dict],
        scene_settings: list[dict],
        target_duration: int = 30,
    ) -> dict:
        """
        Returns:
        {
          "shots": [...],
          "total_duration": int,
          "estimated_cost_usd": float,
          "model_routing": {...}
        }
        """
        char_names = ", ".join(c.get("name", "unnamed") for c in characters) or "none"
        setting_names = ", ".join(s.get("name", "unnamed") for s in scene_settings) or "none"
        insights = "; ".join(brief.get("key_insights", [])) or "none"

        user_prompt = _USER_TEMPLATE.format(
            vertical=brief.get("vertical", "general"),
            offer=brief.get("offer", ""),
            hook_style=brief.get("hook_style", "direct"),
            ad_arc=brief.get("ad_arc", "problem-solution"),
            visual_rhythm=brief.get("visual_rhythm", "mixed"),
            color_palette=brief.get("color_palette", ""),
            cta_style=brief.get("cta_style", "verbal"),
            duration=target_duration,
            script=script,
            characters=char_names,
            settings=setting_names,
            key_insights=insights,
        )

        raw = _call_gemini(user_prompt, _SYSTEM_PROMPT)
        shots = _parse_shot_list(raw)

        # Enrich with routing + cost
        total_cost = 0.0
        for shot in shots:
            shot_type = shot.get("model_hint") or shot.get("shot_type", "b_roll")
            model_id = MultiProviderVideoService.route_model(shot_type)
            dur = int(shot.get("duration", 6))
            cost = Pricing.video(model_id, dur)
            shot["routed_model"] = model_id
            shot["estimated_cost_usd"] = cost
            total_cost += cost

        # Build routing summary
        routing_summary: dict[str, int] = {}
        for shot in shots:
            m = shot.get("routed_model", "unknown")
            routing_summary[m] = routing_summary.get(m, 0) + 1

        return {
            "shots": shots,
            "total_duration": sum(s.get("duration", 6) for s in shots),
            "estimated_cost_usd": round(total_cost, 4),
            "model_routing": routing_summary,
        }

    @staticmethod
    def generate_hook_variants(
        base_shots: list[dict],
        brief: dict,
        num_variants: int = 3,
    ) -> list[list[dict]]:
        """
        Generate N alternative first-shot hooks, keeping the rest of the
        base storyboard unchanged.
        Returns list of shot lists (one per variant).
        """
        if not base_shots:
            return []

        system = """You are an ad creative director specializing in first-3-second hooks.
Given a base hook shot and a brief, produce N alternative hook variations.
Each variation should have a different emotional angle (urgency, curiosity, social proof, fear of loss, transformation).
Return ONLY a JSON array of hook shot objects (same schema as base), one per variant."""

        base_hook = base_shots[0]
        user = f"""Base hook: {json.dumps(base_hook)}
Brief: vertical={brief.get('vertical')}, arc={brief.get('ad_arc')}, insights={brief.get('key_insights')}
Produce {num_variants} alternative hook shots with different emotional angles."""

        raw = _call_gemini(user, system)
        hooks = _parse_shot_list(raw)

        variants = []
        for hook in hooks[:num_variants]:
            # Merge: replace first shot with variant hook
            variant_shots = [hook] + base_shots[1:]
            variants.append(variant_shots)

        return variants
