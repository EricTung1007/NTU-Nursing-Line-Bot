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
import shutil
import socket
from datetime import datetime
from pathlib import Path
import sys

sys.path.append(os.path.dirname(__file__))

from prompts import fields_examples, fields_system_prompt, greet_message, no_data_reply
from RAG_module import query_with_context, build_augmented_prompt
from memory_module import (
    append_to_memory, read_memory, update_memory_gp, get_memory_file_path,
    LLM_extract_from_text, mark_memory_failed, update_memory_weeks, update_memory_isdad, update_memory_name
)
from config import (
    CHAT_ENDPOINT, CHAT_MODEL, CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET,
    APP_DIR, EMBEDDING_MODEL, FLASK_HOST, FLASK_LOCAL_URL, FLASK_PORT, LM_STUDIO_HOST, RESOURCE_DIR,
    COMPLETIONS_ENDPOINT,
    LINE_WEBHOOK_ENDPOINT, LINE_WEBHOOK_TEST_ENDPOINT, LINE_PUSH_ENDPOINT, LINE_REPLY_ENDPOINT,
    LINE_ADMIN_USER_ID, NOTIFY_USER_IDS
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("LB")

app = Flask(__name__)
_last_webhook_post_at = None

EMERGENCY_REPLY = (
    "您描述的狀況可能需要立即處理，請立刻聯絡醫院或直接就醫。\n"
    "台大醫院總機：(02) 2312-3456\n"
    "產房分機：270908、270909\n"
    "若有大量出血、劇烈腹痛、破水、胎動明顯減少或停止、昏倒、抽搐、呼吸困難、胸痛，請不要等待 LINE 回覆，請立即撥打醫院電話或 119。"
)

EMERGENCY_KEYWORDS = (
    "大量出血", "一直流血", "血流不停", "劇烈腹痛", "很痛", "痛到受不了",
    "規則宮縮", "破水", "羊水", "胎動變少", "胎動減少", "沒有胎動", "胎動停止",
    "昏倒", "暈倒", "抽搐", "呼吸困難", "喘不過氣", "胸痛", "嚴重頭痛",
    "視力模糊", "高燒", "發燒不退", "意識不清", "想吐又頭痛"
)

# Silence Flask/Werkzeug request logs by default
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def diag_ok(message):
    logger.info("[DIAG OK] %s", message)


def diag_warn(message):
    logger.warning("[DIAG] %s", message)


def diag_error(message):
    logger.error("[DIAG] %s", message)


def has_real_line_access_token():
    token = (CHANNEL_ACCESS_TOKEN or "").strip()
    return bool(token) and token != "your_channel_access_token_here"


def has_real_line_channel_secret():
    secret = (CHANNEL_SECRET or "").strip()
    return bool(secret) and secret != "your_channel_secret_here"


def is_emergency_message(text):
    return any(keyword in text for keyword in EMERGENCY_KEYWORDS)


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
        diag_error(
            "Reply to LINE failed. The webhook reached this bot, but LINE rejected the reply. "
            "Check channel access token, channel mismatch, and whether the reply token expired."
        )


def clean_model_reply(text):
    """Remove reasoning traces that some local reasoning models leak into content."""
    if not text:
        return ""

    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    draft_match = re.search(r"(?is)\*+\s*Draft\s+\d+\s*:\*+\s*(.*?)(?=\n\s*\*+\s*(?:Count|Critique|Wait)\b|\Z)", text)
    if draft_match:
        text = draft_match.group(1).strip()
    text = re.sub(r"(?is)^Thinking Process:\s*.*?(?=\n\s*(?:答案|回答|建議|您|你|太太|老婆|胎位|可以|如果|請|目前|一般|資料來源|[-•*]?\s*\*\*)|\Z)", "", text).strip()

    markers = [
        "Final Answer:",
        "Final answer:",
        "Answer:",
        "回答：",
        "答案：",
        "建議：",
    ]
    for marker in markers:
        if marker in text:
            text = text.split(marker, 1)[1].strip()

    # If only an English reasoning fragment remains, avoid sending it to users.
    if re.match(r"(?is)^[-* ]*(Role|Constraint|Content Focus|User Data|Conflict Resolution|Safety Check|Extract|Drafting|Refining|Analyze|Analysis|Need to|We need|The reference|Data Insufficient)\b", text):
        return ""

    return text


# ---------------------------------------------------------------------------
# Core event handler
# ---------------------------------------------------------------------------
def handle_event(event):
    event_type = event.get("type")
    source = event.get("source", {})
    message = event.get("message", {})
    user_id_for_log = source.get("userId", "unknown")
    logger.info(
        "LINE event received: type=%s user=%s message_type=%s",
        event_type,
        user_id_for_log,
        message.get("type", "-"),
    )

    if not (event.get("type") == "message" and event["message"].get("type") == "text"):
        logger.info("LINE event ignored: unsupported event/message type")
        diag_warn("LINE event reached the bot but was ignored because it was not a text message.")
        return

    user_id = event["source"]["userId"]
    user_text = event["message"]["text"]
    reply_token = event["replyToken"]
    logger.info("LINE text from %s: %s", user_id, user_text)
    diag_ok("LINE text message reached the bot; forwarding it through memory/RAG/LM Studio.")

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

    if is_emergency_message(user_text):
        diag_warn("Emergency-like LINE message detected. Sending hospital phone guidance without waiting for RAG.")
        send_reply(reply_token, EMERGENCY_REPLY, user_id)
        return "OK"

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
        # Pass the strict zero-shot extraction prompt directly
        system_prompt = fields_system_prompt

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
            mark_memory_failed(user_id)
            generated_text = no_data_reply
        else:
            if "prompt" in finaljson:
                response = requests.post(
                    COMPLETIONS_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json=finaljson,
                    timeout=120
                )
                lm_response = response.json()
                generated_text = clean_model_reply((lm_response["choices"][0].get("text") or "").strip())
            else:
                response = requests.post(
                    CHAT_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json=finaljson,
                    timeout=120
                )
                lm_response = response.json()
                msg = lm_response["choices"][0]["message"]
                generated_text = clean_model_reply((msg.get("content") or "").strip())
                # Fallback for thinking/reasoning models
                if not generated_text:
                    generated_text = clean_model_reply((msg.get("reasoning_content") or "").strip())

            if not generated_text:
                mark_memory_failed(user_id)
                generated_text = "❌ 模型未產生回應，請稍後再試。"
            if source_summary:
                generated_text += f"\n資料來源: {source_summary}"

    except Exception as e:
        mark_memory_failed(user_id)
        logger.error("LM Studio request error: %s", e)
        diag_error(
            "LM Studio/RAG failed after a LINE message was received. Run TEST_LM_STUDIO.bat and confirm "
            "both embedding and chat endpoint tests pass."
        )

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
                diag_error(
                    "LM Studio retry failed too. Most likely causes: LM Studio server stopped, model unloaded, "
                    "CHAT_MODEL/EMBEDDING_MODEL mismatch, or request timeout."
                )
                generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"
        else:
            generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"

    send_reply(reply_token, generated_text, user_id)
    return "OK"


# ---------------------------------------------------------------------------
# Flask webhook route
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health_root():
    return "NTU Nursing LINE Bot is running"


@app.route("/callback", methods=["GET"])
def callback_health():
    return "LINE webhook endpoint is running. LINE sends POST requests here."


@app.route("/callback", methods=["POST"])
def callback():
    global _last_webhook_post_at
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    _last_webhook_post_at = time.time()
    logger.info(
        "Webhook POST received: remote=%s bytes=%d signature_present=%s",
        request.remote_addr,
        len(body.encode("utf-8")),
        bool(signature),
    )

    if not validate_signature(body, signature):
        logger.error(
            "Invalid LINE signature. Check LINE_CHANNEL_SECRET and make sure you are messaging the same LINE channel as this .env."
        )
        diag_error(
            "LINE reached this bot, but signature validation failed. Most likely: LINE_CHANNEL_SECRET is wrong "
            "or you are messaging a different LINE bot/channel than the one in .env."
        )
        abort(400)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.exception("Webhook body is not valid JSON: %s", body[:500])
        diag_error("LINE reached this bot, but the webhook body was not valid JSON.")
        abort(400)

    events = data.get("events", [])
    logger.info("Webhook signature OK; events=%d", len(events))
    diag_ok("LINE webhook reached this bot and signature validation passed.")
    if not events:
        diag_warn("LINE webhook POST had zero events. This is often a LINE verify/test request, not a user message.")
    for event in events:
        handle_event(event)
    return "OK"


# ---------------------------------------------------------------------------
# LINE push message
# ---------------------------------------------------------------------------
def send_push(user_id, text):
    if not has_real_line_access_token():
        diag_warn(
            "LINE push skipped because LINE_CHANNEL_ACCESS_TOKEN is empty or still the placeholder. "
            "Edit the .env file beside NTULineBot.exe, not the .env.example file."
        )
        return

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
def find_cloudflared_path():
    cloudflared_path = shutil.which("cloudflared")
    if not cloudflared_path:
        search_dirs = [
            str(APP_DIR),
            str(RESOURCE_DIR),
            os.path.dirname(__file__),
            os.getcwd(),
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        ]
        local_names = [
            "cloudflared",
            "cloudflared.exe",
            "cloudflared-windows-amd64.exe",
        ]
        for base_dir in search_dirs:
            if not base_dir:
                continue
            for name in local_names:
                local_path = os.path.join(base_dir, name)
                if os.path.exists(local_path):
                    cloudflared_path = local_path
                    break
            if cloudflared_path:
                break

    return cloudflared_path


def run_cloudflare_tunnel():
    cloudflared_path = find_cloudflared_path()
    if not cloudflared_path:
        logger.error("cloudflared CLI not found. LINE webhook modes need cloudflared.exe beside NTULineBot.exe or bundled in _internal.")
        return None, None

    logger.info("Using cloudflared: %s", cloudflared_path)
    logger.info("Starting Cloudflare tunnel to local Flask URL: %s", FLASK_LOCAL_URL)

    proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", FLASK_LOCAL_URL],
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
            candidate = match.group(0)
            if "api.trycloudflare.com" not in candidate:
                public_url = candidate
                break

    if not public_url:
        logger.error("無法取得 Cloudflare 公網網址！")

    return public_url, proc


def update_line_webhook(public_url):
    if not has_real_line_access_token():
        diag_error(
            "Cannot update LINE webhook because LINE_CHANNEL_ACCESS_TOKEN is empty or still the placeholder. "
            "Open the .env file beside NTULineBot.exe and set LINE_CHANNEL_ACCESS_TOKEN to the long channel access token from LINE Developers."
        )
        return

    endpoint = f"{public_url}/callback"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"endpoint": endpoint}
    
    for attempt in range(1, 7):
        time.sleep(5)
        try:
            r = requests.put(
                LINE_WEBHOOK_ENDPOINT,
                headers=headers,
                data=json.dumps(payload),
                timeout=15
            )
            if r.status_code == 200:
                logger.info("Webhook 更新成功: %s", r.text)
                break
            else:
                logger.warning("Webhook 更新失敗 (嘗試 %d/6): %s %s", attempt, r.status_code, r.text)
        except Exception as e:
            logger.error("Webhook 更新發生錯誤 (嘗試 %d/6): %s", attempt, e)


# ---------------------------------------------------------------------------
# Flask runner
# ---------------------------------------------------------------------------
def check_line_webhook_endpoint(headers):
    try:
        r = requests.get(LINE_WEBHOOK_ENDPOINT, headers=headers, timeout=15)
        if r.status_code == 200:
            logger.info("Current LINE webhook setting: %s", r.text)
            diag_ok("Read LINE webhook setting successfully. Confirm this endpoint matches the Cloudflare URL printed above.")
        else:
            logger.warning("Could not read LINE webhook setting: %s %s", r.status_code, r.text)
            diag_warn("Could not read LINE webhook setting. Check channel access token permissions.")
    except Exception as e:
        logger.warning("Could not read LINE webhook setting: %s", e)
        diag_warn("Could not read LINE webhook setting. Network or LINE API access may be blocked.")


def test_line_webhook_endpoint(headers, endpoint):
    payload = {"endpoint": endpoint}
    for attempt in range(1, 7):
        time.sleep(2)
        try:
            r = requests.post(
                LINE_WEBHOOK_TEST_ENDPOINT,
                headers=headers,
                data=json.dumps(payload),
                timeout=15,
            )
            if r.status_code == 200:
                logger.info("LINE webhook test result: %s", r.text)
                diag_ok("LINE webhook test API passed. If user messages still do not arrive, check that you are chatting with this exact LINE bot.")
                return True

            logger.warning(
                "LINE webhook test failed (attempt %d/6): %s %s",
                attempt,
                r.status_code,
                r.text,
            )
            diag_warn(
                "LINE webhook test failed. Most likely: Cloudflare URL is not reachable yet, /callback is not reachable, "
                "or LINE rejected the temporary tunnel URL. The bot will retry."
            )
        except Exception as e:
            logger.warning("LINE webhook test error (attempt %d/6): %s", attempt, e)
            diag_warn("LINE webhook test could not contact LINE or the tunnel. Check internet/firewall/Cloudflare tunnel.")

    logger.error("LINE webhook test did not pass. Messages from LINE may not reach this bot.")
    diag_error("Webhook update may be saved, but LINE cannot verify delivery. User messages probably will not reach LM Studio.")
    return False


def update_line_webhook(public_url):
    endpoint = f"{public_url}/callback"
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"endpoint": endpoint}

    for attempt in range(1, 7):
        time.sleep(5)
        try:
            r = requests.put(
                LINE_WEBHOOK_ENDPOINT,
                headers=headers,
                data=json.dumps(payload),
                timeout=15,
            )
            if r.status_code == 200:
                logger.info("Webhook updated successfully: %s", r.text)
                diag_ok("LINE webhook endpoint was updated to the current Cloudflare /callback URL.")
                check_line_webhook_endpoint(headers)
                test_line_webhook_endpoint(headers, endpoint)
                return

            logger.warning("Webhook update failed (attempt %d/6): %s %s", attempt, r.status_code, r.text)
            diag_warn(
                "LINE rejected the webhook endpoint update. Check LINE token, Cloudflare URL format, and whether the tunnel is ready."
            )
        except Exception as e:
            logger.error("Webhook update error (attempt %d/6): %s", attempt, e)
            diag_warn("Webhook update request failed. Check network access to LINE API.")


def run_flask():
    for notify_user_id in NOTIFY_USER_IDS:
        send_push(notify_user_id, f"[後臺訊息]LINE Bot 已啟動（{datetime.now()})")

    threading.Thread(target=webhook_inactivity_watchdog, daemon=True).start()
    logger.info("Flask webhook server port: %s", FLASK_PORT)
    logger.info("Flask webhook local URL: http://127.0.0.1:%s/callback", FLASK_PORT)
    logger.info("Flask bind address: %s:%s", FLASK_HOST, FLASK_PORT)
    app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True)


def webhook_inactivity_watchdog():
    time.sleep(90)
    if _last_webhook_post_at is None:
        diag_warn(
            "No LINE webhook POST has reached this bot in the first 90 seconds. "
            "If you already sent a LINE message, likely causes are: wrong webhook URL in LINE console, "
            "messaging a different bot, Cloudflare tunnel not reachable, or LINE webhook delivery disabled."
        )


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------
def print_model_usage(loaded_models=None):
    loaded_models = loaded_models or []
    chat_match = _match_loaded_model(CHAT_MODEL, loaded_models)
    embedding_match = _match_loaded_model(EMBEDDING_MODEL, loaded_models)

    print("")
    print("Model configuration:")
    print(f"  Chat model:      {CHAT_MODEL}")
    if chat_match and chat_match != CHAT_MODEL:
        print(f"  Chat loaded as:  {chat_match}")
    print(f"  Embedding model: {EMBEDDING_MODEL}")
    if embedding_match and embedding_match != EMBEDDING_MODEL:
        print(f"  Embedding loaded as: {embedding_match}")
    print("")


def run_cli():
    path = get_memory_file_path("CLI")
    if os.path.exists(path):
        os.remove(path)
    print_model_usage(_get_loaded_models() or [])
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


def _match_loaded_model(model_id, loaded_models):
    """Return the loaded LM Studio model ID that matches a configured model."""
    if not model_id or not loaded_models:
        return None
    if model_id in loaded_models:
        return model_id

    model_id_lower = model_id.lower()
    for loaded_model in loaded_models:
        if model_id_lower == loaded_model.lower():
            return loaded_model

    for loaded_model in loaded_models:
        if model_id_lower in loaded_model.lower():
            return loaded_model

    return None


def _is_port_available(host, port):
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


def _doctor_line(status, label, detail):
    print(f"[{status}] {label}: {detail}")


def ensure_editable_env_file():
    env_path = Path(APP_DIR) / ".env"
    if env_path.exists():
        return env_path, False, "existing"

    candidates = [
        Path(APP_DIR) / ".env.example",
        Path(RESOURCE_DIR) / ".env.example",
    ]
    for template in candidates:
        if template.exists():
            shutil.copyfile(template, env_path)
            return env_path, True, f"created from {template}"

    env_path.write_text(
        "\n".join(
            [
                "# LINE Bot Credentials",
                "LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token_here",
                "LINE_CHANNEL_SECRET=your_channel_secret_here",
                "LINE_ADMIN_USER_ID=",
                "LINE_NOTIFY_USER_IDS=",
                "LINE_ACTIVE_USER_IDS=",
                "",
                "# LM Studio",
                "LM_STUDIO_HOST=http://127.0.0.1:1234",
                "EMBEDDING_MODEL=text-embedding-bge-small-zh-v1.5",
                "CHAT_MODEL=your_loaded_chat_model_id_here",
                "CHAT_MODEL_KEY=",
                "",
                "# Webhook server",
                "FLASK_PORT=5001",
                "FLASK_HOST=0.0.0.0",
                "FLASK_TUNNEL_HOST=127.0.0.1",
                "",
                "# Locked-down computers may need manual LM Studio setup",
                "LM_STUDIO_AUTO_START=false",
                "LM_STUDIO_AUTO_LOAD_MODELS=false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return env_path, True, "created from built-in fallback"


def run_deployment_doctor():
    """Print actionable deployment diagnostics for non-developer operators."""
    print("")
    print("=== NTU Nursing LINE Bot Deployment Diagnostics ===")
    print("")

    env_path, created_env, env_source = ensure_editable_env_file()
    if env_path.exists():
        status = "WARN" if created_env else "PASS"
        _doctor_line(status, ".env file", f"{env_path} ({env_source})")
        if created_env:
            _doctor_line("WARN", ".env reload", "Edit .env, save it, then restart this exe so the new values are loaded.")
    else:
        _doctor_line("FAIL", ".env file", f"Missing at {env_path}. Copy .env.example to .env and fill the LINE/model settings.")

    if has_real_line_access_token():
        _doctor_line("PASS", "LINE access token", "Looks filled, not the placeholder.")
    else:
        _doctor_line("FAIL", "LINE access token", "Set LINE_CHANNEL_ACCESS_TOKEN in .env.")

    if has_real_line_channel_secret():
        _doctor_line("PASS", "LINE channel secret", "Looks filled, not the placeholder.")
    else:
        _doctor_line("FAIL", "LINE channel secret", "Set LINE_CHANNEL_SECRET in .env from the same LINE channel.")

    _doctor_line("INFO", "Flask port", str(FLASK_PORT))
    _doctor_line("INFO", "Local callback URL", f"http://127.0.0.1:{FLASK_PORT}/callback")
    if _is_port_available(FLASK_HOST, FLASK_PORT):
        _doctor_line("PASS", "Flask port availability", "Port is free before starting the bot.")
    else:
        _doctor_line("FAIL", "Flask port availability", f"Port {FLASK_PORT} is already in use. Edit .env and set FLASK_PORT=5050, then restart.")

    cloudflared_path = find_cloudflared_path()
    if cloudflared_path:
        _doctor_line("PASS", "cloudflared", cloudflared_path)
    else:
        _doctor_line("FAIL", "cloudflared", "Missing. Copy cloudflared.exe beside NTULineBot.exe or use NTULineBot-windows-deploy.zip.")

    loaded = _get_loaded_models()
    if loaded:
        _doctor_line("PASS", "LM Studio API", "Responded with loaded models.")
        chat_match = _match_loaded_model(CHAT_MODEL, loaded)
        embed_match = _match_loaded_model(EMBEDDING_MODEL, loaded)
        if chat_match:
            _doctor_line("PASS", "Chat model", chat_match)
        else:
            _doctor_line("FAIL", "Chat model", f"{CHAT_MODEL} is not loaded. Load it in LM Studio or fix CHAT_MODEL in .env.")
        if embed_match:
            _doctor_line("PASS", "Embedding model", embed_match)
        else:
            _doctor_line("FAIL", "Embedding model", f"{EMBEDDING_MODEL} is not loaded. Load it in LM Studio or fix EMBEDDING_MODEL in .env.")
    else:
        _doctor_line("FAIL", "LM Studio API", f"No response from {LM_STUDIO_HOST}. Start LM Studio local server and load the models.")

    if has_real_line_access_token():
        headers = {
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.get(LINE_WEBHOOK_ENDPOINT, headers=headers, timeout=15)
            if r.status_code == 200:
                current = r.json().get("endpoint") or ""
                if current:
                    _doctor_line("PASS", "LINE saved webhook", current)
                    try:
                        test = requests.post(
                            LINE_WEBHOOK_TEST_ENDPOINT,
                            headers=headers,
                            data=json.dumps({"endpoint": current}),
                            timeout=15,
                        )
                        body = test.json()
                        if body.get("success") is True:
                            _doctor_line("PASS", "LINE webhook delivery test", "LINE can reach the saved webhook URL.")
                        else:
                            _doctor_line(
                                "FAIL",
                                "LINE webhook delivery test",
                                f"LINE could not reach the saved URL. statusCode={body.get('statusCode')} detail={body.get('detail')}. Restart mode 2 to create/update the tunnel.",
                            )
                    except Exception as e:
                        _doctor_line("FAIL", "LINE webhook delivery test", f"Could not run test: {e}")
                else:
                    _doctor_line("FAIL", "LINE saved webhook", "No endpoint is saved in LINE Developers. Run mode 2.")
            else:
                _doctor_line("FAIL", "LINE saved webhook", f"LINE API returned {r.status_code}: {r.text}")
        except Exception as e:
            _doctor_line("FAIL", "LINE API access", f"Could not contact LINE API: {e}")
    else:
        _doctor_line("SKIP", "LINE webhook API checks", "No valid LINE_CHANNEL_ACCESS_TOKEN.")

    print("")
    print("How to fix the common offline-message problem:")
    print("1. If cloudflared is FAIL, use the packaged deploy zip or copy cloudflared.exe beside NTULineBot.exe.")
    print("2. If Flask port is FAIL, set FLASK_PORT=5050 in .env and restart.")
    print("3. If LINE webhook delivery test is FAIL, run mode 2. Confirm the printed public_url matches the LINE saved webhook.")
    print("4. If the bot can push an online message but cannot receive your message, focus on cloudflared/webhook delivery, not LM Studio.")
    print("")
    print("Config variables available in .env:")
    print("- LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET")
    print("- LINE_NOTIFY_USER_IDS, LINE_ACTIVE_USER_IDS, LINE_ADMIN_USER_ID")
    print("- FLASK_PORT, FLASK_HOST, FLASK_TUNNEL_HOST")
    print("- LM_STUDIO_HOST, EMBEDDING_MODEL, CHAT_MODEL, CHAT_MODEL_KEY")
    print("- LM_STUDIO_AUTO_START, LM_STUDIO_AUTO_LOAD_MODELS")
    print("")


def _ensure_models_loaded():
    """Check if required models are loaded, auto-load if not."""
    from config import (
        EMBEDDING_MODEL,
        CHAT_MODEL,
        LM_STUDIO_AUTO_LOAD_MODELS,
        LM_STUDIO_AUTO_START,
    )

    # CHAT_MODEL_KEY is the path/key for lms load; falls back to CHAT_MODEL
    try:
        from config import CHAT_MODEL_KEY
    except ImportError:
        CHAT_MODEL_KEY = CHAT_MODEL

    loaded = _get_loaded_models()
    if loaded is None:
        if not LM_STUDIO_AUTO_START:
            logger.error("LM Studio API is not reachable. Start LM Studio server manually, then retry.")
            return False

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
    embed_match = _match_loaded_model(EMBEDDING_MODEL, loaded)
    if not embed_match:
        if not LM_STUDIO_AUTO_LOAD_MODELS:
            logger.error("Embedding model '%s' is not loaded in LM Studio.", EMBEDDING_MODEL)
            return False
        logger.info("📦 Embedding model '%s' not loaded — loading...", EMBEDDING_MODEL)
        if not _lms_load(EMBEDDING_MODEL, identifier=EMBEDDING_MODEL):
            return False
        time.sleep(2)  # Brief wait for model to register in API

    # Check chat model
    chat_match = _match_loaded_model(CHAT_MODEL, loaded)
    if not chat_match:
        if not LM_STUDIO_AUTO_LOAD_MODELS:
            logger.error("Chat model '%s' is not loaded in LM Studio.", CHAT_MODEL)
            return False
        logger.info("📦 Chat model '%s' not loaded — loading via key '%s'...", CHAT_MODEL, CHAT_MODEL_KEY)
        if not _lms_load(CHAT_MODEL_KEY, identifier=CHAT_MODEL):
            return False
        time.sleep(2)

    # Final verification
    loaded = _get_loaded_models()
    if loaded:
        logger.info("Using chat model: %s", CHAT_MODEL)
        logger.info("Using embedding model: %s", EMBEDDING_MODEL)
        logger.info("Loaded models: %s", loaded)
    return True


def startup_check():
    """Verify critical dependencies before starting."""
    ok = True

    logger.info("Using chat model: %s", CHAT_MODEL)
    logger.info("Using embedding model: %s", EMBEDDING_MODEL)
    logger.info("Using Flask webhook port: %s", FLASK_PORT)
    logger.info("Local webhook health URL: http://127.0.0.1:%s/callback", FLASK_PORT)

    cloudflared_path = find_cloudflared_path()
    if cloudflared_path:
        logger.info("Using cloudflared: %s", cloudflared_path)
    else:
        logger.warning("cloudflared.exe was not found. LINE webhook modes 2/3 cannot create a public Cloudflare URL.")
        diag_warn(
            "Copy cloudflared.exe beside NTULineBot.exe, or use the full NTULineBot-windows-deploy package. "
            "If you copied only dist\\NTULineBot, cloudflared may be missing."
        )

    # Check .env credentials
    if not has_real_line_access_token():
        logger.warning("LINE_CHANNEL_ACCESS_TOKEN is empty or placeholder — LINE webhook/push won't work (CLI is fine)")
        diag_warn("Edit .env beside NTULineBot.exe and fill LINE_CHANNEL_ACCESS_TOKEN. Do not edit only .env.example.")
    if not has_real_line_channel_secret():
        logger.warning("LINE_CHANNEL_SECRET is empty or placeholder — signature validation will fail")
        diag_warn("Edit .env beside NTULineBot.exe and fill LINE_CHANNEL_SECRET from the same LINE Messaging API channel.")

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

    if argv:
        mode = argv[0]
    else:
        mode = input("請選擇模式：1=CLI測試，2=Flask webhook，3=同時執行，5=Deployment diagnostics：")

    if mode in ("5", "doctor", "diagnose", "diagnostics", "check"):
        run_deployment_doctor()
        raise SystemExit(0)

    # Startup health check
    startup_check()

    if mode in ("1", "cli", "CLI"):
        run_cli()

    elif mode == "2":
        public_url, tunnel_proc = run_cloudflare_tunnel()
        if public_url:
            logger.info("🌐 public_url = %s", public_url)
            threading.Thread(target=update_line_webhook, args=(public_url,), daemon=True).start()
        run_flask()
        if tunnel_proc:
            tunnel_proc.kill()

    elif mode == "3":
        public_url, tunnel_proc = run_cloudflare_tunnel()
        if public_url:
            threading.Thread(target=update_line_webhook, args=(public_url,), daemon=True).start()

        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        time.sleep(1)

        cli_thread = threading.Thread(target=run_cli)
        cli_thread.start()
        cli_thread.join()

        if tunnel_proc:
            tunnel_proc.kill()

    else:
        print("❌ 無效選項")
