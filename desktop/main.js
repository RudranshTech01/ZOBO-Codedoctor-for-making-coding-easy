const { app, BrowserWindow, globalShortcut, ipcMain, dialog, desktopCapturer, Menu, screen } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const BACKEND_PORT = 8765;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
let win, server;

function projectRoot() { return path.resolve(__dirname, '..'); }
function backendDirectory() {
  return app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.join(projectRoot(), 'backend');
}
function frontendDirectory() {
  return app.isPackaged ? path.join(process.resourcesPath, 'frontend') : path.join(projectRoot(), 'frontend');
}
function pythonExecutable() {
  const env = process.env.CODEDOCTOR_PYTHON;
  if (env) return env;
  const root = projectRoot();
  const winPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  const unixPython = path.join(root, '.venv', 'bin', 'python');
  if (fs.existsSync(winPython)) return winPython;
  if (fs.existsSync(unixPython)) return unixPython;
  return process.platform === 'win32' ? 'py' : 'python3';
}
function startBackend() {
  const py = pythonExecutable();
  const args = [...(py === 'py' ? ['-3'] : []), '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)];
  const cwd = app.isPackaged ? process.resourcesPath : projectRoot();
  server = spawn(py, args, { cwd, env: { ...process.env, PYTHONUNBUFFERED: '1' }, windowsHide: true });
  server.on('error', err => dialog.showErrorBox('Backend failed to start', `Install Python and backend requirements. ${err.message}`));
  server.stderr?.on('data', data => console.error('[backend]', data.toString()));
}
function ready() {
  return new Promise((resolve, reject) => {
    let tries = 0;
    const poll = () => {
      http.get(`${BACKEND_URL}/health`, r => { r.resume(); resolve(); }).on('error', () => {
        if (++tries > 45) reject(new Error('Backend did not start. Install requirements and check terminal logs.'));
        else setTimeout(poll, 400);
      });
    };
    poll();
  });
}
function createWindow() {
  const display = screen.getPrimaryDisplay();
  const area = display.workArea;
  const width = Math.min(560, Math.max(480, area.width - 40));
  win = new BrowserWindow({
    x: area.x + area.width - width,
    y: area.y,
    width,
    height: area.height,
    minWidth: 460,
    minHeight: 520,
    title: 'CodeDoctor AI V2', webPreferences: {
      preload: path.join(__dirname, 'preload.js'), contextIsolation: true,
      nodeIntegration: false, sandbox: true
    } });
  win.loadURL(BACKEND_URL);
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('did-finish-load', async () => {
    // Local OCR package is loaded from a trusted file path by injecting the bundled script.
    const script = path.join(__dirname, 'node_modules', 'tesseract.js', 'dist', 'tesseract.min.js');
    if (fs.existsSync(script)) {
      try { await win.webContents.executeJavaScript(fs.readFileSync(script, 'utf8')); }
      catch (e) { console.error('OCR injection failed:', e); }
    }
  });
  win.on('closed', () => { win = null; });
}

ipcMain.handle('capture-with-permission', async () => {
  if (!win) return null;
  const permission = await dialog.showMessageBox(win, {
    type: 'question', buttons: ['Cancel', 'Choose screen / window'], defaultId: 0, cancelId: 0,
    title: 'CodeDoctor screen capture permission',
    message: 'Allow CodeDoctor to capture a screen or window?',
    detail: 'The selected screenshot is processed locally with OCR. You must review the text and separately click Analyze Code to send it to Groq.'
  });
  if (permission.response !== 1) return null;
  const sources = await desktopCapturer.getSources({ types: ['window', 'screen'], thumbnailSize: { width: 1920, height: 1080 }, fetchWindowIcons: false });
  if (!sources.length) return null;
  const names = sources.map((s, i) => `${i + 1}. ${s.name}`);
  // Native message boxes cannot provide a reliable source selector; use a dedicated chooser window.
  const chooser = new BrowserWindow({ parent: win, modal: true, width: 540, height: 420, resizable: false,
    title: 'Select capture source', webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } });
  const html = `<!doctype html><meta charset="utf-8"><style>body{background:#101c30;color:#fff;font:14px Arial;padding:16px}button{display:block;width:100%;margin:7px 0;padding:10px;text-align:left;background:#233956;color:white;border:1px solid #547091;border-radius:8px;cursor:pointer}</style><h2>Select a screen or window</h2><p>Only the source you choose will be captured.</p>${names.map((n,i)=>`<button onclick="location.href='codedoctor-select:${i}'">${n.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}</button>`).join('')}`;
  let chosen = null;
  const choice = new Promise(resolve => {
    chooser.webContents.on('will-navigate', (event, url) => {
      if (url.startsWith('codedoctor-select:')) {
        event.preventDefault(); const index = Number(url.slice('codedoctor-select:'.length));
        if (Number.isInteger(index) && index >= 0 && index < sources.length) chosen = sources[index];
        chooser.close();
      } else event.preventDefault();
    });
    chooser.on('closed', () => resolve(chosen));
  });
  await chooser.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
  const source = await choice;
  return source ? source.thumbnail.toDataURL() : null;
});

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  startBackend();
  try { await ready(); createWindow(); }
  catch (e) { dialog.showErrorBox('CodeDoctor backend unavailable', e.message); app.quit(); return; }
  const ok = globalShortcut.register('CommandOrControl+Shift+Alt+J', () => {
    if (!win) return;
    if (win.isVisible()) {
      win.hide();
      return;
    }
    const display = screen.getPrimaryDisplay();
    const area = display.workArea;
    const bounds = win.getBounds();
    win.setBounds({ x: area.x + area.width - bounds.width, y: area.y, width: bounds.width, height: area.height });
    win.show();
    win.focus();
    win.webContents.send('request-scan');
  });
  if (!ok) dialog.showMessageBox({ type:'warning', message:'Ctrl+Shift+Alt+J is already used by another app. Open CodeDoctor manually.' });
});
app.on('will-quit', () => { globalShortcut.unregisterAll(); if (server && !server.killed) server.kill(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (!win) createWindow(); });
