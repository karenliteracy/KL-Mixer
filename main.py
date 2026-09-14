import os, re, shutil, subprocess, threading, uuid, sys
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

FROZEN = getattr(sys, "frozen", False)
RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BASE = Path(os.environ.get("MEDIA_AUDIO_STUDIO_DATA", Path(__file__).resolve().parent)) if FROZEN else Path(__file__).resolve().parent
INPUT = BASE / "input"
OUTPUT = BASE / "output"
TEMP = BASE / "temp"
SEPARATED = BASE / "separated"
STATIC = RESOURCE_BASE / "static"
for p in (INPUT, OUTPUT, TEMP, SEPARATED):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Media Audio Studio V3.1")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

JOBS = {}
LOCK = threading.Lock()

def require_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise HTTPException(500, "FFmpeg was not found in PATH.")

def safe_name(name):
    return Path(name or "media").name.replace(" ", "_")

def valid_youtube(url):
    return bool(re.match(r"^https?://(www\.)?(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)", url.strip(), re.I))

def allowed_source(path):
    p = Path(path).resolve()
    for base in (INPUT.resolve(), OUTPUT.resolve()):
        try:
            p.relative_to(base)
            return p
        except ValueError:
            pass
    raise HTTPException(400, "Invalid source file.")

def run_cmd(args, timeout=7200):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "The operation timed out.")

def run_ffmpeg(args, timeout=3600):
    require_ffmpeg()
    r = run_cmd([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args], timeout)
    if r.returncode:
        raise HTTPException(500, r.stderr[-5000:] or "FFmpeg failed.")
    return r

def set_job(jid, **kwargs):
    with LOCK:
        JOBS.setdefault(jid, {}).update(kwargs)

def detect_device():
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import torch; print('cuda' if torch.cuda.is_available() else 'cpu')"],
            capture_output=True, text=True, timeout=30
        )
        return "cuda" if r.returncode == 0 and r.stdout.strip() == "cuda" else "cpu"
    except Exception:
        return "cpu"

def separation_worker(jid, source, model, device):
    try:
        set_job(jid, status="running", progress=5, message=f"Starting AI separation on {device.upper()}...")
        outdir = SEPARATED / jid
        outdir.mkdir(parents=True, exist_ok=True)
        if FROZEN:
            runner = Path(sys.executable).with_name("demucs_runner.exe" if os.name == "nt" else "demucs_runner")
            cmd = [str(runner), "-n", model, "-d", device, "--out", str(outdir), str(source)]
        else:
            cmd = [sys.executable, "-m", "demucs", "-n", model, "-d", device, "--out", str(outdir), str(source)]
        r = run_cmd(cmd, timeout=6*60*60)
        if r.returncode != 0:
            set_job(jid, status="error", progress=0, message=(r.stderr or r.stdout)[-5000:] or "AI separation failed.")
            return
        stems = {}
        for name in ("vocals", "drums", "bass", "other"):
            matches = list(outdir.rglob(f"{name}.wav"))
            if matches:
                stems[name] = str(matches[0])
        if len(stems) != 4:
            set_job(jid, status="error", progress=0, message="AI finished but the four main stems were not found.")
            return
        set_job(jid, status="complete", progress=100, message="AI separation complete.", stems=stems)
    except Exception as e:
        set_job(jid, status="error", progress=0, message=str(e))

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse(STATIC / "index.html")

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No file selected.")
    jid = uuid.uuid4().hex
    p = INPUT / f"{jid}_{safe_name(file.filename)}"
    with p.open("wb") as f:
        while c := await file.read(1024*1024):
            f.write(c)
    return {"id": jid, "filename": p.name, "path": str(p), "size": p.stat().st_size}

@app.post("/api/youtube")
async def youtube(url: str = Form(...)):
    url = url.strip()
    if not is_valid_youtube_url(url):
        raise HTTPException(400, "Please enter a valid YouTube URL.")
    jid = uuid.uuid4().hex
    outdir = INPUT / jid
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
        opts = {
            "noplaylist": True,
            "restrictfilenames": True,
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": str(outdir / "%(title).100s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            requested = Path(ydl.prepare_filename(info))
        candidates = list(outdir.glob("*"))
        if requested.exists():
            path = requested
        else:
            candidates = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)
            if not candidates:
                raise HTTPException(500, "Download completed but the local file could not be found.")
            path = candidates[0]
        return {"id": jid, "filename": path.name, "path": str(path), "size": path.stat().st_size}
    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(outdir, ignore_errors=True)
        raise HTTPException(500, str(e)[-5000:] or "YouTube download failed.")

@app.get("/api/preview")
def preview(path: str):
    p = allowed_source(path)
    if not p.exists():
        raise HTTPException(404, "Preview file not found.")
    return FileResponse(p)

@app.post("/api/extract")
async def extract(
    source_path: str = Form(...),
    output_format: str = Form("wav"),
    bitrate: str = Form("320k"),
    start: float = Form(0),
    end: float = Form(0),
    normalize: bool = Form(False)
):
    source = allowed_source(source_path)
    if not source.exists():
        raise HTTPException(404, "Source file not found.")
    if output_format not in {"mp3","wav","flac","m4a"}:
        raise HTTPException(400, "Unsupported output format.")
    if start < 0 or end < 0 or (end and end <= start):
        raise HTTPException(400, "Invalid start/end values.")
    out = OUTPUT / f"{source.stem}_extracted_{uuid.uuid4().hex[:8]}.{output_format}"
    args = []
    if start > 0:
        args += ["-ss", str(start)]
    args += ["-i", str(source)]
    if end > 0:
        args += ["-t", str(end - start)]
    filters = []
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-vn"]
    if output_format == "mp3":
        args += ["-c:a","libmp3lame","-b:a",bitrate]
    elif output_format == "wav":
        args += ["-c:a","pcm_s16le"]
    elif output_format == "flac":
        args += ["-c:a","flac"]
    else:
        args += ["-c:a","aac","-b:a",bitrate]
    args += [str(out)]
    run_ffmpeg(args)
    return {"filename": out.name, "path": str(out), "url": f"/api/download/{out.name}"}

@app.post("/api/separate")
async def separate(source_path: str = Form(...), model: str = Form("htdemucs"), device: str = Form("auto")):
    source = allowed_source(source_path)
    if not source.exists():
        raise HTTPException(404, "Source file not found.")
    if model not in {"htdemucs","htdemucs_ft","htdemucs_6s"}:
        raise HTTPException(400, "Unsupported Demucs model.")
    if device not in {"auto","cpu","cuda"}:
        raise HTTPException(400, "Invalid device.")
    if device == "auto":
        device = detect_device()
    if device == "cuda":
        try:
            import torch
            if not torch.cuda.is_available():
                device = "cpu"
        except Exception:
            device = "cpu"
    jid = uuid.uuid4().hex
    set_job(jid, status="queued", progress=0, message="Queued for AI separation.", source=str(source))
    threading.Thread(target=separation_worker, args=(jid, source, model, device), daemon=True).start()
    return {"job_id": jid, "device": device, "model": model}

@app.get("/api/job/{job_id}")
def job(job_id: str):
    with LOCK:
        data = dict(JOBS.get(job_id, {}))
    if not data:
        raise HTTPException(404, "Job not found.")
    return data

@app.get("/api/stem/{job_id}/{stem}")
def stem(job_id: str, stem: str):
    if stem not in {"vocals","drums","bass","other"}:
        raise HTTPException(400, "Invalid stem.")
    with LOCK:
        p = Path(JOBS.get(job_id, {}).get("stems", {}).get(stem, ""))
    if not p.exists():
        raise HTTPException(404, "Stem not found.")
    return FileResponse(p, filename=f"{stem}.wav", media_type="audio/wav")

def pitch_filter(semitones):
    n = float(semitones)
    if abs(n) < 0.001:
        return None
    ratio = 2 ** (n / 12.0)
    # Change sample rate to shift pitch, then resample and compensate tempo.
    # atempo supports 0.5..2.0, so one step is sufficient for +/-12 semitones.
    return f"asetrate=44100*{ratio:.10f},aresample=44100,atempo={1/ratio:.10f}"

@app.post("/api/export")
async def export_audio(
    job_id: str = Form(...),
    mode: str = Form("karaoke"),
    vocals: float = Form(0),
    drums: float = Form(100),
    bass: float = Form(100),
    other: float = Form(100),
    pitch: float = Form(0),
    output_format: str = Form("mp3"),
    bitrate: str = Form("320k"),
    normalize: bool = Form(False),
    start: float = Form(0),
    end: float = Form(0)
):
    with LOCK:
        j = dict(JOBS.get(job_id, {}))
    if j.get("status") != "complete":
        raise HTTPException(400, "AI separation is not complete.")
    stems = j.get("stems", {})
    if any(s not in stems for s in ("vocals","drums","bass","other")):
        raise HTTPException(400, "Required stems are missing.")
    if not -12 <= pitch <= 12:
        raise HTTPException(400, "Pitch must be between -12 and +12.")
    levels = [vocals,drums,bass,other]
    if any(v < 0 or v > 100 for v in levels):
        raise HTTPException(400, "Stem volumes must be 0-100.")
    if start < 0 or end < 0 or (end and end <= start):
        raise HTTPException(400, "Invalid trim range.")
    if output_format not in {"mp3","wav","flac","m4a"}:
        raise HTTPException(400, "Unsupported output format.")

    out = OUTPUT / f"{job_id}_{mode}_{uuid.uuid4().hex[:8]}.{output_format}"
    args = []
    if start > 0:
        args += ["-ss", str(start)]
    for s in ("vocals","drums","bass","other"):
        args += ["-i", stems[s]]
    if end > 0:
        args += ["-t", str(end-start)]

    filters = [
        f"[0:a]volume={vocals/100:.4f}[v]",
        f"[1:a]volume={drums/100:.4f}[d]",
        f"[2:a]volume={bass/100:.4f}[b]",
        f"[3:a]volume={other/100:.4f}[o]",
        "[v][d][b][o]amix=inputs=4:duration=longest:normalize=0[mix]"
    ]
    label = "[mix]"
    pf = pitch_filter(pitch)
    if pf:
        filters.append(f"{label}{pf}[pit]")
        label = "[pit]"
    if normalize:
        filters.append(f"{label}loudnorm=I=-16:TP=-1.5:LRA=11[norm]")
        label = "[norm]"

    args += ["-filter_complex", ";".join(filters), "-map", label]
    if output_format == "mp3":
        args += ["-c:a","libmp3lame","-b:a",bitrate]
    elif output_format == "wav":
        args += ["-c:a","pcm_s16le"]
    elif output_format == "flac":
        args += ["-c:a","flac"]
    else:
        args += ["-c:a","aac","-b:a",bitrate]
    args += [str(out)]
    run_ffmpeg(args)
    return {"filename":out.name,"path":str(out),"url":f"/api/download/{out.name}"}

@app.get("/api/download/{filename}")
def download(filename: str):
    p = OUTPUT / Path(filename).name
    if not p.exists():
        raise HTTPException(404, "File not found.")
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
