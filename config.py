# config.py
ACTIVE_USER_IDS = ["U7a80751a6a87b6719dd382a1182ed5bb"]
NOFTIFY_USER_IDS = ["Ufe0538fc14e00b31e7fb451aff84638e"]  # 用於啟動通知的用戶 ID 列表(尚未完成，因LINE api無法主動查ID)

# LM Studio 伺服器設定
LM_STUDIO_HOST = "http://127.0.0.1:1234"
EMBEDDING_ENDPOINT = f"{LM_STUDIO_HOST}/v1/embeddings"
CHAT_ENDPOINT = f"{LM_STUDIO_HOST}/v1/chat/completions"

# LM 模型名稱（請依實際修改）
EMBEDDING_MODEL = "text-embedding-bge-small-zh-v1.5"
#CHAT_MODEL = "Qwen2.5-3B-Instruct"  
CHAT_MODEL = "Qwen2.5-7B-Instruct"  #可行
#CHAT_MODEL = "gpt-OSS-20B"  
#CHAT_MODEL = "gemma-3-4B-instruct" #太笨，沒辦法正常執行目前版本
#CHAT_MODEL = "gemma-3-7B-instruct" 

# LINE Bot 機密
CHANNEL_ACCESS_TOKEN = "SL10e9svEqBH/z1GZy0gBTFXijWTa31VfEmOTh9RfwrQIWHt0vWSCBHnYjsvpvPXVbOShqHnFoSAts0u2Uu1faCZZnmhDGwGV+vdzeQnclya3n8EmKBhg9D3vv/7cbST9jqf/CD1eWghmNGemLm4BAdB04t89/1O/w1cDnyilFU="
CHANNEL_SECRET = "7810e950994952b0c7e288d593587fe8"
LINE_WEBHOOK_ENDPOINT = "https://api.line.me/v2/bot/channel/webhook/endpoint"
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"
LINE_ADMIN_USER_ID = "Ufe0538fc14e00b31e7fb451aff84638e"
# FAISS 索引與資料儲存
INDEX_PATH = "database/faiss_index.index"
METADATA_PATH = "database/metadata.json"
JSONL_PATH = "database/combined.jsonl"  # 用於 knowledge base 建立

# 使用者記憶檔案路徑
MEMORY_FOLDER = "memory_data"
