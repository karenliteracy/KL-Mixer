import os
import shutil
from PyInstaller.__main__ import run

sep = os.pathsep
common = [
    "--noconfirm", "--clean", "--onefile",
    "--collect-all=demucs",
    "--collect-all=torchaudio",
    "--collect-all=torch",
    "--collect-all=yt_dlp",
    "--collect-all=imageio_ffmpeg",
    "--hidden-import=uvicorn.logging",
    "--hidden-import=uvicorn.loops.auto",
    "--hidden-import=uvicorn.protocols.http.auto",
    "--hidden-import=uvicorn.protocols.websockets.auto",
    "--hidden-import=uvicorn.lifespan.on",
]

run(["main.py", "--name=media_audio_backend", *common])
run(["backend/demucs_runner.py", "--name=demucs_runner", *common])

os.makedirs("backend/dist", exist_ok=True)
for name in ("media_audio_backend", "demucs_runner"):
    src = os.path.join("dist", name + (".exe" if os.name == "nt" else ""))
    dst = os.path.join("backend", "dist", name + (".exe" if os.name == "nt" else ""))
    shutil.copy2(src, dst)
