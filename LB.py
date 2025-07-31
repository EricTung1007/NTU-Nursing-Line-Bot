#LB.py
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

from RAG_module import query_with_context, build_augmented_prompt
from memory_module import (
    append_to_memory, read_memory, update_memory_gp,get_memory_file_path,
    LLM_extract_from_text, update_memory_weeks, update_memory_isdad, update_memory_name
)
from config import CHAT_ENDPOINT, CHAT_MODEL, CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET, LINE_WEBHOOK_ENDPOINT, LINE_PUSH_ENDPOINT, LINE_REPLY_ENDPOINT, LINE_ADMIN_USER_ID

app = Flask(__name__)
'''
CHANNEL_ACCESS_TOKEN = CHANNEL_ACCESS_TOKEN #"SL10e9svEqBH/z1GZy0gBTFXijWTa31VfEmOTh9RfwrQIWHt0vWSCBHnYjsvpvPXVbOShqHnFoSAts0u2Uu1faCZZnmhDGwGV+vdzeQnclya3n8EmKBhg9D3vv/7cbST9jqf/CD1eWghmNGemLm4BAdB04t89/1O/w1cDnyilFU="
CHANNEL_SECRET = CHANNEL_SECRET #"7810e950994952b0c7e288d593587fe8"
'''
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # 或 logging.CRITICAL 完全靜音
#logging.getLogger('werkzeug').setLevel(logging.INFO) #reopen

def validate_signature(body, signature):
    hash = hmac.new(
        CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(hash).decode()
    return hmac.compare_digest(expected_signature, signature)

def send_reply(reply_token, text, user_id=None):
    if user_id:
        append_to_memory(user_id, f"Bot: {text}")  # ⬅️ 不論 CLI 還是 LINE 都寫入
    
    if reply_token == "CLI_TOKEN":
        print("\nBot：" + text)
        return
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }
    response = requests.post(
        LINE_REPLY_ENDPOINT, #"https://api.line.me/v2/bot/message/reply",
        headers=headers,
        data=json.dumps(payload)
    )
    if response.status_code != 200:
        print(f"❌ LINE API Error: {response.status_code} {response.text}")


def handle_event(event):

            if not (event.get("type") == "message" and event["message"].get("type") == "text"):
                return
            
            user_id = event["source"]["userId"]
            user_text = event["message"]["text"]
            reply_token = event["replyToken"]

            

            if user_text.startswith("更正"):
                correction = user_text.replace("更正", "", 1).strip()
                memory_file = get_memory_file_path(user_id)

                if re.match(r"^G\(\d*\)P\(\d*\)W\(\d*\)IsDad\((True|False)?\)Name\((.*?)\)$", correction):
                    # ✅ 全欄位更正
                    lines = read_memory(user_id).splitlines()
                    lines[0] = correction
                    with open(memory_file, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines) + "\n")
                    send_reply(reply_token, f"✅ 已更正整行資料為：\n{correction}", user_id)
                    return "OK"

                # ✅ 單欄位更正
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

            # ✅ 把訊息寫進記憶檔案
            append_to_memory(user_id, f"User: {user_text}")

            # ✅ 讀取記憶檔案第一行
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
                                #print(f"[DEBUG] 檢查欄位：{field} → 空字串 Name() → 補問")
                                missing_fields.append("Name")
                            #else:
                                #print(f"[DEBUG] 檢查欄位：{field} → {match.group(0)}")
                        except IndexError:
                            #print(f"[DEBUG] 檢查欄位：{field} → 無效格式 → 補問")
                            missing_fields.append("Name")
                    else:
                        #print(f"[DEBUG] 檢查欄位：{field} → 無匹配")
                        missing_fields.append("Name")

                else:
                    if not match:
                        #print(f"[DEBUG] 檢查欄位：{field} → 無匹配")
                        missing_fields.append(field)
                    #else:
                        #print(f"[DEBUG] 檢查欄位：{field} → {match.group(0)}")




            if missing_fields:
                examples = """
                【示例1】
                輸入：「懷孕3次，生產一次，目前10週」
                輸出：G(3)P(1)W(10)IsDad()Name()

                【示例2】
                輸入：「我是爸爸」
                輸出：G()P()W()IsDad(True)Name()

                【示例3】
                輸入：「我叫小美」
                輸出：G()P()W()IsDad()Name(小美)

                【示例4】
                輸入：「目前5週」
                輸出：G()P()W(5)IsDad()Name()
                
                【示例5】
                輸入：「懷過五胎，生過5胎」
                輸出：G(5)P(5)W()IsDad()Name()

                【示例6】
                輸入：「已懷孕2次、落地一胎」
                輸出：G(2)P(1)W()IsDad()Name()
                
                【示例7】
                輸入：「懷過八胎」
                輸出：G(8)P()W()IsDad()Name()
                
                【示例8】
                輸入：「懷過一胎，還沒生」
                輸出：G(1)P(0)W()IsDad()Name()
                
                【示例9】
                輸入：「懷過一胎，生過0胎」
                輸出：G(1)P(0)W()IsDad()Name()
                
                【示例10】
                輸入：「我是吳子翔，是母親，已經懷孕5次，生產0次，目前懷孕5週。」
                輸出：G(5)P(0)W(5)IsDad(False)Name(吳子翔)

                """

                system_prompt = (
                    f"已知欄位：{first_line.strip()}。\n"
                    f"請從以下文字補充缺失欄位：{', '.join(missing_fields)}。\n"
                    "⚠️ 已知欄位不要修改。\n"
                    "⚠️ 僅回傳缺失欄位的格式，例如：G(5)P(3)、W(10)、IsDad(True)、Name(Alice)。\n"
                    "⚠️ 如果文字中有明確資料，即便語意不同（例如：『懷過5胎』、『生產過3次』），也要提取對應數值。\n"
                    "⚠️ 如果缺少明確回答，請保持欄位空白，例如：G()P()W()IsDad()Name()\n"
                    "❌ 不要根據名字或上下文推測欄位值。\n"
                    "不要回覆任何其他內容。\n\n"
                    f"{examples}"
                )



                #print(f"[DEBUG] system_prompt: {system_prompt}")

                # ✅ 呼叫 LLM 提取缺失欄位
                extracted_value = LLM_extract_from_text(user_text, system_prompt)
                #print(f"[DEBUG] LLM 回傳: {extracted_value}")

                # ✅ 更新記憶檔案
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

                # ✅ 再次檢查是否還缺欄位
                memory_content = read_memory(user_id)
                first_line = memory_content.splitlines()[0] if memory_content else ""
                still_missing = [field for field, pattern in field_patterns.items() if not re.search(pattern, first_line)]

                if still_missing:
                    # ⭕ 提示用戶補資料
                    prompt = "\n您好，請提供以下資訊：\n"
                    for f in missing_fields:
                        if f in field_descriptions:
                            prompt += f"🔸{field_descriptions[f]}\n"
                        else:
                            print(f"[WARNING] 無法為欄位 {f} 提示描述")
                            prompt += f"🔸請補上欄位：{f}\n"


                    send_reply(reply_token, prompt, user_id)
                    return "OK"
                else:
                    # ✅ 全部資料補齊
                   # 解析 G/P/W/IsDad/Name
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

                    # 組合自然語言描述
                    summary_text = f"✅ 已儲存您的資料：您是{isdad_value}，"
                    summary_text += f"產婦曾懷胎{g_value}次，曾產{p_value}胎，"
                    if week_value:
                        summary_text += f"目前懷胎{week_value}週，"
                    summary_text += f"登記名字是{name_value}。"


                    # 發送訊息
                    send_reply(reply_token, summary_text + "\n您可以開始提問囉～", user_id)
                    return "OK"

            # ✅ 所有資料齊全，開始正常對話
            history_text = "\n".join(memory_content.splitlines()[1:])
            gp_match = re.search(r"G\((\d+)\)P\((\d+)\)", first_line)
            week_match = re.search(r"W\((\d+)\)", first_line)
            isdad_match = re.search(r"IsDad\((True|False)\)", first_line)
            g_value = int(gp_match.group(1)) if gp_match else 0
            p_value = int(gp_match.group(2)) if gp_match else 0
            week_value = int(week_match.group(1)) if week_match else 0
            isdad_value = True if isdad_match and isdad_match.group(1) == "True" else False
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

                response = requests.post(
                    CHAT_ENDPOINT, #LMstudioIP
                    headers={"Content-Type": "application/json"},
                    json=finaljson
                )
                #print(f"[DEBUG]FinalJson:{finaljson}")
                lm_response = response.json()
                generated_text = lm_response["choices"][0]["message"]["content"].strip()
                if source_summary:
                    generated_text += f"\n資料來源: {source_summary}"
                    
            except Exception as e:
                print(f"LM Studio request error: {e}")
                
                generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"


            send_reply(reply_token, generated_text, user_id)
            return "OK"
        
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    if not validate_signature(body, signature):
        print("❌ Invalid signature")
        abort(400)

    data = json.loads(body)

    for event in data.get("events", []):
        handle_event(event)
    return "OK"

def send_push(user_id, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }
    response = requests.post(
        LINE_PUSH_ENDPOINT, #"https://api.line.me/v2/bot/message/push",
        headers=headers,
        data=json.dumps(payload)
    )
    if response.status_code != 200:
        print(f"❌ LINE Push Error: {response.status_code} {response.text}")
        
def run_cloudflare_tunnel():
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:5000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    public_url = None
    timeout = time.time() + 15  # 最多等 15 秒
    while time.time() < timeout:
        line = proc.stdout.readline()
        if not line:
            break
        #print("🌐 Tunnel輸出：", line.strip())
        match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
        if match:
            public_url = match.group(0)
            break

    if not public_url:
        print("❌ 無法取得 Cloudflare 公網網址！")
    #else:
        #print("🌐 取得 URL：", public_url)

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
        #print("⚙️ 正在更新 Webhook 到：", endpoint)
        r = requests.put(
            LINE_WEBHOOK_ENDPOINT, #"https://api.line.me/v2/bot/channel/webhook/endpoint",
            headers=headers,
            data=json.dumps(payload)
        )
        #print("📡 Webhook 更新:", r.status_code, r.text)
        
        
    except Exception as e:
        print("❌ Webhook 更新失敗:", e)

        
def run_flask():
    YOUR_USER_ID = "Ufe0538fc14e00b31e7fb451aff84638e" 
    send_push(YOUR_USER_ID, f"🚀 LINE Bot 已啟動，準備接受訊息！（{datetime.now()})")
    app.run(host="0.0.0.0", port=5000, threaded=True)

# ✅ CLI 任務：用終端機測試對話

def run_cli():
    path = get_memory_file_path("CLI")
    if os.path.exists(path):
        os.remove(path)
        
    while True:
        user_input = input("你：")
        if user_input.lower() in ["exit", "quit"]:
            break
        if user_input.lower() in ["restart"]:
            path = get_memory_file_path("CLI")
            if os.path.exists(path):
                os.remove(path)

        # 模擬 LINE 傳進來的 event 結構
        event = {
            "type": "message",
            "message": {
                "type": "text",
                "text": user_input
            },
            "source": {
                "userId": "CLI"
            },
            "replyToken": "CLI_TOKEN"  # 用不到實際 token
        }

        handle_event(event)



if __name__ == "__main__":
    mode = input("請選擇模式：1=CLI測試，2=Flask webhook，3=同時執行：")

    if mode in ("1", "cli", "CLI"):
        run_cli()

    elif mode == "2":
        public_url, tunnel_proc = run_cloudflare_tunnel()
        if public_url:
            print("🌐 [Debug] public_url = ", public_url)
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
