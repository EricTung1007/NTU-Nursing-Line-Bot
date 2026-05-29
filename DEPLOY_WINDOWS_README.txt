NTU Nursing LINE Bot - Windows deployment

Target computer requirement:
- Windows
- LM Studio installed
- The required embedding and chat models downloaded in LM Studio

Start:
1. Extract this whole folder. Do not run NTULineBot.exe from inside the zip.
2. Open LM Studio and make sure the local server can run at http://127.0.0.1:1234.
3. Double-click TEST_LM_STUDIO.bat. It should list loaded model ids.
4. Edit .env:
   - LINE_CHANNEL_ACCESS_TOKEN
   - LINE_CHANNEL_SECRET
   - LINE_ADMIN_USER_ID / LINE_NOTIFY_USER_IDS / LINE_ACTIVE_USER_IDS
   - EMBEDDING_MODEL, exactly matching the loaded embedding model id
   - CHAT_MODEL, exactly matching one loaded chat model id shown by TEST_LM_STUDIO.bat
5. Double-click RUN_NTULineBot.bat.

Modes:
1 = CLI test mode.
2 = LINE webhook mode with Cloudflare tunnel.
3 = LINE webhook plus CLI.

Important:
- Keep _internal, database, memory_data, cloudflared.exe, and NTULineBot.exe together.
- This package intentionally does not include the developer machine's .env secrets.
- If LM Studio does not auto-start, open LM Studio manually, enable the local server, load:
  - text-embedding-bge-small-zh-v1.5
  - the chat model named in CHAT_MODEL
- If CLI mode cannot reach LM Studio, run TEST_LM_STUDIO.bat first. The bot cannot work until all 3 tests pass.
- If Windows Defender blocks NTULineBot.exe, choose "More info" then "Run anyway", or rebuild on a trusted Windows machine with build_windows_exe.bat.
