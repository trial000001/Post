#!/usr/bin/env python3
"""Génère une vidéo verticale (~70 s) :
script (Claude) -> voix (edge-tts, gratuit) -> visuels (Pexels, gratuit) -> montage + sous-titres (ffmpeg).

Sortie : output/video.mp4 + output/meta.json
Test sans réseau : python generate.py --offline
"""
import argparse
import asyncio
import datetime
import json
import os
import pathlib
import random
import re
import shutil
import subprocess

import requests

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "output"
TMP = OUT / "tmp"
HISTORY = ROOT / "history.json"

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")
W, H, FPS = 1080, 1920, 30

CATEGORIES = [
    "ancient history",
    "modern history",
    "psychology",
    "human behavior and social psychology",
    "science discoveries",
    "space and astronomy",
    "philosophy",
    "economics and money",
    "unsolved mysteries",
    "how everyday things work",
    "the human brain",
    "famous historical figures",
]

PROMPT = """You write scripts for a daily educational short-form vertical video (YouTube Shorts / TikTok / Reels).
Category: {category}
Already covered, do NOT repeat these topics: {past}

Pick one fascinating, TRUE, specific topic in this category. Write a narration of 170-190 words (about 70 seconds spoken):
- the first sentence is a strong hook (a surprising fact or a question), no greeting, no "welcome"
- explain clearly in simple spoken English, short sentences, concrete facts; never invent statistics or quotes
- end with a memorable closing line or a question that invites comments
- plain text only: no stage directions, no emojis, no hashtags, no markdown

Also give 9 visual search keywords (1-3 English words each, concrete and easy to film, e.g. "old library", "crowd walking", "night city"), in the order the story unfolds.

Reply with ONLY a JSON object:
{{"topic": "...", "title": "<max 70 chars, curiosity-driven>", "description": "<1-2 sentences>", "hashtags": ["#...", "#...", "#...", "#...", "#..."], "script": "...", "keywords": ["...", "..."]}}"""

FALLBACK_COLORS = ["0x1b1b2f", "0x162447", "0x1f4068", "0x2c3e50", "0x252a34", "0x2d132c"]


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Commande échouée: {' '.join(map(str, cmd))}\n{p.stderr[-2000:]}")
    return p.stdout


def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return []


def pick_category(history):
    recent = [h.get("category") for h in history[-len(CATEGORIES):]]
    counts = {c: recent.count(c) for c in CATEGORIES}
    low = min(counts.values())
    return random.choice([c for c, n in counts.items() if n == low])


def llm_script(category, history):
    key = os.environ["ANTHROPIC_API_KEY"]
    past = "; ".join(h["topic"] for h in history[-60:] if h.get("topic")) or "none yet"
    last_err = None
    for _ in range(3):
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 2500,
                "messages": [{"role": "user", "content": PROMPT.format(category=category, past=past)}],
            },
            timeout=120,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"])
        try:
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0))
            n = len(data["script"].split())
            if not 120 <= n <= 260:
                raise ValueError(f"script de {n} mots")
            if len(data["keywords"]) < 3:
                raise ValueError("pas assez de mots-clés")
            return data
        except Exception as e:  # on réessaie
            last_err = e
    raise RuntimeError(f"Script invalide après 3 essais: {last_err}")


def probe_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


async def _tts(text, path):
    import edge_tts

    try:
        com = edge_tts.Communicate(text, VOICE, rate="+5%", boundary="WordBoundary")
    except TypeError:  # anciennes versions : WordBoundary par défaut
        com = edge_tts.Communicate(text, VOICE, rate="+5%")
    words = []
    with open(path, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append((start, start + ch["duration"] / 1e7, ch["text"]))
    return words


def even_words(text, duration):
    toks = text.split()
    step = duration / max(len(toks), 1)
    return [(i * step, (i + 1) * step, t) for i, t in enumerate(toks)]


def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(words, path, total):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,86,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,80,80,640,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.!?]$", w[2]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    lines = []
    for i, ch in enumerate(chunks):
        start = ch[0][0]
        end = chunks[i + 1][0][0] if i + 1 < len(chunks) else min(ch[-1][1] + 0.3, total)
        text = " ".join(w[2] for w in ch).upper().replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")
    pathlib.Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def pexels_clip(keyword, used, idx):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": keyword, "orientation": "portrait", "size": "medium", "per_page": 12},
            timeout=30,
        )
        r.raise_for_status()
        vids = [v for v in r.json().get("videos", []) if v["id"] not in used and v.get("duration", 0) >= 4]
        random.shuffle(vids)
        for v in vids:
            files = [
                f for f in v["video_files"]
                if f.get("file_type") == "video/mp4" and f.get("width") and f["height"] >= f["width"]
            ]
            if not files:
                continue
            f = min(files, key=lambda f: abs(f["width"] - 1080))
            dest = TMP / f"raw_{idx}.mp4"
            with requests.get(f["link"], stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for part in resp.iter_content(1 << 20):
                        fh.write(part)
            used.add(v["id"])
            return dest
    except Exception as e:
        print(f"[pexels] '{keyword}': {e}")
    return None


ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def make_segment(src, dur, idx):
    out = TMP / f"seg_{idx}.mp4"
    if src:
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"fps={FPS},setsar=1,eq=brightness=-0.10"
        )
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.3f}", "-vf", vf, "-an", *ENC, str(out)])
    else:
        color = FALLBACK_COLORS[idx % len(FALLBACK_COLORS)]
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r={FPS}", "-t", f"{dur:.3f}", "-an", *ENC, str(out)])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="test sans réseau (voix = bip, fonds unis)")
    args = ap.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    TMP.mkdir(parents=True)
    history = load_history()
    category = pick_category(history)

    if args.offline:
        data = {
            "topic": "offline test",
            "title": "Offline test video",
            "description": "Local test.",
            "hashtags": ["#test"],
            "script": " ".join(["This is a short offline test sentence for the subtitles."] * 3),
            "keywords": ["a", "b", "c"],
        }
        audio = TMP / "voice.mp3"
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=9", "-c:a", "libmp3lame", str(audio)])
        dur = probe_duration(audio)
        words = even_words(data["script"], dur)
    else:
        data = llm_script(category, history)
        print(f"[script] {data['title']} ({len(data['script'].split())} mots)")
        audio = TMP / "voice.mp3"
        words = asyncio.run(_tts(data["script"], audio))
        dur = probe_duration(audio)
        if len(words) < len(data["script"].split()) * 0.5:  # pas de WordBoundary exploitable
            words = even_words(data["script"], dur)

    total = dur + 0.6
    build_ass(words, TMP / "subs.ass", total)

    kws = data["keywords"]
    seg_dur = total / len(kws)
    used, segs = set(), []
    for i, kw in enumerate(kws):
        src = None if args.offline else pexels_clip(kw, used, i)
        segs.append(make_segment(src, seg_dur, i))
    (TMP / "list.txt").write_text("".join(f"file '{s.name}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "visual.mp4"], cwd=TMP)

    final = OUT / "video.mp4"
    run(
        [
            "ffmpeg", "-y", "-i", "visual.mp4", "-i", "voice.mp3",
            "-vf", "ass=subs.ass",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart",
            str(final),
        ],
        cwd=TMP,
    )

    tags = data.get("hashtags", [])
    if "#shorts" not in [t.lower() for t in tags]:
        tags.append("#shorts")
    today = datetime.date.today().isoformat()
    meta = {
        "date": today,
        "topic": data["topic"],
        "title": data["title"][:100],
        "description": data["description"],
        "hashtags": tags,
        "caption": f"{data['description']}\n\n{' '.join(tags)}",
        "script": data["script"],
        "duration": round(total, 1),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    shutil.rmtree(TMP, ignore_errors=True)

    if not args.offline:
        history.append({"date": today, "topic": data["topic"], "title": data["title"], "category": category})
        HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1))
    print(f"[ok] {final} ({total:.0f}s)")


if __name__ == "__main__":
    main()
