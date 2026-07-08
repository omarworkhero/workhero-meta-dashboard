"""
Dashboard watchdog — runs every 12h via watchdog.yml
Fetches the live dashboard, checks the Generated timestamp.
Fails loudly (GitHub email) if stale >36h.
Sends Slack alert if SLACK_WEBHOOK_URL secret is set.
"""
import os, re, sys, requests
from datetime import datetime, timezone

DASHBOARD_URL = "https://omarworkhero.github.io/workhero-meta-dashboard/"
STALE_THRESHOLD_HOURS = 36
SLACK = os.environ.get("SLACK_WEBHOOK_URL", "")

def slack_alert(msg: str):
    if not SLACK:
        return
    try:
        requests.post(SLACK, json={"text": msg}, timeout=10)
    except Exception as e:
        print(f"Slack notify failed (non-fatal): {e}")

print(f"Fetching {DASHBOARD_URL} ...")
try:
    resp = requests.get(DASHBOARD_URL, timeout=30)
    resp.raise_for_status()
except Exception as e:
    msg = f"Dashboard unreachable: {e}"
    print(f"::error title=Dashboard Unreachable::{msg}")
    slack_alert(f":rotating_light: *Meta Dashboard Unreachable*\n{msg}")
    sys.exit(1)

# Parse "Generated YYYY-MM-DD HH:MM" from the page
match = re.search(r"Generated (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", resp.text)
if not match:
    msg = "Could not find Generated timestamp — dashboard may be broken."
    print(f"::error title=Dashboard Parse Error::{msg}")
    slack_alert(f":rotating_light: *Meta Dashboard Parse Error*\n{msg}")
    sys.exit(1)

generated_str = match.group(1)
generated = datetime.strptime(generated_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
now = datetime.now(timezone.utc)
age_hours = (now - generated).total_seconds() / 3600

print(f"Generated: {generated_str} UTC ({age_hours:.1f}h ago)")

if age_hours > STALE_THRESHOLD_HOURS:
    msg = (
        f"Meta Ads Dashboard is STALE — last updated {age_hours:.0f}h ago "
        f"(threshold: {STALE_THRESHOLD_HOURS}h). "
        f"Trigger manually: https://github.com/omarworkhero/workhero-meta-dashboard/actions/workflows/refresh.yml"
    )
    print(f"::error title=Dashboard Stale — {age_hours:.0f}h::{msg}")
    slack_alert(f":rotating_light: *Meta Dashboard Stale*\nLast updated {age_hours:.0f}h ago. Trigger: https://github.com/omarworkhero/workhero-meta-dashboard/actions")
    sys.exit(1)

print(f"Dashboard is fresh. ({age_hours:.1f}h old, threshold {STALE_THRESHOLD_HOURS}h)")
