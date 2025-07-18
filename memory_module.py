import os
import re
import requests

MEMORY_FOLDER = "memory_data"
if not os.path.exists(MEMORY_FOLDER):
    os.makedirs(MEMORY_FOLDER)

LMStudioIp = "http://127.0.0.1:1234/"  # LM Studio API 位置
EMBED_MODEL = "gemma-3-4b-it"          # 你的 LM 模型名稱

def get_memory_file_path(user_id):
    return os.path.join(MEMORY_FOLDER, f"{user_id}.txt")

def is_new_user(user_id):
    """
    檢查是否為新用戶
    """
    return not os.path.exists(get_memory_file_path(user_id))

def create_memory_file(user_id):
    """
    建立新記憶檔案，寫入初始內容
    """
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("G()P()na()aa()[孕產史]\n")
    return file_path

def append_to_memory(user_id, content):
    """
    將新內容加入記憶檔案
    """
    file_path = create_memory_file(user_id)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(content + "\n")

def read_memory(user_id):
    """
    讀取記憶檔案內容
    """
    file_path = get_memory_file_path(user_id)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def update_memory_gp(user_id, gp_value):
    """
    更新記憶檔案中的 G()P() 數值
    """
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        create_memory_file(user_id)

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines:
        lines[0] = re.sub(r"G\(\d*\)P\(\d*\)", gp_value, lines[0])

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def extract_gp_from_text(text):
    """
    嘗試從純文字提取 G/P，失敗時用 LM Studio 輔助
    """
    # 🟢 1. 正則檢查
    match = re.search(r"G\((\d+)\)\s*P\((\d+)\)", text)
    if match:
        g, p = int(match.group(1)), int(match.group(2))
        if g < p:
            print(f"❌ 使用者輸入 G({g}) < P({p})，請提醒確認")
            return "INVALID:G<P"  # 讓外層提示用戶
        return f"G({g})P({p})"

    match2 = re.search(r"懷[孕過]?(\d+)胎[^生]*生[產過]?(\d+)胎?", text)
    if match2:
        g, p = int(match2.group(1)), int(match2.group(2))
        if g < p:
            print(f"❌ 使用者輸入 G({g}) < P({p})，請提醒確認")
            return "INVALID:G<P"
        return f"G({g})P({p})"

    # 🟡 2. 呼叫 LM Studio 模型
    try:
        lm_payload = {
    "model": EMBED_MODEL,
    "messages": [
        {
            "role": "system",
            "content": (
                "請從以下文字正確提取孕產史（懷孕次數 G 和生產次數 P）。"
                "⚠️ G 代表懷孕次數，P 代表生產次數。\n"
                "⚠️ **G 必須 >= P，否則是錯誤的**。\n"
                "只回傳格式 G(x)P(y)，不要回覆任何解釋或其他內容。"
            )
        },
        {"role": "user", "content": text}
    ],
    "temperature": 0.1,
    "max_tokens": 20,
    "stream": False
}

        response = requests.post(
            f"{LMStudioIp}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=lm_payload,
            timeout=10
        )
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # 檢查 LM 回傳是否有效
        gp_match = re.search(r"G\((\d+)\)\s*P\((\d+)\)", content)
        if gp_match:
            g, p = int(gp_match.group(1)), int(gp_match.group(2))
            if g < p:
                print(f"⚠️ LM 回傳 G({g}) < P({p})，視為模型誤判，不採用")
                return None  # 丟掉這次 LM 回傳
            return f"G({g})P({p})"

    except Exception as e:
        print(f"⚠️ LM Studio 輔助提取失敗: {e}")

    # 🟥 完全失敗
    return None

