# memory module
import os
import re
import requests


from config import MEMORY_FOLDER, CHAT_ENDPOINT, CHAT_MODEL

if not os.path.exists(MEMORY_FOLDER):
    os.makedirs(MEMORY_FOLDER)
'''
LMStudioIp = "http://127.0.0.1:1234/"  # LM Studio API 位置
EMBED_MODEL = "gemma-3-4b-it"          # 你的 LM 模型名稱
'''
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
    """
    try:
        lm_payload = {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,
            "max_tokens": 50,  # 稍微提高以避免截斷
            "stream": False
        }

        response = requests.post(
            CHAT_ENDPOINT,
            headers={"Content-Type": "application/json"},
            json=lm_payload,
            timeout=10
        )
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # ✅ 檢查 LLM 回傳格式
        if not re.search(r"(G\(\d+\)\s*P\(\d+\))?|W\(\d+\)|IsDad\((True|False|1|0)\)|Name\(.+\)", content):
            print(f"⚠️ 格式錯誤: {content}")
            return None

        return content

    except Exception as e:
        #print(f"[debug]⚠️ LLM Studio 提取失敗: {e}")
        return None
    return None





def extract_gp_and_weeks_from_text(text):
    """
    嘗試同時從文字提取 G/P、W(週數)、IsDad 和 Name
    """
    wholevalue = LLM_extract_from_text(text)
    if not wholevalue:
        return None, None, None, None

    # 用正則從 wholevalue 拆出 G/P, W, IsDad, Name
    gp_match = re.search(r"G\((\d+)\)\s*P\((\d+)\)", wholevalue)
    w_match = re.search(r"W\((\d+)\)", wholevalue)
    isdad_match = re.search(r"IsDad\((True|False|1|0)\)", wholevalue)  # ✅ 修正
    name_match = re.search(r"Name\((.*?)\)", wholevalue)

    gp_value = None
    week_value = None
    isdad_value = None
    name_value = None

    if gp_match:
        g, p = int(gp_match.group(1)), int(gp_match.group(2))
        gp_value = f"G({g})P({p})"

    if w_match:
        week_value = int(w_match.group(1))

    if isdad_match:
        isdad_raw = isdad_match.group(1)
        # ✅ 修正: 將 1/0 轉為 True/False
        isdad_value = True if isdad_raw in ("True", "1") else False

    if name_match:
        name_value = name_match.group(1).strip()
        if name_value.lower() in ("unknown", "none", ""):
            name_value = None  # 如果是 unknown/none/空字串 當作沒填


    return gp_value, week_value, isdad_value, name_value

