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
        "-c:a", "copy", out,
    ])
    return out if ok else None


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

            shot_paths = [s.video_path for s in shots if s.video_path and os.path.isfile(s.video_path)]
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
