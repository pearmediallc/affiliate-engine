"""
Accurate captions from OUR known script (no ASR guesswork → no fillers/gaps):
  1) forced-align the exact script to the TTS audio → word timestamps
     (ElevenLabs Forced Alignment primary; Deepgram fallback)
  2) build a clean ASS subtitle (short phrase lines, word-timed)
  3) the caller burns it with ffmpeg (subtitles=…), or VEED-via-fal for fancy styles.
"""
import difflib
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


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _relabel_with_script(timed: list, script: str) -> list:
    """Keep the aligner's TIMINGS but make the caption TEXT the exact SCRIPT tokens, so the burn
    reads as WRITTEN ("$31", not Whisper's transcribed "thirty one"). Whisper/Deepgram transcribe
    the AUDIO, which drops glyphs the voice can't pronounce (the "$"); the script is ground truth.

    Per-span alignment: 1:1 when the counts match; otherwise diff the aligner words against the
    script tokens and KEEP each matched word's REAL timestamp — redistribute ONLY inside a
    mismatched span (e.g. "$31" ↔ "thirty one"), over that span's own sub-window. This keeps
    on-beat timing everywhere except the tiny number/symbol spans, instead of re-laying the whole
    track as an even split (which drifts captions ahead of the voice on any pause)."""
    tokens = [w for w in re.split(r"\s+", (script or "").strip()) if w]
    if not tokens or not timed:
        return timed
    if len(tokens) == len(timed):                      # clean 1:1 — exact per-word timing kept
        return [{"word": tok, "start": t.get("start", 0), "end": t.get("end", 0)}
                for tok, t in zip(tokens, timed)]
    a = [_norm(t.get("word", "")) for t in timed]
    b = [_norm(tok) for tok in tokens]
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":                             # matched → keep REAL whisper timing
            for k in range(j2 - j1):
                t = timed[i1 + k]
                out.append({"word": tokens[j1 + k], "start": t.get("start", 0), "end": t.get("end", 0)})
        else:                                          # local spread only (e.g. "$31" <-> "thirty one")
            seg = timed[i1:i2] or timed[max(0, i1 - 1):i1] or timed
            s, e = float(seg[0].get("start") or 0), float(seg[-1].get("end") or 0)
            toks = tokens[j1:j2]
            if not toks:
                continue
            span = max(0.0, e - s); wts = [max(2, len(x)) for x in toks]; tot = float(sum(wts)); t = s
            for tok, wt in zip(toks, wts):
                d = span * (wt / tot) if span > 0 else 0.0
                out.append({"word": tok, "start": round(t, 3), "end": round(t + d, 3)}); t += d
    return out or timed


def align(audio_path: str, text: str) -> tuple:
    """Word timings that are NEVER empty. Returns (words, method).
    Real aligners first (their timings track the actual voice, so captions stay on the beat);
    even-split only as a last resort — it is approximate and WILL feel off-pace.

    ElevenLabs FA aligns OUR script text directly, so its words already read as written. The
    Whisper/Deepgram fallbacks TRANSCRIBE the audio (losing the "$" etc.), so we keep their real
    TIMINGS but relabel the text with the SCRIPT tokens whenever we have a script."""
    for name, fn, from_script in (
            ("elevenlabs-fa", lambda: _elevenlabs_align(audio_path, text), True),
            ("whisper", lambda: _whisper_align(audio_path), False),
            ("deepgram", lambda: _deepgram_align(audio_path), False)):
        out = fn()
        if out:
            if not from_script and (text or "").strip():   # transcription path → script text wins
                out = _relabel_with_script(out, text)
            logger.info(f"captions: aligned via {name} ({len(out)} words)")
            return out, name
    dur = audio_duration(audio_path)
    words = even_split(text, dur)
    if words:
        logger.warning(f"captions: ALL aligners failed → even-split over {dur:.1f}s (pace will be approximate)")
        return words, "even-split"
    return [], "none"


def _elevenlabs_align(audio_path: str, text: str) -> list:
    if not settings.elevenlabs_api_key:
        return []
    try:
        with open(audio_path, "rb") as f:
            r = requests.post("https://api.elevenlabs.io/v1/forced-alignment",
                              headers={"xi-api-key": settings.elevenlabs_api_key},
                              files={"file": f}, data={"text": text}, timeout=120)
        if r.status_code == 200:
            words = (r.json() or {}).get("words") or []
            return [{"word": w.get("text", "").strip(), "start": w.get("start", 0), "end": w.get("end", 0)}
                    for w in words if w.get("text", "").strip()]
        logger.warning(f"elevenlabs FA {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"elevenlabs forced-align failed: {e}")
    return []


def _whisper_align(audio_path: str) -> list:
    """OpenAI Whisper word-level timestamps. These are timings against the ACTUAL audio, so the
    captions land on the beat the voice says them — this is what makes the pace correct."""
    if not settings.openai_api_key:
        return []
    try:
        with open(audio_path, "rb") as f:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": (os.path.basename(audio_path), f, "audio/mpeg")},
                data=[("model", "whisper-1"), ("response_format", "verbose_json"),
                      ("timestamp_granularities[]", "word")],
                timeout=180)
        if r.status_code == 200:
            words = (r.json() or {}).get("words") or []
            return [{"word": str(w.get("word", "")).strip(), "start": w.get("start", 0), "end": w.get("end", 0)}
                    for w in words if str(w.get("word", "")).strip()]
        logger.warning(f"whisper align {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"whisper align failed: {e}")
    return []


def _deepgram_align(audio_path: str) -> list:
    if not settings.deepgram_api_key:
        return []
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


def forced_align(audio_path: str, text: str) -> list:
    """Return [{word, start, end}] aligning `text` to `audio_path`.
    ElevenLabs FA (exact, uses our script) → Whisper word timestamps (real timings from the
    audio itself) → Deepgram. Whisper matters: it's what keeps the caption pace on the voice."""
    for name, fn in (("elevenlabs-fa", lambda: _elevenlabs_align(audio_path, text)),
                     ("whisper", lambda: _whisper_align(audio_path)),
                     ("deepgram", lambda: _deepgram_align(audio_path))):
        out = fn()
        if out:
            logger.info(f"captions: aligned via {name} ({len(out)} words)")
            return out
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


def _cta_button_lines(text: str, start: float, end: float, play_w: int, play_h: int, marginv: int, k: float) -> list:
    """Render a spoken CTA as an ANIMATED, HIGHLIGHTED button instead of a static box:
       • pop-in when it first appears, then a gentle continuous pulse (grows/shrinks) so the eye
         is pulled to it — a clear 'tap me' affordance the old static box lacked;
       • an expanding, fading outline RING once per pulse = a tap-ripple around the button.
    Pure ASS animation (\\t transforms) so it stays in the SAME single libass burn — no extra
    ffmpeg pass, no image assets, no new dependency."""
    cx = play_w // 2
    cy = play_h - marginv           # button centre (\an5), independent of caption flow
    # Use the caller's `end` verbatim — it ALREADY held the CTA (up to ~2.5s) and capped it at the
    # next caption's start. Stretching here (the old max(0.8,…)) pushed the pulsing button PAST that
    # cap, so it overlapped the next caption. Only guard a degenerate zero/negative window.
    if end - start < 0.25:
        end = start + 0.25
    cyc = 0.65                       # one pulse cycle
    lines, t, first = [], start, True
    while t < end - 1e-3:
        ce = min(t + cyc, end)
        ms = max(120, int((ce - t) * 1000))
        half = max(60, ms // 2)
        if first:                    # pop-in: snap up from small, overshoot, settle
            eff = r"{\an5\pos(%d,%d)\fscx70\fscy70\t(0,200,\fscx106\fscy106)\t(200,%d,\fscx100\fscy100)}" % (cx, cy, ms)
            first = False
        else:                        # steady pulse: grow then shrink within the cycle
            eff = r"{\an5\pos(%d,%d)\t(0,%d,\fscx106\fscy106)\t(%d,%d,\fscx100\fscy100)}" % (cx, cy, half, half, ms)
        lines.append("Dialogue: 2,%s,%s,Cta,,0,0,0,,%s%s" % (_fmt(t), _fmt(ce), eff, text))
        # NOTE: the old "tap-ripple ring" (a CtaGlow copy of the SAME words with an expanding outline)
        # rendered as a large, OFFSET yellow duplicate BEHIND the blue button — it read as a broken
        # double caption. Removed: the blue pulsing button alone is the CTA affordance now.
        t = ce
    return lines


def build_ass(words: list, out_ass_path: str, per_line: int = 3, play_w: int = 1080, play_h: int = 1920) -> str | None:
    """TikTok/Reels-style burned captions — NOT movie subtitles.

    Big bold uppercase, 2-3 words at a time, heavy black outline so it reads on any footage,
    parked in the lower third (well clear of the player chrome). Sizes are derived from the
    ACTUAL video height, so the text is never tiny on a 576p clip or huge on a 4K one.
    A spoken CTA ("click below", "get your quote"…) becomes an opaque blue BUTTON instead."""
    if not words:
        return None
    # scale everything off the real frame height (1920 is our reference design)
    k = max(0.35, play_h / 1920.0)
    fs      = int(96 * k)    # caption size — big, like a TikTok
    cta_fs  = int(76 * k)
    outline = max(2, int(8 * k))     # thick black stroke = readable on any background
    shadow  = max(1, int(3 * k))
    # Park captions NEAR THE BOTTOM (~11% of frame height), not at a "lower third" 22% up.
    # 430*k sat 22% up the frame — fine for a wide shot, but lip-sync/UGC output is a face-filling
    # CLOSE-UP, so 22% up landed on the chin/mouth and covered the character's face.
    marginv = max(40, int(play_h * 0.11))
    side    = int(90 * k)
    # How many CHARACTERS actually fit on one line? Text overflowed the frame because the font was
    # sized off the HEIGHT while the line runs off the WIDTH. Arial bold averages ~0.55em/char.
    usable = max(120, play_w - 2 * side)
    max_chars = max(8, int(usable / (0.55 * fs)))
    header = (
        # WrapStyle 0 = smart wrapping. It was 2 — "no wrapping at all" — so any line too wide for
        # the frame simply ran off the edges instead of breaking. That was the overflow.
        "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        # white text, fat black outline, bottom-centre — the TikTok look
        f"Style: Def,Arial,{fs},&H00FFFFFF,&H00000000,&H00000000,-1,0,1,{outline},{shadow},2,{side},{side},{marginv}\n"
        # BorderStyle=3 = opaque box → renders as a button; Outline value is the button padding.
        f"Style: Cta,Arial,{cta_fs},&H00FFFFFF,&H00E07A1F,&H00000000,-1,0,3,{max(10, int(16 * k))},0,2,{side},{side},{marginv}\n"
        # CtaGlow = outline-only ring (transparent fill) that expands + fades = a "tap here" ripple
        # around the button. BorderStyle=1 so only the bright border shows; animated in the events.
        f"Style: CtaGlow,Arial,{cta_fs},&HFF000000,&H0000D7FF,&H00000000,-1,0,1,{max(4, int(5 * k))},0,5,{side},{side},{marginv}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        % (play_w, play_h)
    )
    ctas = _cta_spans(words)
    cta_start = {s: e for s, e in ctas}
    inside = {i for s, e in ctas for i in range(s, e)}

    def _chunk(c, style):
        start = float(c[0]["start"]); end = float(c[-1]["end"])
        if end <= start:
            end = start + 0.5
        text = " ".join(str(w["word"]) for w in c).replace("\n", " ").strip().upper()
        text = re.sub(r"\s+", " ", text)
        return {"start": start, "end": end, "style": style, "text": text}

    chunks, i, buf = [], 0, []
    while i < len(words):
        if i in cta_start:                       # flush the pending text, then emit the button
            if buf:
                chunks.append(_chunk(buf, "Def")); buf = []
            e = cta_start[i]
            chunks.append(_chunk(words[i:e], "Cta"))
            i = e
            continue
        if i in inside:                          # already covered by a CTA span
            i += 1
            continue
        # break on WORD COUNT *or* on how wide the line would actually render — whichever comes
        # first. Word count alone let "PROTECTION WITHOUT BREAKING" run off a 1080-wide frame.
        nxt_len = len(" ".join(str(w["word"]) for w in buf + [words[i]]))
        if buf and (len(buf) >= per_line or nxt_len > max_chars):
            chunks.append(_chunk(buf, "Def")); buf = []
        buf.append(words[i]); i += 1
    if buf:
        chunks.append(_chunk(buf, "Def"))

    # TikTok captions are CONTINUOUS — each line holds until the next one starts, so there's no
    # flicker/gap between phrases. Also enforce a readable minimum on-screen time.
    lines = []
    for n, c in enumerate(chunks):
        nxt = chunks[n + 1]["start"] if n + 1 < len(chunks) else None
        end = c["end"]
        if nxt is not None:
            end = max(end, min(nxt, c["start"] + 2.5))   # hold to the next line (cap the hold)
            end = min(end, nxt)                          # never overlap the next line
        else:
            end = max(end, c["start"] + 0.9)
        if end - c["start"] < 0.35:                      # too quick to read → give it a beat
            end = c["start"] + 0.35
        if c["style"] == "Cta":                          # spoken CTA → animated highlighted button
            lines.extend(_cta_button_lines(c["text"], c["start"], end, play_w, play_h, marginv, k))
        else:
            lines.append(f"Dialogue: 0,{_fmt(c['start'])},{_fmt(end)},{c['style']},,0,0,0,,{c['text']}")
    with open(out_ass_path, "w") as f:
        f.write(header + "\n".join(lines) + "\n")
    return out_ass_path


_KINETIC_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "with", "is",
    "are", "was", "were", "be", "been", "am", "i", "you", "it", "this", "that", "my", "your",
    "no", "now", "so", "we", "he", "she", "they", "them", "me", "us", "our", "if", "then",
    "than", "as", "by", "from", "not", "do", "did", "get", "got", "can", "will", "just",
}


def _ekey(raw: str) -> str:
    """Normalize a token for emphasis matching: lowercase, letters+digits only ('$51' -> '51')."""
    return re.sub(r"[^a-z0-9]", "", (raw or "").lower())


def _has_number(raw: str) -> bool:
    return ("$" in (raw or "")) or any(c.isdigit() for c in (raw or ""))


def _auto_emphasis(words: list) -> set:
    """Pick words to BOX: every token with a digit/'$', plus the single longest non-stopword per
    short phrase (phrases split on sentence/clause punctuation)."""
    emp, phrase = set(), []

    def _flush(ph):
        best, best_len = None, 0
        for raw in ph:
            if _has_number(raw):
                emp.add(_ekey(raw)); continue
            k = _ekey(raw)
            if not k or k.isdigit() or k in _KINETIC_STOP or len(k) < 4:
                continue
            if len(k) > best_len:
                best, best_len = k, len(k)
        if best:
            emp.add(best)

    for w in words:
        raw = str(w.get("word") or "")
        phrase.append(raw)
        if re.search(r"[.!?,;:]", raw):
            _flush(phrase); phrase = []
    if phrase:
        _flush(phrase)
    return emp


def build_kinetic_ass(words: list, out_ass_path: str, play_w: int = 1080, play_h: int = 1920,
                      emphasis=None) -> str | None:
    """KINETIC captions for b-roll VO: bold white uppercase, 1-2 words on screen at a time, each
    timed to its own word (from `align`). EMPHASIS words (numbers/'$' and one keyword per phrase)
    render as white text on a RED opaque box (BorderStyle=3). Same 11%-from-bottom placement as
    build_ass, centered. Additive — never touches build_ass. Returns the .ass path, or None on any
    failure. `emphasis` is a set/list of lowercased words to box; None → auto-pick."""
    if not words:
        return None
    try:
        emp = ({_ekey(x) for x in emphasis} if emphasis is not None else _auto_emphasis(words))

        def _is_emph(raw: str) -> bool:
            return _has_number(raw) or (_ekey(raw) in emp)

        # scale everything off the real frame height (1920 is our reference design), like build_ass
        k = max(0.35, play_h / 1920.0)
        fs      = int(104 * k)                  # 1-2 words → a touch bigger than build_ass
        outline = max(2, int(9 * k))            # thick black stroke = readable on any footage
        shadow  = max(1, int(3 * k))
        marginv = max(40, int(play_h * 0.11))   # same lower band as build_ass
        side    = int(90 * k)
        pad     = max(8, int(14 * k))           # red-box padding (Outline value in BorderStyle 3)
        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
            # plain word: white text, fat black outline, bottom-centre
            f"Style: Kdef,Arial,{fs},&H00FFFFFF,&H00000000,&H00000000,-1,0,1,{outline},{shadow},2,{side},{side},{marginv}\n"
            # emphasis word: white text on a RED opaque box. BorderStyle=3 → the box FILL is the
            # OutlineColour (same convention build_ass's Cta button relies on); red in ASS BGR = &H000000FF.
            f"Style: Kbox,Arial,{fs},&H00FFFFFF,&H000000FF,&H000000FF,-1,0,3,{pad},0,2,{side},{side},{marginv}\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            % (play_w, play_h)
        )
        # chunk: an emphasis word stands ALONE (so the box wraps only it); plain words pair up (<=2)
        chunks, i = [], 0
        while i < len(words):
            raw = str(words[i].get("word") or "")
            if _is_emph(raw):
                chunks.append(([words[i]], "Kbox")); i += 1
            else:
                grp = [words[i]]; i += 1
                if i < len(words) and not _is_emph(str(words[i].get("word") or "")):
                    grp.append(words[i]); i += 1
                chunks.append((grp, "Kdef"))
        lines = []
        for n, (grp, style) in enumerate(chunks):
            start = float(grp[0].get("start") or 0)
            end = float(grp[-1].get("end") or 0)
            if end <= start:
                end = start + 0.4
            nxt = float(chunks[n + 1][0][0].get("start") or 0) if n + 1 < len(chunks) else None
            if nxt is not None:                       # continuous: hold to the next word (capped)
                end = max(end, min(nxt, start + 1.2))
                end = min(end, nxt)
            else:
                end = max(end, start + 0.5)
            if end - start < 0.18:                    # too quick to read → give it a beat
                end = start + 0.18
            text = re.sub(r"\s+", " ", " ".join(str(w.get("word") or "") for w in grp)).strip().upper()
            if not text:
                continue
            lines.append(f"Dialogue: 0,{_fmt(start)},{_fmt(end)},{style},,0,0,0,,{text}")
        with open(out_ass_path, "w") as f:
            f.write(header + "\n".join(lines) + "\n")
        return out_ass_path
    except Exception as e:
        logger.warning(f"build_kinetic_ass failed: {e}")
        return None


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
