"""
Discord webhook notifications — posts pipeline events (clip posted / failed / run
summary / metrics digest) to a Discord channel.

No-op if notifications are disabled or DISCORD_WEBHOOK_URL is unset, so it never breaks a
run. Create a webhook in Discord: Server Settings -> Integrations -> Webhooks -> New
Webhook -> Copy URL, then put it in .env as DISCORD_WEBHOOK_URL.
"""
import requests

from .config import env

GREEN = 0x2ECC71
RED = 0xE74C3C
BLURPLE = 0x5865F2


def send(content: str = "", embeds: list[dict] | None = None, enabled: bool = True) -> None:
    url = env("DISCORD_WEBHOOK_URL")
    if not enabled or not url:
        return
    payload: dict = {}
    if content:
        payload["content"] = content[:2000]
    if embeds:
        payload["embeds"] = embeds[:10]
    if not payload:
        return
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"  [discord] notify failed: {e}")


def posted_embed(title: str, url: str, creator: str, source: str,
                 narrated: bool, voice: str) -> dict:
    return {
        "title": title[:256],
        "url": url,
        "description": "✅ Posted to YouTube Shorts",
        "color": GREEN,
        "fields": [
            {"name": "Creator", "value": creator or "—", "inline": True},
            {"name": "Source", "value": source or "—", "inline": True},
            {"name": "Voiceover", "value": (f"yes · {voice}" if narrated else "no"), "inline": True},
        ],
    }
