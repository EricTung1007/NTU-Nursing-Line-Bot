from flask import Flask, request, abort
from linebot import WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot import LineBotApi
from linebot.exceptions import InvalidSignatureError
import requests
import re
from RAG_module import query_with_context, build_augmented_prompt
from memory_module import (
    is_new_user, create_memory_file, append_to_memory,
    read_memory, update_memory_gp, extract_gp_from_text
)

app = Flask(__name__)
LMStudioIp = "http://127.0.0.1:1234/"
CHANNEL_ACCESS_TOKEN = 'SL10e9svEqBH/z1GZy0gBTFXijWTa31VfEmOTh9RfwrQIWHt0vWSCBHnYjsvpvPXVbOShqHnFoSAts0u2Uu1faCZZnmhDGwGV+vdzeQnclya3n8EmKBhg9D3vv/7cbST9jqf/CD1eWghmNGemLm4BAdB04t89/1O/w1cDnyilFU='
CHANNEL_SECRET = '7810e950994952b0c7e288d593587fe8'

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text

    # ✅ 把訊息寫進記憶檔案
    append_to_memory(user_id, f"User: {user_text}")

    # ✅ 檢查是否新用戶或 G()P() 尚未填寫
    memory_content = read_memory(user_id)
    first_line = memory_content.splitlines()[0] if memory_content else ""
    needs_gp = is_new_user(user_id) or "G()" in first_line

    if needs_gp:
        create_memory_file(user_id)  # 若是新用戶，建立記憶檔

        # 嘗試從使用者輸入抓取 G(x)P(y)
        gp_value = extract_gp_from_text(user_text)

        if gp_value:
            # ✅ 加入 G/P 上限檢查
            gp_match = re.search(r"G\((\d+)\)P\((\d+)\)", gp_value)
            if gp_match:
                g = int(gp_match.group(1))
                p = int(gp_match.group(2))
                if g > 15 or p > 15:
                    try:
                        line_bot_api.reply_message(
                            event.reply_token,
                            TextSendMessage(text="⚠️ 懷孕次數或生產次數超過上限，請重新確認。")
                        )
                    except Exception as e:
                        print(f"Reply error: {e}")
                    return  # 🛑 超過上限直接結束

            # ✅ 更新 G/P
            update_memory_gp(user_id, gp_value)
            try:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"✅ 已儲存您的孕產史：{gp_value}\n您可以開始提問囉～")
                )
            except Exception as e:
                print(f"Reply error: {e}")
        else:
            try:
                line_bot_api.reply_message(
                    event.reply_token,
                    #TextSendMessage(text="您好，很高興為您服務。請先提供您的孕產史，以及目前週數（例如：我懷過1胎，生過0胎、目前五周）。")
                    TextSendMessage(text="您好，很高興為您服務，請先提供您的孕產史（例如：我懷過1胎，生過0胎）。")
                )
            except Exception as e:
                print(f"Reply error: {e}")
        return  # 🛑 已提示或儲存後結束，不跑後續問答

    # 🟢 已填孕產史 → 正常進入問答模式
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 已收到您的訊息，模型正在運算中，可能有數十秒的延遲，請稍候...")
        )
    except Exception as e:
        print(f"Reply error: {e}")

    # 🧠 讀取記憶
    memory_lines = read_memory(user_id).splitlines()
    gp_line = memory_lines[0] if memory_lines else ""
    history_text = "\n".join(memory_lines[1:])

    # 📦 解析 G()P()
    gp_match = re.search(r"G\((\d+)\)P\((\d+)\)", gp_line)
    g_value = int(gp_match.group(1)) if gp_match else 0
    p_value = int(gp_match.group(2)) if gp_match else 0

    # 🔗 呼叫模型
    model_name = "gemma-3-4b-it"  # fallback
    try:
        model_response = requests.get(f"{LMStudioIp}/v1/models")
        model_response.raise_for_status()
        models_data = model_response.json()
        if "data" in models_data and len(models_data["data"]) > 0:
            model_name = models_data["data"][0]["id"]
    except Exception as e:
        print(f"取得模型失敗: {e}")

    system_message = (
        "⚠️ 你是一位產科與母嬰護理顧問，請根據上下文專業、簡潔回答問題，不要重複提醒孕產史。"
        "如果資料不足，請說明「資料不足」，不要編造內容。"
    )

    try:
        contexts = query_with_context(user_text, 3)
        finaljson = build_augmented_prompt(
            contexts,
            user_question=user_text,
            modelname=model_name,
            g_value=g_value,
            p_value=p_value,
            history_text=history_text
        )

        response = requests.post(
            f"{LMStudioIp}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=finaljson
        )
        lm_response = response.json()
        choices = lm_response.get("choices")
        if choices and isinstance(choices, list) and len(choices) > 0:
            message = choices[0].get("message")
            if message and isinstance(message, dict):
                generated_text = message.get("content", "（模型回應沒有內容）")
            else:
                generated_text = "（模型回應格式錯誤）"
        else:
            generated_text = "（模型沒有回傳 choices）"

    except Exception as e:
        print(f"LM Studio request error: {e}")
        generated_text = "❌ 抱歉，目前無法取得回應，請稍後再試。"

    # ✅ fallback 檢查（移到這裡）
    if "孕產史提取" in generated_text and "無法提取孕產史" in generated_text:
        generated_text = (
            "資料不足，請洽詢專業醫護人員。\n"
            "台大醫院電話:(02)2312-3456\n衛教專線:轉266546\n診後說明處:轉266549\n9F產房護理站:轉270908或270909\n"
            "或是衛服部孕產婦關懷諮詢服務專線: 0800-870-870。"
        )

    # 📝 記錄模型回應
    append_to_memory(user_id, f"Bot: {generated_text}")

    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=generated_text)
        )
    except Exception as e:
        print(f"Push message error: {e}")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
