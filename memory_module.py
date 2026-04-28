# memory module
import os
import re
import logging
import requests


from config import MEMORY_FOLDER, CHAT_ENDPOINT, CHAT_MODEL

logger = logging.getLogger(__name__)

if not os.path.exists(MEMORY_FOLDER):
    os.makedirs(MEMORY_FOLDER)

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
            f.write("G()P()W()IsDad()Name()\n")
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

def update_memory_weeks(user_id, week_value):
    """
    更新記憶檔案中的 W() 週數
    """
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        create_memory_file(user_id)

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines:
        if "W(" not in lines[0]:
            # 修正：在 P(...) 後插入 W(...)
            lines[0] = re.sub(r"(P\(\d*\))", r"\1W({})".format(week_value), lines[0])
        else:
            lines[0] = re.sub(r"W\(\d*\)", f"W({week_value})", lines[0])

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

def update_memory_isdad(user_id, isdad_value):
    """
    更新記憶檔案中的 IsDad() 狀態
    """
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        create_memory_file(user_id)

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines:
        # 修正：匹配 IsDad() 或 IsDad(True|False)
        if re.search(r"IsDad\((True|False)?\)", lines[0]):
            lines[0] = re.sub(r"IsDad\((True|False)?\)", f"IsDad({isdad_value})", lines[0])
        else:
            lines[0] = lines[0].strip() + f"IsDad({isdad_value})\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def update_memory_name(user_id, name_value):
    """
    更新記憶檔案中的 Name() 名字
    """
    file_path = get_memory_file_path(user_id)
    if not os.path.exists(file_path):
        create_memory_file(user_id)

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines:
        # 不要檢查是否存在，直接替換
        lines[0] = re.sub(r"Name\((.*?)\)", f"Name({name_value})", lines[0])

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def LLM_extract_from_text(text, system_prompt):
    """
    使用 LLM 提取單一欄位，並檢查格式合法性
    Supports both regular and thinking/reasoning models (e.g. gemma-4).
    """
    try:
        lm_payload = {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,
            "max_tokens": 300,  # Reasoning models need headroom for thinking + answer
            "stream": False
        }

        response = requests.post(
            CHAT_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json=lm_payload,
            timeout=30
        )
        result = response.json()
        msg = result["choices"][0]["message"]

        # Get content — thinking models may put output in reasoning_content
        content = (msg.get("content") or "").strip()
        if not content:
            # Fallback: extract from reasoning_content for thinking models
            reasoning = (msg.get("reasoning_content") or "").strip()
            if reasoning:
                # Try to find the structured output within the reasoning text
                field_match = re.search(
                    r"(G\(\d*\)\s*P\(\d*\)\s*W\(\d*\)\s*IsDad\([^)]*\)\s*Name\([^)]*\))",
                    reasoning
                )
                if field_match:
                    content = field_match.group(1)
                else:
                    # Try to find any individual field patterns
                    parts = []
                    for pat in [r"G\(\d+\)\s*P\(\d+\)", r"W\(\d+\)", r"IsDad\((True|False|1|0)\)", r"Name\([^)]+\)"]:
                        m = re.search(pat, reasoning)
                        if m:
                            parts.append(m.group(0))
                    content = "".join(parts) if parts else ""

        if not content:
            logger.debug("LLM returned empty content and no usable reasoning")
            return None

        # Check format validity
        if not re.search(r"(G\(\d+\)\s*P\(\d+\))?|W\(\d+\)|IsDad\((True|False|1|0)\)|Name\(.+\)", content):
            logger.warning("LLM 回傳格式錯誤: %s", content)
            return None

        return content

    except Exception as e:
        logger.debug("LLM Studio 提取失敗: %s", e)
        return None


