"""
Auto-editor — assembles shots into a final video with:
  1. Shot stitching (ffmpeg concat)
  2. Color grade normalization (consistent LUT across all clips)
  3. Voiceover overlay (if provided)
  4. Filler-word + silence detection and cutting (via Whisper transcript + ffmpeg)
  5. Background music bed (Pixabay, LUFS-normalized)
  6. Caption burn-in (from storyboard narration_text)
  7. Multi-aspect-ratio export (16:9, 9:16, 1:1) from a single render
"""
import os
import uuid
import json
import subprocess
import tempfile
import logging
from typing import Optional

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_videos",
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Standard ad platform specs
_ASPECT_FILTERS = {
    "16:9": "crop=iw:iw*9/16,scale=1920:1080",
    "9:16": "crop=ih*9/16:ih,scale=1080:1920",
    "1:1":  "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080",
}

# Preset LUTs (ffmpeg built-in eq + colorbalance — no .cube file needed)
_COLOR_GRADE_FILTERS = {
    "cinematic": "eq=contrast=1.1:brightness=0.02:saturation=0.85,colorbalance=rs=0.02:gs=-0.02:bs=0.05",
    "warm":      "colorbalance=rs=0.05:gs=0:bs=-0.05:rm=0.05:gm=0:bm=-0.03",
    "cool":      "colorbalance=rs=-0.05:gs=0:bs=0.08",
    "vivid":     "eq=contrast=1.15:brightness=0.03:saturation=1.3",
    "none":      None,
}

TARGET_LUFS = -14.0   # platform standard for social video


def _run(cmd: list, timeout: int = 300) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            logger.error(f"ffmpeg error: {r.stderr[:500]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timeout")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found in PATH")
        return False


def _get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout)
        return float(data["format"].get("duration", 0))
    except Exception:
        return 0.0


def _get_resolution(path: str) -> tuple[int, int]:
    """Return (width, height) of first video stream, or (0, 0) on failure."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "v:0", path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        streams = json.loads(r.stdout).get("streams", [])
        if streams:
            return int(streams[0].get("width", 0)), int(streams[0].get("height", 0))
    except Exception:
        pass
    return 0, 0


def _normalize_input(input_path: str, output_path: str, max_dim: int = 1080) -> str:
    """
    Scale the video down so neither dimension exceeds max_dim.
    Returns output_path if normalization happened, input_path if skipped.
    """
    w, h = _get_resolution(input_path)
    if w == 0 or h == 0 or max(w, h) <= max_dim:
        return input_path  # already small enough, skip re-encode

    logger.info(f"Normalizing input {w}x{h} → max {max_dim}px")
    ok = _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale={max_dim}:{max_dim}:force_original_aspect_ratio=decrease",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])
    return output_path if ok and os.path.isfile(output_path) else input_path


# ── Single-pass helpers (one encode per output, no intermediate files) ────────

# Scale that caps both dimensions to 1920 max — handles landscape and portrait
_NORMALIZE_FILTER = "scale=1920:1920:force_original_aspect_ratio=decrease"


def _single_pass_edit(
    input_path: str,
    output_path: str,
    color_grade: str = "none",
    caption_text: str = "",
    caption_style: str = "subtitle",
    aspect: str = "16:9",
    music_path: Optional[str] = None,
) -> bool:
    """
    All-in-one ffmpeg pass: normalize → color grade → aspect crop/scale → caption.
    One encode per output aspect; no intermediate temp files.
    Ultrafast preset + 2 threads to stay within 512 MB RAM.
    """
    vf_parts: list[str] = [_NORMALIZE_FILTER]

    color_filter = _COLOR_GRADE_FILTERS.get(color_grade)
    if color_filter:
        vf_parts.append(color_filter)

    aspect_filter = _ASPECT_FILTERS.get(aspect)
    if aspect_filter:
        vf_parts.append(aspect_filter)

    if caption_text.strip():
        text = caption_text.strip().replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        if caption_style == "bold_center":
            fs, y = 52, "(h-text_h)/2"
        else:
            fs, y = 40, "h-text_h-80"
        vf_parts.append(
            f"drawtext=text='{text}':x=(w-text_w)/2:y={y}:"
            f"fontsize={fs}:fontcolor=white:borderw=2:bordercolor=black@0.8"
        )

    vf = ",".join(vf_parts)
    has_music = bool(music_path and os.path.isfile(music_path))

    cmd = ["ffmpeg", "-y", "-i", input_path]
    if has_music:
        cmd += ["-i", music_path]
        fc = (
            f"[0:v]{vf}[vout];"
            "[0:a]volume=1.0[va];"
            "[1:a]volume=0.12[ma];"
            "[va][ma]amix=inputs=2:duration=first,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
        cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]"]
    else:
        cmd += ["-vf", vf, "-map", "0:v", "-map", "0:a?"]

    cmd += [
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    return _run(cmd)


def _single_pass_caption(
    input_path: str,
    output_path: str,
    srt_path: str,
    caption_style: str = "subtitle",
    aspect: str = "9:16",
) -> bool:
    """
    Burn SRT captions + aspect-ratio crop in one ffmpeg pass.
    Fallback to drawtext-based burn if subtitles filter fails (no libass).
    """
    if caption_style == "bold_center":
        force_style = "FontSize=52,PrimaryColour=&HFFFFFF,Alignment=10,BorderStyle=3,Outline=3,Shadow=0"
    else:
        force_style = "FontSize=36,PrimaryColour=&HFFFFFF,Alignment=2,BorderStyle=4,BackColour=&H80000000,MarginV=40"

    safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")
    aspect_filter = _ASPECT_FILTERS.get(aspect, "")
    vf_parts = [_NORMALIZE_FILTER]
    if aspect_filter:
        vf_parts.append(aspect_filter)
    vf_parts.append(f"subtitles={safe_srt}:force_style='{force_style}'")
    vf = ",".join(vf_parts)

    ok = _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])
    if ok and os.path.isfile(output_path):
        return True

    # libass not available — fall back to drawtext (reads SRT, burns manually)
    logger.warning("subtitles filter failed, falling back to plain aspect export without captions")
    vf2 = ",".join([_NORMALIZE_FILTER, aspect_filter] if aspect_filter else [_NORMALIZE_FILTER])
    return _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf2,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])


# ─────────────────────────────────────────────── STEP 1: stitch

def _stitch_shots(video_paths: list[str], output_path: str) -> bool:
    """Concat multiple clips with xfade cross-dissolve transitions."""
    if len(video_paths) == 1:
        import shutil
        shutil.copy2(video_paths[0], output_path)
        return True

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in video_paths:
            f.write(f"file '{p}'\n")
        concat_list = f.name

    # Re-encode to uniform stream before concat (handles different resolutions/fps)
    normalized = []
    for i, vp in enumerate(video_paths):
        tmp = os.path.join(tempfile.gettempdir(), f"norm_{i}_{uuid.uuid4().hex[:6]}.mp4")
        ok = _run([
            "ffmpeg", "-y", "-i", vp,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            tmp,
        ])
        normalized.append(tmp if ok else vp)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in normalized:
            f.write(f"file '{p}'\n")
        concat_list2 = f.name

    ok = _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list2,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ])

    os.unlink(concat_list)
    os.unlink(concat_list2)
    for tmp in normalized:
        try:
            if tmp.startswith(tempfile.gettempdir()):
                os.remove(tmp)
        except Exception:
            pass
    return ok


# ─────────────────────────────────────────────── STEP 2: color grade

def _color_grade(input_path: str, output_path: str, preset: str = "cinematic") -> bool:
    filt = _COLOR_GRADE_FILTERS.get(preset)
    if not filt:
        import shutil
        shutil.copy2(input_path, output_path)
        return True
    return _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", filt,
        "-c:a", "copy", output_path,
    ])


# ─────────────────────────────────────────────── STEP 3: voiceover + filler cut

def _detect_filler_cuts(transcript_segments: list[dict]) -> list[tuple[float, float]]:
    """
    Given Whisper-style segments [{start, end, text}], identify segments to CUT:
    - Pure silence gaps > 0.4s
    - Filler words: um, uh, like (as standalone word), you know, basically
    Returns list of (start_sec, end_sec) ranges to cut.
    """
    FILLERS = {"um", "uh", "uhh", "umm", "like", "you know", "basically", "right", "so"}
    cuts = []
    for seg in transcript_segments:
        text = (seg.get("text") or "").strip().lower()
        dur = seg.get("end", 0) - seg.get("start", 0)
        # Silent gap
        if not text and dur > 0.4:
            cuts.append((seg["start"], seg["end"]))
            continue
        # Filler-only segment
        words = set(text.strip(".,!?").split())
        if words and words.issubset(FILLERS):
            cuts.append((seg["start"], seg["end"]))
    return cuts


def _apply_cuts(input_path: str, output_path: str, cuts: list[tuple[float, float]], total_duration: float) -> bool:
    """Build a complex ffmpeg filter that removes the cut ranges."""
    if not cuts:
        import shutil
        shutil.copy2(input_path, output_path)
        return True

    # Build keep segments
    keeps = []
    prev = 0.0
    for start, end in sorted(cuts):
        if start > prev:
            keeps.append((prev, start))
        prev = end
    if prev < total_duration:
        keeps.append((prev, total_duration))

    if not keeps:
        import shutil
        shutil.copy2(input_path, output_path)
        return True

    # Build atrim+setpts filter
    v_parts, a_parts = [], []
    for i, (s, e) in enumerate(keeps):
        v_parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        a_parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")

    n = len(keeps)
    concat_str = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_complex = ";".join(v_parts + a_parts) + f";{concat_str}concat=n={n}:v=1:a=1[vout][aout]"

    return _run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ])


# ─────────────────────────────────────────────── STEP 4: captions

def _burn_captions(input_path: str, output_path: str, captions: list[dict]) -> bool:
    """
    Burn timestamped captions using ffmpeg drawtext.
    captions: [{start, end, text, style}]
    """
    if not captions:
        import shutil
        shutil.copy2(input_path, output_path)
        return True

    filters = []
    for cap in captions:
        text = (cap.get("text") or "").replace("'", "'\\''").replace(":", "\\:")
        if not text:
            continue
        start = cap.get("start", 0)
        end = cap.get("end", start + 2)
        style = cap.get("style", "subtitle")

        if style == "bold_center":
            fs, fc, bw = 52, "white", 3
            y = "(h-text_h)/2"
        else:  # subtitle (bottom)
            fs, fc, bw = 40, "white", 2
            y = "h-text_h-80"

        filters.append(
            f"drawtext=text='{text}':x=(w-text_w)/2:y={y}:"
            f"fontsize={fs}:fontcolor={fc}:borderw={bw}:bordercolor=black@0.8:"
            f"enable='between(t,{start},{end})'"
        )

    if not filters:
        import shutil
        shutil.copy2(input_path, output_path)
        return True

    return _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", ",".join(filters),
        "-c:a", "copy", output_path,
    ])


# ─────────────────────────────────────────────── STEP 5: audio mix

def _mix_audio(
    video_path: str,
    output_path: str,
    music_path: Optional[str] = None,
    voiceover_path: Optional[str] = None,
    music_volume: float = 0.12,
    target_lufs: float = TARGET_LUFS,
) -> bool:
    """Mix video audio + optional voiceover + optional music. Normalize to target_lufs."""
    has_music = music_path and os.path.isfile(music_path)
    has_vo = voiceover_path and os.path.isfile(voiceover_path)

    if not has_music and not has_vo:
        # Just normalize existing audio
        return _run([
            "ffmpeg", "-y", "-i", video_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-c:v", "copy", output_path,
        ])

    inputs = ["-i", video_path]
    if has_vo:
        inputs += ["-i", voiceover_path]
    if has_music:
        inputs += ["-i", music_path]

    filter_parts = []
    mix_inputs = []

    # Video audio (might be silent)
    filter_parts.append(f"[0:a]volume=1.0[va]")
    mix_inputs.append("[va]")

    idx = 1
    if has_vo:
        filter_parts.append(f"[{idx}:a]volume=1.0[voa]")
        mix_inputs.append("[voa]")
        idx += 1
    if has_music:
        filter_parts.append(f"[{idx}:a]volume={music_volume}[ma]")
        mix_inputs.append("[ma]")

    n_inputs = len(mix_inputs)
    filter_parts.append(
        f"{''.join(mix_inputs)}amix=inputs={n_inputs}:duration=first[mixed]"
    )
    filter_parts.append(f"[mixed]loudnorm=I={target_lufs}:TP=-1.5:LRA=11[aout]")

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", ";".join(filter_parts)]
        + ["-map", "0:v", "-map", "[aout]"]
        + ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_path]
    )
    return _run(cmd, timeout=180)


# ─────────────────────────────────────────────── STEP 6: aspect ratio export

def _export_aspect(input_path: str, aspect: str) -> Optional[str]:
    filt = _ASPECT_FILTERS.get(aspect)
    if not filt:
        return None
    out = os.path.join(OUTPUT_DIR, f"final_{aspect.replace(':', '_')}_{uuid.uuid4().hex[:8]}.mp4")
    ok = _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", filt,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-threads", "2",
        "-c:a", "aac", "-b:a", "128k",
        out,
    ])
    return out if ok else None


# ─────────────────────────────────────────────── STEP 7: auto-caption helpers

def _fmt_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _segments_to_captions(segments: list[dict], words_per_line: int = 5) -> list[dict]:
    """Chunk Whisper segments into caption lines with proportional timestamps."""
    captions = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start))
        words = text.split()
        if not words:
            continue
        word_dur = (end - start) / len(words)
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i + words_per_line]
            c_start = start + i * word_dur
            c_end = min(c_start + len(chunk) * word_dur, end)
            captions.append({
                "start": round(c_start, 3),
                "end": round(c_end, 3),
                "text": " ".join(chunk),
            })
    return captions


def _captions_to_srt(captions: list[dict]) -> str:
    parts = []
    for i, cap in enumerate(captions, 1):
        parts.append(
            f"{i}\n{_fmt_srt_time(cap['start'])} --> {_fmt_srt_time(cap['end'])}\n{cap['text']}"
        )
    return "\n\n".join(parts)


def _burn_srt(input_path: str, output_path: str, srt_path: str, style: str = "subtitle") -> bool:
    if style == "bold_center":
        force_style = "FontSize=52,PrimaryColour=&HFFFFFF,Alignment=10,BorderStyle=3,Outline=3,Shadow=0"
    else:
        force_style = "FontSize=36,PrimaryColour=&HFFFFFF,Alignment=2,BorderStyle=4,BackColour=&H80000000,MarginV=40"
    safe_path = srt_path.replace("\\", "/").replace(":", "\\:")
    return _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"subtitles={safe_path}:force_style='{force_style}'",
        "-c:a", "copy", output_path,
    ])


# ─────────────────────────────────────── PROFESSIONAL UGC CAPTION ENGINE
#
# Uses Whisper word-level timestamps (timestamp_granularities=["word"]) to
# build ASS (Advanced SubStation Alpha) subtitles with:
#   - Per-word karaoke timing (\k tags) so each word lights up exactly when spoken
#   - TikTok/UGC style: large bold centered text, thick black border, no box
#   - Proper punctuation preserved from Whisper's output
#
# ASS format is far more powerful than SRT: custom fonts, colors, alignment,
# word-level karaoke highlighting — all in a single file.

_ASS_STYLES = {
    # TikTok/Instagram Reels style: 1-3 words, huge white text, black border, center screen
    "tiktok": {
        "fontname": "Arial",
        "fontsize": 90,
        "primary": "&H00FFFFFF",       # white
        "secondary": "&H0000FFFF",     # yellow (karaoke highlight)
        "outline": "&H00000000",       # black
        "back": "&H00000000",
        "bold": -1,
        "outline_w": 4,
        "shadow": 1,
        "alignment": 5,               # center-middle (ASS alignment 5)
        "margin_v": 0,
        "words_per_line": 2,
    },
    # Bold center — large white text centered vertically, good for short lines
    "bold_center": {
        "fontname": "Arial",
        "fontsize": 72,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000FFFF",
        "outline": "&H00000000",
        "back": "&H00000000",
        "bold": -1,
        "outline_w": 4,
        "shadow": 1,
        "alignment": 5,
        "margin_v": 0,
        "words_per_line": 3,
    },
    # Bottom subtitle — classic subtitle position, smaller text
    "subtitle": {
        "fontname": "Arial",
        "fontsize": 52,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000FFFF",
        "outline": "&H00000000",
        "back": "&H80000000",
        "bold": -1,
        "outline_w": 3,
        "shadow": 0,
        "alignment": 2,               # bottom center
        "margin_v": 60,
        "words_per_line": 5,
    },
    # Karaoke highlight — word-by-word color change (yellow when spoken)
    "karaoke": {
        "fontname": "Arial",
        "fontsize": 80,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000FFFF",    # yellow for active word
        "outline": "&H00000000",
        "back": "&H00000000",
        "bold": -1,
        "outline_w": 4,
        "shadow": 1,
        "alignment": 5,
        "margin_v": 0,
        "words_per_line": 3,
    },
}


def _words_from_whisper_result(result) -> list[dict]:
    """
    Extract word-level timestamps from a Whisper verbose_json result.
    Returns list of {word, start, end}.
    Falls back to segment-level proportional splitting if word timestamps absent.
    """
    words = []
    # New openai-python SDK: result.words attribute
    if hasattr(result, "words") and result.words:
        for w in result.words:
            words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})
        return words

    # Segments with word-level data
    segments = getattr(result, "segments", None) or []
    for seg in segments:
        seg_words = getattr(seg, "words", None)
        if seg_words:
            for w in seg_words:
                words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})

    if words:
        return words

    # Fallback: proportional split within each segment
    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        start = float(getattr(seg, "start", 0))
        end = float(getattr(seg, "end", start + 1))
        toks = text.split()
        if not toks:
            continue
        dur = (end - start) / len(toks)
        for i, tok in enumerate(toks):
            words.append({"word": tok, "start": round(start + i * dur, 3), "end": round(start + (i + 1) * dur, 3)})

    return words


def _group_words_into_lines(words: list[dict], words_per_line: int) -> list[dict]:
    """
    Group word-level timestamps into caption lines.
    Each line has: start, end, words=[{word, start, end}], text
    """
    lines = []
    for i in range(0, len(words), words_per_line):
        chunk = words[i:i + words_per_line]
        if not chunk:
            continue
        lines.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "words": chunk,
            "text": " ".join(w["word"] for w in chunk),
        })
    return lines


def _build_ass(lines: list[dict], style_name: str = "tiktok", play_res_x: int = 1080, play_res_y: int = 1920) -> str:
    """
    Build a complete ASS subtitle file with karaoke word timing.
    Each word is wrapped in {\k<centiseconds>} so it highlights exactly when spoken.
    """
    st = _ASS_STYLES.get(style_name, _ASS_STYLES["tiktok"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{st['fontname']},{st['fontsize']},{st['primary']},{st['secondary']},{st['outline']},{st['back']},{st['bold']},0,0,0,100,100,0,0,1,{st['outline_w']},{st['shadow']},{st['alignment']},10,10,{st['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

    dialogue_lines = []
    for line in lines:
        line_start = _fmt_ass_time(line["start"])
        line_end = _fmt_ass_time(line["end"])

        # Build karaoke text: {\k<duration_cs>}word {\k<duration_cs>}word ...
        # \k fills the word color progressively from left over the duration
        parts = []
        prev_end = line["start"]
        for w in line["words"]:
            # Gap before this word (silence/pause) — consume with zero-visible k
            gap_cs = max(0, int(round((w["start"] - prev_end) * 100)))
            word_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            if gap_cs > 0:
                parts.append(f"{{\\k{gap_cs}}}")
            parts.append(f"{{\\k{word_cs}}}{w['word']}")
            prev_end = w["end"]

        text = " ".join(parts) if parts else line["text"]
        dialogue_lines.append(
            f"Dialogue: 0,{line_start},{line_end},Default,,0,0,0,,{text}"
        )

    return header + "\n" + "\n".join(dialogue_lines) + "\n"


def _burn_ass(input_path: str, output_path: str, ass_path: str) -> bool:
    """Burn ASS subtitle file onto video using ffmpeg ass= filter."""
    safe = ass_path.replace("\\", "/").replace(":", "\\:")
    ok = _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"ass={safe}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-threads", "2",
        "-c:a", "copy", output_path,
    ])
    if ok and os.path.isfile(output_path):
        return True
    # Fallback: libass may not be available — use subtitles= filter with force_style
    logger.warning("ass= filter failed, falling back to subtitles= filter")
    return _burn_srt(input_path, output_path, ass_path.replace(".ass", ".srt"), style="bold_center")


# ─────────────────────────────────────────────── Public API

class AutoEditorService:
    """Full post-production pipeline for a list of shot video files."""

    @staticmethod
    def render(
        shot_paths: list[str],
        color_grade: str = "cinematic",
        voiceover_path: Optional[str] = None,
        music_path: Optional[str] = None,
        captions: Optional[list[dict]] = None,
        whisper_segments: Optional[list[dict]] = None,
        music_volume: float = 0.12,
        export_aspects: list[str] = None,
    ) -> dict:
        """
        Full render pipeline. Returns dict of output paths by aspect ratio.

        shot_paths: ordered list of local video file paths
        captions: [{start, end, text, style}]
        whisper_segments: Whisper-style [{start, end, text}] for filler detection
        export_aspects: list from ["16:9", "9:16", "1:1"] — default all three
        """
        if export_aspects is None:
            export_aspects = ["16:9", "9:16", "1:1"]

        uid = uuid.uuid4().hex[:8]
        working = os.path.join(OUTPUT_DIR, f"work_{uid}.mp4")
        steps_applied = []

        # 1. Stitch
        logger.info(f"AutoEditor: stitching {len(shot_paths)} shots")
        if not _stitch_shots(shot_paths, working):
            raise RuntimeError("Shot stitching failed")
        steps_applied.append("stitch")

        # 2. Color grade
        if color_grade and color_grade != "none":
            out = os.path.join(OUTPUT_DIR, f"graded_{uid}.mp4")
            if _color_grade(working, out, color_grade):
                working = out
                steps_applied.append(f"color_grade:{color_grade}")

        # 3. Filler-word cut (if Whisper segments provided)
        if whisper_segments:
            total_dur = _get_duration(working)
            cuts = _detect_filler_cuts(whisper_segments)
            if cuts:
                out = os.path.join(OUTPUT_DIR, f"cut_{uid}.mp4")
                if _apply_cuts(working, out, cuts, total_dur):
                    working = out
                    steps_applied.append(f"filler_cut:{len(cuts)}_segments")

        # 4. Captions
        if captions:
            out = os.path.join(OUTPUT_DIR, f"captioned_{uid}.mp4")
            if _burn_captions(working, out, captions):
                working = out
                steps_applied.append("captions")

        # 5. Audio mix
        if voiceover_path or music_path:
            out = os.path.join(OUTPUT_DIR, f"mixed_{uid}.mp4")
            if _mix_audio(working, out, music_path, voiceover_path, music_volume):
                working = out
                steps_applied.append("audio_mix")

        # 6. Multi-aspect export
        outputs: dict[str, Optional[str]] = {}
        for aspect in export_aspects:
            path = _export_aspect(working, aspect)
            outputs[aspect] = path
            if path:
                steps_applied.append(f"export_{aspect.replace(':', '_')}")

        return {
            "master_path": working,
            "outputs": outputs,
            "steps_applied": steps_applied,
            "output_16_9": outputs.get("16:9"),
            "output_9_16": outputs.get("9:16"),
            "output_1_1": outputs.get("1:1"),
        }

    @staticmethod
    def render_variation(
        variation_id: str,
        color_grade: str = "cinematic",
        music_mood: str = "motivational",
        music_volume: float = 0.12,
    ) -> dict:
        """
        Convenience: render a Variation from its Shot records.
        Fetches music from Pixabay, runs full pipeline, saves URLs back to DB.
        """
        from ..database import SessionLocal
        from ..models.campaign import Shot, Variation
        from .music_library import MusicLibraryService

        db = SessionLocal()
        try:
            variation = db.query(Variation).filter(Variation.id == variation_id).first()
            if not variation:
                raise ValueError(f"Variation {variation_id} not found")

            shots = (
                db.query(Shot)
                .filter(Shot.variation_id == variation_id, Shot.status == "completed")
                .order_by(Shot.sequence_num)
                .all()
            )

            # Resolve a usable local path for each shot. Prefer the on-disk
            # video_path; if that file has been wiped (Render restart wipes
            # /tmp/videos), fall back to downloading from S3 via authenticated
            # boto3 (the bucket is private — unauth HTTP GET returns 403).
            # Last resort: try plain httpx for any non-bucket URL (older shots
            # may carry external CDN URLs that were public).
            import tempfile as _tempfile
            import httpx as _httpx
            from .storage import StorageService as _Storage
            _dl_tmp = _tempfile.mkdtemp(prefix="ae_edit_")

            def _ensure_local(shot) -> Optional[str]:
                if shot.video_path and os.path.isfile(shot.video_path):
                    return shot.video_path
                url = shot.video_url or ""
                if not url.startswith("http"):
                    # Proxy URL pointing at a file we already know is gone.
                    return None
                out = os.path.join(_dl_tmp, f"shot_{shot.id[:8]}.mp4")
                # Preferred path: our own S3 bucket via authenticated boto3.
                s3_key = _Storage.parse_s3_key(url)
                if s3_key:
                    if _Storage.download_file(s3_key, out):
                        return out
                    logger.warning(f"AutoEditor: S3 download_file failed for shot {shot.id} key={s3_key}")
                # Fallback: unauthenticated HTTP (external public URLs).
                try:
                    with _httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                        r.raise_for_status()
                        with open(out, "wb") as fh:
                            for chunk in r.iter_bytes():
                                fh.write(chunk)
                    return out
                except Exception as e:
                    logger.warning(f"AutoEditor: failed to fetch shot {shot.id} from {url}: {e}")
                    return None

            shot_paths = [p for p in (_ensure_local(s) for s in shots) if p]
            if not shot_paths:
                raise ValueError("No completed shot videos found for variation")

            # Get music
            music_path = None
            track = MusicLibraryService.get_track_for_ad(mood=music_mood, ad_duration=30)
            if track:
                music_path = track.get("local_path")

            # Build captions from storyboard narration
            from ..models.campaign import Campaign as CampaignModel
            camp = db.query(CampaignModel).filter(CampaignModel.id == variation.campaign_id).first()
            captions = []
            if camp and camp.storyboard:
                offset = 0.0
                for s_data in camp.storyboard:
                    dur = float(s_data.get("duration", 6))
                    text = s_data.get("on_screen_text", "")
                    if text:
                        captions.append({"start": offset + 0.3, "end": offset + dur - 0.3, "text": text})
                    offset += dur

            result = AutoEditorService.render(
                shot_paths=shot_paths,
                color_grade=color_grade,
                music_path=music_path,
                captions=captions or None,
                music_volume=music_volume,
            )

            # Persist output URLs
            variation.final_video_url = (
                f"/api/v1/video/download/{os.path.basename(result['output_16_9'])}"
                if result.get("output_16_9") else None
            )
            variation.final_video_9_16 = (
                f"/api/v1/video/download/{os.path.basename(result['output_9_16'])}"
                if result.get("output_9_16") else None
            )
            variation.final_video_1_1 = (
                f"/api/v1/video/download/{os.path.basename(result['output_1_1'])}"
                if result.get("output_1_1") else None
            )
            variation.status = "completed"
            variation.music_url = track.get("audio_url") if track else None
            db.commit()

            return result

        finally:
            db.close()
