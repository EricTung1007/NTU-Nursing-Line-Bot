"""Filesystem layout. Everything lives beside the app so a folder copy is a full deployment."""
from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)).resolve()
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    RESOURCE_DIR = APP_DIR

DATA_DIR = APP_DIR / "data"        # nursebot.db, logs
KB_DIR = APP_DIR / "database"      # source documents + FAISS index (existing location)
MODELS_DIR = APP_DIR / "models"    # *.gguf
BIN_DIR = APP_DIR / "bin"          # llama-server, cloudflared
STATIC_DIR = RESOURCE_DIR / "nursebot" / "web" / "static"


def ensure_dirs() -> None:
    for d in (DATA_DIR, KB_DIR, MODELS_DIR, BIN_DIR):
        d.mkdir(parents=True, exist_ok=True)
