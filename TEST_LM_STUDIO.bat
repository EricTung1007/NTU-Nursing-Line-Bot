@echo off
cd /d "%~dp0"
chcp 65001 >nul
title Test LM Studio API

set "LM_STUDIO_HOST=http://127.0.0.1:1234"
set "CHAT_MODEL="
set "EMBEDDING_MODEL=text-embedding-bge-small-zh-v1.5"

if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="LM_STUDIO_HOST" set "LM_STUDIO_HOST=%%B"
        if /i "%%A"=="CHAT_MODEL" set "CHAT_MODEL=%%B"
        if /i "%%A"=="EMBEDDING_MODEL" set "EMBEDDING_MODEL=%%B"
    )
)

echo Testing LM Studio OpenAI-compatible API...
echo Host: %LM_STUDIO_HOST%
echo Chat model: %CHAT_MODEL%
echo Embedding model: %EMBEDDING_MODEL%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$hostUrl = '%LM_STUDIO_HOST%'.TrimEnd('/'); $chatModel = '%CHAT_MODEL%'; $embedModel = '%EMBEDDING_MODEL%';" ^
  "'[1/3] GET /v1/models';" ^
  "try { $r = Invoke-RestMethod -Uri ($hostUrl + '/v1/models') -TimeoutSec 8; 'OK: LM Studio API reachable.'; 'Loaded model ids:'; $r.data | ForEach-Object { ' - ' + $_.id } } catch { 'FAIL: /v1/models not reachable'; $_.Exception.Message; exit 1 };" ^
  "''; '[2/3] POST /v1/embeddings';" ^
  "try { $body = @{ model = $embedModel; input = 'test' } | ConvertTo-Json; $e = Invoke-RestMethod -Method Post -Uri ($hostUrl + '/v1/embeddings') -ContentType 'application/json' -Body $body -TimeoutSec 30; 'OK: embedding endpoint works. Vector length: ' + $e.data[0].embedding.Count } catch { 'FAIL: embedding endpoint failed'; $_.Exception.Message; if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message }; exit 2 };" ^
  "''; '[3/3] POST /v1/chat/completions';" ^
  "if ([string]::IsNullOrWhiteSpace($chatModel) -or $chatModel -like 'your_loaded*') { 'FAIL: CHAT_MODEL is empty or still placeholder in .env'; exit 3 };" ^
  "try { $body = @{ model = $chatModel; messages = @(@{ role = 'user'; content = 'reply with OK only' }); max_tokens = 8; temperature = 0 } | ConvertTo-Json -Depth 5; $c = Invoke-RestMethod -Method Post -Uri ($hostUrl + '/v1/chat/completions') -ContentType 'application/json' -Body $body -TimeoutSec 60; 'OK: chat endpoint works. Reply: ' + $c.choices[0].message.content } catch { 'FAIL: chat endpoint failed'; $_.Exception.Message; if ($_.ErrorDetails.Message) { $_.ErrorDetails.Message }; exit 4 }"

echo.
echo If all 3 tests pass but the bot still fails, send me the bot error text.
echo.
pause
