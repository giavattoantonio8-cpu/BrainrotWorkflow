"""
generate_video.py — Current public prototype: MoviePy 2.x + Pillow subtitles
Font Arial Black 85px | centrato H+V | bordo 8px | 2-3 parole per gruppo
Narrazione singola: am_michael
"""

import json
import random
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    ImageClip, VideoFileClip, AudioFileClip,
    CompositeVideoClip,
)

BASE = Path(__file__).parent


def load_config() -> dict:
    config_path = BASE / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            "Missing config.json. Copy config.example.json to config.json and "
            "set the local model paths before running this script."
        )
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


CFG = load_config()


def project_path(value: str) -> Path:
    """Resolve a project-relative configuration path."""
    path = Path(value)
    return path if path.is_absolute() else BASE / path


MODEL_PATH = project_path(CFG["tts"]["model_path"])
VOICES_PATH = project_path(CFG["tts"]["voices_path"])
SAMPLE_RATE = 24000
VIDEO_W, VIDEO_H = map(int, CFG["video"]["resolution"].split("x"))
FONT_SIZE = CFG["video"]["font_size"]
BORDER_W = CFG["video"]["border_width"]
MIN_WORDS = CFG["subtitles"]["min_words"]
MAX_WORDS = CFG["subtitles"]["max_words"]
CHUNK_SIZE = 3

EMOTION_SPEED = {
    "shock":    1.30,
    "dramatic": 1.08,
    "amused":   1.40,
    "normal":   1.20,
}
PRE_SILENCE = {
    "shock":    0.28,
    "dramatic": 0.22,
    "amused":   0.12,
    "normal":   0.15,
}

SHOCK_WORDS    = {"cheated","affair","pregnant","died","arrested","lied","betrayed",
                  "secret","fired","dead","exposed","confessed","revealed","discovered"}
DRAMATIC_WORDS = {"hospital","cancer","divorce","funeral","destroyed","serious","cry",
                  "cried","broke","broken","lost","losing","silence","stared","tears","sobbed"}
AMUSED_WORDS   = {"ridiculous","literally","crazy","insane","unbelievable","wild",
                  "hilarious","absurd","weird","bizarre","audacity","seriously"}

PART1_TEASER = (
    "That is Part One. Follow for Part Two - "
    "you are not going to believe how this ends.",
    "dramatic",
)


# ── Font ──────────────────────────────────────────────────────────────────────

_FONT = None

def get_font():
    global _FONT
    if _FONT is None:
        configured_font = CFG["video"].get("font_path", "")
        font_paths = [project_path(configured_font)] if configured_font else []
        for path in font_paths:
            try:
                _FONT = ImageFont.truetype(path, FONT_SIZE)
                print(f"  Font: {Path(path).name} @ {FONT_SIZE}px")
                break
            except OSError:
                continue
        if _FONT is None:
            _FONT = ImageFont.load_default()
            print("  Font: default (fallback)")
    return _FONT


# ── Kokoro ────────────────────────────────────────────────────────────────────

_kokoro = None

def get_kokoro():
    global _kokoro
    if _kokoro is None:
        print("  [Kokoro] Caricamento modello...", flush=True)
        _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        print("  [Kokoro] Pronto.", flush=True)
    return _kokoro


# ── Text ──────────────────────────────────────────────────────────────────────

def detect_emotion(text):
    words = set(re.findall(r'\b\w+\b', text.lower()))
    if words & SHOCK_WORDS:    return "shock"
    if words & DRAMATIC_WORDS: return "dramatic"
    if words & AMUSED_WORDS:   return "amused"
    return "normal"


def clean_text(text):
    for sub in CFG.get("text_cleanup", {}).get("sostituzioni", []):
        pattern = r'\b' + re.escape(sub["da"]) + r'\b'
        text = re.sub(pattern, sub["a"], text, flags=re.IGNORECASE)
    return text


def split_sentences(text):
    # Non spezza sui '...' — solo su '.' singolo, '!' o '?'
    parts = re.split(r'(?<=[!?])\s+|(?<!\.)\.(?!\.)\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


CLUE_EXTRA = {
    "but","however","then","suddenly","except","until","problem",
    "realised","realized","found","called","told","said","proposed",
    "confessed","never","always","everything","nothing","just","only",
}

def find_clue_moment(sentences):
    n = len(sentences)
    if n < 4:
        return n // 2
    min_idx    = max(2, int(n * 0.40))
    max_idx    = min(n - 2, int(n * 0.70))
    best_idx   = min_idx + (max_idx - min_idx) // 2
    best_score = -1
    for i in range(min_idx, max_idx + 1):
        words  = set(re.findall(r'\b\w+\b', sentences[i].lower()))
        score  = len(words & SHOCK_WORDS)    * 3
        score += len(words & DRAMATIC_WORDS) * 2
        score += len(words & CLUE_EXTRA)     * 1
        if sentences[i].strip()[-1:] in ('?', '!'):
            score += 2
        if len(sentences[i].split()) < 10:
            score += 1
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx


def split_story(sentences):
    idx = find_clue_moment(sentences)
    return sentences[:idx + 1], sentences[idx + 1:]


def build_narration(sentences):
    lines, i = [], 0
    while i < len(sentences):
        chunk   = sentences[i : i + CHUNK_SIZE]
        txt     = " ".join(chunk)
        emotion = detect_emotion(txt)
        lines.append({"text": txt, "emotion": emotion})
        i += CHUNK_SIZE
    return lines


# ── Audio ─────────────────────────────────────────────────────────────────────

def estimate_word_timings(words, total_duration):
    GAP         = 0.04
    total_chars = sum(len(w) for w in words)
    speech_dur  = max(0, total_duration - GAP * (len(words) - 1))
    timings, t  = [], 0.0
    for i, w in enumerate(words):
        dur = (len(w) / max(total_chars, 1)) * speech_dur
        timings.append({"word": w, "start": t, "end": t + dur})
        t += dur + (GAP if i < len(words) - 1 else 0)
    return timings


def genera_linea(text, emotion, wav_path):
    speed       = EMOTION_SPEED[emotion]
    samples, sr = get_kokoro().create(
        text, voice=CFG["tts"]["voice"], speed=speed, lang=CFG["tts"]["language"]
    )
    sf.write(str(wav_path), samples, sr, subtype="PCM_16")
    duration    = len(samples) / sr
    return estimate_word_timings(text.split(), duration), duration


def genera_silenzio(path, duration):
    silence = np.zeros(int(duration * SAMPLE_RATE), dtype=np.int16)
    sf.write(str(path), silence, SAMPLE_RATE, subtype="PCM_16")


def concat_wavs(wav_list, out_path):
    filelist = out_path.parent / "_concat.txt"
    with open(filelist, "w", encoding="utf-8") as f:
        for p in wav_list:
            f.write(f"file '{p.resolve()}'\n")
    result = subprocess.run(
        ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(filelist),
         "-c:a", "pcm_s16le", "-y", str(out_path)],
        capture_output=True, text=True,
    )
    filelist.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError("Merge WAV:\n" + result.stderr[-600:])


def get_audio_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


# ── Subtitle grouping ─────────────────────────────────────────────────────────

def group_words(timings, offset):
    segments, group = [], []
    for i, t in enumerate(timings):
        group.append(t)
        last_char     = t["word"][-1:] if t["word"] else ""
        is_last       = i == len(timings) - 1
        natural_break = last_char in ('.', '!', '?', ',', ';', ':') and len(group) >= MIN_WORDS
        at_max        = len(group) >= MAX_WORDS

        if at_max or natural_break or is_last:
            segments.append({
                "text":  " ".join(x["word"] for x in group).upper(),
                "start": group[0]["start"] + offset,
                "end":   group[-1]["end"]   + offset,
            })
            group = []
    return segments


# ── MoviePy + Pillow subtitle clip ────────────────────────────────────────────

def make_sub_clip(text, start, end):
    font = get_font()
    img  = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    x    = (VIDEO_W - tw) // 2 - bbox[0]
    y    = (VIDEO_H - th) // 2 - bbox[1]

    draw.text(
        (x, y), text, font=font,
        fill=(255, 255, 255, 255),
        stroke_width=BORDER_W,
        stroke_fill=(0, 0, 0, 255),
    )

    arr = np.array(img)  # RGBA — transparent=True (default) gestisce l'alpha
    return (
        ImageClip(arr, transparent=True)
        .with_start(start)
        .with_duration(max(0.05, end - start))
    )


# ── Genera audio ──────────────────────────────────────────────────────────────

def genera_parte(lines, work_dir, part_name):
    clips_dir = work_dir / part_name
    clips_dir.mkdir(parents=True, exist_ok=True)
    audio_files = []
    all_subs    = []
    cumulative  = 0.0

    for i, line in enumerate(lines):
        if i > 0:
            gap      = PRE_SILENCE.get(line["emotion"], 0.32)
            gap_path = clips_dir / f"{i:02d}_silence.wav"
            genera_silenzio(gap_path, gap)
            audio_files.append(gap_path)
            cumulative += gap

        wav      = clips_dir / f"{i:02d}_guy_{line['emotion']}.wav"
        timings, dur = genera_linea(line["text"], line["emotion"], wav)
        segs     = group_words(timings, cumulative)
        all_subs.extend(segs)
        audio_files.append(wav)
        cumulative += dur
        print(f"    [{part_name}] {line['text'][:55]} ({dur:.1f}s, {len(segs)} sub)")

    merged = work_dir / f"{part_name}_merged.wav"
    concat_wavs(audio_files, merged)
    print(f"    [{part_name}] totale: {cumulative:.1f}s | {len(all_subs)} subtitle groups")
    return merged, all_subs, cumulative


# ── Composizione video ────────────────────────────────────────────────────────

def prepare_gameplay(gp_path, duration, tmp_path):
    """ffmpeg: scale-to-fill + crop centrato → 1080x1920 garantito senza distorsioni."""
    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-t", str(duration + 2),
        "-i", str(gp_path),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "15",
        "-an", str(tmp_path),
    ], capture_output=True, check=True)


def componi_video(label, merged_wav, subs, out_path):
    clips = list(project_path(CFG["paths"]["gameplay"]).glob("*.mp4"))
    if not clips:
        raise FileNotFoundError(
            "No .mp4 gameplay clips found. Add a licensed clip to the configured gameplay directory."
        )
    gp_path  = random.choice(clips)
    duration = get_audio_duration(merged_wav)

    print(f"\n  [{label}] Compositing {duration:.1f}s | {gp_path.name} | {len(subs)} subtitles")

    # Pre-croppa con ffmpeg (affidabile, niente stretching da MoviePy)
    gp_tmp = out_path.parent / "_gp_tmp.mp4"
    prepare_gameplay(gp_path, duration, gp_tmp)
    gameplay = VideoFileClip(str(gp_tmp), audio=False).subclipped(0, duration)

    print(f"    Rendering {len(subs)} subtitle clips (MoviePy + Pillow)...")
    sub_clips = [make_sub_clip(s["text"], s["start"], s["end"]) for s in subs]

    audio = AudioFileClip(str(merged_wav))
    final = (
        CompositeVideoClip([gameplay] + sub_clips, size=(VIDEO_W, VIDEO_H))
        .with_audio(audio)
        .with_duration(duration)
    )
    final.write_videofile(
        str(out_path), fps=CFG["video"]["fps"],
        codec="libx264", audio_codec="aac", audio_bitrate="192k",
        logger=None,
    )
    gameplay.close()
    final.close()
    mb = out_path.stat().st_size / 1024 / 1024
    print(f"  [{label}] -> {out_path.name} ({mb:.1f} MB)")
    gp_tmp.unlink(missing_ok=True)


# ── Pipeline ──────────────────────────────────────────────────────────────────

def processa_storia(story_path):
    story_path = project_path(story_path)
    with story_path.open(encoding="utf-8") as handle:
        storia = json.load(handle)
    titolo = storia["titolo"]
    testo  = clean_text(storia["testo_ottimizzato"])

    print(f"\n[TEST] {titolo}")
    print(f"  Testo: {testo}")

    sentences              = split_sentences(testo)
    part1_sent, part2_sent = split_story(sentences)
    print(f"  Frasi: {len(sentences)} | Part1: {len(part1_sent)} | Part2: {len(part2_sent)}")

    lines_p1 = build_narration(part1_sent)
    lines_p1.append({"text": PART1_TEASER[0], "emotion": PART1_TEASER[1]})
    lines_p2 = build_narration(part2_sent)

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    wdir = project_path(CFG["paths"]["tts_work"]) / f"{titolo}_{ts}"
    out_dir = project_path(CFG["paths"]["video_output"]) / f"{titolo}_{ts}"
    wdir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    get_kokoro()

    print("\n  --- Part 1 ---")
    wav1, subs1, _ = genera_parte(lines_p1, wdir, "part1")
    componi_video("Part 1", wav1, subs1, out_dir / "part1.mp4")

    if lines_p2:
        print("\n  --- Part 2 ---")
        wav2, subs2, _ = genera_parte(lines_p2, wdir, "part2")
        componi_video("Part 2", wav2, subs2, out_dir / "part2.mp4")

    print(f"\n  Output: {out_dir}")


def main():
    paths = sys.argv[1:] if len(sys.argv) > 1 else ["data/sample_story.json"]
    for p in paths:
        processa_storia(p)
    print("\nCompletato.")


if __name__ == "__main__":
    main()
