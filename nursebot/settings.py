"""Settings stored in SQLite and edited from the GUI. Every setting is described here once; the GUI
renders the full settings page from this table, validation and reset-to-default come for free.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .db import DB
from .prompts import fields_system_prompt, no_data_reply, normal_system_prompt

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

LAST_GOOD_KEY = "_last_good"


@dataclass
class Spec:
    default: str
    group: str
    zh: str
    en: str
    kind: str = "text"        # text | int | float | secret | bool | select | area | model | prompt
    options: Tuple[Tuple[str, str], ...] = ()   # (value, label) for select
    minv: Optional[float] = None
    maxv: Optional[float] = None
    help_zh: str = ""
    help_en: str = ""
    advanced: bool = False
    restart: bool = False     # needs a bot restart to take effect

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


_YESNO = (("true", "是 / Yes"), ("false", "否 / No"))
G_LINE, G_SAFE, G_MODEL, G_ANS, G_NET, G_PROMPT, G_SYS = "line", "safety", "model", "answer", "network", "prompts", "system"

SCHEMA: Dict[str, Spec] = {s[0]: s[1] for s in [
    # ---- LINE
    ("line_channel_access_token", Spec("", G_LINE, "Channel Access Token", "Channel Access Token", "secret",
        help_zh="LINE Developers 後台 Messaging API 頁籤裡的長字串。", help_en="Long string on the Messaging API tab in LINE Developers.")),
    ("line_channel_secret", Spec("", G_LINE, "Channel Secret", "Channel Secret", "secret",
        help_zh="LINE Developers 後台 Basic settings 頁籤。", help_en="Basic settings tab in LINE Developers.")),
    ("line_notify_user_ids", Spec("", G_LINE, "啟動時通知的 LINE User ID", "LINE user IDs notified at startup",
        help_zh="多個用逗號分隔，可留空。", help_en="Comma separated, optional.")),
    # ---- safety
    ("emergency_keywords", Spec(DEFAULT_EMERGENCY_KEYWORDS, G_SAFE, "緊急關鍵字", "Emergency keywords", "area",
        help_zh="使用者訊息含任一關鍵字，立刻回覆下方的緊急訊息。以逗號分隔。", help_en="Any match triggers the emergency reply immediately. Comma separated.")),
    ("emergency_reply", Spec(DEFAULT_EMERGENCY_REPLY, G_SAFE, "緊急回覆內容", "Emergency reply text", "area",
        help_zh="請確認電話號碼是最新的。", help_en="Make sure the phone numbers are current.")),
    # ---- answers
    ("top_k", Spec("5", G_ANS, "參考段落數", "Passages retrieved", "int", minv=1, maxv=20,
        help_zh="每次回答參考幾段衛教資料。越多越完整但越慢。", help_en="How many knowledge passages feed each answer.")),
    ("max_distance", Spec("1.2", G_ANS, "相關度門檻", "Relevance threshold", "float", minv=0.01, maxv=100,
        help_zh="越小越嚴格（更常回答「沒有相關資料」）；越大越寬鬆。", help_en="Smaller is stricter (more 'no data' replies).")),
    ("max_tokens", Spec("500", G_ANS, "回答長度上限", "Max answer length (tokens)", "int", minv=50, maxv=4000)),
    ("temperature", Spec("0.6", G_ANS, "溫度", "Temperature", "float", minv=0, maxv=2,
        help_zh="越低越穩定、越高越多變。衛教建議 0.3 到 0.7。", help_en="Lower is steadier. 0.3 to 0.7 suggested.")),
    ("history_turns", Spec("10", G_ANS, "帶入的對話輪數", "Conversation turns kept in context", "int", minv=0, maxv=50)),
    ("show_sources", Spec("true", G_ANS, "回覆附上資料來源", "Append sources to replies", "select", _YESNO)),
    ("request_timeout", Spec("120", G_ANS, "模型回應逾時（秒）", "Model timeout (seconds)", "int", minv=10, maxv=600, advanced=True)),
    # ---- model
    ("llm_mode", Spec("managed", G_MODEL, "模型來源", "Model source", "select",
        (("managed", "由本程式啟動 llama.cpp / App runs llama.cpp"), ("external", "外部 OpenAI 相容服務 / External server")), restart=True)),
    ("chat_model_path", Spec("", G_MODEL, "對話模型", "Chat model", "model", restart=True,
        help_zh="留空＝自動選擇 models 資料夾內的模型。", help_en="Empty = pick automatically from the models folder.")),
    ("embed_model_path", Spec("", G_MODEL, "檢索（向量）模型", "Embedding model", "model", restart=True,
        help_zh="檔名含 embed 或 bge 會被自動選為檢索模型。更換後須重建知識庫。", help_en="Names containing embed/bge are auto-selected. Rebuild the knowledge base after changing.")),
    ("llm_ctx", Spec("4096", G_MODEL, "上下文長度", "Context length", "int", minv=512, maxv=131072, restart=True,
        help_zh="記憶體不足時請調小。", help_en="Lower it if memory runs out.")),
    ("llm_gpu_layers", Spec("0", G_MODEL, "GPU 層數", "GPU layers", "int", minv=0, maxv=999, restart=True,
        help_zh="0＝只用 CPU（最穩定）。有獨立顯卡可調高。", help_en="0 = CPU only (most reliable).")),
    ("embed_pooling", Spec("", G_MODEL, "向量池化方式", "Embedding pooling", "select",
        (("", "自動 / Auto"), ("cls", "cls"), ("mean", "mean"), ("last", "last")), advanced=True, restart=True)),
    ("extra_llama_args", Spec("", G_MODEL, "額外 llama-server 參數", "Extra llama-server arguments", "text", advanced=True, restart=True,
        help_zh="進階。例如 --threads 4。會同時加到對話與檢索模型。", help_en="Advanced, e.g. --threads 4. Applied to both servers.")),
    ("llama_server_path", Spec("", G_MODEL, "llama-server 路徑", "llama-server path", "text", advanced=True, restart=True,
        help_zh="留空＝自動在 bin 資料夾尋找。", help_en="Empty = look in the bin folder.")),
    ("chat_model_name", Spec("local", G_MODEL, "外部服務：對話模型名稱", "External: chat model name", "text", advanced=True)),
    ("embed_model_name", Spec("local", G_MODEL, "外部服務：檢索模型名稱", "External: embedding model name", "text", advanced=True)),
    ("external_chat_url", Spec("http://127.0.0.1:1234", G_MODEL, "外部服務網址（對話）", "External URL (chat)", "text", advanced=True)),
    ("external_embed_url", Spec("http://127.0.0.1:1234", G_MODEL, "外部服務網址（檢索）", "External URL (embeddings)", "text", advanced=True)),
    # ---- network
    ("webhook_port", Spec("5001", G_NET, "Webhook 連接埠", "Webhook port", "int", minv=1024, maxv=65535, restart=True, advanced=True,
        help_zh="被占用時，「自動修復」會幫您換一個。", help_en="If it is taken, Auto-fix picks another.")),
    ("ui_port", Spec("5050", G_NET, "管理介面連接埠", "GUI port", "int", minv=1024, maxv=65535, restart=True, advanced=True)),
    ("chat_port", Spec("8081", G_NET, "對話模型連接埠", "Chat model port", "int", minv=1024, maxv=65535, restart=True, advanced=True)),
    ("embed_port", Spec("8082", G_NET, "檢索模型連接埠", "Embedding model port", "int", minv=1024, maxv=65535, restart=True, advanced=True)),
    ("tunnel_enabled", Spec("true", G_NET, "自動建立 Cloudflare 通道", "Auto-create Cloudflare tunnel", "select", _YESNO, restart=True)),
    # ---- system
    ("autostart", Spec("true", G_SYS, "開啟程式時自動啟動機器人", "Start the bot when the app opens", "select", _YESNO)),
    ("auto_repair", Spec("true", G_SYS, "自動修復（模型或通道當掉時自動重啟）", "Self-repair (restart crashed model/tunnel)", "select", _YESNO)),
    ("worker_threads", Spec("4", G_SYS, "同時處理訊息數", "Concurrent message workers", "int", minv=1, maxv=32, restart=True, advanced=True)),
    ("log_level", Spec("INFO", G_SYS, "記錄詳細程度", "Log detail", "select",
        (("INFO", "一般 / Normal"), ("DEBUG", "詳細（除錯用）/ Debug")), advanced=True)),
    # ---- prompts
    ("system_prompt", Spec(normal_system_prompt, G_PROMPT, "回答用系統提示詞", "Answer system prompt", "prompt", advanced=True,
        help_zh="決定機器人的角色與語氣。改壞了可按「還原預設」。", help_en="Defines role and tone. Use Reset if it breaks.")),
    ("no_data_reply", Spec(no_data_reply, G_PROMPT, "查無資料時的回覆", "Reply when no knowledge is found", "prompt", advanced=True)),
    ("fields_prompt", Spec(fields_system_prompt, G_PROMPT, "資料擷取提示詞", "Profile extraction prompt", "prompt", advanced=True)),
]}

GROUP_TITLES = {
    G_LINE: ("LINE 連線", "LINE connection"), G_SAFE: ("緊急狀況", "Emergency handling"),
    G_ANS: ("回答行為", "Answer behaviour"), G_MODEL: ("語言模型", "Language models"),
    G_NET: ("連接埠與通道", "Ports & tunnel"), G_SYS: ("系統", "System"), G_PROMPT: ("提示詞", "Prompts"),
}

_ENV_MAP = {
    "LINE_CHANNEL_ACCESS_TOKEN": "line_channel_access_token",
    "LINE_CHANNEL_SECRET": "line_channel_secret",
    "LINE_NOTIFY_USER_IDS": "line_notify_user_ids",
    "FLASK_PORT": "webhook_port",
}
_PLACEHOLDERS = {"your_channel_access_token_here", "your_channel_secret_here"}
_PORT_KEYS = ("webhook_port", "ui_port", "chat_port", "embed_port")
_MULTILINE = ("area", "prompt")


class Settings:
    def __init__(self, db: DB):
        self.db = db
        self._lock = threading.Lock()
        self._cache: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._cache = {k: v.default for k, v in SCHEMA.items()}
            self._cache.update({k: v for k, v in self.db.load_settings().items() if k in SCHEMA})

    def get(self, key: str) -> str:
        return self._cache[key]

    def int(self, key: str) -> int:
        try:
            return int(self._cache[key])
        except ValueError:
            return int(SCHEMA[key].default)

    def float(self, key: str) -> float:
        try:
            return float(self._cache[key])
        except ValueError:
            return float(SCHEMA[key].default)

    def bool(self, key: str) -> bool:
        return self._cache[key].strip().lower() in ("1", "true", "yes", "on")

    def values(self) -> Dict[str, str]:
        return dict(self._cache)

    def list(self, key: str) -> List[str]:
        return [x.strip() for x in self._cache[key].replace("\n", ",").split(",") if x.strip()]

    # ---- validation --------------------------------------------------------
    def validate(self, items: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
        """Returns {key: (zh, en)} for each bad value. Empty dict = all good."""
        errors: Dict[str, Tuple[str, str]] = {}
        merged = dict(self._cache)
        for k, v in items.items():
            if k in SCHEMA and not (SCHEMA[k].secret and str(v).strip() == ""):
                merged[k] = str(v)
        for k, v in items.items():
            spec = SCHEMA.get(k)
            if not spec or (spec.secret and str(v).strip() == ""):
                continue
            v = str(v).strip()
            if spec.kind in ("int", "float"):
                try:
                    n = int(v) if spec.kind == "int" else float(v)
                except ValueError:
                    errors[k] = (f"「{spec.zh}」必須是數字", f"'{spec.en}' must be a number")
                    continue
                if (spec.minv is not None and n < spec.minv) or (spec.maxv is not None and n > spec.maxv):
                    errors[k] = (f"「{spec.zh}」請填 {spec.minv:g} 到 {spec.maxv:g} 之間",
                                 f"'{spec.en}' must be between {spec.minv:g} and {spec.maxv:g}")
            elif spec.kind == "select" and v not in [o[0] for o in spec.options]:
                errors[k] = (f"「{spec.zh}」的選項無效", f"Invalid option for '{spec.en}'")
            elif k in ("external_chat_url", "external_embed_url") and v and not v.startswith(("http://", "https://")):
                errors[k] = ("網址必須以 http:// 或 https:// 開頭", "URL must start with http:// or https://")
            elif k in ("emergency_reply", "system_prompt", "no_data_reply") and not v:
                errors[k] = (f"「{spec.zh}」不可留空（可按「還原預設」）", f"'{spec.en}' cannot be empty (use Reset)")
        # ports must be distinct
        seen: Dict[str, str] = {}
        for k in _PORT_KEYS:
            p = merged.get(k)
            if p in seen:
                errors.setdefault(k, (f"連接埠與「{SCHEMA[seen[p]].zh}」重複", f"Port clashes with '{SCHEMA[seen[p]].en}'"))
            seen[p] = k
        return errors

    # ---- mutation ----------------------------------------------------------
    def update(self, items: Dict[str, Any]) -> None:
        clean = {}
        for k, v in items.items():
            spec = SCHEMA.get(k)
            if not spec:
                continue
            v = "" if v is None else (str(v) if spec.kind in _MULTILINE else str(v).strip())
            if spec.secret and v == "":
                continue  # blank secret in the form means "keep current"
            clean[k] = v
        if clean:
            self.db.save_settings(clean)
            self.reload()

    def reset(self, keys: Optional[List[str]] = None) -> None:
        keys = [k for k in (keys or list(SCHEMA)) if k in SCHEMA and not SCHEMA[k].secret]
        c = self.db.conn()
        with c:
            c.executemany("DELETE FROM settings WHERE key=?", [(k,) for k in keys])
        self.reload()

    def snapshot_good(self) -> None:
        """Remember the settings that produced a fully healthy run, so a bad edit can be undone."""
        snap = {k: v for k, v in self._cache.items() if not SCHEMA[k].secret}
        self.db.save_settings({LAST_GOOD_KEY: json.dumps(snap, ensure_ascii=False)})

    def last_good(self) -> Optional[Dict[str, str]]:
        raw = self.db.load_settings().get(LAST_GOOD_KEY)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def differs_from_good(self) -> List[str]:
        g = self.last_good()
        return [k for k, v in (g or {}).items() if k in SCHEMA and self._cache.get(k) != v]

    def restore_good(self) -> List[str]:
        g = self.last_good() or {}
        changed = self.differs_from_good()
        self.update({k: g[k] for k in changed})
        return changed

    def public(self) -> Dict[str, Any]:
        """Values for the GUI: secrets are replaced by a has-value flag."""
        out: Dict[str, Any] = {}
        for k, spec in SCHEMA.items():
            out[k] = "" if spec.secret else self._cache[k]
            if spec.secret:
                out[k + "_set"] = bool(self._cache[k])
        return out

    def meta(self) -> List[Dict[str, Any]]:
        return [{"key": k, "group": s.group, "zh": s.zh, "en": s.en, "kind": s.kind, "default": "" if s.secret else s.default,
                 "options": [list(o) for o in s.options], "min": s.minv, "max": s.maxv, "help_zh": s.help_zh,
                 "help_en": s.help_en, "advanced": s.advanced, "restart": s.restart} for k, s in SCHEMA.items()]

    def redacted(self) -> Dict[str, str]:
        return {k: ("(set)" if self._cache[k] else "(empty)") if SCHEMA[k].secret else self._cache[k] for k in SCHEMA
                if SCHEMA[k].kind != "prompt"}

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
        if os.environ.get("FLASK_PORT") and "webhook_port" not in found:
            found["webhook_port"] = os.environ["FLASK_PORT"]
        if found:
            self.db.save_settings(found)
            self.reload()
        return bool(found)

    def line_ready(self) -> bool:
        t, s = self.get("line_channel_access_token"), self.get("line_channel_secret")
        return bool(t and s and t not in _PLACEHOLDERS and s not in _PLACEHOLDERS)
