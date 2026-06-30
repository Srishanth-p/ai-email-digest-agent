"""
llm_processor.py – AI-powered email categorization and summarization.

Supports (all 100 % free):
  • Ollama  – fully local, offline, no account needed (default)
             Install: https://ollama.com  →  ollama pull llama3
  • Gemini  – Google Gemini 2.0 Flash via REST API
             Free tier: 15 RPM / 1 500 req/day / 1 M tokens/day, no card needed
             Get key:   https://aistudio.google.com/apikey
  • Groq    – Llama-3/Mixtral hosted on Groq Cloud (free tier: 14 400 req/day)
             Get key:   https://console.groq.com

A single LLM call per email handles BOTH categorization and summarization.

Category IDs returned by the LLM are normalized to one of:
    PLACEMENT  – Campus Placements & Career
    NEWSLETTER – Newsletters & Tech Digests
    MARKETING  – Advertisements & Marketing
    GENERAL    – General / Miscellaneous
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, Any, List

from config import cfg

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Category constants
# ──────────────────────────────────────────────

CATEGORIES = {
    "PLACEMENT":  "Campus Placements & Career",
    "NEWSLETTER": "Newsletters & Tech Digests",
    "MARKETING":  "Advertisements & Marketing",
    "GENERAL":    "General / Miscellaneous",
}

CATEGORY_EMOJI = {
    "PLACEMENT":  "🎓",
    "NEWSLETTER": "📰",
    "MARKETING":  "🏷️",
    "GENERAL":    "📬",
}

# ──────────────────────────────────────────────
# Prompt template
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an email analysis assistant. Your job is to read an email and return a JSON object with exactly two keys:
- "category": one of PLACEMENT, NEWSLETTER, MARKETING, GENERAL
- "summary": a single concise bullet-point sentence (max 25 words) capturing the core action item or key takeaway.

Category definitions:
  PLACEMENT  – job offers, internships, campus placements, interviews, career fairs, LinkedIn/recruiter messages
  NEWSLETTER – tech digests, blogs, educational content, weekly roundups
  MARKETING  – promotional deals, advertisements, discount codes, sales
  GENERAL    – everything else (receipts, OTPs, social, personal, admin)

Respond ONLY with the raw JSON object. No markdown, no explanation.
Example: {"category": "PLACEMENT", "summary": "Google scheduled a technical round for Friday at 3 PM – action required."}
"""

USER_PROMPT_TEMPLATE = """\
From: {sender}
Subject: {subject}
Date: {date}

Body:
{body}
"""

# ──────────────────────────────────────────────
# LLM backends  (all free)
# ──────────────────────────────────────────────

def _call_ollama(user_content: str) -> str:
    """
    Call a local Ollama model via its OpenAI-compatible /v1/chat endpoint.
    Ollama is 100% free and runs entirely on your own machine.
    Install: https://ollama.com  then:  ollama pull llama3
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("Run: pip install openai") from exc

    client = OpenAI(
        base_url=f"{cfg.ollama_base_url.rstrip('/')}/v1",
        api_key="ollama",   # Ollama ignores the key value
    )
    resp = client.chat.completions.create(
        model=cfg.ollama_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.2,
        max_tokens=120,
        timeout=60,
    )
    return resp.choices[0].message.content.strip()


def _call_gemini(user_content: str) -> str:
    """
    Call Google Gemini 2.0 Flash via the generateContent REST endpoint.
    Free tier: 15 RPM, 1 500 req/day, 1 M tokens/day — no billing required.
    Get a free key at: https://aistudio.google.com/apikey
    """
    import requests as _req

    model = cfg.gemini_model   # e.g. "gemini-2.0-flash"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={cfg.gemini_api_key}"
    )
    # Gemini REST API has no separate system role; prepend into the user turn.
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_content}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 120},
    }
    resp = _req.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_groq(user_content: str) -> str:
    """
    Call Groq Cloud via its OpenAI-compatible endpoint.
    Free tier: 14 400 req/day on Llama-3-8B / Mixtral — no billing required.
    Get a free key at: https://console.groq.com
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("Run: pip install openai") from exc

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=cfg.groq_api_key,
    )
    resp = client.chat.completions.create(
        model=cfg.groq_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.2,
        max_tokens=120,
        timeout=30,
    )
    return resp.choices[0].message.content.strip()


# ──────────────────────────────────────────────
# Core analysis function
# ──────────────────────────────────────────────

def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception looks like an HTTP 429 Too Many Requests."""
    msg = str(exc)
    return "429" in msg or "Too Many Requests" in msg or "RESOURCE_EXHAUSTED" in msg


def _call_llm(user_content: str, retries: int = 4) -> Dict[str, str]:
    """
    Dispatch to the configured free LLM backend and parse the JSON response.

    Back-off strategy:
      • 429 / rate-limit errors  → wait 60 s before retrying (respects the RPM window)
      • Any other transient error → exponential back-off: 5 s, 10 s, 20 s
    """
    provider = cfg.llm_provider

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if provider == "ollama":
                raw = _call_ollama(user_content)
            elif provider == "gemini":
                raw = _call_gemini(user_content)
            elif provider == "groq":
                raw = _call_groq(user_content)
            else:
                raise ValueError(
                    f"Unknown LLM_PROVIDER='{provider}'. "
                    "Choose 'ollama', 'gemini', or 'groq'."
                )

            # Strip accidental markdown code fences that some models add
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            category = parsed.get("category", "GENERAL").upper()
            if category not in CATEGORIES:
                category = "GENERAL"
            summary = parsed.get("summary", "No summary available.").strip()
            return {"category": category, "summary": summary}

        except json.JSONDecodeError as exc:
            log.warning("Attempt %d – LLM returned non-JSON: %s", attempt, exc)
            last_exc = exc
            time.sleep(5 * attempt)
        except Exception as exc:
            log.warning("Attempt %d – LLM API error: %s", attempt, exc)
            last_exc = exc
            if _is_rate_limit_error(exc):
                wait = 65  # wait out the full 1-minute RPM window + 5 s buffer
                log.warning("Rate limit hit – waiting %d s before retry …", wait)
                time.sleep(wait)
            else:
                time.sleep(5 * attempt)  # 5s, 10s, 15s for other errors

    log.error("LLM failed after %d attempts: %s", retries, last_exc)
    return {"category": "GENERAL", "summary": "Could not summarise this email (LLM error)."}


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def analyze_email(email_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich a single email dict with 'category' and 'summary' keys.
    Returns the original dict updated in-place (also returned for convenience).
    """
    user_content = USER_PROMPT_TEMPLATE.format(
        sender=email_dict.get("sender", "Unknown"),
        subject=email_dict.get("subject", "(No subject)"),
        date=email_dict.get("date", ""),
        body=email_dict.get("body", ""),
    )

    result = _call_llm(user_content)
    email_dict["category"] = result["category"]
    email_dict["summary"]  = result["summary"]
    log.debug("Analyzed: [%s] %s → %s", result["category"], email_dict["subject"], result["summary"])
    return email_dict


def analyze_emails(email_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze a list of email dicts sequentially with provider-appropriate pacing."""
    for i, em in enumerate(email_list, start=1):
        log.info("Analyzing email %d/%d: '%s'", i, len(email_list), em.get("subject", ""))
        analyze_email(em)
        if i < len(email_list):
            # Gemini free tier: 15 RPM (flash) / 30 RPM (flash-lite)
            # 6 s gap → max 10 req/min → safely under both limits.
            # Ollama: local, no limit. Groq: 14 400 req/day, 1 s is fine.
            time.sleep(6.0 if cfg.llm_provider == "gemini" else 1.0)
    return email_list


def group_by_category(email_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Return a dict of {category_id: [email, ...]} preserving CATEGORIES order."""
    groups: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in CATEGORIES}
    for em in email_list:
        cat = em.get("category", "GENERAL")
        groups.setdefault(cat, []).append(em)
    return groups
