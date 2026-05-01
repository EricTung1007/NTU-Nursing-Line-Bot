# config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Load .env file (lightweight, no third-party dependency needed)
# ---------------------------------------------------------------------------
def _load_dotenv(path=".env"):
    """Read a .env file and inject its values into os.environ."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key:
                os.environ.setdefault(key, value)

_load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# LINE Bot Credentials  (loaded from .env — never hard-code secrets!)
# ---------------------------------------------------------------------------
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_ADMIN_USER_ID = os.environ.get("LINE_ADMIN_USER_ID", "")

# Comma-separated user ID lists
NOTIFY_USER_IDS = [
    uid.strip()
    for uid in os.environ.get("LINE_NOTIFY_USER_IDS", "").split(",")
    if uid.strip()
]
ACTIVE_USER_IDS = [
    uid.strip()
    for uid in os.environ.get("LINE_ACTIVE_USER_IDS", "").split(",")
    if uid.strip()
]

# ---------------------------------------------------------------------------
# LM Studio Server
# ---------------------------------------------------------------------------
LM_STUDIO_HOST = os.environ.get("LM_STUDIO_HOST", "http://127.0.0.1:1234")
EMBEDDING_ENDPOINT = f"{LM_STUDIO_HOST}/v1/embeddings"
CHAT_ENDPOINT = f"{LM_STUDIO_HOST}/v1/chat/completions"
COMPLETIONS_ENDPOINT = f"{LM_STUDIO_HOST}/v1/completions"
MODELS_ENDPOINT = f"{LM_STUDIO_HOST}/v1/models"

# LM Studio CLI path (for auto-loading models)
_default_lms = os.path.join(os.path.expanduser("~"), ".lmstudio", "bin",
                            "lms.exe" if os.name == "nt" else "lms")
LMS_CLI_PATH = os.environ.get("LMS_CLI_PATH", _default_lms)

# LM Model Names (change to match models loaded in LM Studio)
EMBEDDING_MODEL = "text-embedding-bge-small-zh-v1.5"

# CHAT_MODEL = the API identifier (used in requests)
# CHAT_MODEL_KEY = the model key or path for `lms load` (can differ from API name)
CHAT_MODEL = os.environ.get("CHAT_MODEL", "Qwen3.5-4B")
CHAT_MODEL_KEY = os.environ.get("CHAT_MODEL_KEY", CHAT_MODEL)

# ---------------------------------------------------------------------------
# LINE API Endpoints
# ---------------------------------------------------------------------------
LINE_WEBHOOK_ENDPOINT = "https://api.line.me/v2/bot/channel/webhook/endpoint"
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"

# ---------------------------------------------------------------------------
# FAISS Index & Data Storage
# ---------------------------------------------------------------------------
INDEX_PATH = str(BASE_DIR / "database" / "faiss_index.index")
METADATA_PATH = str(BASE_DIR / "database" / "metadata.json")
JSONL_PATH = str(BASE_DIR / "database" / "combined.jsonl")

# ---------------------------------------------------------------------------
# User Memory Files
# ---------------------------------------------------------------------------
MEMORY_FOLDER = str(BASE_DIR / "memory_data")
