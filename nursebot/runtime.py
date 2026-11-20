"""Wires components together and owns the bot's lifecycle.

    STOPPED -> STARTING -> RUNNING      start(): llama-server(s), webhook server, tunnel
    RUNNING -> STOPPING -> STOPPED      stop() reverses it

The webhook server (public, via the tunnel) is a separate Flask app on its own port from the admin
GUI. Only /callback is reachable from the internet; the GUI never is.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from flask import Flask, abort, request
from werkzeug.serving import make_server

from . import paths
from .bot import Bot, Dispatcher
from .db import DB
from .kb import KnowledgeBase
from .line import LineClient
from .llm import LlamaServers, LlmClient, find_llama_server, resolve_model
from .settings import Settings
from .tunnel import Tunnel, find_cloudflared

log = logging.getLogger("runtime")


class Life(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class Runtime:
    def __init__(self, db: DB):
        self.db = db
        self.settings = Settings(db)
        self.llm = LlmClient(self.settings)
        self.servers = LlamaServers(self.settings)
        self.kb = KnowledgeBase(paths.KB_DIR, self.settings, self.llm)
        self.line = LineClient(self.settings)
        self.bot = Bot(db, self.settings, self.llm, self.kb, self.line)
        self.tunnel = Tunnel(self.line)
        self.dispatcher: Optional[Dispatcher] = None
        self.life = Life.STOPPED
        self.problems: Dict[str, str] = {}
        self.last_webhook_at: Optional[float] = None
        self._http = None
        self._lock = threading.Lock()

    # ---- webhook app (public) ---------------------------------------------
    def _webhook_app(self) -> Flask:
        app = Flask("webhook")

        @app.get("/")
        def root() -> str:
            return "NTU Nursing LINE Bot is running"

        @app.get("/callback")
        def cb_health() -> str:
            return "LINE webhook endpoint is running. LINE sends POST requests here."

        @app.post("/callback")
        def callback() -> str:
            import time
            self.last_webhook_at = time.time()
            body = request.get_data()
            if not self.line.verify_signature(body, request.headers.get("X-Line-Signature", "")):
                log.error("invalid LINE signature (wrong channel secret?)")
                abort(400)
            try:
                events = json.loads(body).get("events", [])
            except ValueError:
                abort(400)
            for ev in events:
                self.dispatcher.submit(ev)  # type: ignore[union-attr]
            return "OK"  # answer LINE immediately; the model runs in the worker pool

        return app

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> Dict[str, str]:
        with self._lock:
            if self.life != Life.STOPPED:
                return self.problems
            self.life = Life.STARTING
        problems: Dict[str, str] = {}
        try:
            if not self.settings.line_ready():
                problems["line"] = "尚未設定 LINE Channel Access Token / Secret"
            if self.settings.get("llm_mode") == "managed":
                problems.update(self.servers.start())
            self.dispatcher = Dispatcher(self.bot)
            port = self.settings.int("webhook_port")
            self._http = make_server("127.0.0.1", port, self._webhook_app(), threaded=True)
            threading.Thread(target=self._http.serve_forever, daemon=True, name="webhook").start()
            if self.settings.bool("tunnel_enabled") and self.settings.line_ready():
                self.tunnel.start(port)
            for uid in self.settings.list("line_notify_user_ids"):
                self.line.push(uid, f"[後臺訊息]LINE Bot 已啟動（{datetime.now():%Y-%m-%d %H:%M}）")
            self.life = Life.RUNNING
        except OSError as e:  # typically: port already in use
            problems["webhook"] = f"無法啟動 Webhook（連接埠 {self.settings.get('webhook_port')} 可能被占用）：{e}"
            self._teardown()
        except Exception as e:
            log.exception("start failed")
            problems["start"] = str(e)
            self._teardown()
        self.problems = problems
        return problems

    def _teardown(self) -> None:
        self.life = Life.STOPPING
        self.tunnel.stop()
        if self._http:
            self._http.shutdown()
            self._http = None
        if self.dispatcher:
            self.dispatcher.shutdown()
            self.dispatcher = None
        self.servers.stop()
        self.life = Life.STOPPED

    def stop(self) -> None:
        with self._lock:
            if self.life in (Life.STOPPED, Life.STOPPING):
                return
        self._teardown()

    # ---- GUI status --------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        s = self.settings
        health = self.llm.health()
        managed = s.get("llm_mode") == "managed"
        return {
            "life": self.life.value,
            "problems": self.problems,
            "line": {"configured": s.line_ready(), "last_webhook_at": self.last_webhook_at},
            "tunnel": self.tunnel.status(),
            "llm": {
                "mode": s.get("llm_mode"),
                "chat_ready": health["chat"], "embed_ready": health["embed"],
                "server_found": bool(find_llama_server(s)) if managed else True,
                "chat_model": bool(resolve_model(s, "chat")) if managed else True,
                "embed_model": bool(resolve_model(s, "embed")) if managed else True,
            },
            "cloudflared_found": bool(find_cloudflared()),
            "kb": self.kb.status(),
            "counts": {
                "users": (self.db.one("SELECT COUNT(*) n FROM users WHERE user_id NOT LIKE 'gui-%'") or {}).get("n", 0),
                "unanswered": (self.db.one("SELECT COUNT(*) n FROM messages WHERE flag IS NOT NULL "
                                           "AND user_id NOT LIKE 'gui-%'") or {}).get("n", 0),
            },
        }
