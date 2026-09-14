const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let backend = null;
const port = 8765;

function waitForServer(url, tries = 160) {
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(url, res => { res.resume(); resolve(); });
      req.on('error', () => {
        if (--tries <= 0) reject(new Error('Local audio engine did not start.'));
        else setTimeout(check, 250);
      });
    };
    check();
  });
}

function startBackend() {
  if (app.isPackaged) {
    const backendDir = path.join(process.resourcesPath, 'backend');
    const exe = path.join(backendDir, process.platform === 'win32' ? 'media_audio_backend.exe' : 'media_audio_backend');
    backend = spawn(exe, ['--host','127.0.0.1','--port',String(port)], {
      windowsHide: true,
      env: { ...process.env, MEDIA_AUDIO_STUDIO_DATA: app.getPath('userData') }
    });
  } else {
    const exe = process.platform === 'win32' ? 'python' : 'python3';
    backend = spawn(exe, [path.join(__dirname, '..', 'main.py'), '--host','127.0.0.1','--port',String(port)], {
      windowsHide: true,
      env: { ...process.env, MEDIA_AUDIO_STUDIO_DATA: path.join(app.getPath('userData'), 'data') }
    });
  }
  backend.on('error', err => dialog.showErrorBox('Media Audio Studio', err.message));
}

async function createWindow() {
  startBackend();
  try { await waitForServer(`http://127.0.0.1:${port}/`); }
  catch (e) { dialog.showErrorBox('Media Audio Studio', e.message); app.quit(); return; }

  const win = new BrowserWindow({
    width: 1280,
    height: 850,
    minWidth: 980,
    minHeight: 700,
    title: 'Media Audio Studio',
    icon: path.join(__dirname, '..', 'assets', 'logo.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false }
  });

  await win.loadURL(`http://127.0.0.1:${port}/`);
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (backend) backend.kill(); if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (backend) backend.kill(); });
