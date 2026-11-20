"""Local admin GUI: Flask app bound to 127.0.0.1 only, never exposed through the tunnel.

Guards against a hostile web page driving it from the user's browser: Host header must be loopback
(DNS rebinding) and every write needs the per-run token embedded in the page (CSRF).
"""
from __future__ import annotations

import io
import json
import logging
import platform
import sys
import time
import secrets
import tempfile
import zipfile
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, Response, abort, jsonify, request, send_file

from .. import paths
from ..llm import LlamaServers, list_models
from ..runtime import Runtime
from ..settings import GROUP_TITLES, SCHEMA

log = logging.getLogger("admin")


class RingHandler(logging.Handler):
    """Keeps the last N log lines for the GUI's log tab."""

    def __init__(self, size: int = 500):
        super().__init__()
        self.lines: deque = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def create_admin_app(rt: Runtime, ring: RingHandler, on_quit: Callable[[], None], ui_port: Optional[int] = None) -> Flask:
    app = Flask("admin", static_folder=None)
    token = secrets.token_urlsafe(24)
    ui_port = ui_port or rt.settings.int("ui_port")
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
        return jsonify(settings=rt.settings.public(), meta=rt.settings.meta(), groups=GROUP_TITLES,
                       models=[m.name for m in list_models()], differs=rt.settings.differs_from_good(),
                       restart_needed=bool(rt.life.value == "running"))

    @app.put("/api/settings")
    def put_settings():
        items = request.get_json(force=True) or {}
        errors = rt.settings.validate(items)
        if errors:
            return jsonify(ok=False, errors={k: list(v) for k, v in errors.items()}), 400
        rt.settings.update(items)
        rt.llm.clear_cache()
        logging.getLogger().setLevel(getattr(logging, rt.settings.get("log_level"), logging.INFO))
        restart = [k for k in items if k in SCHEMA and SCHEMA[k].restart]
        return jsonify(ok=True, restart_needed=bool(restart) and rt.life.value == "running")

    @app.post("/api/settings/reset")
    def reset_settings():
        d = request.get_json(force=True) or {}
        rt.settings.reset(d.get("keys"))
        return jsonify(ok=True)

    @app.post("/api/settings/restore_good")
    def restore_good():
        return jsonify(changed=rt.settings.restore_good())

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

    # ---- NP rounds / debug ----------------------------------------------------
    @app.get("/api/np")
    def np_checkup():
        checks = rt.np.run(deep=request.args.get("deep") == "1")
        return jsonify(checks=[c.to_dict() for c in checks], summary=rt.np.summary(checks))

    @app.post("/api/np/fix")
    def np_fix():
        ok, zh, en = rt.np.fix((request.get_json(force=True) or {}).get("id", ""))
        return jsonify(ok=ok, zh=zh, en=en)

    @app.post("/api/np/fix_all")
    def np_fix_all():
        return jsonify(started=rt.np.fix_all_async())

    @app.get("/api/np/job")
    def np_job():
        return jsonify(rt.np.job())

    @app.get("/api/incidents")
    def incidents():
        return jsonify(items=list(rt.incidents)[::-1])

    @app.get("/api/metrics")
    def metrics():
        m = list(rt.bot.metrics)
        secs = sorted(x["secs"] for x in m)
        return jsonify(n=len(m), errors=sum(1 for x in m if x["flag"] == "error"), no_data=sum(1 for x in m if x["flag"] == "no_data"),
                       p50=secs[len(secs) // 2] if secs else None, p95=secs[int(len(secs) * 0.95) - 1] if len(secs) >= 2 else (secs[0] if secs else None),
                       last_webhook_at=rt.last_webhook_at, uptime=(time.time() - rt.started_at) if rt.started_at and rt.life.value == "running" else None)

    @app.post("/api/selftest")
    def selftest():
        """End-to-end probe with timings, so 'it does not answer' becomes 'step 3 failed'."""
        steps = []

        def step(name_zh, name_en, fn):
            t0 = time.time()
            try:
                detail = fn()
                steps.append({"zh": name_zh, "en": name_en, "ok": True, "secs": round(time.time() - t0, 2), "detail": detail or ""})
                return True
            except Exception as e:
                steps.append({"zh": name_zh, "en": name_en, "ok": False, "secs": round(time.time() - t0, 2), "detail": str(e)[:300]})
                return False

        vec = {}
        if step("產生向量（檢索模型）", "Embed a question", lambda: vec.setdefault("v", rt.llm.embed(["孕期腰痠怎麼辦"])[0]) and f"{len(vec['v'])} dims") \
           and step("搜尋知識庫", "Search the knowledge base", lambda: f"{len(rt.kb.search(vec['v'], rt.settings.int('top_k'), 1e9))} passages"):
            step("產生回答（對話模型）", "Generate a reply", lambda: rt.llm.chat([{"role": "user", "content": "請用一句話說：測試成功"}], max_tokens=40)[:80])
        return jsonify(steps=steps, ok=all(s["ok"] for s in steps))

    @app.get("/api/logs")
    def logs():
        src = request.args.get("source", "app")
        level = request.args.get("level", "")
        q = request.args.get("q", "").lower()
        if src in ("chat", "embed"):
            lines = LlamaServers.tail(src, 300)
        else:
            lines = list(ring.lines)[-1000:]
            if level:
                order = ["DEBUG", "INFO", "WARNING", "ERROR"]
                lines = [l for l in lines if any(f"[{x}]" in l for x in order[order.index(level):])]
        if q:
            lines = [l for l in lines if q in l.lower()]
        return jsonify(lines=lines[-400:])

    @app.get("/api/guide")
    def guide():
        p = paths.STATIC_DIR / "nurse_note.md"
        return jsonify(text=p.read_text(encoding="utf-8") if p.exists() else "")

    @app.get("/api/diagnostic")
    def diagnostic():
        """Support bundle: logs, redacted settings, NP report. Secrets are never included."""
        checks = rt.np.run(deep=True)
        report = json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "platform": platform.platform(), "python": sys.version,
                             "life": rt.life.value, "settings": rt.settings.redacted(),
                             "checks": [c.to_dict() for c in checks], "kb": rt.kb.status(),
                             "incidents": list(rt.incidents)[-100:]}, ensure_ascii=False, indent=2, default=str)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.json", report)
            z.writestr("app.log", "\n".join(ring.lines))
            for kind in ("chat", "embed"):
                z.writestr(f"llama-{kind}.log", "\n".join(LlamaServers.tail(kind, 300)))
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="nursebot-diagnostic.zip")

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
