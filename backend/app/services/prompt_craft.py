"""
Prompt craft — the team's production prompt-engineering skills, encoded so the engine's LLM personas
compose shots / character / ad-structure the SAME way the team does by hand. Injected as CONTENT
guidance (each persona still returns its own JSON); the deterministic realism engine assembles the
final model prompt. Source: the team's Seedance/UGC skill files.
"""

# seedance-clean → how to write ONE Seedance shot (guides the Director's per-beat action/blocking).
SEEDANCE_SHOT_CRAFT = """SEEDANCE SHOT CRAFT — apply when writing each beat's action/environment/gesture:
- WRITE THE VISIBLE: turn every abstraction into something seen. Not "tense" -> "man freezes, clenches fist, light from the side, half his face in shadow". Not "sad" -> "eyes drop, jaw tightens, swallows once".
- ONE continuous physical action per beat — never sequence two actions or "then/after that".
- POSITIVE ONLY: state what happens, never what to avoid ("stays upright, feet planted", not "does not fall").
- BLOCKING: where each person stands/sits/moves, what each hand does, what's between them, gaze direction (left/right is from the camera).
- CAMERA: shot size (ECU/CU/MCU/MS/WS) + FOV in DEGREES from {8,12,18,29,47,63,84,107} (portrait 18-29, neutral 47, wide 63-84) — never mm/arbitrary; state height, movement + its motivation; camera on the shadow side.
- MEASURES: speeds in km/h; atmosphere in %/meters; scale via human-height; white balance in Kelvin fixed per scene.
- PERFORMANCE: pore-level skin, catch-lights, living eyes, visible breath, micro-pauses, restraint.
- COLOR via material + light beam + role ("crimson silk catching cold tungsten spill"), never a flat list; background in foreground/midground/background layers.
- Describe the LOOK, not gear — no director/camera/film/lens model names."""

# seedance-20-ugc-ad-director → the UGC ad shape + iPhone realism + native audio (guides the plan).
UGC_AD_CRAFT = """UGC AD CRAFT — apply when planning the ad structure + shots:
- SHAPE: Hook -> Problem/Proof -> Benefit/Demo -> CTA. ONE consistent creator/character across every segment (same identity).
- THIS IS UGC, NOT CINEMA — must look like iPhone footage a real person filmed.
  ALWAYS: iPhone handheld, natural/window light, UGC style, slight camera shake, casual, authentic, 9:16.
  NEVER: cinematic, ARRI/RED/Blackmagic, anamorphic, film grain, dramatic lighting, speed ramp, lens flare, whip pan, crane, dolly, steadicam, gimbal, Dutch angle, color grade, LUT, bokeh, "epic/breathtaking/stunning", slow-mo (unless "iPhone slow-mo").
- SEEDANCE MAKES AUDIO NATIVELY (dialogue+lipsync+room tone) — never "add voiceover in post". Direct the voice (age, gender, tone, energy — e.g. "warm male, early 40s, genuine dad-energy, not performative") AND room tone matching the setting (kitchen=open ambient, car=muffled close, bathroom=tiled reverb, outdoors=natural ambience+slight wind, bedroom=soft carpeted).
- DIALOGUE sounds REAL: contractions, filler ("like","honestly","so basically"), casual grammar, genuine excitement/skepticism. Good: "Okay so I've been using this for like two weeks and honestly? It actually works." Bad: "This revolutionary product has transformed my routine."
- DETAIL every 5s: what each hand does, exact expression, what's on the surface AND what's not, background, light source+direction — undescribed = the model invents it."""

# ugc-image-prompt → UGC avatar/model IMAGE craft (guides the portrait/character image prompt).
UGC_IMAGE_CRAFT = """UGC IMAGE CRAFT — apply when writing a portrait/model image prompt:
- OPEN with a realism tag: "Photorealistic candid iPhone [front-camera/selfie/UGC-style] portrait of ...".
- ORDER: [realism tag][shot type][ethnicity+age+location][camera angle+framing][appearance+hair+skin][outfit head-to-toe][expression+body language][props][full background][lighting][9:16][anti-polish][exclusions].
- NATURAL SKIN: visible pores, scattered freckles, slight redness, subtle texture, minor blemishes, real imperfections; zero plastic skin, zero AI smoothing, zero artificial makeup. Darker tones: visible pores, subtle marks, slight uneven tone, subtle hyperpigmentation.
- AGE: Gen Z 20-25 smooth plump no age lines; Millennial 30-35 subtle laugh lines; Mature 45-50 fine lines/crow's feet; Senior 55-65 deeply weathered, gray/white hair.
- STYLE by setting: iPhone selfie=straight-on eye level like a propped phone, ambient light, grainy; outdoor=arm's length below eye level, raw distortion; home=warm ambient indoor, no ring light; car=diffused daylight from windows.
- LOCATION bg: Texas=tan/beige brick ranch homes, wide flat roads, oak trees, harsh warm sun; Midwest/South=beige suburban home, mature trees; California=bright airy natural window light.
- END with anti-polish: "no ring light, no studio lighting, no filters, no heavy retouching. Slightly grainy raw iPhone footage. Vertical 9:16. Photorealistic, natural skin texture, authentic UGC style. No text overlays." ONE single person only."""

# Concise literal tag lines for the DETERMINISTIC portrait string (not LLM guidance — real prompt text).
UGC_PORTRAIT_TAGS = (
    "Natural un-retouched skin — visible pores, subtle texture, minor real imperfections, zero plastic "
    "AI skin, zero smoothing. Slightly grainy raw iPhone footage, ambient/window light, no ring light, "
    "no studio lighting, no filters, no heavy retouching. Authentic UGC look, correct anatomy."
)

# Extends realism_prompt_engine's REALISM_LAYER — the anti-cinematic never-use house rule.
ANTI_CINEMATIC = (
    "Looks like real iPhone footage: natural/window light, casual authentic framing. NO cinematic look, "
    "no film grade/LUT, no dramatic lighting, no lens flare, no anamorphic, no crane/dolly/steadicam/gimbal, "
    "no whip pan, no Dutch angle, no bokeh-heavy separation."
)
