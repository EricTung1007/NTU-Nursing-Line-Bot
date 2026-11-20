"""Settings stored in SQLite and edited from the GUI. No .env editing for staff."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List

from .db import DB

DEFAULT_EMERGENCY_REPLY = (
    "您描述的狀況可能需要立即處理，請立刻聯絡醫院或直接就醫。\n"
    "台大醫院總機：(02) 2312-3456\n"
    "產房分機：270908、270909\n"
    "若有大量出血、劇烈腹痛、破水、胎動明顯減少或停止、昏倒、抽搐、呼吸困難、胸痛，"
    "請不要等待 LINE 回覆，請立即撥打醫院電話或 119。"
)
DEFAULT_EMERGENCY_KEYWORDS = (
    "大量出血,一直流血,血流不停,劇烈腹痛,很痛,痛到受不了,規則宮縮,破水,羊水,胎動變少,胎動減少,"
    "沒有胎動,胎動停止,昏倒,暈倒,抽搐,呼吸困難,喘不過氣,胸痛,嚴重頭痛,視力模糊,高燒,發燒不退,"
    "意識不清,想吐又頭痛"
)

# key -> (default, is_secret)
SCHEMA: Dict[str, tuple] = {
    "line_channel_access_token": ("", True),
    "line_channel_secret": ("", True),
    "line_notify_user_ids": ("", False),
    "webhook_port": ("5001", False),
    "ui_port": ("5050", False),
    "autostart": ("true", False),
    "tunnel_enabled": ("true", False),
    # LLM: "managed" = the app runs llama.cpp's llama-server itself; "external" = any OpenAI-compatible URL
    "llm_mode": ("managed", False),
    "llama_server_path": ("", False),
    "chat_model_path": ("", False),
    "embed_model_path": ("", False),
    "chat_port": ("8081", False),
    "embed_port": ("8082", False),
    "llm_ctx": ("4096", False),
    "llm_gpu_layers": ("0", False),
    "embed_pooling": ("", False),
    "external_chat_url": ("http://127.0.0.1:1234", False),
    "external_embed_url": ("http://127.0.0.1:1234", False),
    "chat_model_name": ("local", False),
    "embed_model_name": ("local", False),
    # RAG / reply
    "top_k": ("5", False),
    "max_distance": ("1.2", False),
    "max_tokens": ("500", False),
    "temperature": ("0.6", False),
    "history_turns": ("10", False),
    # Staff-editable safety text
    "emergency_reply": (DEFAULT_EMERGENCY_REPLY, False),
    "emergency_keywords": (DEFAULT_EMERGENCY_KEYWORDS, False),
}

_ENV_MAP = {
    "LINE_CHANNEL_ACCESS_TOKEN": "line_channel_access_token",
    "LINE_CHANNEL_SECRET": "line_channel_secret",
    "LINE_NOTIFY_USER_IDS": "line_notify_user_ids",
    "FLASK_PORT": "webhook_port",
}
_PLACEHOLDERS = {"your_channel_access_token_here", "your_channel_secret_here"}


class Settings:
    def __init__(self, db: DB):
        self.db = db
        self._lock = threading.Lock()
        self._cache: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._cache = {k: v[0] for k, v in SCHEMA.items()}
            self._cache.update({k: v for k, v in self.db.load_settings().items() if k in SCHEMA})

    def get(self, key: str) -> str:
        return self._cache[key]

    def int(self, key: str) -> int:
        try:
            return int(self._cache[key])
        except ValueError:
            return int(SCHEMA[key][0])

    def float(self, key: str) -> float:
        try:
            return float(self._cache[key])
        except ValueError:
            return float(SCHEMA[key][0])

    def bool(self, key: str) -> bool:
        return self._cache[key].strip().lower() in ("1", "true", "yes", "on")

    def list(self, key: str) -> List[str]:
        raw = self._cache[key].replace("\n", ",")
        return [x.strip() for x in raw.split(",") if x.strip()]

    def update(self, items: Dict[str, Any]) -> None:
        clean = {}
        for k, v in items.items():
            if k not in SCHEMA:
                continue
            v = "" if v is None else str(v).strip() if k not in ("emergency_reply",) else str(v)
            if SCHEMA[k][1] and v == "":
                continue  # blank secret in the form means "keep current"
            clean[k] = v
        if clean:
            self.db.save_settings(clean)
            self.reload()

    def public(self) -> Dict[str, Any]:
        """Settings for the GUI: secrets are replaced by a has-value flag."""
        out: Dict[str, Any] = {}
        for k, (_, secret) in SCHEMA.items():
            out[k] = "" if secret else self._cache[k]
            if secret:
                out[k + "_set"] = bool(self._cache[k])
        return out

    def import_env(self, env_path: Path) -> bool:
        """One-time import of the old .env so existing deployments keep their LINE credentials."""
        if self.db.load_settings() or not env_path.exists():
            return False
        found: Dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k in _ENV_MAP and v and v not in _PLACEHOLDERS and not v.startswith("user_id_"):
                found[_ENV_MAP[k]] = v
        for k, name in (("FLASK_PORT", "webhook_port"),):
            if os.environ.get(k) and name not in found:
                found[name] = os.environ[k]
        if found:
            self.db.save_settings(found)
            self.reload()
        return bool(found)

    # convenience
    def line_ready(self) -> bool:
        t, s = self.get("line_channel_access_token"), self.get("line_channel_secret")
        return bool(t and s and t not in _PLACEHOLDERS and s not in _PLACEHOLDERS)
