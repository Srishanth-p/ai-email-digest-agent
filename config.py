"""
config.py – Centralised configuration loader.

Reads every setting from environment variables (populated by python-dotenv
from a .env file).  All other modules import from here instead of reading
os.environ directly, so there is exactly one place to change defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv()  # load .env into os.environ (no-op if already set)


# ──────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────

def _require(key: str) -> str:
    """Return the value of an env var, raising clearly if it is missing."""
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Check your .env file."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ──────────────────────────────────────────────────────────────
# Config dataclass
# ──────────────────────────────────────────────────────────────

@dataclass
class Config:
    # ── Email ─────────────────────────────────
    email_provider: str = field(default_factory=lambda: _optional("EMAIL_PROVIDER", "gmail").lower())
    email_address: str = field(default_factory=lambda: _require("EMAIL_ADDRESS"))
    email_app_password: str = field(default_factory=lambda: _require("EMAIL_APP_PASSWORD"))

    # IMAP overrides (used when email_provider == "imap")
    imap_host: str = field(default_factory=lambda: _optional("IMAP_HOST", "imap.gmail.com"))
    imap_port: int = field(default_factory=lambda: int(_optional("IMAP_PORT", "993")))

    # ── LLM ───────────────────────────────────
    # Provider: "ollama" (local, free) | "gemini" (free API) | "groq" (free API)
    llm_provider: str = field(default_factory=lambda: _optional("LLM_PROVIDER", "ollama").lower())

    # Ollama – local, zero cost
    ollama_base_url: str = field(default_factory=lambda: _optional("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _optional("OLLAMA_MODEL", "llama3"))

    # Gemini – free tier (15 RPM / 1 500 req/day), no billing required
    gemini_api_key: str = field(default_factory=lambda: _optional("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _optional("GEMINI_MODEL", "gemini-2.0-flash-lite"))

    # Groq – free tier (14 400 req/day on Llama-3 / Mixtral), no billing required
    groq_api_key: str = field(default_factory=lambda: _optional("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _optional("GROQ_MODEL", "llama-3.1-8b-instant"))

    # ── Notifications ─────────────────────────
    notification_provider: str = field(default_factory=lambda: _optional("NOTIFICATION_PROVIDER", "telegram").lower())
    telegram_bot_token: str = field(default_factory=lambda: _optional("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _optional("TELEGRAM_CHAT_ID"))
    discord_webhook_url: str = field(default_factory=lambda: _optional("DISCORD_WEBHOOK_URL"))

    # ── Scheduler ─────────────────────────────
    schedule_times: List[str] = field(default_factory=lambda: [
        t.strip() for t in _optional("SCHEDULE_TIMES", "08:00,20:00").split(",") if t.strip()
    ])
    timezone: str = field(default_factory=lambda: _optional("TIMEZONE", "Asia/Kolkata"))

    # ── Processing ────────────────────────────
    lookback_hours: int = field(default_factory=lambda: int(_optional("LOOKBACK_HOURS", "12")))
    max_emails_per_run: int = field(default_factory=lambda: int(_optional("MAX_EMAILS_PER_RUN", "20")))
    gmail_processed_label: str = field(default_factory=lambda: _optional("GMAIL_PROCESSED_LABEL", "Processed_by_Agent"))
    max_body_chars: int = field(default_factory=lambda: int(_optional("MAX_BODY_CHARS", "2000")))

    def validate(self) -> None:
        """Raise EnvironmentError early if critical settings are missing."""
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY must be set when LLM_PROVIDER=gemini. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise EnvironmentError(
                "GROQ_API_KEY must be set when LLM_PROVIDER=groq. "
                "Get a free key at https://console.groq.com"
            )
        if self.notification_provider == "telegram":
            if not self.telegram_bot_token or not self.telegram_chat_id:
                raise EnvironmentError(
                    "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set when "
                    "NOTIFICATION_PROVIDER=telegram."
                )
        if self.notification_provider == "discord" and not self.discord_webhook_url:
            raise EnvironmentError(
                "DISCORD_WEBHOOK_URL must be set when NOTIFICATION_PROVIDER=discord."
            )


# Singleton – import `cfg` everywhere instead of re-instantiating.
cfg = Config()
