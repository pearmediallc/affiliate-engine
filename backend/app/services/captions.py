"""
Accurate captions from OUR known script (no ASR guesswork → no fillers/gaps):
  1) forced-align the exact script to the TTS audio → word timestamps
     (ElevenLabs Forced Alignment primary; Deepgram fallback)
  2) build a clean ASS subtitle (short phrase lines, word-timed)
  3) the caller burns it with ffmpeg (subtitles=…), or VEED-via-fal for fancy styles.
"""
import logging
import os
import re
import subprocess
import time
import requests

from ..config import settings

logger = logging.getLogger(__name__)

# Spoken CTAs — when the script says one of these, the caption becomes a BUTTON, not a text line.
CTA_PHRASES = [
    "click below", "click the link", "click the button", "click here", "tap below",
    "tap the link", "tap the button", "link below", "link in bio", "swipe up",
    "get your quote", "check your rate", "see if you qualify", "check eligibility",
    "apply now", "call now", "get started", "sign up", "learn more",
]


def _fmt(t: float) -> str:
    t = max(0.0, float(t)); h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def audio_duration(path: str) -> float:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=30)
        return float((p.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def even_split(text: str, duration: float) -> list:
    """Last-resort alignment: we ALWAYS know the exact script and the audio length, so spread the
    words across the duration weighted by word length. Not sample-accurate, but it means captions
    can never silently vanish just because an aligner API hiccuped."""
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words or duration <= 0:
        return []
    weights = [max(2, len(w)) for w in words]
    total = float(sum(weights))
    out, t = [], 0.0
    for w, wt in zip(words, weights):
        dur = duration * (wt / total)
        out.append({"word": w, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur
    return out


def align(audio_path: str, text: str) -> tuple:
    """Word timings that are NEVER empty. Returns (words, method).
    forced-align (exact) → even-split from the known script (approximate but always present)."""
    words = forced_align(audio_path, text)
    if words:
        return words, "forced-align"
    dur = audio_duration(audio_path)
    words = even_split(text, dur)
    if words:
        logger.warning(f"captions: aligners returned nothing → even-split fallback over {dur:.1f}s")
        return words, "even-split"
    return [], "none"


def forced_align(audio_path: str, text: str) -> list:
    """Return [{word, start, end}] aligning `text` to `audio_path`. ElevenLabs → Deepgram."""
    # ElevenLabs Forced Alignment (we already use ElevenLabs for voice)
    if settings.elevenlabs_api_key:
        try:
            with open(audio_path, "rb") as f:
                r = requests.post("https://api.elevenlabs.io/v1/forced-alignment",
                                  headers={"xi-api-key": settings.elevenlabs_api_key},
                                  files={"file": f}, data={"text": text}, timeout=120)
            if r.status_code == 200:
                d = r.json()
                words = d.get("words") or []
                out = [{"word": w.get("text", "").strip(), "start": w.get("start", 0), "end": w.get("end", 0)}
                       for w in words if w.get("text", "").strip()]
                if out:
                    return out
            else:
                logger.warning(f"elevenlabs FA {r.status_code}: {r.text[:160]}")
        except Exception as e:
            logger.warning(f"elevenlabs forced-align failed: {e}")
    # Deepgram fallback (word timestamps from ASR — less exact but has timings)
    if settings.deepgram_api_key:
        try:
            with open(audio_path, "rb") as f:
                r = requests.post("https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
                                  headers={"Authorization": f"Token {settings.deepgram_api_key}",
                                           "Content-Type": "audio/mpeg"}, data=f.read(), timeout=120)
            if r.status_code == 200:
                w = (((r.json().get("results") or {}).get("channels") or [{}])[0].get("alternatives") or [{}])[0].get("words") or []
                return [{"word": x.get("word", ""), "start": x.get("start", 0), "end": x.get("end", 0)} for x in w if x.get("word")]
        except Exception as e:
            logger.warning(f"deepgram align fallback failed: {e}")
    return []


def _cta_spans(words: list) -> list:
    """Word-index ranges [start, end) where the script actually speaks a CTA, so we can render
    that phrase as a BUTTON instead of a normal caption line."""
    toks, offs, pos = [], [], 0
    for w in words:
        t = re.sub(r"[^a-z0-9 ]", "", (w.get("word") or "").lower())
        toks.append(t)
        offs.append((pos, pos + len(t)))
        pos += len(t) + 1
    joined = " ".join(toks)
    spans = []
    for p in CTA_PHRASES:
        for m in re.finditer(re.escape(p), joined):
            s, e = m.start(), m.end()
            si = next((i for i, (a, b) in enumerate(offs) if b > s), None)
            ei = next((i for i in range(len(offs) - 1, -1, -1) if offs[i][0] < e), None)
            if si is not None and ei is not None and ei >= si:
                spans.append((si, ei + 1))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def build_ass(words: list, out_ass_path: str, per_line: int = 4, play_w: int = 1080, play_h: int = 1920) -> str | None:
    """Group words into short phrase lines (word-timed) and write a clean ASS subtitle.
    A spoken CTA ("click below", "get your quote"…) is emitted as a whole phrase in the CTA
    style — an opaque blue button with white bold text — so the viewer sees a real call-to-action."""
    if not words:
        return None
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        "Style: Def,Arial,64,&H00FFFFFF,&H00000000,&H96000000,-1,0,1,3,1,2,60,60,220\n"
        # BorderStyle=3 = opaque box; Outline=14 = the button's padding; box colour is BGR blue.
        "Style: Cta,Arial,66,&H00FFFFFF,&H00E07A1F,&H00000000,-1,0,3,14,0,2,80,80,260\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        % (play_w, play_h)
    )
    ctas = _cta_spans(words)
    cta_start = {s: e for s, e in ctas}
    inside = {i for s, e in ctas for i in range(s, e)}

    def _line(chunk, style):
        start = chunk[0]["start"]; end = chunk[-1]["end"]
        if end <= start:
            end = start + 1.2
        if style == "Cta":
            end += 0.6   # let the button linger a beat so it's readable/clickable-feeling
        text = " ".join(w["word"] for w in chunk).replace("\n", " ").strip().upper()
        return f"Dialogue: 0,{_fmt(start)},{_fmt(end)},{style},,0,0,0,,{text}"

    lines, i, buf = [], 0, []
    while i < len(words):
        if i in cta_start:                       # flush the pending text, then emit the button
            if buf:
                lines.append(_line(buf, "Def")); buf = []
            e = cta_start[i]
            lines.append(_line(words[i:e], "Cta"))
            i = e
            continue
        if i in inside:                          # covered by a span we already emitted
            i += 1
            continue
        buf.append(words[i]); i += 1
        if len(buf) >= per_line:
            lines.append(_line(buf, "Def")); buf = []
    if buf:
        lines.append(_line(buf, "Def"))
    with open(out_ass_path, "w") as f:
        f.write(header + "\n".join(lines) + "\n")
    return out_ass_path


def _srt_ts(t: float) -> str:
    t = max(0.0, float(t)); h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words: list, out_srt_path: str, per_line: int = 6) -> str | None:
    """SRT from our forced-aligned words — fed to VEED so it keeps OUR accuracy (skips its ASR)."""
    if not words:
        return None
    blocks, idx = [], 1
    for i in range(0, len(words), per_line):
        chunk = words[i:i + per_line]
        start = chunk[0]["start"]; end = chunk[-1]["end"] or (start + 1.2)
        if end <= start:
            end = start + 1.2
        text = " ".join(w["word"] for w in chunk).strip()
        blocks.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}\n")
        idx += 1
    with open(out_srt_path, "w") as f:
        f.write("\n".join(blocks))
    return out_srt_path


def veed_subtitles(video_url: str, preset: str = "glide", srt_text: str | None = None) -> str:
    """Burn styled captions via the VEED Subtitle API on fal.ai. Returns the output video URL.
    Passes our SRT when possible (keeps forced-alignment accuracy); else VEED transcribes."""
    key = settings.fal_key
    if not key:
        raise RuntimeError("no fal key (VEED captions run on fal.ai)")
    base = "https://queue.fal.run/veed/subtitles"
    inp = {"video_url": video_url}
    if preset:
        inp["preset"] = preset
    if srt_text:
        inp["subtitles"] = srt_text   # bypass VEED transcription → keep our exact words/timing
    h = {"Authorization": f"Key {key}"}
    r = requests.post(base, headers={**h, "Content-Type": "application/json"}, json=inp, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"veed {r.status_code}: {r.text[:200]}")
    rid = r.json().get("request_id")
    for _ in range(150):
        time.sleep(4)
        s = requests.get(f"{base}/requests/{rid}/status", headers=h, timeout=30).json()
        st = (s.get("status") or "").upper()
        if st == "COMPLETED":
            res = requests.get(f"{base}/requests/{rid}", headers=h, timeout=30).json()
            out = (res.get("video") or {}).get("url") or res.get("video_url")
            if out:
                return out
            raise RuntimeError(f"veed completed without url: {res}")
        if st in ("FAILED", "ERROR"):
            raise RuntimeError(f"veed {st}: {s}")
    raise RuntimeError("veed captions timed out")
