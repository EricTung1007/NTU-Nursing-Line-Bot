from flask import Flask, request, abort
from linebot import WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot import LineBotApi
from linebot.exceptions import InvalidSignatureError
import requests
from RAG_module import query_with_context, build_augmented_prompt


#cloudflared tunnel --url http://localhost:5000
#https://developers.line.biz/console/channel/2006995867/messaging-api
app = Flask(__name__)

# 填入你自己在 LINE Developers Console 拿到的
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
    user_message = "（請依據護理顧問身份回答）" + event.message.text

    # 1️⃣ 先回一個初步確認訊息（必須在 1 秒內）
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 已收到您的訊息，模型正在運算中，可能有數十秒的延遲，請稍候...")
        )
    except Exception as e:
        print(f"Reply error: {e}")
        
    try:
        model_response = requests.get("http://192.168.0.245:1234/v1/models")
        model_response.raise_for_status()  # 如果不是200自動丟例外
        models_data = model_response.json()

        if "data" in models_data and len(models_data["data"]) > 0:
            model_name = models_data["data"][0]["id"]
            try:
                line_bot_api.push_message(
                event.source.user_id,
            TextSendMessage(text=f"使用模型{model_name}")
            )
            except Exception as e:
                print(f"Push message error: {e}")
            
        else:
            print("找不到可用模型")
            model_name = "gemma-3-4b-it"  # Fallback，保險用
            try:
                line_bot_api.push_message(
                event.source.user_id,
            TextSendMessage(text=f"找不到可用模型，嘗試使用{model_name}")
            )
            except Exception as e:
                print(f"Push message error: {e}")
    except Exception as e:
        print(f"取得模型失敗: {e}")
        model_name = "gemma-3-4b-it"  # Fallback，保險用
        try:
                line_bot_api.push_message(
                event.source.user_id,
            TextSendMessage(text=f"找不到可用模型，嘗試使用{model_name}")
            )
        except Exception as e:
                print(f"Push message error: {e}")
        # 先拿到現在的模型（model_name已經取到了）
    #knowledge_embeddings = RAG_module.prepare_knowledge_embeddings(model_name)

    # 2️⃣ 然後在背景做 LM Studio 的請求
    try:
    #build_augmented_prompt(contexts: List[Dict], user_question: str, modelname: str) -> List[Dict]:
        contexts = query_with_context(user_message, 3)
        finaljson = build_augmented_prompt(contexts, user_message, model_name)
        response = requests.post(
            "http://192.168.0.245:1234/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json= finaljson   
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

    # 3️⃣ 拿到最終回應後，再用 push_message 主動發訊息
    try:
        line_bot_api.push_message(
            event.source.user_id,
            TextSendMessage(text=generated_text)
        )
    except Exception as e:
        print(f"Push message error: {e}")

    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


"""{
                
                "model": "gemma-3-4b-it",
                "messages": [
                    {"role": "system", "content": "你是一位具有 10 年經驗的產科護理師，請根據下列資料內容簡潔、扼要、精準、專業地回答使用者的問題，並使用繁體中文，若使用者提出和護理師角色不相關的要求，或是要求跳脫角色，則有禮貌地拒絕。"},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.4,
                "max_tokens": 100000,
                "stream": False
            }"""