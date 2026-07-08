import re, sys, subprocess
from pathlib import Path

html_path = Path("dashboard.html")
if not html_path.exists():
    print("ERROR: dashboard.html not found — generate_dashboard.py failed silently")
    sys.exit(1)

html = html_path.read_text()
has_meta = "const HAS_META = true" in html

days_raw = Path("token_days_left.txt").read_text().strip() if Path("token_days_left.txt").exists() else "unknown"

stale_match = re.search(r"const AD_DATA_STALE\s*=\s*(true|false)", html)
ad_stale = stale_match.group(1) if stale_match else "unknown"

print(f"has_meta={has_meta}  token_days={days_raw}  ad_stale={ad_stale}")

if not has_meta:
    print("::error title=Meta Token Expired::Dashboard is stale. Update META_ACCESS_TOKEN secret.")
    sys.exit(1)

days = int(days_raw) if days_raw.isdigit() else 9999
if days <= 14:
    print(f"::error title=Meta Token Expiring in {days} Days::Rotate token before dashboard breaks.")
    sys.exit(1)

if ad_stale == "true":
    print("::error title=Creative Data Stale::Ad-level data is >7 days old. Re-run workflow.")
    sys.exit(1)

# Publish
Path("index.html").write_text(html)
print("index.html written")

# Commit
subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
subprocess.run(["git", "add", "index.html"], check=True)

diff = subprocess.run(["git", "diff", "--staged", "--quiet"])
if diff.returncode != 0:
    from datetime import date
    subprocess.run(["git", "commit", "-m", f"chore: refresh dashboard {date.today()}"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Committed and pushed.")
else:
    print("No changes to commit.")
