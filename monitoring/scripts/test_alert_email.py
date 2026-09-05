#!/usr/bin/env python3
"""
Fire a synthetic alert straight into Alertmanager's API so you can confirm
the email pipeline (SMTP -> dssiitbhu@gmail.com, see alertmanager.yml) is
actually delivering, without needing to genuinely max out CPU/disk/memory.

Usage:
    python3 test_alert_email.py                       # fire + auto-resolve after 30s
    python3 test_alert_email.py --no-resolve           # leave it firing
    python3 test_alert_email.py --resolve-only         # resolve a previously fired test alert
    python3 test_alert_email.py --url http://monitor.slcrdss.in:9093
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

import requests

DEFAULT_ALERTMANAGER_URL = "http://localhost:9093"
ALERTNAME = "TestAlertEmailCheck"


def build_alert(resolved: bool, hold_seconds: int) -> dict:
    now = datetime.now(timezone.utc)
    starts_at = now - timedelta(seconds=hold_seconds if resolved else 0)
    alert = {
        "labels": {
            "alertname": ALERTNAME,
            "severity": "warning",
            "instance": "manual-test:9100",
            "job": "test-script",
        },
        "annotations": {
            "summary": "Manual test alert to verify email delivery",
            "description": "This alert was fired by test_alert_email.py to confirm "
            "Alertmanager -> SMTP -> inbox is working end to end.",
        },
        "startsAt": starts_at.isoformat(),
        "generatorURL": "http://localhost/test_alert_email.py",
    }
    if resolved:
        alert["endsAt"] = now.isoformat()
    return alert


def post_alert(base_url: str, alert: dict) -> None:
    resp = requests.post(f"{base_url}/api/v2/alerts", json=[alert], timeout=10)
    resp.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_ALERTMANAGER_URL, help="Alertmanager base URL (default: %(default)s)")
    parser.add_argument("--no-resolve", action="store_true", help="Only fire the alert, don't send a resolved follow-up")
    parser.add_argument("--resolve-only", action="store_true", help="Only send the resolved follow-up (e.g. after using --no-resolve)")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    try:
        if args.resolve_only:
            print(f"Sending RESOLVED for '{ALERTNAME}' to {base_url} ...")
            post_alert(base_url, build_alert(resolved=True, hold_seconds=60))
            print("Resolved alert sent. Since send_resolved=true, a resolution email should arrive too.")
            return 0

        print(f"Firing test alert '{ALERTNAME}' to {base_url} ...")
        post_alert(base_url, build_alert(resolved=False, hold_seconds=0))
        print(
            "Alert posted. Check dssiitbhu@gmail.com within a few minutes "
            "(group_wait is 30s per alertmanager.yml)."
        )

        if not args.no_resolve:
            print("Leaving it active. Run again with --resolve-only when you're done checking the resolve email.")
    except requests.exceptions.RequestException as exc:
        print(f"Failed to reach Alertmanager at {base_url}: {exc}", file=sys.stderr)
        print("Is Alertmanager running and is port 9093 reachable from here?", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
