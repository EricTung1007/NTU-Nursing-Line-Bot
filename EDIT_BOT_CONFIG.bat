@echo off
cd /d "%~dp0"
chcp 65001 >nul
title NTU Nursing LINE Bot - Edit Config

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo Created .env from .env.example.
    ) else (
        echo # LINE Bot Credentials>.env
        echo LINE_CHANNEL_ACCESS_TOKEN=your_channel_access_token_here>>.env
        echo LINE_CHANNEL_SECRET=your_channel_secret_here>>.env
        echo LINE_ADMIN_USER_ID=>>.env
        echo LINE_NOTIFY_USER_IDS=>>.env
        echo LINE_ACTIVE_USER_IDS=>>.env
        echo.>>.env
        echo # LM Studio>>.env
        echo LM_STUDIO_HOST=http://127.0.0.1:1234>>.env
        echo EMBEDDING_MODEL=text-embedding-bge-small-zh-v1.5>>.env
        echo CHAT_MODEL=your_loaded_chat_model_id_here>>.env
        echo CHAT_MODEL_KEY=>>.env
        echo.>>.env
        echo # Webhook server>>.env
        echo FLASK_PORT=5001>>.env
        echo FLASK_HOST=0.0.0.0>>.env
        echo FLASK_TUNNEL_HOST=127.0.0.1>>.env
        echo.>>.env
        echo LM_STUDIO_AUTO_START=false>>.env
        echo LM_STUDIO_AUTO_LOAD_MODELS=false>>.env
        echo Created fallback .env.
    )
)

echo Opening .env in Notepad. Save the file, close Notepad, then restart the bot.
notepad .env
