"""
notifier.py – Send the email digest to a mobile device.

Supported channels:
  • Telegram  (via Bot API)   – preferred
  • Discord   (via Webhook)   – fallback

Uses Telegram's HTML parse mode for reliable formatting (bold, italic,
code blocks) — more stable than Markdown which breaks on special characters.
"""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime
from typing import Dict, List, Any

import pytz
import requests

from config import cfg
from llm_processor import CATEGORIES

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Character limits
# ──────────────────────────────────────────────

TELEGRAM_MAX_CHARS = 4096   # Telegram hard limit per message
DISCORD_MAX_CHARS  = 2000   # Discord webhook content limit

# ──────────────────────────────────────────────
# HTML helpers (Telegram HTML parse mode)
# ──────────────────────────────────────────────

def _e(text: str) -> str:
    """Escape a plain string for safe use inside Telegram HTML."""
    return html.escape(str(text))


def _b(text: str) -> str:
    """Bold."""
    return f"<b>{_e(text)}</b>"


def _i(text: str) -> str:
    """Italic."""
    return f"<i>{_e(text)}</i>"


def _divider() -> str:
    return "---"


# ──────────────────────────────────────────────
# Digest builder
# ──────────────────────────────────────────────

def _greeting_header() -> str:
    """Return a header with time label and date — no emojis."""
    tz   = pytz.timezone(cfg.timezone)
    now  = datetime.now(tz)
    hour = now.hour
    if 5 <= hour < 12:
        label = "Morning"
    elif 12 <= hour < 18:
        label = "Afternoon"
    else:
        label = "Evening"
    time_str = now.strftime("%I:%M %p")
    date_str = now.strftime("%a, %d %b %Y")
    return (
        f"{_b(f'{label} Email Digest')}\n"
        f"<i>{date_str} - {time_str}</i>"
    )


def build_digest(grouped: Dict[str, List[Dict[str, Any]]], total_unread: int = 0) -> str:
    """
    Build a clean, structured HTML digest for Telegram.

    Layout per email:
        N. Sender name
        <i>Subject line</i>
        Summary sentence.
    """
    lines: List[str] = [_greeting_header(), ""]

    processed = sum(len(v) for v in grouped.values())
    skipped   = total_unread - processed

    if processed == 0 and total_unread == 0:
        lines.append("No unread emails in your inbox.")
        lines.append("")
        lines.append(_divider())
        lines.append("Sent by Email Agent")
        return "\n".join(lines)

    lines.append(f"{_b(f'{processed} email(s) summarised')}")
    if skipped > 0:
        lines.append(f"{_b(f'{skipped} older unread email(s) not processed')} - run again to catch up.")
    lines.append("")

    global_idx = 1  # continuous numbering across all categories

    for cat_id, label in CATEGORIES.items():
        emails = grouped.get(cat_id, [])
        if not emails:
            continue

        # Category header: bold name + count
        lines.append(f"{_b(f'{label} ({len(emails)})')}")
        lines.append("")

        # Marketing: collapse if more than 2
        if cat_id == "MARKETING" and len(emails) > 2:
            lines.append(f"{global_idx}. {_i(f'{len(emails)} promotional emails - skipped.')}")
            global_idx += len(emails)
        else:
            for em in emails:
                sender  = em.get("sender", "Unknown").split("<")[0].strip()
                subject = em.get("subject", "(No subject)")
                summary = em.get("summary", "")

                if len(sender)  > 35: sender  = sender[:32]  + "..."
                if len(subject) > 60: subject = subject[:57] + "..."

                lines.append(f"{global_idx}. {_b(sender)}")
                lines.append(_i(subject))
                lines.append(_e(summary))
                lines.append("")
                global_idx += 1

        lines.append(_divider())
        lines.append("")

    lines.append("Sent by Email Agent")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Channel senders
# ──────────────────────────────────────────────

def _split_message(text: str, limit: int) -> List[str]:
    """Split a long message into chunks that fit within `limit` characters."""
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    while text:
        chunk = text[:limit]
        split_at = chunk.rfind("\n")
        if split_at > limit // 2:
            chunk = text[:split_at]
        parts.append(chunk)
        text = text[len(chunk):].lstrip("\n")
    return parts


def _send_telegram(text: str) -> None:
    """Send a message (or multiple parts) via the Telegram Bot API using HTML formatting."""
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    for part in _split_message(text, TELEGRAM_MAX_CHARS):
        payload = {
            "chat_id":    cfg.telegram_chat_id,
            "text":       part,
            "parse_mode": "HTML",
        }
        # Retry up to 3 times on transient network / SSL errors
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, timeout=20)
                if not resp.ok:
                    log.error("Telegram API error %s: %s", resp.status_code, resp.text)
                    resp.raise_for_status()
                break  # success — move to next part
            except requests.exceptions.SSLError as exc:
                log.warning("Telegram SSL error (attempt %d/3): %s", attempt, exc)
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)  # 5s, 10s then give up
            except requests.exceptions.ConnectionError as exc:
                log.warning("Telegram connection error (attempt %d/3): %s", attempt, exc)
                if attempt == 3:
                    raise
                time.sleep(5 * attempt)
    log.info("Telegram notification sent.")


def _send_discord(text: str) -> None:
    """Send a message (or multiple parts) via a Discord Webhook."""
    for part in _split_message(text, DISCORD_MAX_CHARS):
        payload = {"content": part}
        resp = requests.post(cfg.discord_webhook_url, json=payload, timeout=15)
        if not resp.ok:
            log.error("Discord webhook error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
    log.info("Discord notification sent.")


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def send_digest(grouped: Dict[str, List[Dict[str, Any]]], total_unread: int = 0) -> None:
    """
    Build the digest from grouped emails and dispatch it to the configured
    notification provider.  Raises on fatal delivery errors.
    """
    digest_text = build_digest(grouped, total_unread=total_unread)
    log.debug("Digest content:\n%s", digest_text)

    provider = cfg.notification_provider
    if provider == "telegram":
        _send_telegram(digest_text)
    elif provider == "discord":
        _send_discord(digest_text)
    else:
        raise ValueError(
            f"Unknown NOTIFICATION_PROVIDER='{provider}'. "
            "Choose 'telegram' or 'discord'."
        )
