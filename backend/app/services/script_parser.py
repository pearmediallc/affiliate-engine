"""
Parses user-pasted scripts of any format into a list of per-segment prompts
suitable for Veo 3.1's 8s base + N*7s extension model.

Tries structured patterns first (fast, free, no API call). Falls back to
Gemini for unstructured blobs.
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


# Patterns tried in order of specificity
TIMESTAMP_RE = re.compile(r"^\s*[\[\(]?\s*(\d{1,2}:\d{2}(?:[-–—]\s*\d{1,2}:\d{2})?|\d{1,3}:\d{2})\s*[\]\)]?\s*[:\-\.]?\s*(.+)$")
DURATION_RE = re.compile(r"^\s*[\[\(]?\s*(\d{1,2})\s*(?:s|sec|second|seconds?)\s*[\]\)]?\s*[:\-\.]?\s*(.+)$", re.IGNORECASE)
NUMBERED_RE = re.compile(r"^\s*(?:(?:Scene|Shot|Segment|Part)\s*)?(\d+)\s*[\.\)\:\-]\s*(.+)$", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*[\*\-\•\–\+]\s*(.+)$")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _try_line_pattern(lines: List[str], pattern: re.Pattern, group_idx: int = -1) -> List[str]:
    """Return list of content-groups if ALL non-empty lines match pattern, else []."""
    out = []
    for line in lines:
        if not line.strip():
            continue
        m = pattern.match(line)
        if not m:
            return []
        out.append(_clean(m.group(group_idx)))
    return out


def _split_paragraphs(text: str) -> List[str]:
    """Split on blank-line separators."""
    paras = re.split(r"\n\s*\n", text.strip())
    return [_clean(p) for p in paras if p.strip()]


def _gemini_segment(text: str, target_segments: int) -> List[str]:
    """Last-resort: ask Gemini to split unstructured blob into N cinematic shots."""
    try:
        from google import genai
        from ..config import settings
        if not settings.gemini_api_key:
            logger.warning("No Gemini key - returning text as single segment")
            return [_clean(text)]

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            f"Split the following text into exactly {target_segments} cinematic shot descriptions, "
            f"each ~7 seconds of video. Keep the subject/setting consistent across shots for visual "
            f"continuity. Output ONLY the shot descriptions, one per line, no numbering, no prefixes.\n\n"
            f"TEXT:\n{text}\n\nOUTPUT:"
        )
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        out_text = (resp.text or "").strip()
        shots = [_clean(line) for line in out_text.split("\n") if line.strip()]
        # If Gemini didn't give exactly target_segments, pad or truncate sensibly
        if not shots:
            return [_clean(text)]
        return shots[:target_segments]
    except Exception as e:
        logger.warning(f"Gemini segmentation failed: {e}")
        return [_clean(text)]


def parse_script(raw_text: str, target_segments: int = None) -> List[str]:
    """
    Returns a list of segment prompts. Does NOT enforce length — that's the
    long_video_service's job (which caps at budget/length limits).

    If target_segments is provided AND the raw text has no structure, we
    use Gemini to split it into exactly that many segments.
    """
    if not raw_text or not raw_text.strip():
        return []

    text = raw_text.strip()
    lines = [ln for ln in text.splitlines()]

    # 1. Timestamps
    segs = _try_line_pattern(lines, TIMESTAMP_RE, group_idx=2)
    if len(segs) >= 2:
        logger.info(f"Parsed {len(segs)} segments via timestamp pattern")
        return segs

    # 2. Duration prefix
    segs = _try_line_pattern(lines, DURATION_RE, group_idx=2)
    if len(segs) >= 2:
        logger.info(f"Parsed {len(segs)} segments via duration pattern")
        return segs

    # 3. Numbered scenes
    segs = _try_line_pattern(lines, NUMBERED_RE, group_idx=2)
    if len(segs) >= 2:
        logger.info(f"Parsed {len(segs)} segments via numbered pattern")
        return segs

    # 4. Bullets
    segs = _try_line_pattern(lines, BULLET_RE, group_idx=1)
    if len(segs) >= 2:
        logger.info(f"Parsed {len(segs)} segments via bullet pattern")
        return segs

    # 5. Paragraph split (blank-line separators)
    paras = _split_paragraphs(text)
    if len(paras) >= 2:
        logger.info(f"Parsed {len(paras)} segments via paragraph split")
        return paras

    # 6. Single-line-per-segment fallback (if user provided multiple non-empty lines)
    nonempty = [_clean(ln) for ln in lines if ln.strip()]
    if len(nonempty) >= 2:
        logger.info(f"Parsed {len(nonempty)} segments via line split")
        return nonempty

    # 7. Last resort: Gemini segmentation for unstructured blob
    if target_segments and target_segments > 1:
        logger.info(f"Falling back to Gemini segmentation for {target_segments} segments")
        return _gemini_segment(text, target_segments)

    # 8. Single segment
    return [_clean(text)]


def normalize_for_veo(segments: List[str], max_segments: int) -> List[dict]:
    """
    Convert raw segment prompts to Veo-ready plan:
    - segment 0: 8s base clip
    - segments 1..N-1: 7s extensions (Veo's fixed increment)
    Caps at max_segments.
    """
    capped = segments[:max_segments]
    plan = []
    for i, prompt in enumerate(capped):
        plan.append({
            "index": i,
            "prompt": prompt,
            "duration": 8 if i == 0 else 7,
            "kind": "base" if i == 0 else "extension",
            "status": "pending",
            "operation_name": None,
            "video_filename": None,
        })
    return plan
