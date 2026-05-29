import logging
import os
import sys
import threading
import time

import LB


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def configure_logging():
    log_level = logging.DEBUG if "--verbose" in sys.argv else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def choose_mode():
    args = [arg for arg in sys.argv[1:] if arg != "--verbose"]
    if args:
        return args[0].strip().lower()

    print("請選擇模式：")
    print("1. CLI 測試")
    print("2. Flask webhook + Cloudflare tunnel")
    print("3. Both")
    return input("> ").strip().lower()


def main():
    os.chdir(app_dir())
    configure_logging()
    LB.startup_check()

    mode = choose_mode()
    if mode in ("1", "cli"):
        LB.run_cli()
        return

    if mode in ("2", "flask", "webhook"):
        public_url, tunnel_proc = LB.run_cloudflare_tunnel()
        if public_url:
            logging.getLogger("LB").info("Public URL: %s", public_url)
            threading.Thread(target=LB.update_line_webhook, args=(public_url,), daemon=True).start()
        try:
            LB.run_flask()
        finally:
            if tunnel_proc:
                tunnel_proc.kill()
        return

    if mode in ("3", "both"):
        public_url, tunnel_proc = LB.run_cloudflare_tunnel()
        if public_url:
            logging.getLogger("LB").info("Public URL: %s", public_url)
            threading.Thread(target=LB.update_line_webhook, args=(public_url,), daemon=True).start()

        flask_thread = threading.Thread(target=LB.run_flask, daemon=True)
        flask_thread.start()
        time.sleep(1)

        try:
            LB.run_cli()
        finally:
            if tunnel_proc:
                tunnel_proc.kill()
        return

    print("無效選項，請輸入 1、2 或 3。")


if __name__ == "__main__":
    main()
