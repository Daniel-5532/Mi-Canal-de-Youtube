---
name: shorts-editor
description: Editor de vídeos cortos. Convierte un vídeo largo (URL o archivo) en shorts/reels verticales 9:16 con subtítulos palabra por palabra. Úsala cuando el usuario pida crear, cortar, subtitular, reencuadrar o copiar el estilo de un short, reel o TikTok.
---

# Shorts editor

Herramientas (todas de código abierto salvo HeyGen):

| Paso | Herramienta | Uso |
|---|---|---|
| Descarga | yt-dlp | `yt_dlp` en Python; descarga hasta 1080p |
| Transcripción | faster-whisper (SYSTRAN) | tiempos por palabra; el modelo por defecto es `small` |
| Selección de momentos | OpenAI API | solo si existe `OPENAI_API_KEY`; si no, heurística local |
| Encuadre 9:16 | OpenCV | detección de cara (Haar), recorte centrado en ella |
| Corte y render | FFmpeg | libx264/aac, subtítulos ASS quemados |
| Portadas / títulos animados | Puppeteer | renderiza HTML a PNG/vídeo y se superpone con FFmpeg (no incluido aún) |
| Avatar / intro | HeyGen API | opcional, requiere clave del usuario (no incluido aún) |

## Flujo

1. Instala dependencias una vez: `pip install -r .claude/skills/shorts-editor/requirements.txt`. Necesita `ffmpeg` en el PATH.
2. Ejecuta:
   ```
   python3 .claude/skills/shorts-editor/scripts/shorts.py <URL|archivo> -n 3 --min 20 --max 59 --lang es -o output
   ```
3. Revisa `output/shortN.mp4` (1080x1920) y enséñale al usuario los tiempos y títulos elegidos.

## Notas

- `opencv-python-headless` debe ser <5: la versión 5 no trae `CascadeClassifier`.
- `youtube.com` puede estar bloqueado por la red del entorno. Si yt-dlp da 403 del proxy, pide al usuario que suba el archivo.
- El recorte es fijo por clip (mediana de la posición de la cara); con varias personas o cámara en movimiento queda peor.
- Para copiar el estilo de un reel de referencia: pide el archivo o capturas, analiza fotogramas (ritmo de cortes, fuente, color y posición de subtítulos, zooms, música) y ajusta `make_ass` (estilo ASS) y la cadena `-vf` en `render`.
- No añadas marcas de agua ni copies contenido ajeno: se replica el estilo, no el material.
