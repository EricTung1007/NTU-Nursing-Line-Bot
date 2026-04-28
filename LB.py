# LB.py
from flask import Flask, request, abort
import requests
import hmac
import hashlib
import base64
import json
import re
import threading
import os
import time
import logging
import subprocess
from datetime import datetime
import sys

sys.path.append(os.path.dirname(__file__))

from prompts import fields_examples, fields_system_prompt, greet_message, no_data_reply
from RAG_module import query_with_context, build_augmented_prompt
from memory_module import (
    append_to_memory, read_memory, update_memory_gp, get_memory_file_path,
    LLM_extract_from_text, update_memory_weeks, update_memory_isdad, update_memory_name
)
from config import (
    CHAT_ENDPOINT, CHAT_MODEL, CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET,
    LINE_WEBHOOK_ENDPOINT, LINE_PUSH_ENDPOINT, LINE_REPLY_ENDPOINT,
    LINE_ADMIN_USER_ID, NOTIFY_USER_IDS
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("LB")

app = Flask(__name__)

# Silence Flask/Werkzeug request logs by default
logging.getLogger("werkzeug").setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# LINE signature validation
# ---------------------------------------------------------------------------
def validate_signature(body, signature):
    hash = hmac.new(
        CHANNEL_SECRET.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash).decode()
    return hmac.compare_digest(expected_signature, signature)


# ---------------------------------------------------------------------------
# Send reply (LINE or CLI)
# ---------------------------------------------------------------------------
def send_reply(reply_token, text, user_id=None):
    if user_id:
        append_to_memory(user_id, f"Bot: {text}")

    if reply_token == "CLI_TOKEN":
        print("\nBot：" + text)
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    response = requests.post(
        LINE_REPLY_ENDPOINT,
        headers=headers,
        data=json.dumps(payload),
        timeout=15
    )
    if response.status_code != 200:
        logger.error("LINE API Error: %s %s", response.status_code, response.text)


# ---------------------------------------------------------------------------
# Core event handler
# ---------------------------------------------------------------------------
def handle_event(event):
    if not (event.get("type") == "message" and event["message"].get("type") == "text"):
        return

    user_id = event["source"]["userId"]
    user_text = event["message"]["text"]
    reply_token = event["replyToken"]

    # --- Correction commands (更正) ---
    if user_text.startswith("更正"):
        correction = user_text.replace("更正", "", 1).strip()
        memory_file = get_memory_file_path(user_id)

        if re.match(r"^G\(\d*\)P\(\d*\)W\(\d*\)IsDad\((True|False)?\)Name\((.*?)\)$", correction):
            # Full profile correction
            lines = read_memory(user_id).splitlines()
            lines[0] = correction
            with open(memory_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            send_reply(reply_token, f"✅ 已更正整行資料為：\n{correction}", user_id)
            return "OK"

        elif re.match(r"^G\(\d+\)P\(\d+\)$", correction):
            update_memory_gp(user_id, correction)
            send_reply(reply_token, f"✅ 已更新 G/P 為：{correction}", user_id)
            return "OK"

        elif re.match(r"^W\(\d+\)$", correction):
            week_value = int(re.search(r"W\((\d+)\)", correction).group(1))
            update_memory_weeks(user_id, week_value)
            send_reply(reply_token, f"✅ 已更新週數 W 為：{week_value}", user_id)
            return "OK"

        elif re.match(r"^IsDad\((True|False)\)$", correction):
            isdad_value = correction == "IsDad(True)"
            update_memory_isdad(user_id, isdad_value)
            send_reply(reply_token, f"✅ 已更新 IsDad 為：{isdad_value}", user_id)
            return "OK"

        elif re.match(r"^Name\((.*?)\)$", correction):
            name_value = re.search(r"Name\((.*?)\)", correction).group(1)
            update_memory_name(user_id, name_value)
            send_reply(reply_token, f"✅ 已更新名字 Name 為：{name_value}", user_id)
            return "OK"

        else:
            send_reply(reply_token, "❌ 格式錯誤。\n請使用以下格式：\n"
                                    "G(數字)P(數字)\n"
                                    "W(數字)\n"
                                    "IsDad(True|False)\n"
                                    "Name(名字)\n"
                                    "或整行：G()P()W()IsDad()Name()", user_id)
            return "OK"

    # --- Save message to memory ---
    append_to_memory(user_id, f"User: {user_text}")

    # --- Read user profile (first line of memory file) ---
    memory_content = read_memory(user_id)
    first_line = memory_content.splitlines()[0] if memory_content else ""

    field_patterns = {
        "G/P": r"G\(\d+\)\s*P\(\d+\)",
        "W": r"W\(\d+\)",
        "IsDad": r"IsDad\((True|False|1|0)\)",
        "Name": r"Name\((.*?)\)"
    }
    field_descriptions = {
        "G/P": "孕產史（例如：我懷過1胎，生過0胎）",
        "W": "目前週數（例如：目前5週）",
        "IsDad": "您是否為父親（請回答：我是父親/不是父親）",
        "Name": "您的名字（例如：小美）"
    }

    missing_fields = []

    for field, pattern in field_patterns.items():
        match = re.search(pattern, first_line)

        if field == "Name":
            if match:
                try:
                    name_inner = match.group(1).strip()
                    if name_inner == "":
                        missing_fields.append("Name")
                except IndexError:
                    missing_fields.append("Name")
            else:
                missing_fields.append("Name")
        else:
            if not match:
                missing_fields.append(field)

    if missing_fields:
        system_prompt = (
            f"已知欄位：{first_line.strip()}。\n"
            f"請從以下文字補充缺失欄位：{', '.join(missing_fields)}。\n"
            f"{fields_system_prompt}\n"
            f"{fields_examples}"
        )

        # Call LLM to extract missing fields
        extracted_value = LLM_extract_from_text(user_text, system_prompt)
        logger.debug("LLM 回傳: %s", extracted_value)

        # Update memory with extracted fields
        if extracted_value:
            if re.search(r"G\(\d+\)\s*P\(\d+\)", extracted_value):
                update_memory_gp(user_id, re.search(r"G\(\d+\)\s*P\(\d+\)", extracted_value).group(0))
            if re.search(r"W\(\d+\)", extracted_value):
                update_memory_weeks(user_id, int(re.search(r"W\((\d+)\)", extracted_value).group(1)))
            if re.search(r"IsDad\((True|False|1|0)\)", extracted_value):
                isdad_raw = re.search(r"IsDad\((True|False|1|0)\)", extracted_value).group(1)
                isdad_value = isdad_raw in ["True", "1"]
                update_memory_isdad(user_id, isdad_value)
            if re.search(r"Name\((.*?)\)", extracted_value):
                name_value = re.search(r"Name\((.*?)\)", extracted_value).group(1).strip()
                if name_value.lower() not in ["unknown", "none", ""]:
                    update_memory_name(user_id, name_value)

        # Re-check if fields are still missing
        memory_content = read_memory(user_id)
        first_line = memory_content.splitlines()[0] if memory_content else ""
        still_missing = [field for field, pattern in field_patterns.items() if not re.search(pattern, first_line)]

        if still_missing:
            prompt = "\n您好，請提供以下資訊：\n"
            for f in missing_fields:
                if f in field_descriptions:
                    prompt += f"🔸{field_descriptions[f]}\n"
                else:
                    logger.warning("無法為欄位 %s 提示描述", f)
                    prompt += f"🔸請補上欄位：{f}\n"

            send_reply(reply_token, prompt, user_id)
            return "OK"
        else:
            # All fields collected — send summary
            gp_match = re.search(r"G\((\d+)\)P\((\d+)\)", first_line)
            w_match = re.search(r"W\((\d+)\)", first_line)
            isdad_match = re.search(r"IsDad\((True|False)\)", first_line)
            name_match = re.search(r"Name\((.*?)\)", first_line)

            g_value = int(gp_match.group(1)) if gp_match else 0
            p_value = int(gp_match.group(2)) if gp_match else 0
            week_value = int(w_match.group(1)) if w_match else None
            isdad_value = (
                "準爸爸" if isdad_match and isdad_match.group(1) == "True"
                else "準媽媽" if isdad_match and isdad_match.group(1) == "False"
                else "未知身份"
            )
            name_value = name_match.group(1) if name_match else "未提供"

            summary_text = f"✅ 已儲存您的資料：您是{isdad_value}，"
            summary_text += f"產婦曾懷胎{g_value}次，曾產{p_value}胎，"
            if week_value:
                summary_text += f"目前懷胎{week_value}週，"
            summary_text += f"登記名字是{name_value}。"

            send_reply(reply_token, summary_text + "\n您可以開始提問囉～", user_id)
            return "OK"

    # --- All fields present — normal RAG conversation ---
    entries = re.split(r'(?=User:\s)', memory_content)
    entries = [e.strip() for e in entries if e.strip()]
    history_text = "\n\n".join(entries[-10:])

    gp_match = re.search(r"G\((\d+)\)P\((\d+)\)", first_line)
    week_match = re.search(r"W\((\d+)\)", first_line)
    isdad_match = re.search(r"IsDad\((True|False)\)", first_line)
    g_value = int(gp_match.group(1)) if gp_match else 0
    p_value = int(gp_match.group(2)) if gp_match else 0
    week_value = int(week_match.group(1)) if week_match else 0
    isdad_value = True if isdad_match and isdad_match.group(1) == "True" else False

    finaljson = None  # Guard against NameError in except block
    try:
        contexts = query_with_context(user_text, 5)
        finaljson, source_summary = build_augmented_prompt(
            contexts,
            user_question=user_text,
            modelname=CHAT_MODEL,
            g_value=g_value,
            p_value=p_value,
            history_text=history_text,
            week_value=week_value,
            isdad=isdad_value
        )

        if finaljson is None:
            generated_text = no_data_reply
        else:
            response = requests.post(
                CHAT_ENDPOINT,
                headers={"Content-Type": "application/json"},
                json=finaljson,
                timeout=120
            )
            lm_response = response.json()
            msg = lm_response["choices"][0]["message"]
            generated_text = (msg.get("content") or "").strip()
            # Fallback for thinking/reasoning models
            if not generated_text:
                generated_text = (msg.get("reasoning_content") or "").strip()
            if not generated_text:
                generated_text = "❌ 模型未產生回應，請稍後再試。"
            if source_summary:
                generated_text += f"\n資料來源: {source_summary}"

    except Exception as e:
        logger.error("LM Studio request error: %s", e)

        if finaljson is not None:
            logger.debug("CHAT_ENDPOINT=%s", CHAT_ENDPOINT)
            logger.debug("FinalJson=%s", json.dumps(finaljson, ensure_ascii=False)[:2000])
            try:
                r = requests.post(
                    CHAT_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json=finaljson,
                    timeout=30
                )
                logger.debug("Retry Status=%s", r.status_code)
                logger.debug("Retry Body=%s", r.text[:2000])
                r.raise_for_status()
                lm_response = r.json()
                generated_text = lm_response["choices"][0]["message"]["content"].strip()
            except Exception as retry_err:
                logger.error("LM Studio retry also failed: %s", repr(retry_err))
                generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"
        else:
            generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"

    send_reply(reply_token, generated_text, user_id)
    return "OK"


# ---------------------------------------------------------------------------
# Flask webhook route
# ---------------------------------------------------------------------------
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    if not validate_signature(body, signature):
        logger.error("Invalid signature")
        abort(400)

    data = json.loads(body)

    for event in data.get("events", []):
        handle_event(event)
    return "OK"


# ---------------------------------------------------------------------------
# LINE push message
# ---------------------------------------------------------------------------
def send_push(user_id, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}]
    }
    response = requests.post(
        LINE_PUSH_ENDPOINT,
        headers=headers,
        data=json.dumps(payload),
        timeout=15
    )
    if response.status_code != 200:
        logger.error("LINE Push Error: %s %s", response.status_code, response.text)


# ---------------------------------------------------------------------------
# Cloudflare Tunnel
# ---------------------------------------------------------------------------
def run_cloudflare_tunnel():
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:5000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    public_url = None
    timeout = time.time() + 15
    while time.time() < timeout:
        line = proc.stdout.readline()
        if not line:
            break
        match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
        if match:
            public_url = match.group(0)
            break

    if not public_url:
        logger.error("無法取得 Cloudflare 公網網址！")

    return public_url, proc


def update_line_webhook(public_url):
    time.sleep(5)
    endpoint = f"{public_url}/callback"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"endpoint": endpoint}
    try:
        r = requests.put(
            LINE_WEBHOOK_ENDPOINT,
            headers=headers,
            data=json.dumps(payload),
            timeout=15
        )
        logger.info("Webhook 更新: %s %s", r.status_code, r.text)
    except Exception as e:
        logger.error("Webhook 更新失敗: %s", e)


# ---------------------------------------------------------------------------
# Flask runner
# ---------------------------------------------------------------------------
def run_flask():
    for notify_user_id in NOTIFY_USER_IDS:
        send_push(notify_user_id, f"[後臺訊息]LINE Bot 已啟動（{datetime.now()})")

    app.run(host="0.0.0.0", port=5000, threaded=True)


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------
def run_cli():
    path = get_memory_file_path("CLI")
    if os.path.exists(path):
        os.remove(path)
    print(greet_message)
    while True:
        user_input = input("你：")
        if user_input.lower() in ["exit", "quit"]:
            break
        if user_input.lower() == "restart":
            path = get_memory_file_path("CLI")
            if os.path.exists(path):
                os.remove(path)

        event = {
            "type": "message",
            "message": {"type": "text", "text": user_input},
            "source": {"userId": "CLI"},
            "replyToken": "CLI_TOKEN"
        }
        handle_event(event)


# ---------------------------------------------------------------------------
# Startup health check & model auto-loading
# ---------------------------------------------------------------------------
def _lms_load(model_key, identifier=None):
    """Load a model into LM Studio using the lms CLI."""
    from config import LMS_CLI_PATH

    lms_path = LMS_CLI_PATH
    if not os.path.exists(lms_path):
        logger.error("lms CLI not found at %s — cannot auto-load models", lms_path)
        return False

    cmd = [lms_path, "load", model_key, "-y"]
    if identifier:
        cmd.extend(["--identifier", identifier])

    logger.info("⏳ Loading model: %s ...", model_key)
    try:
        result = subprocess.run(
            cmd,
            timeout=180,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode == 0:
            logger.info("✅ Model loaded: %s", model_key)
            return True
        else:
            logger.error("❌ Failed to load model %s: %s", model_key, result.stderr or result.stdout)
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ Model load timed out for %s (180s)", model_key)
        return False
    except Exception as e:
        logger.error("❌ Failed to load model %s: %s", model_key, e)
        return False


def _get_loaded_models():
    """Query LM Studio API for currently loaded model IDs."""
    from config import MODELS_ENDPOINT
    try:
        r = requests.get(MODELS_ENDPOINT, timeout=5)
        r.raise_for_status()
        models = r.json().get("data", [])
        return [m["id"] for m in models]
    except Exception:
        return None  # Server not reachable


def _ensure_models_loaded():
    """Check if required models are loaded, auto-load if not."""
    from config import EMBEDDING_MODEL, CHAT_MODEL, LM_STUDIO_HOST

    # CHAT_MODEL_KEY is the path/key for lms load; falls back to CHAT_MODEL
    try:
        from config import CHAT_MODEL_KEY
    except ImportError:
        CHAT_MODEL_KEY = CHAT_MODEL

    loaded = _get_loaded_models()
    if loaded is None:
        # Server not reachable — try starting it
        from config import LMS_CLI_PATH
        if os.path.exists(LMS_CLI_PATH):
            logger.info("🔁 LM Studio server not reachable, trying to start...")
            subprocess.Popen(
                [LMS_CLI_PATH, "server", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Wait for server to come up
            for i in range(15):
                time.sleep(2)
                loaded = _get_loaded_models()
                if loaded is not None:
                    logger.info("✅ LM Studio server is now running")
                    break
            else:
                logger.error("❌ Could not start LM Studio server")
                return False
        else:
            logger.error("❌ LM Studio not reachable and lms CLI not found")
            return False

    # Check embedding model
    embed_loaded = any(EMBEDDING_MODEL in mid for mid in loaded)
    if not embed_loaded:
        logger.info("📦 Embedding model '%s' not loaded — loading...", EMBEDDING_MODEL)
        if not _lms_load(EMBEDDING_MODEL, identifier=EMBEDDING_MODEL):
            return False
        time.sleep(2)  # Brief wait for model to register in API

    # Check chat model
    chat_loaded = any(CHAT_MODEL in mid for mid in loaded)
    if not chat_loaded:
        logger.info("📦 Chat model '%s' not loaded — loading via key '%s'...", CHAT_MODEL, CHAT_MODEL_KEY)
        if not _lms_load(CHAT_MODEL_KEY, identifier=CHAT_MODEL):
            return False
        time.sleep(2)

    # Final verification
    loaded = _get_loaded_models()
    if loaded:
        logger.info("✅ Loaded models: %s", loaded)
    return True


def startup_check():
    """Verify critical dependencies before starting."""
    ok = True

    # Check .env credentials
    if not CHANNEL_ACCESS_TOKEN:
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN is empty — LINE webhook won't work (CLI is fine)")
    if not CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_SECRET is empty — signature validation will fail")

    # Check FAISS index
    from config import INDEX_PATH, METADATA_PATH
    if not os.path.exists(INDEX_PATH):
        logger.error("FAISS index not found at %s — run 'python prep.py' first", INDEX_PATH)
        ok = False
    if not os.path.exists(METADATA_PATH):
        logger.error("Metadata not found at %s — run 'python prep.py' first", METADATA_PATH)
        ok = False

    # Auto-load LM Studio models
    if not _ensure_models_loaded():
        logger.error("⚠️ Models could not be loaded — bot may not function correctly")
        ok = False

    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Configure logging level
    log_level = logging.DEBUG if "--verbose" in sys.argv else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )

    # Clean --verbose from argv so it doesn't interfere with mode selection
    argv = [a for a in sys.argv[1:] if a != "--verbose"]

    # Startup health check
    startup_check()

    if argv:
        mode = argv[0]
    else:
        mode = input("請選擇模式：1=CLI測試，2=Flask webhook，3=同時執行：")

    if mode in ("1", "cli", "CLI"):
        run_cli()

    elif mode == "2":
        public_url, tunnel_proc = run_cloudflare_tunnel()
        if public_url:
            logger.info("🌐 public_url = %s", public_url)
            update_line_webhook(public_url)
        run_flask()
        tunnel_proc.kill()

    elif mode == "3":
        public_url, tunnel_proc = run_cloudflare_tunnel()
        if public_url:
            update_line_webhook(public_url)

        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        time.sleep(1)

        cli_thread = threading.Thread(target=run_cli)
        cli_thread.start()
        cli_thread.join()

        tunnel_proc.kill()

    else:
        print("❌ 無效選項")
