[中文](README.zh-TW.md) | **English**

# AI Prenatal Education LINE Bot

Bilingual prenatal education chatbot (NTU capstone prototype). A local LLM answers questions using retrieval over official Taiwanese maternal and child health materials, delivered through LINE.

This version runs without a terminal and without LM Studio: a local GUI manages everything, inference is llama.cpp, and all state lives in one SQLite file.

## Architecture

```
LINE ──▶ Cloudflare tunnel ──▶ webhook server :5001 (/callback only, public)
                                   │  returns 200 at once, work runs in a worker pool
                                   ▼
                              Bot pipeline ── SQLite (users, messages, settings)
                                   │  correction cmd → emergency check → onboarding → RAG answer
                                   ├─ FAISS knowledge base  (embeddings: llama-server --embeddings)
                                   └─ chat model            (llama-server)

Admin GUI :5050 (127.0.0.1 only, never exposed through the tunnel)
```

| Path | Purpose |
|---|---|
| `app.py` | Entry point. Opens the GUI (native window if `pywebview` is installed, else browser) |
| `nursebot/profile.py` | Onboarding state machine and all profile / 更正 parsing |
| `nursebot/bot.py` | Conversation pipeline and per-user ordered worker pool |
| `nursebot/llm.py` | llama-server supervisor and OpenAI-compatible client |
| `nursebot/kb.py` | Document ingestion, batched embedding, atomic FAISS rebuild |
| `nursebot/db.py`, `settings.py` | SQLite store; settings are edited in the GUI |
| `nursebot/tunnel.py`, `line.py` | Cloudflare tunnel + LINE webhook registration; LINE API client |
| `nursebot/nurse_practitioner.py` | The in-app nurse practitioner (NP): health checks, plain-language steps, auto-fixes |
| `nursebot/runtime.py` | Lifecycle, supervisor (auto-restart), incident log |
| `nursebot/web/` | Admin GUI (API + single page) and the nurse note |

## Download (for nurses and end users)

Go to the repository's **Releases** page and download `NTULineBot-Setup.exe` (Windows) or `NTULineBot-mac.dmg` (Mac). Install, open, press **Fix everything**: the app downloads llama.cpp, cloudflared and the models itself (about 2.7 GB, resumable, checksum-verified). No terminal at any point. The installer is unsigned, so Windows SmartScreen shows "More info, then Run anyway" once; on Mac use right-click, Open.

Releases are built by GitHub Actions (`.github/workflows/release.yml`) when a tag such as `v1.0.0` is pushed. The Windows installer is made with Inno Setup (`packaging/installer.iss`) from a PyInstaller windowed build (`packaging/NTULineBot.spec`). Installed apps keep user data in `%LOCALAPPDATA%\NTULineBot` (macOS: `~/Library/Application Support/NTULineBot`), so upgrades never touch it.

## Setup from source

1. Python 3.9+, then `pip install -r requirements.txt` (add `requirements-gui.txt` for a native window).
2. `python app.py`, then press **Fix everything**: missing llama-server, cloudflared and models are found (Downloads/Desktop/Documents) or downloaded automatically. You can also drop files into `bin/` and `models/` yourself (the embedding model file name should contain `embed` or `bge`).
3. The Overview page lists anything still missing.
4. Settings page: paste the LINE Channel Access Token and Secret. Knowledge Base page: press "Rebuild".
5. Press "Start bot". The tunnel URL is registered with LINE automatically.

Upgrading from the old version: on first launch the app imports `.env` LINE credentials and `memory_data/*.txt` into SQLite once. Rebuild the knowledge base after switching the embedding model; the GUI warns when the index was built with a different one.

## Updates and live status

- **Check for updates** (top right) asks GitHub Releases for a newer version; the app also checks every 12 hours (switchable in Settings). On Windows "Update now" downloads the installer, verifies its SHA-256, installs silently and relaunches. On macOS it opens the new `.dmg`. Versions are stamped from the release tag.
- **Live model light** (top bar): offline, loading, idle, searching, generating (with a queue count). It reads in-flight request counters, so it reflects real activity, including test chats.

## Self-repair and debugging

The app watches itself so operators do not have to:

- **Fix everything** (top bar): runs every health check, applies the safe fixes (busy ports, moved model files, invalid settings, crashed models, dropped tunnel, stale knowledge base), then lists anything left with numbered plain-language steps in Chinese and English.
- **Supervisor**: restarts a crashed llama-server (lowering context/GPU use after an out-of-memory), reconnects a lost tunnel, with rate limits so a permanently broken part is reported instead of restarted forever.
- **Preflight** on every start applies the same safe fixes silently. A second double-click just reopens the existing window.
- **Last working settings** are remembered after the first fully healthy run; one button undoes a bad edit.
- **Debug page**: full checks including network, end-to-end self-test with per-step timings, reply latency stats, event timeline, live filtered logs (app and both model servers), and a diagnostic zip for IT that never contains LINE keys.
- **Settings page**: every setting with bilingual help, validation, per-field reset, and search; the prompts are editable too.

Nurse-facing instructions (Chinese and English) are in the app's Guide tab, from [`nursebot/web/static/nurse_note.md`](nursebot/web/static/nurse_note.md).

## What staff can do in the GUI (no files, no commands)

- Start/stop the bot, see LINE / model / knowledge base status
- View, edit, delete users and read their conversations
- See questions the bot could not answer (knowledge gaps), then upload documents and rebuild
- Chat with the bot as a test user (not sent to LINE)
- Edit emergency keywords and the emergency reply
- Download a backup (database + documents)

## Tests

```bash
pip install pytest && python -m pytest tests
```

## Disclaimer

Educational prototype. It does not replace professional medical advice.
