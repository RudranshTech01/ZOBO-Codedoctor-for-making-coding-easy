# CodeDoctor AI V2 — Electron + Groq + NeMo Guardrails

Based on the original CodeDoctor AI MVP. Existing FastAPI backend and HTML frontend are retained.

## Requirements
- Python 3.10–3.12 recommended (NeMo Guardrails dependency compatibility may vary)
- Node.js 20+ and npm
- Windows/macOS/Linux (Windows targeted for packaging)

## First-time setup
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```
Edit `.env` with **your own** `GROQ_API_KEY`. Never share it. The existing model setting is preserved; change `GROQ_MODEL` and guardrails/config.yml if your provider doesn't support it.

```powershell
cd desktop
npm install
npm start
```

The desktop app launches the Python backend on 127.0.0.1:8765. To use another Python executable, set `CODEDOCTOR_PYTHON` before starting Electron. `npm start` must be run from the `desktop` directory. For browser-only mode, run `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` from the project root.

## Side panel and code-only screen scan
1. Start CodeDoctor. It opens as a narrow panel on the right edge of the primary display.
2. From any app, press **Ctrl+Shift+Alt+J** to toggle the panel. When opened with the shortcut, the screen-scan permission flow starts.
3. Click **Allow & choose screen**, confirm, and select a screen/window. Drag a box tightly around only the code in the preview.
4. Click **Read selected code area**. Tesseract.js runs locally on just that crop; the rest of the screenshot is not processed by OCR.
5. Review the extracted code, select its language, and click **Analyze Code** to send the reviewed code to Groq. No automatic upload or editor modification.

OCR accuracy depends on font size, screen resolution, and image quality. Code region selection is manual; OCR reads only the crop the user draws and cannot infer exactly which text is source code by itself. The captured image is not written to disk. Some operating systems require screen recording permission.

## Build a Windows installer
From `desktop`: `npm run dist:win`. This generates an installer in `dist/` when build dependencies are available. **Important:** This is a developer-oriented installer: it does not bundle a Python runtime or installed pip dependencies. Users must install Python + requirements and configure their own key. For a public consumer installer, bundle a backend executable, implement key management, and code-sign the installer.

## Known limitations
- Code region selection is manual; OCR reads only the selected crop and is not project-wide IDE integration.
- OCR may misread symbols, whitespace, indentation and braces.
- No automatic Apply Fix/Undo or editor injection in this release.
- No live Groq API or Windows installer test was performed in this environment.
- NeMo Guardrails must be installed separately and configured correctly; runtime behavior requires testing with your environment.
- `backend/guardrails/config.yml` still uses its original model setting; keep it in sync with your selected Groq model.
- Local HTTP server is intended for trusted single-user machines only; add local authentication and hardening before broad public distribution.
