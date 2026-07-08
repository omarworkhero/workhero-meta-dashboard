import os, re, sys, subprocess, requests
from pathlib import Path
from datetime import date

SLACK = os.environ.get("SLACK_WEBHOOK_URL", "")

def slack_alert(msg: str):
    if not SLACK:
        return
    try:
        requests.post(SLACK, json={"text": msg}, timeout=10)
    except Exception as e:
        print(f"Slack notify failed (non-fatal): {e}")

def fail(title: str, detail: str):
    print(f"::error title={title}::{detail}")
    slack_alert(f":rotating_light: *{title}*\n{detail}\nFix: https://github.com/omarworkhero/workhero-meta-dashboard/actions")
    sys.exit(1)

html_path = Path("dashboard.html")
if not html_path.exists():
    fail("Dashboard Generation Failed", "dashboard.html not found — generate_dashboard.py failed silently.")

html = html_path.read_text()
has_meta = "const HAS_META = true" in html
days_raw = Path("token_days_left.txt").read_text().strip() if Path("token_days_left.txt").exists() else "unknown"
stale_match = re.search(r"const AD_DATA_STALE\s*=\s*(true|false)", html)
ad_stale = stale_match.group(1) if stale_match else "unknown"

print(f"has_meta={has_meta}  token_days={days_raw}  ad_stale={ad_stale}")

if not has_meta:
    fail("Meta Token Broken", "META_ACCESS_TOKEN secret is invalid or revoked. Regenerate: Business Manager → System Users → WorkHero-Dashboard → Generate token.")

days = int(days_raw) if days_raw.isdigit() else 9999
if days <= 14:
    fail(f"Meta Token Expiring in {days} Days", "Regenerate now: Business Manager → System Users → WorkHero-Dashboard → Generate token → update META_ACCESS_TOKEN secret.")

if ad_stale == "true":
    fail("Creative Data Stale", "Ad-level data is >7 days old — likely a Meta API pagination issue. Re-run the workflow.")

# Publish
Path("index.html").write_text(html)
print("index.html written")

# Commit
subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
subprocess.run(["git", "add", "index.html"], check=True)

diff = subprocess.run(["git", "diff", "--staged", "--quiet"])
if diff.returncode != 0:
    subprocess.run(["git", "commit", "-m", f"chore: refresh dashboard {date.today()}"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Committed and pushed.")
else:
    print("No changes to commit.")
