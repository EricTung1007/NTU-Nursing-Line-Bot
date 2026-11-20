"""Filesystem layout. Everything lives beside the app so a folder copy is a full deployment."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)).resolve()
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    RESOURCE_DIR = APP_DIR


def _user_dir() -> Path:
    """Installed app: user data lives outside the install folder, so upgrades and uninstalls never touch it."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "NTULineBot"


ROOT = _user_dir() if FROZEN else APP_DIR
DATA_DIR = ROOT / "data"        # nursebot.db, logs
KB_DIR = ROOT / "database"      # source documents + FAISS index
MODELS_DIR = ROOT / "models"    # *.gguf
BIN_DIR = ROOT / "bin"          # llama-server, cloudflared
STATIC_DIR = RESOURCE_DIR / "nursebot" / "web" / "static"


def seed_bundled_kb() -> None:
    """First run of an installed app: copy the education booklets and prebuilt index that ship inside it."""
    src = RESOURCE_DIR / "database"
    if not FROZEN or not src.is_dir() or any(KB_DIR.glob("*.pdf")) or (KB_DIR / "faiss_index.index").exists():
        return
    for f in src.iterdir():
        if f.is_file() and f.suffix.lower() in (".pdf", ".txt", ".md", ".index", ".json"):
            shutil.copy2(f, KB_DIR / f.name)


def ensure_dirs() -> None:
    for d in (DATA_DIR, KB_DIR, MODELS_DIR, BIN_DIR):
        d.mkdir(parents=True, exist_ok=True)
    seed_bundled_kb()
