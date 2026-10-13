from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    delivered: bool
    error: str | None = None


class WebhookNotifier:
    def __init__(self, channels: dict[str, str | None], timeout: float = 3.0):
        self.channels = channels
        self.timeout = timeout

    def send(self, title: str, content: str) -> list[NotificationResult]:
        results: list[NotificationResult] = []
        for channel, url in self.channels.items():
            if not url:
                continue
            payload = {"msg_type": "text", "content": {"text": f"{title}\n{content}"}}
            if channel == "dingtalk":
                payload = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
            elif channel == "wecom":
                payload = {"msgtype": "text", "text": {"content": f"{title}\n{content}"}}
            try:
                request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    results.append(NotificationResult(channel, 200 <= response.status < 300))
            except Exception as exc:  # noqa: BLE001 - notification failure must not crash command path
                results.append(NotificationResult(channel, False, type(exc).__name__))
        return results
