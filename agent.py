"""
agent.py – Main entry point for the Email Agent.

Responsibilities:
  1. Validate configuration on startup.
  2. Define the pipeline: fetch → analyse → group → notify.
  3. Schedule the pipeline to run at configured times (default 8 AM & 8 PM).
  4. Provide a --run-now CLI flag for immediate one-shot execution (testing).

Usage:
    python agent.py               # start scheduler (blocking)
    python agent.py --run-now     # run pipeline once immediately, then exit
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import cfg
from email_fetcher import fetch_unread_emails
from llm_processor import analyze_emails, group_by_category
from notifier import send_digest

# ──────────────────────────────────────────────
# Logging setup
# ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("agent")


# ──────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────

def run_pipeline() -> None:
    """
    Full pipeline execution:
      1. Fetch all unread emails (capped at MAX_EMAILS_PER_RUN).
      2. Analyse each email with the LLM (categorize + summarize).
      3. Group by category.
      4. Send digest notification (includes overflow warning if capped).

    Safe to call even when the inbox is empty or the network is unavailable.
    """
    tz  = pytz.timezone(cfg.timezone)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    log.info("═" * 50)
    log.info("Pipeline started at %s", now)

    try:
        # ── Step 1: Fetch ──────────────────────────────
        log.info("STEP 1/3 – Fetching unread emails …")
        emails, total_unread = fetch_unread_emails()
        log.info("Fetched %d/%d email(s).", len(emails), total_unread)

        # ── Step 2: Analyse ────────────────────────────
        if emails:
            log.info("STEP 2/3 – Analysing emails with LLM …")
            analyze_emails(emails)
        else:
            log.info("STEP 2/3 – Skipped (inbox empty).")

        # ── Step 3: Notify ─────────────────────────────
        log.info("STEP 3/3 – Sending digest notification …")
        grouped = group_by_category(emails)
        send_digest(grouped, total_unread=total_unread)

    except Exception as exc:
        log.error("Pipeline failed: %s", exc, exc_info=True)
        # Attempt a failure notification so you know something went wrong
        try:
            _send_error_notification(str(exc))
        except Exception:
            pass  # If notification also fails, just log it – don't crash

    log.info("Pipeline finished.")
    log.info("═" * 50)


def _send_error_notification(error: str) -> None:
    """Send a brief error alert via the configured channel."""
    from notifier import _send_telegram, _send_discord  # local import to avoid circular
    msg = (
        "⚠️ *Email Agent Error*\n"
        f"The pipeline encountered an error:\n`{error[:300]}`\n\n"
        "_Check agent.log for full details._"
    )
    if cfg.notification_provider == "telegram":
        _send_telegram(msg)
    elif cfg.notification_provider == "discord":
        _send_discord(msg)


# ──────────────────────────────────────────────
# Scheduler
# ──────────────────────────────────────────────

def start_scheduler() -> None:
    """
    Configure APScheduler with a CronTrigger for each time in SCHEDULE_TIMES
    and block until interrupted (Ctrl-C or SIGTERM).
    """
    scheduler = BlockingScheduler(timezone=cfg.timezone)

    for time_str in cfg.schedule_times:
        try:
            hour, minute = time_str.strip().split(":")
            trigger = CronTrigger(
                hour=int(hour),
                minute=int(minute),
                timezone=cfg.timezone,
            )
            scheduler.add_job(
                run_pipeline,
                trigger=trigger,
                id=f"email_digest_{time_str.replace(':', '')}",
                name=f"Email digest at {time_str}",
                max_instances=1,
                misfire_grace_time=300,  # allow up to 5-min late start
            )
            log.info("Scheduled pipeline at %s (%s)", time_str, cfg.timezone)
        except ValueError:
            log.error("Invalid SCHEDULE_TIMES entry: '%s'. Expected HH:MM.", time_str)
            sys.exit(1)

    log.info("Scheduler running. Press Ctrl-C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


# ──────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI-driven email digest agent.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the pipeline once immediately and exit (useful for testing).",
    )
    args = parser.parse_args()

    log.info("Email Agent starting up …")
    log.info("Provider: email=%s  llm=%s  notify=%s",
             cfg.email_provider, cfg.llm_provider, cfg.notification_provider)

    # Validate all required settings before doing anything
    try:
        cfg.validate()
    except EnvironmentError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)

    if args.run_now:
        log.info("--run-now flag detected. Running pipeline once …")
        run_pipeline()
    else:
        start_scheduler()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Last-resort crash handler — catches errors that happen before
        # logging is initialised (e.g. import errors, missing .env).
        import traceback, os
        crash_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"\nFATAL ERROR: {exc}")
        print(f"Full traceback written to: {crash_path}")
        input("\nPress Enter to close …")
        sys.exit(1)
