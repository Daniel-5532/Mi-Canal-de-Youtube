#!/usr/bin/env python3
"""Editor de shorts: URL/archivo -> clips verticales 1080x1920 con subtítulos.

Pipeline: yt-dlp (descarga) -> faster-whisper (transcripción por palabra)
-> selección de momentos (OpenAI si hay OPENAI_API_KEY, si no heurística)
-> OpenCV (encuadre 9:16 sobre la cara) -> FFmpeg (corte + subtítulos).
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

import cv2


def download(url, out):
    import yt_dlp
    opts = {"outtmpl": str(out / "source.%(ext)s"), "format": "bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4", "quiet": True}
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    return out / "source.mp4"


def transcribe(video, lang, model):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, compute_type="int8")
    segs, _ = m.transcribe(str(video), language=lang, word_timestamps=True, vad_filter=True)
    return [{"start": s.start, "end": s.end, "text": s.text.strip(),
             "words": [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in s.words]}
            for s in segs]


def pick_llm(segs, n, lo, hi):
    from openai import OpenAI
    text = "\n".join(f"[{i}] {s['start']:.1f}-{s['end']:.1f} {s['text']}" for i, s in enumerate(segs))
    r = OpenAI().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   f"Elige los {n} mejores momentos virales para shorts ({lo}-{hi}s cada uno, "
                   f"sin solaparse, empezando con un gancho y terminando en frase completa). "
                   f'Responde JSON {{"clips":[{{"start":seg,"end":seg,"title":"..."}}]}} usando '
                   f"los tiempos en segundos de la transcripción.\n\n{text}"}])
    return [(c["start"], c["end"], c.get("title", "")) for c in json.loads(r.choices[0].message.content)["clips"]]


def pick_heuristic(segs, n, lo, hi):
    """Ventanas de frases completas puntuadas por densidad de habla y énfasis."""
    cands = []
    for i, a in enumerate(segs):
        for j in range(i, len(segs)):
            d = segs[j]["end"] - a["start"]
            if d > hi:
                break
            if d >= lo:
                txt = " ".join(s["text"] for s in segs[i:j + 1])
                score = len(txt.split()) / d + 0.5 * txt.count("?") + 0.3 * txt.count("!")
                cands.append((score, a["start"], segs[j]["end"], txt[:50]))
    cands.sort(reverse=True)
    out = []
    for _, s, e, t in cands:
        if all(e <= o[0] or s >= o[1] for o in out):
            out.append((s, e, t))
        if len(out) == n:
            break
    return sorted(out)


def face_center(video, start, end):
    """Centro horizontal mediano de la cara más grande (0..1); 0.5 si no hay."""
    cap = cv2.VideoCapture(str(video))
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs = []
    for k in range(12):
        cap.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (k + .5) / 12) * 1000)
        ok, f = cap.read()
        if not ok:
            continue
        faces = det.detectMultiScale(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(60, 60))
        if len(faces):
            x, _, w, _ = max(faces, key=lambda b: b[2] * b[3])
            xs.append((x + w / 2) / f.shape[1])
    cap.release()
    return sorted(xs)[len(xs) // 2] if xs else 0.5


def ass_time(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def make_ass(segs, start, end, path):
    words = [w for s in segs for w in s["words"] if w["s"] >= start and w["e"] <= end]
    ev = []
    for i in range(0, len(words), 3):
        g = words[i:i + 3]
        for k, w in enumerate(g):
            line = " ".join(f"{{\\c&H00FFFF&}}{x['w']}{{\\c&HFFFFFF&}}" if x is w else x["w"] for x in g)
            nxt = g[k + 1]["s"] if k + 1 < len(g) else w["e"]
            ev.append(f"Dialogue: 0,{ass_time(w['s'] - start)},{ass_time(nxt - start)},C,,0,0,0,,{line.upper()}")
    path.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
                    "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BorderStyle,Outline,Shadow,Alignment,MarginV\n"
                    "Style: C,Arial,84,&H00FFFFFF,&H00000000,1,6,0,2,520\n\n"
                    "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n" + "\n".join(ev) + "\n")


def render(video, segs, start, end, idx, out):
    cx = face_center(video, start, end)
    ass = out / f"clip{idx}.ass"
    make_ass(segs, start, end, ass)
    # recorte 9:16 sobre la cara (x limitado a los bordes) y escala a 1080x1920
    crop = f"crop=ih*9/16:ih:max(0\\,min(iw-ih*9/16\\,iw*{cx:.3f}-ih*9/32)):0"
    vf = f"{crop},scale=1080:1920,subtitles={ass.name}"
    dst = out / f"short{idx}.mp4"
    # cwd=out para que subtitles= encuentre el .ass sin escapar rutas
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                    "-i", str(video.resolve()), "-vf", vf, "-c:v", "libx264", "-crf", "20",
                    "-preset", "medium", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                    dst.name], cwd=out, check=True)
    return dst


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", help="URL o ruta de vídeo")
    p.add_argument("-n", "--clips", type=int, default=3)
    p.add_argument("--min", type=int, default=20)
    p.add_argument("--max", type=int, default=59)
    p.add_argument("--lang", default="es")
    p.add_argument("--model", default="small")
    p.add_argument("-o", "--out", default="output")
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    video = download(a.source, out) if a.source.startswith("http") else Path(a.source)
    segs = transcribe(video, a.lang, a.model)
    if not segs:
        sys.exit("No se detectó habla en el vídeo.")
    picks = pick_llm(segs, a.clips, a.min, a.max) if os.getenv("OPENAI_API_KEY") else pick_heuristic(segs, a.clips, a.min, a.max)
    for i, (s, e, title) in enumerate(picks, 1):
        print(f"short{i}: {s:.1f}-{e:.1f}s  {title}")
        print("  ->", render(video, segs, s, e, i, out))


if __name__ == "__main__":
    main()
