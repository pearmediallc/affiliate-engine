"""
fal.ai video generation — cheap new-from-scratch lane. Model-explicit IDs (fal-seedance /
fal-kling / fal-wan) so the cost ledger + learning loop can judge which model performs best.
Slugs are env-overridable (fal versions paths occasionally) — nothing hard-locked.
"""
import logging
import os
import time
import uuid

import requests

from ..config import settings

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# id → (text-to-video slug, image-to-video slug). Override any via env FAL_SLUG_<ID>.
FAL_VIDEO_MODELS = {
    "fal-seedance": ("fal-ai/bytedance/seedance/v1/lite/text-to-video",
                     "fal-ai/bytedance/seedance/v1/lite/image-to-video"),
    "fal-kling":    ("fal-ai/kling-video/v2.1/standard/text-to-video",
                     "fal-ai/kling-video/v2.1/standard/image-to-video"),
    "fal-wan":      ("fal-ai/wan/v2.2-a14b/text-to-video",
                     "fal-ai/wan/v2.2-a14b/image-to-video"),
}
# rough per-clip cost for the ledger (fal is per-second; refined by the model page)
FAL_VIDEO_COST_PER_SEC = {"fal-seedance": 0.09, "fal-kling": 0.05, "fal-wan": 0.07}


def _slug(model_id: str, image: bool) -> str:
    env = os.getenv(f"FAL_SLUG_{model_id.replace('-', '_').upper()}")
    if env:
        return env
    t2v, i2v = FAL_VIDEO_MODELS.get(model_id, FAL_VIDEO_MODELS["fal-seedance"])
    return i2v if image else t2v


def generate_video(model_id: str, prompt: str, *, image_url: str = None, seconds: int = 5,
                   aspect_ratio: str = "9:16", resolution: str = "480p") -> dict:
    """Generate one clip via a fal video model. Returns {provider, model, video_url, local_path, cost_usd}."""
    key = settings.fal_key
    if not key:
        raise RuntimeError("no fal key")
    slug = _slug(model_id, bool(image_url))
    base = f"https://queue.fal.run/{slug}"
    inp = {"prompt": prompt, "duration": str(seconds), "aspect_ratio": aspect_ratio, "resolution": resolution}
    if image_url:
        inp["image_url"] = image_url
    h = {"Authorization": f"Key {key}"}
    r = requests.post(base, headers={**h, "Content-Type": "application/json"}, json=inp, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"fal {model_id} {r.status_code}: {r.text[:200]}")
    sub = r.json()
    rid = sub.get("request_id")
    # fal collapses MULTI-segment model slugs (e.g. fal-ai/bytedance/seedance/v1/lite/text-to-video)
    # down to the APP prefix (fal-ai/bytedance) in its queue URLs — so rebuilding the poll URL from
    # the full slug 404/405s and yields a non-JSON body ("Expecting value: line 1 column 1"). ALWAYS
    # follow the status_url / response_url fal hands back in the submit response instead.
    status_url = sub.get("status_url") or f"{base}/requests/{rid}/status"
    result_url = sub.get("response_url") or f"{base}/requests/{rid}"
    out = None
    for _ in range(150):   # ~10 min
        time.sleep(4)
        s = requests.get(status_url, headers=h, timeout=30).json()
        st = (s.get("status") or "").upper()
        if st == "COMPLETED":
            res = requests.get(result_url, headers=h, timeout=30).json()
            out = (res.get("video") or {}).get("url") or res.get("video_url")
            break
        if st in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal {model_id} {st}: {s}")
    if not out:
        raise RuntimeError(f"fal {model_id} no output / timed out")
    local = os.path.join(DOWNLOADS_DIR, f"fal_{model_id}_{uuid.uuid4().hex[:8]}.mp4")
    resp = requests.get(out, timeout=120)
    with open(local, "wb") as f:
        f.write(resp.content)
    cost = round(FAL_VIDEO_COST_PER_SEC.get(model_id, 0.09) * seconds, 4)
    return {"provider": "fal", "model": model_id, "video_url": out, "local_path": local, "cost_usd": cost}
