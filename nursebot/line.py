"""LINE Messaging API client (reply, push, webhook management, signature check)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Optional

import requests

from .settings import Settings

log = logging.getLogger("line")
API = "https://api.line.me/v2/bot"
WEBHOOK_EP = f"{API}/channel/webhook/endpoint"
WEBHOOK_TEST = f"{API}/channel/webhook/test"
MAX_TEXT = 5000  # LINE text message limit


class LineClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.s.get('line_channel_access_token')}",
                "Content-Type": "application/json"}

    def verify_signature(self, body: bytes, signature: str) -> bool:
        secret = self.s.get("line_channel_secret").encode("utf-8")
        expected = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected, signature or "")

    def _post(self, url: str, payload: dict) -> bool:
        if not self.s.line_ready():
            log.warning("LINE credentials not set; message not sent")
            return False
        try:
            r = self.http.post(url, headers=self._headers(), json=payload, timeout=15)
        except requests.RequestException as e:
            log.error("LINE request failed: %s", e)
            return False
        if r.status_code != 200:
            log.error("LINE API %s: %s", r.status_code, r.text[:300])
        return r.status_code == 200

    def reply(self, token: str, text: str) -> bool:
        return self._post(f"{API}/message/reply",
                          {"replyToken": token, "messages": [{"type": "text", "text": text[:MAX_TEXT]}]})

    def push(self, user_id: str, text: str) -> bool:
        return self._post(f"{API}/message/push",
                          {"to": user_id, "messages": [{"type": "text", "text": text[:MAX_TEXT]}]})

    def set_webhook(self, endpoint: str) -> bool:
        try:
            r = self.http.put(WEBHOOK_EP, headers=self._headers(), json={"endpoint": endpoint}, timeout=15)
            return r.status_code == 200
        except requests.RequestException as e:
            log.warning("set webhook failed: %s", e)
            return False

    def test_webhook(self, endpoint: str) -> bool:
        try:
            r = self.http.post(WEBHOOK_TEST, headers=self._headers(), json={"endpoint": endpoint}, timeout=15)
            return r.status_code == 200 and bool(r.json().get("success", True))
        except (requests.RequestException, ValueError):
            return False

    def bot_name(self) -> Optional[str]:
        """Credential check used by the GUI 'test connection' button."""
        try:
            r = self.http.get(f"{API}/info", headers=self._headers(), timeout=10)
            return r.json().get("displayName") if r.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None
