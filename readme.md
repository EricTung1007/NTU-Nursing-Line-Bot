[**中文版 README**](README.zh-TW.md) ｜ English

# AI-Driven Prenatal Education LINE Bot

This repository contains the working capstone prototype for a bilingual Chinese/English prenatal education chatbot developed at National Taiwan University. The system integrates a locally hosted large language model with retrieval-augmented generation grounded in curated maternal health education materials from official Taiwanese health sources.

The project was designed as a low-cost, privacy-conscious prototype that could deliver personalized prenatal education through LINE, a communication platform already familiar to many users in Taiwan. Its broader purpose was to explore how clinically grounded AI systems can improve access to trustworthy health education without requiring new apps, new accounts, or full dependence on commercial cloud services.

## Research Objective

- Improve accessibility and consistency of prenatal health education.
- Reduce hallucination risk by grounding responses in verified health education materials.
- Explore whether locally deployable AI can support multilingual, clinically aligned health communication in everyday care settings.
- Reduce adoption friction by using a communication platform already familiar to the target population.

## System Overview

- **Interface**: Flask + LINE Messaging API.
- **Generation**: locally hosted chat model through LM Studio or OpenAI-compatible endpoint.
- **Retrieval**: FAISS vector index over curated obstetric and maternal health education content.
- **Personalization**: pregnancy week, gravida/parity, parental role, and user name.
- **Memory**: lightweight per-user memory file for context continuity.

## Architecture

```
LINE App ──▶ Cloudflare Tunnel ──▶ Flask /callback ──▶ handle_event()
                                                        │
                                                        ├─ memory_module  (per-user profile & history)
                                                        ├─ RAG_module     (FAISS + LM Studio embeddings)
                                                        └─ LM Studio     (chat completion)
```

## Main Files

| File | Purpose |
|---|---|
| `LB.py` | LINE webhook handling and response orchestration |
| `config.py` | All configuration (reads secrets from `.env`) |
| `prompts.py` | System prompts and few-shot examples |
| `RAG_module.py` | Retrieval and augmented prompt construction |
| `memory_module.py` | User-specific memory and profile extraction |
| `prep.py` | Knowledge base preparation (PDF → JSONL → FAISS) |
| `product_entry.py` | PyInstaller entry point for packaged builds |
| `start.bat` | One-click Windows launcher (starts LM Studio + bot) |
| `start.command` | One-click macOS launcher (starts LM Studio + bot) |

## Prerequisites

- **Python** 3.11+
- **LM Studio** 0.3.x — load the following models:
  1. `text-embedding-bge-small-zh-v1.5` (embedding)
  2. A chat model of your choice (update `CHAT_MODEL` in `config.py`)
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

### 4. Run the bot

**Option A — One-click (macOS):**

```bash
chmod +x start.command
./start.command
```

If LM Studio installed the `lms` CLI somewhere other than `~/.lmstudio/bin/lms`, set `LMS_CLI_PATH` in `.env`.

**Option B — One-click (Windows):**

```bash
start.bat
```

**Option C — Manual:**

```bash
python LB.py
```

You'll be prompted to choose a mode:
- `1` — CLI test mode (chat in your terminal)
- `2` — Flask webhook mode (LINE bot)
- `3` — Both simultaneously

Models are automatically loaded into LM Studio on startup if not already present.

## Data Correction Commands (LINE)

Users can correct their profile by sending messages starting with `更正`:

| Command | Example |
|---|---|
| Full profile | `更正G(2)P(1)W(10)IsDad(False)Name(小美)` |
| G/P only | `更正G(3)P(1)` |
| Weeks only | `更正W(20)` |
| Parent role | `更正IsDad(True)` |
| Name only | `更正Name(小華)` |

## Current Status and Limitations

This repository reflects an academic prototype used for a poster presentation and technical demonstration. Current evaluation is preliminary and scenario-based. The system has not yet undergone large-scale user testing or clinical deployment.

## Packaging (optional)

```bash
python -m PyInstaller --clean --onedir --console --name NTULineBot product_entry.py
```

## License

This project is intended for academic and clinical education use at NTU Hospital.
