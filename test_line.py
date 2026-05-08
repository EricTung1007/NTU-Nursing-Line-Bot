import urllib.request
import urllib.error
import os
import json

from config import CHANNEL_ACCESS_TOKEN

LINE_WEBHOOK_ENDPOINT = "https://api.line.me/v2/bot/channel/webhook/endpoint"

def test_webhook(url):
    headers = {
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = json.dumps({"endpoint": url}).encode('utf-8')
    print(f"Testing URL: {url}")
    req = urllib.request.Request(LINE_WEBHOOK_ENDPOINT, data=payload, headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Status: {response.status}")
            print(f"Response: {response.read().decode('utf-8')}")
    except urllib.error.HTTPError as e:
        print(f"Status: {e.code}")
        print(f"Response: {e.read().decode('utf-8')}")

if __name__ == "__main__":
    test_webhook("https://decided-reception-come-broke.trycloudflare.com/callback")
    test_webhook("https://my-custom-domain-example.com/callback")
