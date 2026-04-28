# NTU Nursing LINE Bot 🏥

A RAG-powered (Retrieval-Augmented Generation) LINE chatbot for **obstetric & maternal-infant care** at National Taiwan University Hospital. The bot answers pregnancy-related questions using locally-hosted LLMs via [LM Studio](https://lmstudio.ai/) and a FAISS vector knowledge base built from official health education PDFs.

## Features

- **LINE Messaging API** — receives and replies to messages on LINE
- **RAG pipeline** — retrieves relevant passages from a FAISS index, then generates answers with a local LLM
- **User memory** — tracks each user's pregnancy profile (`G/P`, gestational weeks, name, parent role) across conversations
- **Cloudflare Tunnel** — auto-creates a public URL and updates the LINE webhook so no static server is needed
- **CLI mode** — test the full conversation flow locally without LINE

## Architecture

```
LINE App ──▶ Cloudflare Tunnel ──▶ Flask /callback ──▶ handle_event()
                                                        │
                                                        ├─ memory_module  (per-user .txt files)
                                                        ├─ RAG_module     (FAISS + LM Studio embeddings)
                                                        └─ LM Studio     (chat completion)
```

| File | Purpose |
|---|---|
| `LB.py` | Main app — Flask webhook, event handler, CLI, tunnel setup |
| `config.py` | All configuration (reads secrets from `.env`) |
| `prompts.py` | System prompts and few-shot examples |
| `RAG_module.py` | Embedding search + prompt builder |
| `memory_module.py` | Per-user profile & conversation memory |
| `prep.py` | One-time script: PDF → JSONL → FAISS index |
| `product_entry.py` | PyInstaller entry point for packaged builds |
| `start.bat` | One-click Windows launcher (starts LM Studio + bot) |

## Prerequisites

- **Python** 3.12+
- **LM Studio** 0.3.x — load the following models:
  1. `text-embedding-bge-small-zh-v1.5` (embedding)
  2. `gemma-3-1B` (chat) — or any model you prefer; update `CHAT_MODEL` in `config.py`
- **Cloudflare Tunnel** (`cloudflared` CLI) — for public webhook exposure
- A **LINE Messaging API** channel ([developer console](https://developers.line.biz/console/))

## Quick Start

### 1. Clone & install dependencies

```bash
git clone https://github.com/EricTung1007/NTU-Nursing-Line-Bot.git
cd NTU-Nursing-Line-Bot
pip install -r requirements.txt
```

### 2. Configure secrets

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your LINE channel token, secret, and user IDs. **Never commit `.env`** — it is already in `.gitignore`.

### 3. Build the knowledge base (first time only)

Place your PDF files in the `database/` folder, then run:

```bash
python prep.py
```

This converts PDFs → JSONL → FAISS vector index.

### 4. Start LM Studio

Open LM Studio and load the embedding model and chat model (in that order).

### 5. Run the bot

**Option A — One-click (Windows):**

```bash
start.bat
```

**Option B — Manual:**

```bash
python LB.py
```

You'll be prompted to choose a mode:
- `1` — CLI test mode (chat in your terminal)
- `2` — Flask webhook mode (LINE bot)
- `3` — Both simultaneously

## Data Correction Commands (LINE)

Users can correct their profile by sending messages starting with `更正`:

| Command | Example |
|---|---|
| Full profile | `更正G(2)P(1)W(10)IsDad(False)Name(小美)` |
| G/P only | `更正G(3)P(1)` |
| Weeks only | `更正W(20)` |
| Parent role | `更正IsDad(True)` |
| Name only | `更正Name(小華)` |

## Packaging (optional)

```bash
python -m PyInstaller --clean --onedir --console --name NTULineBot product_entry.py
```

## License

This project is intended for academic and clinical education use at NTU Hospital.