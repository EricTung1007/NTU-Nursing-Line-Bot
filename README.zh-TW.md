中文 ｜ [**English README**](readme.md)

# AI 驅動產前衛教 LINE Bot

國立臺灣大學畢業專題之工作原型：中英雙語產前衛教聊天機器人，以本地大型語言模型搭配檢索增強生成（RAG），知識來源為臺灣官方母嬰健康衛教資料，透過 LINE 提供服務。

此版本不需要終端機視窗，也不需要 LM Studio：以本機圖形介面管理一切，推論使用 llama.cpp，所有資料存放於單一 SQLite 檔案。

## 系統架構

```
LINE ──▶ Cloudflare 通道 ──▶ Webhook 伺服器 :5001（僅 /callback，對外）
                                  │  立即回應 200，實際處理交給背景工作池
                                  ▼
                             Bot 流程 ── SQLite（使用者、對話、設定）
                                  │  更正指令 → 緊急偵測 → 資料填寫 → RAG 回答
                                  ├─ FAISS 知識庫（向量：llama-server --embeddings）
                                  └─ 對話模型（llama-server）

管理介面 :5050（僅限本機 127.0.0.1，不會經由通道對外）
```

## 下載（給護理人員與一般使用者）

到專案的 **Releases** 頁面下載 `NTULineBot-Setup.exe`（Windows）或 `NTULineBot-mac.zip`（Mac）。安裝、開啟、按「一鍵修復」：程式會自己下載 llama.cpp、cloudflared 與模型（約 2.7 GB，可續傳並驗證檔案）。全程不需要終端機。安裝檔未經付費簽章，Windows 第一次會出現「其他資訊 → 仍要執行」；Mac 請按右鍵 → 打開。

發行檔由 GitHub Actions 在推送 `v1.0.0` 這類標籤時自動建置。安裝後的使用者資料放在 `%LOCALAPPDATA%\NTULineBot`（macOS：`~/Library/Application Support/NTULineBot`），更新程式不會動到。

## 從原始碼安裝

1. 安裝 Python 3.9+，執行 `pip install -r requirements.txt`（若要原生視窗，再安裝 `requirements-gui.txt`）。
2. 執行 `python app.py` 後按「一鍵修復」：缺少的 llama-server、cloudflared 與模型會自動尋找（下載、桌面、文件資料夾）或自動下載。也可以自己把檔案放進 `bin/` 與 `models/`（檢索模型檔名需含 `embed` 或 `bge`）。
3. 「總覽」頁會列出尚未完成的項目。
4. 「設定」頁貼上 LINE Channel Access Token 與 Secret；「知識庫」頁按「重建知識庫」。
5. 按「啟動機器人」。通道網址會自動登錄到 LINE。

從舊版升級：首次啟動時，程式會一次性把 `.env` 的 LINE 金鑰與 `memory_data/*.txt` 匯入 SQLite。更換檢索模型後須重建知識庫，介面會在索引與目前模型不一致時提示。

## 自動修復與除錯

- **一鍵修復**（畫面最上方）：執行所有健康檢查並自動處理安全項目（連接埠被占用、模型檔被移動、設定值錯誤、模型當機、通道中斷、知識庫過期），剩下的以中英文白話步驟列出。
- **自動看顧**：模型當機自動重啟（記憶體不足時自動調小設定）、通道中斷自動重連，並限制次數，無法修復時會回報而不是無限重啟。
- **每次啟動前自動檢查**並靜默修復；重複雙擊只會開啟既有視窗。
- **記住上次正常的設定**，改壞時一鍵還原。
- **除錯頁**：完整檢查（含網路）、端對端測試與各步驟耗時、回覆速度統計、事件時間軸、即時記錄（程式與兩個模型）、給資訊人員的診斷檔（不含 LINE 金鑰）。
- **設定頁**：所有設定皆有中英說明、輸入驗證、單項還原與搜尋，提示詞也可調整。

護理人員手冊（中英文）在程式的「手冊」分頁，原始檔為 [`nursebot/web/static/nurse_note.md`](nursebot/web/static/nurse_note.md)。

## 護理人員可在介面中完成（不需檔案、不需指令）

- 啟動／停止機器人，查看 LINE、模型、知識庫狀態
- 檢視、編輯、刪除使用者，閱讀對話內容
- 查看機器人答不出來的問題（知識缺口），上傳文件並重建
- 以測試身分與機器人對話（不會傳到 LINE）
- 調整緊急關鍵字與緊急回覆內容
- 下載備份（資料庫＋文件）

## 測試

```bash
pip install pytest && python -m pytest tests
```

## 免責聲明

教育用途原型，不能取代專業醫療建議。
