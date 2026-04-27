# product_entry.py
import os, sys, re, time, subprocess
import LB

def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def run_cloudflare_tunnel_portable(port=5000, timeout_sec=25):
    base = exe_dir()
    cloudflared_path = os.path.join(base, "cloudflared-windows-amd64.exe")

    if not os.path.exists(cloudflared_path):
        return None, None

    proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    public_url = None
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        raw = proc.stdout.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore")
        m = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
        if m:
            candidate = m.group(0)
            if candidate != "https://api.trycloudflare.com":
                public_url = candidate
            break

    return public_url, proc

def main():
    print("請選擇模式：")
    print("1. CLI")
    print("2. Flask")
    print("3. Both")

    mode = input("> ").strip()

    if mode == "1":
        LB.run_cli()
    elif mode == "2":
        LB.run_flask()
    elif mode == "3":
        LB.run_cli()
        LB.run_flask()
    else:
        print("無效選項")

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    os.chdir(exe_dir())

    public_url, tunnel_proc = run_cloudflare_tunnel_portable(port=5000)
    # 建議保留這行，方便你確認每次網址是否更新
    print("public_url =", public_url)

    if public_url:
        update_line_webhook(public_url)

    run_flask()
