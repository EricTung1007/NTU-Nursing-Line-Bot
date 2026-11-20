"""Local admin GUI: Flask app bound to 127.0.0.1 only, never exposed through the tunnel.

Guards against a hostile web page driving it from the user's browser: Host header must be loopback
(DNS rebinding) and every write needs the per-run token embedded in the page (CSRF).
"""
from __future__ import annotations

import io
import logging
import secrets
import tempfile
import zipfile
from collections import deque
from pathlib import Path
from typing import Callable

from flask import Flask, Response, abort, jsonify, request, send_file

from .. import paths
from ..llm import list_models
from ..runtime import Runtime

log = logging.getLogger("admin")


class RingHandler(logging.Handler):
    """Keeps the last N log lines for the GUI's log tab."""

    def __init__(self, size: int = 500):
        super().__init__()
        self.lines: deque = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def create_admin_app(rt: Runtime, ring: RingHandler, on_quit: Callable[[], None]) -> Flask:
    app = Flask("admin", static_folder=None)
    token = secrets.token_urlsafe(24)
    ui_port = rt.settings.int("ui_port")
    allowed_hosts = {f"127.0.0.1:{ui_port}", f"localhost:{ui_port}"}

    @app.before_request
    def guard() -> None:
        if request.host not in allowed_hosts:
            abort(403)
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Admin-Token") != token:
            abort(403)

    @app.get("/")
    def index() -> Response:
        html = (paths.STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
        return Response(html, mimetype="text/html")

    # ---- status / lifecycle -----------------------------------------------
    @app.get("/api/status")
    def status():
        return jsonify(rt.status())

    @app.post("/api/start")
    def start():
        return jsonify(problems=rt.start())

    @app.post("/api/stop")
    def stop():
        rt.stop()
        return jsonify(ok=True)

    @app.post("/api/quit")
    def quit_app():
        on_quit()
        return jsonify(ok=True)

    # ---- settings ----------------------------------------------------------
    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings=rt.settings.public(), models=[m.name for m in list_models()])

    @app.put("/api/settings")
    def put_settings():
        rt.settings.update(request.get_json(force=True) or {})
        rt.llm.clear_cache()
        return jsonify(ok=True)

    @app.post("/api/line/test")
    def line_test():
        name = rt.line.bot_name()
        return jsonify(ok=bool(name), name=name)

    # ---- users -------------------------------------------------------------
    @app.get("/api/users")
    def users():
        return jsonify(users=rt.db.list_users(request.args.get("q", "")))

    @app.get("/api/users/<uid>")
    def user_detail(uid):
        u = rt.db.get_user(uid)
        if not u:
            abort(404)
        return jsonify(user=u, messages=rt.db.recent_messages(uid, 200))

    @app.put("/api/users/<uid>")
    def user_update(uid):
        from .. import profile as pf
        if not rt.db.get_user(uid):
            abort(404)
        d = request.get_json(force=True) or {}
        fields = {}
        for k in ("g", "p"):
            if d.get(k) not in (None, ""):
                fields[k] = int(d[k])
        if d.get("weeks") not in (None, ""):
            from datetime import date
            fields["weeks"], fields["weeks_set_on"] = int(d["weeks"]), date.today().isoformat()
        if "is_dad" in d and d["is_dad"] in (0, 1, True, False):
            fields["is_dad"] = int(d["is_dad"])
        if "name" in d:
            fields["name"] = str(d["name"]).strip()
        rt.db.update_user(uid, **fields)
        u = rt.db.get_user(uid)
        rt.db.update_user(uid, state=pf.next_state(u["state"], not pf.missing_fields(u)).value)
        return jsonify(user=rt.db.get_user(uid))

    @app.delete("/api/users/<uid>")
    def user_delete(uid):
        rt.db.delete_user(uid)
        return jsonify(ok=True)

    @app.get("/api/unanswered")
    def unanswered():
        return jsonify(items=rt.db.unanswered())

    @app.post("/api/chat")
    def chat():
        d = request.get_json(force=True) or {}
        text = str(d.get("text", "")).strip()
        if not text:
            abort(400)
        return jsonify(reply=rt.bot.handle_text("gui-test", text))

    @app.post("/api/chat/reset")
    def chat_reset():
        rt.db.delete_user("gui-test")
        return jsonify(ok=True)

    # ---- knowledge base ----------------------------------------------------
    @app.get("/api/kb")
    def kb_status():
        return jsonify(rt.kb.status())

    @app.post("/api/kb/upload")
    def kb_upload():
        saved, errors = [], []
        for f in request.files.getlist("files"):
            try:
                saved.append(rt.kb.add_file(f.filename or "", f.read()))
            except ValueError as e:
                errors.append(f"{f.filename}: {e}")
        return jsonify(saved=saved, errors=errors)

    @app.delete("/api/kb/doc")
    def kb_delete():
        rt.kb.remove_file(request.args.get("name", ""))
        return jsonify(ok=True)

    @app.post("/api/kb/rebuild")
    def kb_rebuild():
        return jsonify(started=rt.kb.start_rebuild())

    # ---- logs / backup -----------------------------------------------------
    @app.get("/api/logs")
    def logs():
        return jsonify(lines=list(ring.lines)[-300:])

    @app.get("/api/backup")
    def backup():
        """One zip: database snapshot + knowledge-base sources. Contains LINE secrets: keep it private."""
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "nursebot.db"
            rt.db.backup_to(snap)
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, "data/nursebot.db")
                for p in rt.kb.sources():
                    z.write(p, f"database/{p.name}")
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="nursebot-backup.zip")

    return app
