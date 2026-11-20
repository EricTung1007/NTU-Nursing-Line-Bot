# 護理人員手冊（給不懂電腦的您）

這個程式是病房的「衛教小幫手」：孕婦與家屬在 LINE 問問題，機器人用我們放進去的衛教手冊回答。**您不需要寫程式、也不需要打任何指令。**

## 每天怎麼用

1. 開電腦，**雙擊「NTULineBot」**（開了兩次也沒關係，只會有一個）。
2. 看畫面最上面的燈：
   - **綠燈**：一切正常，什麼都不用做。
   - **黃燈**：正在載入或有小狀況，等 2 到 3 分鐘；若沒變綠，按「一鍵修復」。
   - **紅燈**：有問題。按旁邊的 **「一鍵修復」**。
3. 下班不用關程式。要關電腦前，到「總覽」按「關閉程式」。

> 程式裡住著一位 **NP（執業護理師）**，會自己巡房：模型或網路當掉時，會自動重新啟動並記在「除錯」頁的事件記錄。

## 出問題時（照順序做）

1. 按畫面最上面的 **「一鍵修復」**。程式會自己檢查並修好大部分問題（連接埠被占用、模型檔被移動、設定被改壞、模型當機、LINE 斷線…）。
2. 還有紅字的項目，**照它底下寫的步驟做**，每一項都用白話寫好了。
3. 還是不行：到「除錯」頁按 **「下載診斷檔」**，把檔案傳給資訊人員。檔案裡**不會有** LINE 金鑰。
4. 如果是「剛改過設定」才壞掉，按「還原到上次正常的設定」。

| 看到的狀況 | 通常原因 | 怎麼辦 |
|---|---|---|
| 一直黃燈「模型載入中」 | 第一次載入大型模型 | 等 3 到 5 分鐘 |
| 紅燈「記憶體不足」 | 電腦記憶體小 | 一鍵修復（會自動調小） |
| 紅燈「連接埠被占用」 | 程式開了兩次 | 一鍵修復 |
| 紅燈「LINE 連線失敗」 | 網路中斷或醫院防火牆 | 檢查網路，按「重新連線」 |
| 通道正常但收不到訊息 | LINE 後台設定 | 照「除錯」頁的 4 個步驟檢查 |
| 機器人說「沒有相關資料」 | 知識庫沒有這個主題 | 看「待補充問題」，補文件後重建 |

## 第一次安裝（只做一次，不需要任何指令）

1. 到專案的 GitHub「Releases」頁，下載 **NTULineBot-Setup.exe**（Windows）或 **NTULineBot-mac.dmg**（Mac）。
2. **Windows**：雙擊 Setup，一路按「下一步」。第一次可能出現藍色「Windows 已保護您的電腦」：按「**其他資訊**」→「**仍要執行**」（因為程式沒有付費簽章，這是正常的）。**Mac**：開啟 dmg，把程式拖到「Applications」，第一次要**按右鍵 → 打開**。
3. 開啟「NTU Nursing LINE Bot」。畫面最上方會寫「第一次使用」，按 **「一鍵修復」**，程式會自己下載所需檔案（約 2.7 GB，需要網路，中斷後會接著下載）。
4. 到「設定」→「LINE 連線」貼上 **Channel Access Token** 與 **Channel Secret**，按「測試 LINE 連線」。
5. 再按一次「一鍵修復」。程式會建立知識庫並啟動機器人。
6. 到「測試對話」傳一句話試試，沒問題就完成了。

> 更新程式：畫面右上角按「檢查更新」，有新版時按「立即更新」就會自動完成（程式也會每 12 小時自己檢查一次）。資料與設定都會保留。

## 每週與每月

- **每週**：到「待補充問題」看看哪些問題答不出來；到「總覽」按「下載備份」存到隨身碟。
- **新增衛教資料**：「知識庫」→「上傳」→「重建知識庫」。只能用**可以選取文字**的 PDF（掃描檔無法使用，程式會提醒）。
- **每次人員或電話變動**：到「設定」→「緊急狀況」，確認電話號碼是最新的。

## 請注意

- 機器人**只能提供一般衛教**，不能取代護理人員或醫師的判斷。使用者描述緊急症狀時，機器人會立刻請對方就醫並提供電話。
- 使用者的對話含個人資料，**備份檔請妥善保管**，不要寄到公開的地方。
- 使用者資料存放在電腦的使用者資料夾（Windows：`%LOCALAPPDATA%\NTULineBot`；Mac：`資源庫/Application Support/NTULineBot`），解除安裝不會刪除；請勿手動刪除。

<!--EN-->

# Nurse's Note (no computer skills needed)

This program is the ward's education helper: mothers and families ask questions on LINE, and the bot answers from the education booklets we gave it. **You do not need to code or type any commands.**

## Daily use

1. Turn on the computer and **double-click "NTULineBot"** (opening it twice is harmless; only one copy runs).
2. Look at the light at the top of the window:
   - **Green**: everything is fine, do nothing.
   - **Yellow**: still loading or a small issue. Wait 2 to 3 minutes; if it does not turn green, press **Fix everything**.
   - **Red**: a problem. Press **Fix everything** next to it.
3. No need to close the program at the end of a shift. Before shutting down the computer, press "Quit" on the Overview page.

> A resident **NP (nurse practitioner)** lives inside the program and makes its own rounds: if the model or the network drops, it restarts it automatically and notes it in the Debug page's event list.

## When something goes wrong (in this order)

1. Press **Fix everything** at the top. The program checks itself and repairs most problems (busy port, moved model file, broken settings, model crash, LINE disconnect...).
2. For anything still red, **follow the steps written under it**. Each one is in plain language.
3. Still stuck: on the Debug page press **Download diagnostic file** and send it to IT. The file **never contains** your LINE keys.
4. If it broke right after a settings change, press "Restore last working settings".

| What you see | Usual cause | What to do |
|---|---|---|
| Yellow, "model loading" for long | First load of a large model | Wait 3 to 5 minutes |
| Red, "not enough memory" | Small computer memory | Fix everything (it lowers memory use) |
| Red, "port in use" | Program opened twice | Fix everything |
| Red, "LINE connection failed" | Network down or hospital firewall | Check network, press Reconnect |
| Tunnel OK but no messages | LINE console settings | Follow the 4 steps on the Debug page |
| Bot says "no relevant data" | Topic not in the knowledge base | See "Unanswered questions", add a document, rebuild |

## First-time setup (once, no commands)

1. On the project's GitHub **Releases** page, download **NTULineBot-Setup.exe** (Windows) or **NTULineBot-mac.dmg** (Mac).
2. **Windows**: double-click Setup and keep pressing Next. The first time you may see a blue "Windows protected your PC" box: press **More info** then **Run anyway** (the program has no paid signature; this is expected). **Mac**: open the dmg, drag the app to Applications, and the first time **right-click, then Open**.
3. Open "NTU Nursing LINE Bot". The top says "First run"; press **Fix everything** and the program downloads what it needs (about 2.7 GB, needs internet, resumes if interrupted).
4. Settings → LINE connection: paste the **Channel Access Token** and **Channel Secret**, press "Test LINE connection".
5. Press **Fix everything** again. It builds the knowledge base and starts the bot.
6. Send a line in "Test chat". If it answers, you are done.

> To update: press "Check for updates" at the top right; when a new version exists press "Update now" and it does the rest (the program also checks by itself every 12 hours). Your data and settings are kept.

## Weekly and monthly

- **Weekly**: check "Unanswered questions" for gaps; press "Download backup" on Overview and save it to a USB stick.
- **Adding education material**: Knowledge base → Upload → Rebuild. Use PDFs whose **text can be selected** (scanned PDFs do not work; the program warns you).
- **Whenever staff or phone numbers change**: Settings → Emergency handling, confirm the phone numbers are current.

## Please note

- The bot gives **general education only** and does not replace a nurse's or doctor's judgement. If a user describes an emergency, the bot tells them to seek care immediately and gives the phone numbers.
- Conversations contain personal data. **Keep backup files safe** and never post them publicly.
- User data is kept in the computer's user-data folder (Windows: `%LOCALAPPDATA%\NTULineBot`; Mac: `Library/Application Support/NTULineBot`). Uninstalling does not delete it; do not delete it by hand.
