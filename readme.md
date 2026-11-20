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
| `nursebot/web/` | Admin GUI (API + single page) |

## Setup

1. Python 3.9+, then `pip install -r requirements.txt` (add `requirements-gui.txt` for a native window).
2. Put these files in place (not in git):
   - `bin/llama-server` (from a [llama.cpp release](https://github.com/ggml-org/llama.cpp/releases); keep its DLLs/libs beside it)
   - `bin/cloudflared` (a macOS arm64 build is already there)
   - `models/<chat-model>.gguf` and `models/<embedding-model>.gguf` (the embedding file name should contain `embed` or `bge`; the first non-embedding `.gguf` is used for chat)
3. `python app.py`. The Overview page shows a checklist of what is still missing.
4. Settings page: paste the LINE Channel Access Token and Secret. Knowledge Base page: press "Rebuild".
5. Press "Start bot". The tunnel URL is registered with LINE automatically.

Upgrading from the old version: on first launch the app imports `.env` LINE credentials and `memory_data/*.txt` into SQLite once. Rebuild the knowledge base after switching the embedding model; the GUI warns when the index was built with a different one.

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
