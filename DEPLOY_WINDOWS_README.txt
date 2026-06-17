NTU Nursing LINE Bot - Windows deployment

Target computer requirement:
- Windows
- LM Studio installed
- The required embedding and chat models downloaded in LM Studio

Start:
1. Extract this whole folder. Do not run NTULineBot.exe from inside the zip.
   Use the packaged NTULineBot-windows-deploy folder/zip, not only dist\NTULineBot,
   so cloudflared.exe and the helper files are included.
2. Open LM Studio and make sure the local server can run at http://127.0.0.1:1234.
3. Double-click TEST_LM_STUDIO.bat. It should list loaded model ids.
4. Edit .env:
   - LINE_CHANNEL_ACCESS_TOKEN
   - LINE_CHANNEL_SECRET
   - LINE_ADMIN_USER_ID / LINE_NOTIFY_USER_IDS / LINE_ACTIVE_USER_IDS
   - EMBEDDING_MODEL, exactly matching the loaded embedding model id
   - CHAT_MODEL, exactly matching one loaded chat model id shown by TEST_LM_STUDIO.bat
   - FLASK_PORT, if the default webhook port 5001 is already used on this computer
   You can double-click EDIT_BOT_CONFIG.bat to create/open .env in Notepad.
5. Double-click RUN_NTULineBot.bat.

Modes:
1 = CLI test mode.
2 = LINE webhook mode with Cloudflare tunnel.
3 = LINE webhook plus CLI.
4 = Rebuild knowledge database from PDFs in the database folder.
5 = Deployment diagnostics. Use this first when the bot can send "online" notifications
    but user messages do not reach the computer.

Important:
- Keep _internal, database, memory_data, cloudflared.exe, and NTULineBot.exe together.
- If the exe says cloudflared.exe was not found, LINE webhook modes 2/3 cannot work.
  Copy cloudflared.exe beside NTULineBot.exe or rebuild/package with package_windows_deploy.ps1.
- This package intentionally does not include the developer machine's .env secrets.
- The exe window prints the webhook port and local test URL, for example:
  Flask webhook server port: 5001
  Flask webhook local URL: http://127.0.0.1:5001/callback
- All on-site rescue settings are in .env beside NTULineBot.exe. Use EDIT_BOT_CONFIG.bat.
- To use another port, edit .env beside NTULineBot.exe:
  FLASK_PORT=5050
  Then restart RUN_NTULineBot.bat. Cloudflare and Flask will both use the new port.
- If webhook update shows 401 "Authorization header required", edit the .env file beside NTULineBot.exe and set LINE_CHANNEL_ACCESS_TOKEN. Do not edit only .env.example.
- If LM Studio does not auto-start, open LM Studio manually, enable the local server, load:
  - text-embedding-bge-small-zh-v1.5
  - the chat model named in CHAT_MODEL
- If CLI mode cannot reach LM Studio, run TEST_LM_STUDIO.bat first. The bot cannot work until all 3 tests pass.
- If Windows Defender blocks NTULineBot.exe, choose "More info" then "Run anyway", or rebuild on a trusted Windows machine with build_windows_exe.bat.

When push works but incoming LINE messages do not:
1. Double-click RUN_DEPLOYMENT_DIAGNOSTICS.bat, or run RUN_NTULineBot.bat and choose mode 5.
2. Fix any FAIL lines:
   - cloudflared FAIL: copy cloudflared.exe beside NTULineBot.exe or use the packaged deploy zip.
   - Flask port FAIL: set FLASK_PORT=5050 in .env and restart.
   - LINE webhook delivery test FAIL: run mode 2 so the bot creates a fresh Cloudflare URL and updates LINE.
3. After mode 2 starts, confirm the exe prints:
   Public URL: https://...trycloudflare.com
   Current LINE webhook setting: {"endpoint":"https://...trycloudflare.com/callback",...}
   These two URLs must match.
4. If URLs match but messages still do not arrive, check LINE Developers:
   - Webhook usage/delivery is enabled.
   - You are chatting with this exact Messaging API channel.
   - LINE_CHANNEL_SECRET in .env comes from the same channel.

On-site editable variables:
- LINE_CHANNEL_ACCESS_TOKEN: lets the bot call LINE APIs and update the webhook.
- LINE_CHANNEL_SECRET: verifies incoming LINE messages. Must match the same LINE channel.
- LINE_NOTIFY_USER_IDS / LINE_ACTIVE_USER_IDS / LINE_ADMIN_USER_ID: who receives startup/push messages and who is allowed.
- FLASK_PORT: change this if the default 5001 is occupied.
- FLASK_HOST: usually keep 0.0.0.0.
- FLASK_TUNNEL_HOST: usually keep 127.0.0.1.
- LM_STUDIO_HOST: usually http://127.0.0.1:1234.
- EMBEDDING_MODEL / CHAT_MODEL / CHAT_MODEL_KEY: must match the models loaded in LM Studio.
- LM_STUDIO_AUTO_START / LM_STUDIO_AUTO_LOAD_MODELS: set false on locked-down computers where models are loaded manually.

Prompt overrides:
- Prompts are built into the exe by default.
- You can override them from .env with UTF-8 text files beside the exe, for example:
  NORMAL_SYSTEM_PROMPT_FILE=prompts/normal_system_prompt.txt
  FIELDS_SYSTEM_PROMPT_FILE=prompts/fields_system_prompt.txt

Adding documents:
1. Put new PDF files into the database folder beside NTULineBot.exe.
2. Make sure LM Studio local server is running and the embedding model in EMBEDDING_MODEL is loaded.
3. Run RUN_NTULineBot.bat and choose mode 4.
4. The bot rebuilds combined.jsonl, metadata.json, and faiss_index.index in the same database folder.
