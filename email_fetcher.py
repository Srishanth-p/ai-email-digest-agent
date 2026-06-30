"""
email_fetcher.py – Fetch unread emails from Gmail (IMAP with App Password).

Supports:
  • Gmail via IMAP + App Password (default, no OAuth dance needed)
  • Any generic IMAP server

fetch_unread_emails() returns a tuple: (emails, total_unread)
  - emails       : list of dicts for the processed batch (capped at MAX_EMAILS_PER_RUN)
  - total_unread : full count of unread messages found before the cap

This allows the digest to warn the user when there are more unread emails
than were processed in this run.

Each email dict contains:
    uid        – bytes  : IMAP UID for marking read / labelling
    message_id – str    : RFC-2822 Message-ID header
    sender     – str    : "Name <addr>" or bare address
    subject    – str    : decoded subject line
    date       – str    : raw Date header value
    body       – str    : plain-text body (HTML stripped), truncated to MAX_BODY_CHARS
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from email.header import decode_header
from typing import List, Dict, Any, Optional, Tuple

from bs4 import BeautifulSoup

from config import cfg

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
INBOX = "INBOX"

GMAIL_LABEL = cfg.gmail_processed_label


# ──────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────

def _decode_mime_words(raw: str) -> str:
    """Decode RFC-2047 encoded header values (e.g. =?utf-8?b?...?=)."""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded_parts: List[str] = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts).strip()


def _html_to_text(html: str) -> str:
    """Strip HTML tags and return readable plain text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _extract_body(msg: email.message.Message) -> str:
    """
    Walk a MIME message and return the best plain-text representation.
    Prefer text/plain; fall back to stripping text/html.
    """
    plain: Optional[str] = None
    html_body: Optional[str] = None

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            if ct == "text/plain" and plain is None:
                plain = part.get_payload(decode=True).decode(charset, errors="replace")
            elif ct == "text/html" and html_body is None:
                html_body = part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        ct = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            payload = payload.decode(charset, errors="replace")
        if ct == "text/plain":
            plain = payload
        elif ct == "text/html":
            html_body = payload

    body = plain if plain else (_html_to_text(html_body) if html_body else "")
    return body[: cfg.max_body_chars].strip()


# ──────────────────────────────────────────────
# IMAP connection
# ──────────────────────────────────────────────

def _connect() -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP4_SSL connection."""
    host = GMAIL_IMAP_HOST if cfg.email_provider == "gmail" else cfg.imap_host
    port = GMAIL_IMAP_PORT if cfg.email_provider == "gmail" else cfg.imap_port

    log.info("Connecting to IMAP server %s:%s …", host, port)
    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(cfg.email_address, cfg.email_app_password)
    log.info("Authenticated as %s", cfg.email_address)
    return conn


# ──────────────────────────────────────────────
# Gmail label helper
# ──────────────────────────────────────────────

def _ensure_gmail_label(conn: imaplib.IMAP4_SSL, label: str) -> bool:
    if not label:
        return False
    try:
        conn.create(label)
    except Exception:
        pass
    status, data = conn.list('""', label)
    return status == "OK" and data and data[0] is not None


def _apply_gmail_label(conn: imaplib.IMAP4_SSL, uid: bytes, label: str) -> None:
    if not label:
        return
    try:
        conn.uid("COPY", uid, label)
    except Exception as exc:
        log.warning("Could not apply label '%s' to UID %s: %s", label, uid, exc)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def fetch_unread_emails() -> Tuple[List[Dict[str, Any]], int]:
    """
    Fetch ALL unread emails, cap at MAX_EMAILS_PER_RUN (newest first).
    Marks only the fetched batch as read; skipped emails stay unread
    so the next run (or the user) can still see them.

    Returns:
        emails       – list of processed email dicts
        total_unread – total unread count before the cap was applied
    """
    conn = _connect()
    emails: List[Dict[str, Any]] = []
    total_unread = 0

    try:
        conn.select(INBOX)

        # Search for ALL unread — no time filter
        log.info("Searching inbox for all unread messages …")
        status, data = conn.uid("SEARCH", None, "UNSEEN")

        if status != "OK" or not data or not data[0]:
            log.info("No unread messages found.")
            return [], 0

        all_uids: List[bytes] = data[0].split()
        total_unread = len(all_uids)
        log.info("Found %d unread message(s) total.", total_unread)

        # IMAP returns UIDs oldest→newest; take the last N to get the newest
        cap = cfg.max_emails_per_run
        uids_to_process = all_uids[-cap:]
        if total_unread > cap:
            log.warning(
                "Capping at %d (found %d). The %d oldest unread emails stay unread.",
                cap, total_unread, total_unread - cap,
            )

        # Ensure processed label exists (Gmail only)
        label_usable = False
        if cfg.email_provider == "gmail" and GMAIL_LABEL:
            label_usable = _ensure_gmail_label(conn, GMAIL_LABEL)

        for uid in uids_to_process:
            try:
                fetch_status, msg_data = conn.uid("FETCH", uid, "(RFC822)")
                if fetch_status != "OK" or not msg_data or msg_data[0] is None:
                    log.warning("Failed to fetch UID %s", uid)
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                email_dict: Dict[str, Any] = {
                    "uid": uid,
                    "message_id": msg.get("Message-ID", "").strip(),
                    "sender": _decode_mime_words(msg.get("From", "")),
                    "subject": _decode_mime_words(msg.get("Subject", "(No subject)")),
                    "date": msg.get("Date", ""),
                    "body": _extract_body(msg),
                }
                emails.append(email_dict)

                # Mark as read — only emails we actually processed
                conn.uid("STORE", uid, "+FLAGS", r"(\Seen)")

                # Apply custom label (Gmail only)
                if cfg.email_provider == "gmail" and label_usable:
                    _apply_gmail_label(conn, uid, GMAIL_LABEL)

                time.sleep(0.05)  # gentle throttle

            except Exception as exc:
                log.error("Error processing UID %s: %s", uid, exc, exc_info=True)
                continue

    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass

    log.info("Fetched and processed %d/%d email(s).", len(emails), total_unread)
    return emails, total_unread
