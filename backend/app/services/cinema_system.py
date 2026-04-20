"""Cinema camera system - builds technically accurate cinematic prompts from equipment selection"""
import logging

logger = logging.getLogger(__name__)

CAMERAS = {
    "modular_8k": {"name": "Modular 8K Digital", "desc": "8K native resolution, extreme detail capture, clinical precision"},
    "fullframe_cine": {"name": "Full-Frame Cine Digital", "desc": "Standard cinema sensor, natural skin tones, professional color science"},
    "70mm_film": {"name": "Grand Format 70mm Film", "desc": "Classic large-format film, organic grain, extraordinary depth, IMAX-level scale"},
    "s35_digital": {"name": "Studio Digital S35", "desc": "Industry standard Super 35mm sensor, versatile, proven Hollywood workhorse"},
    "16mm_film": {"name": "Classic 16mm Film", "desc": "Retro documentary aesthetic, heavy grain, intimate handheld feel"},
    "large_format_digital": {"name": "Premium Large Format Digital", "desc": "Ultra-shallow depth of field, medium format sensor, fashion/portrait specialist"},
}

LENSES = {
    "tilt_shift": {"name": "Creative Tilt Lens", "desc": "perspective control, selective focus plane, architectural precision, miniature effect"},
    "compact_anamorphic": {"name": "Compact Anamorphic", "desc": "2.39:1 cinematic feel, horizontal lens flares, oval bokeh, classic widescreen"},
    "extreme_macro": {"name": "Extreme Macro", "desc": "extreme close-up detail, razor-thin focus plane, micro-world perspective"},
    "70s_prime": {"name": "70s Cinema Prime", "desc": "vintage optical character, warm flares, gentle halation, nostalgic softness"},
    "classic_anamorphic": {"name": "Classic Anamorphic", "desc": "dramatic horizontal flares, elliptical bokeh highlights, epic widescreen breathing"},
    "modern_prime": {"name": "Premium Modern Prime", "desc": "clinically sharp, perfectly corrected, zero distortion, neutral color rendering"},
    "vintage_portrait": {"name": "Vintage Portrait Lens", "desc": "creamy swirly bokeh, gentle skin softening, painterly background separation"},
}

FOCAL_LENGTHS = {
    "8": {"fov": "110°+ ultra-wide", "desc": "extreme perspective, environmental immersion, dramatic scale distortion"},
    "18": {"fov": "100° wide", "desc": "wide establishing shots, environmental context, slight perspective enhancement"},
    "24": {"fov": "84° wide", "desc": "standard wide, documentary feel, environmental storytelling"},
    "35": {"fov": "63° standard", "desc": "natural perspective matching human vision, classic cinematography default"},
    "50": {"fov": "46° normal", "desc": "neutral perspective, intimate without distortion, the 'nifty fifty'"},
    "70": {"fov": "34° telephoto", "desc": "moderate compression, flattering portraits, background isolation begins"},
    "85": {"fov": "28° portrait", "desc": "classic portrait focal length, strong background compression, beautiful subject isolation"},
}

APERTURES = {
    "1.4": {"desc": "ultra-shallow depth of field, dreamy creamy bokeh, extreme subject isolation, light-gathering master"},
    "2.8": {"desc": "shallow depth with more context, professional portrait standard, good low-light balance"},
    "4": {"desc": "balanced depth and sharpness, professional standard, sweet spot for most lenses"},
    "8": {"desc": "deep focus, sharp foreground to midground, landscape standard"},
    "11": {"desc": "maximum depth of field, sharp throughout entire frame, documentary/architectural standard"},
}


class CinemaSystem:
    """Builds technically accurate cinematic prompt directives from equipment selection"""

    @staticmethod
    def build_directive(
        camera: str = "fullframe_cine",
        lens: str = "modern_prime",
        focal_length: str = "35",
        aperture: str = "4",
    ) -> str:
        cam = CAMERAS.get(camera, CAMERAS["fullframe_cine"])
        ln = LENSES.get(lens, LENSES["modern_prime"])
        fl = FOCAL_LENGTHS.get(focal_length, FOCAL_LENGTHS["35"])
        ap = APERTURES.get(aperture, APERTURES["4"])

        directive = f"""CINEMATIC CAMERA DIRECTIVE:
Camera: {cam['name']} — {cam['desc']}
Lens: {ln['name']} — {ln['desc']}
Focal Length: {focal_length}mm ({fl['fov']}) — {fl['desc']}
Aperture: f/{aperture} — {ap['desc']}
Look: Shot on {cam['name']} with {ln['name']} at {focal_length}mm f/{aperture}, {ln['desc']}, natural film color science, professional cinematography, production-grade lighting"""

        return directive

    @staticmethod
    def get_cameras() -> dict:
        return {k: v["name"] for k, v in CAMERAS.items()}

    @staticmethod
    def get_lenses() -> dict:
        return {k: v["name"] for k, v in LENSES.items()}

    @staticmethod
    def get_focal_lengths() -> list:
        return list(FOCAL_LENGTHS.keys())

    @staticmethod
    def get_apertures() -> list:
        return list(APERTURES.keys())

    @staticmethod
    def get_all_options() -> dict:
        return {
            "cameras": {k: {"name": v["name"], "description": v["desc"]} for k, v in CAMERAS.items()},
            "lenses": {k: {"name": v["name"], "description": v["desc"]} for k, v in LENSES.items()},
            "focal_lengths": {k: {"fov": v["fov"], "description": v["desc"]} for k, v in FOCAL_LENGTHS.items()},
            "apertures": {k: {"description": v["desc"]} for k, v in APERTURES.items()},
        }
