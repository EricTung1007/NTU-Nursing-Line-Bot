中文 ｜ [**English README**](readme.md)

# AI 驅動產前衛教 LINE Bot

本專案為國立臺灣大學畢業專題之工作原型，開發了一款中英雙語產前衛教聊天機器人。系統整合本地部署之大型語言模型與檢索增強生成（RAG）技術，以臺灣官方母嬰健康衛教資料作為知識基礎。

本專案以低成本、注重隱私之方式設計，透過 LINE——臺灣使用者已廣泛使用的通訊平台——提供個人化產前衛教資訊。其更廣泛的目的在於探索以臨床為基礎的 AI 系統，如何在不需安裝新應用程式、不需註冊新帳號、不需完全依賴商業雲端服務的前提下，改善民眾取得可信賴健康衛教資訊的管道。

## 研究目標

- 提升產前健康衛教的可及性與一致性。
- 透過以驗證過的衛教資料為基礎，降低模型幻覺（hallucination）風險。
- 探索本地可部署的 AI 是否能支援多語言、符合臨床的健康溝通在日常照護情境中的應用。
- 透過使用目標族群已熟悉的通訊平台，降低採用門檻。

## 系統概覽

- **介面**：Flask + LINE Messaging API
- **生成**：透過 LM Studio 或 OpenAI 相容端點的本地語言模型
- **檢索**：基於策展產科與母嬰衛教內容的 FAISS 向量索引
- **個人化**：懷孕週數、孕產史（G/P）、家長角色、使用者姓名
- **記憶**：輕量化逐使用者記憶檔案，維持對話脈絡

## 系統架構

```
LINE App ──▶ Cloudflare Tunnel ──▶ Flask /callback ──▶ handle_event()
                                                        │
                                                        ├─ memory_module  （使用者檔案與歷史）
                                                        ├─ RAG_module     （FAISS + LM Studio 嵌入）
                                                        └─ LM Studio     （對話生成）
```

## 主要檔案

| 檔案 | 用途 |
|---|---|
| `LB.py` | LINE Webhook 處理與回應調度 |
| `config.py` | 所有設定（從 `.env` 讀取機密） |
| `prompts.py` | 系統提示詞與少量樣本範例 |
| `RAG_module.py` | 檢索與增強提示詞建構 |
| `memory_module.py` | 使用者記憶與個人資料提取 |
| `prep.py` | 知識庫建置（PDF → JSONL → FAISS） |
| `product_entry.py` | PyInstaller 打包進入點 |
| `start.bat` | Windows 一鍵啟動（啟動 LM Studio + Bot） |
| `start.command` | macOS 一鍵啟動（啟動 LM Studio + Bot） |

## 前置需求

- **Python** 3.11+
- **LM Studio** 0.3.x — 載入以下模型：
  1. `text-embedding-bge-small-zh-v1.5`（嵌入模型）
  2. 您選擇的對話模型（在 `config.py` 中更新 `CHAT_MODEL`）
- **Cloudflare Tunnel**（`cloudflared` CLI）— 用於公開 Webhook
- **LINE Messaging API** 頻道（[開發者控制台](https://developers.line.biz/console/)）

## 快速開始

### 1. 複製專案並安裝依賴

```bash
git clone https://github.com/EricTung1007/NTU-Nursing-Line-Bot.git
cd NTU-Nursing-Line-Bot
pip install -r requirements.txt
```

### 2. 設定機密資訊

複製範本環境檔並填入您的憑證：

```bash
cp .env.example .env
```

編輯 `.env`，填入您的 LINE 頻道 Token、Secret 及使用者 ID。**切勿提交 `.env`** — 已在 `.gitignore` 中排除。

### 3. 建立知識庫（僅首次需要）

將 PDF 檔案放入 `database/` 資料夾，然後執行：

```bash
python prep.py
```

此步驟將 PDF 轉換為 JSONL → FAISS 向量索引。

### 4. 啟動 Bot

**方法 A — 一鍵啟動（macOS）：**

```bash
chmod +x start.command
./start.command
```

若 LM Studio 的 `lms` CLI 不在 `~/.lmstudio/bin/lms`，請在 `.env` 設定 `LMS_CLI_PATH`。

**方法 B — 一鍵啟動（Windows）：**

```bash
start.bat
```

**方法 C — 手動啟動：**

```bash
python LB.py
```

系統會提示選擇模式：
- `1` — CLI 測試模式（在終端機中對話）
- `2` — Flask Webhook 模式（LINE Bot）
- `3` — 同時執行

啟動時會自動載入 LM Studio 所需模型（若尚未載入）。

## 資料更正指令（LINE）

使用者可透過傳送以「更正」開頭的訊息來修改個人資料：

| 指令 | 範例 |
|---|---|
| 完整資料 | `更正G(2)P(1)W(10)IsDad(False)Name(小美)` |
| 僅 G/P | `更正G(3)P(1)` |
| 僅週數 | `更正W(20)` |
| 家長角色 | `更正IsDad(True)` |
| 僅名字 | `更正Name(小華)` |

## 目前狀態與限制

本專案為學術原型，用於海報發表與技術展示。目前的評估為初步且基於情境的測試，尚未經過大規模使用者測試或臨床部署。

## 打包（選用）

```bash
python -m PyInstaller --clean --onedir --console --name NTULineBot product_entry.py
```

## 授權

本專案用於臺大醫院之學術與臨床教育用途。
