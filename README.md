# Media Audio Studio

Local desktop application for video/audio extraction, YouTube importing, AI stem separation, karaoke mixing, pitch/key adjustment, trimming, and normalization.

## What is included
- Electron desktop shell
- FastAPI local audio engine
- FFmpeg bundled through `imageio-ffmpeg`
- YouTube downloading through `yt-dlp`
- Demucs AI separation with Vocals / Drums / Bass / Other controls
- Key/pitch control from -12 to +12 semitones
- Windows NSIS installer and portable EXE builds
- macOS DMG and ZIP builds
- Application logo in `assets/`

## GitHub build
1. Create a GitHub repository.
2. Upload all files/folders from this project.
3. Go to **Actions**.
4. Select **Build Media Audio Studio**.
5. Click **Run workflow**.
6. Download the Windows artifacts after the build finishes.

A tag such as `v1.0.1` also triggers the build automatically.

## Local development
Requirements: Python 3.11 recommended for the AI build, Node.js 22, and npm.

```powershell
python -m pip install -r requirements.txt
npm install
npm start
```

For browser-only backend development:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## Important
The packaged desktop app keeps its working files in the user's application data directory rather than inside `Program Files`, so installed applications can write downloaded media and generated audio safely.
