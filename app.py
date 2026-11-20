"""Entry point: starts the local admin GUI (and the bot, if configured). No console needed.

    python app.py            open the GUI in a native window if pywebview is installed, else the browser
    python app.py --browser  force the browser
    python app.py --verbose  debug logging
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import webbrowser

from werkzeug.serving import make_server

from nursebot import paths
from nursebot.db import DB
from nursebot.migrate import migrate_memory
from nursebot.runtime import Runtime
from nursebot.web.admin import RingHandler, create_admin_app


def setup_logging(verbose: bool) -> RingHandler:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
    ring = RingHandler()
    ring.setFormatter(fmt)
    fileh = logging.handlers.RotatingFileHandler(paths.DATA_DIR / "bot.log", maxBytes=2_000_000, backupCount=3,
                                                 encoding="utf-8")
    fileh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(ring)
    root.addHandler(fileh)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return ring


def main() -> int:
    paths.ensure_dirs()
    ring = setup_logging("--verbose" in sys.argv)
    db = DB(paths.DATA_DIR / "nursebot.db")
    rt = Runtime(db)
    rt.settings.import_env(paths.APP_DIR / ".env")   # old deployments keep their LINE credentials
    migrate_memory(db, paths.APP_DIR / "memory_data")  # old per-user txt files -> SQLite (once)

    quit_event = threading.Event()
    port = rt.settings.int("ui_port")
    server = make_server("127.0.0.1", port, create_admin_app(rt, ring, quit_event.set), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True, name="admin").start()
    url = f"http://127.0.0.1:{port}/"
    logging.getLogger("app").info("admin GUI: %s", url)

    if rt.settings.bool("autostart") and rt.settings.line_ready():
        threading.Thread(target=rt.start, daemon=True, name="autostart").start()

    window = None
    if "--browser" not in sys.argv:
        try:
            import webview  # optional: pip install pywebview
            window = webview
        except ImportError:
            window = None
    try:
        if window:
            window.create_window("產前衛教機器人", url, width=1120, height=800)
            window.start()  # blocks until the window is closed
        else:
            webbrowser.open(url)
            quit_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        rt.stop()
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
