#!/usr/bin/env python3
"""
WorkHero Meta Ads Dashboard Generator
Pulls from HubSpot + Meta Ads and outputs a self-contained HTML file.

Usage:
    python3 generate_dashboard.py              # last 90 days of data
    python3 generate_dashboard.py 2026-05      # load a specific month

To add Meta spend data:
    Edit config.json and paste your token into "meta_access_token"
    Get one at: developers.facebook.com/tools/explorer
    App: WorkHero API  |  Permissions: ads_read
"""

import json, sys, calendar, requests
from datetime import datetime, timedelta, date as date_cls
from collections import defaultdict
from pathlib import Path

# ─── Config ───────────────────────────────────────────────────────────────────
cfg = json.loads(Path("config.json").read_text())
META_ACCESS_TOKEN = cfg.get("meta_access_token", "").strip()
DAILY_BUDGET      = int(cfg.get("daily_budget", 300))
MQL_CPL_TARGET    = int(cfg.get("mql_cpl_target", 250))

HS_CLIENT_ID     = cfg.get("hs_client_id",     "")
HS_CLIENT_SECRET = cfg.get("hs_client_secret", "")
HS_REFRESH_TOKEN = cfg.get("hs_refresh_token", "")
META_ACCOUNT_ID  = "act_784297103882588"
OUTPUT_FILE      = "dashboard.html"

# ─── Fetch range: last 90 days so date filter works in the browser ────────────
FETCH_DAYS   = 90
fetch_end    = date_cls.today()
fetch_start  = fetch_end - timedelta(days=FETCH_DAYS - 1)
fetch_start_str = fetch_start.strftime("%Y-%m-%d")
fetch_end_str   = fetch_end.strftime("%Y-%m-%d")

print(f"\n WorkHero Meta Dashboard")
print(f"   Fetching  : {fetch_start_str} → {fetch_end_str} ({FETCH_DAYS} days)")
print(f"   Daily target: ${DAILY_BUDGET}/day\n")

# ─── HubSpot ──────────────────────────────────────────────────────────────────
def hs_token():
    r = requests.post("https://api.hubapi.com/oauth/v1/token", data={
        "grant_type": "refresh_token", "client_id": HS_CLIENT_ID,
        "client_secret": HS_CLIENT_SECRET, "refresh_token": HS_REFRESH_TOKEN,
    })
    r.raise_for_status()
    return r.json()["access_token"]

def hs_contacts(token, start_ms, end_ms):
    contacts, after = [], None
    while True:
        payload = {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_analytics_source", "operator": "EQ",  "value": "PAID_SOCIAL"},
                {"propertyName": "createdate",           "operator": "GTE", "value": str(start_ms)},
                {"propertyName": "createdate",           "operator": "LTE", "value": str(end_ms)},
            ]}],
            "properties": [
                "firstname", "lastname", "email", "createdate",
                "lifecyclestage", "hs_lead_status", "disqualification_reason",
                "hs_analytics_source_data_1", "hs_analytics_source_data_2",
            ],
            "limit": 200,
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
        }
        if after:
            payload["after"] = after
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts/search",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        contacts.extend(data.get("results", []))
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    return contacts

# ─── Meta ─────────────────────────────────────────────────────────────────────
def meta_get(token, level, fields, extra=None):
    if not token:
        return []
    params = {
        "fields": fields,
        "time_range": json.dumps({"since": fetch_start_str, "until": fetch_end_str}),
        "level": level, "access_token": token, "limit": 500,
    }
    if extra:
        params.update(extra)
    all_rows, after = [], None
    while True:
        if after:
            params["after"] = after
        r = requests.get(f"https://graph.facebook.com/v19.0/{META_ACCOUNT_ID}/insights", params=params)
        if r.status_code != 200:
            print(f"  ⚠  Meta API error: {r.json().get('error', {}).get('message', r.text)}")
            break
        body = r.json()
        all_rows.extend(body.get("data", []))
        after = body.get("paging", {}).get("cursors", {}).get("after")
        if not after or not body.get("paging", {}).get("next"):
            break
    return all_rows

# ─── Fetch ────────────────────────────────────────────────────────────────────
print("→ HubSpot: fetching contacts...")
access = hs_token()
start_ms = int(datetime.combine(fetch_start, datetime.min.time()).timestamp() * 1000)
end_ms   = int(datetime.combine(fetch_end,   datetime.max.time()).timestamp() * 1000)
contacts = hs_contacts(access, start_ms, end_ms)
print(f"  {len(contacts)} paid social contacts")

print("→ Meta: fetching campaign + ad spend (daily)...")
meta_camp_daily = meta_get(META_ACCESS_TOKEN, "campaign",
    "campaign_name,campaign_id,spend,impressions,clicks",
    {"time_increment": 1})
meta_ad_daily   = meta_get(META_ACCESS_TOKEN, "ad",
    "campaign_name,adset_name,ad_name,spend,inline_link_clicks",
    {"time_increment": 1})

if not META_ACCESS_TOKEN:
    print("  ⚠  No Meta token — add it to config.json and rerun\n")
else:
    print(f"  {len(meta_camp_daily)} campaign-day rows, {len(meta_ad_daily)} ad-day rows")

# ─── Token expiry check ───────────────────────────────────────────────────────
import os as _os
token_days_left = None
token_expiry_str = ""
_app_secret = _os.environ.get("META_APP_SECRET", "")
if META_ACCESS_TOKEN and _app_secret:
    try:
        from datetime import timezone
        dbg = requests.get(
            "https://graph.facebook.com/debug_token",
            params={
                "input_token": META_ACCESS_TOKEN,
                "access_token": f"1501983588253582|{_app_secret}",
            },
            timeout=10,
        ).json().get("data", {})
        exp = dbg.get("expires_at", 0)
        if exp:
            expiry_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            now_utc = datetime.now(tz=timezone.utc)
            token_days_left = (expiry_dt - now_utc).days
            token_expiry_str = expiry_dt.strftime("%Y-%m-%d")
            print(f"  Token expiry: {token_expiry_str} ({token_days_left}d left)")
    except Exception as e:
        print(f"  Token expiry check failed: {e}")

Path("token_days_left.txt").write_text(str(token_days_left) if token_days_left is not None else "unknown")

# ─── Classify ─────────────────────────────────────────────────────────────────
def classify(props):
    disq  = (props.get("disqualification_reason") or "")
    stage = (props.get("lifecyclestage") or "")
    stat  = (props.get("hs_lead_status") or "")
    if disq == "Spam/bot":
        return "bot"
    if stat == "UNQUALIFIED" or (disq and disq != "Spam/bot"):
        return "disqualified"
    if stage in ("247021157", "1030073431", "opportunity", "customer"):
        return "mql"
    return "pending"

# ─── Build raw data blobs for client-side filtering ───────────────────────────
raw_contacts = []
for c in contacts:
    p = c["properties"]
    raw_contacts.append({
        "date":      (p.get("createdate") or "")[:10],
        "name":      f"{p.get('firstname','') or ''} {p.get('lastname','') or ''}".strip() or p.get("email","—"),
        "email":     p.get("email", ""),
        "campaign":  (p.get("hs_analytics_source_data_2") or "Unknown").strip(),
        "status":    classify(p),
        "disq_reason": p.get("disqualification_reason") or "",
        "hs_id":     c["id"],
    })

# Daily Meta spend by campaign
raw_meta_daily = []  # {date, campaign, spend, impressions, clicks}
for row in meta_camp_daily:
    raw_meta_daily.append({
        "date":       row.get("date_start", ""),
        "campaign":   (row.get("campaign_name") or "Unknown").strip(),
        "spend":      float(row.get("spend", 0)),
        "impressions":int(row.get("impressions", 0)),
        "clicks":     int(row.get("clicks", 0)),
    })

# Ad-level daily data (for date-range filtering in JS)
raw_meta_ad_daily = []
for row in meta_ad_daily:
    sp = float(row.get("spend", 0))
    if sp == 0:
        continue
    raw_meta_ad_daily.append({
        "date":        row.get("date_start", ""),
        "ad":          (row.get("ad_name") or "Unknown").strip(),
        "adset":       (row.get("adset_name") or "").strip(),
        "campaign":    (row.get("campaign_name") or "Unknown").strip(),
        "spend":       sp,
        "link_clicks": int(row.get("inline_link_clicks", 0)),
    })

has_meta  = bool(META_ACCESS_TOKEN and raw_meta_daily)
has_ads   = bool(raw_meta_ad_daily)
generated = datetime.now().strftime("%Y-%m-%d %H:%M")

# Print summary
total_mqls = sum(1 for c in raw_contacts if c["status"] == "mql")
print(f"\n  Contacts : {len(raw_contacts)}")
print(f"  MQLs     : {total_mqls}")
print(f"  Has Meta : {'yes' if has_meta else 'no (add token to config.json)'}\n")

# ─── HTML ─────────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WorkHero — Meta Ads Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{
  --bg:#f8f9fa;--card:#fff;--border:#e5e7eb;--text:#111827;--muted:#6b7280;
  --blue:#2563eb;--green:#16a34a;--red:#dc2626;--orange:#d97706;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);font-size:13px;line-height:1.5}}

/* ── Header ── */
.header{{background:#0f172a;color:#f1f5f9;padding:0 24px;display:flex;align-items:stretch;justify-content:space-between}}
.header-left{{display:flex;align-items:center;gap:16px;padding:14px 0}}
.brand{{font-size:13px;font-weight:700;color:#94a3b8;letter-spacing:.05em;text-transform:uppercase}}
.page-title{{font-size:15px;font-weight:600}}
.tab-nav{{display:flex;gap:0}}
.tab-btn{{
  padding:0 20px;height:100%;display:flex;align-items:center;
  font-size:12px;font-weight:500;color:#94a3b8;cursor:pointer;
  border-bottom:3px solid transparent;background:none;border-top:none;border-left:none;border-right:none;
  transition:color .15s,border-color .15s
}}
.tab-btn:hover{{color:#e2e8f0}}
.tab-btn.active{{color:#f1f5f9;border-bottom-color:#3b82f6}}
.header-right{{display:flex;align-items:center;gap:12px;padding:14px 0}}
.meta-status{{font-size:11px;padding:3px 9px;border-radius:4px}}
.meta-ok{{background:#14532d;color:#86efac}}
.meta-err{{background:#7f1d1d;color:#fca5a5}}
.gen-time{{font-size:11px;color:#475569}}
.reload-btn{{background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 12px;border-radius:4px;font-size:11px;cursor:pointer}}

/* ── Tab panels ── */
.panel{{display:none}}.panel.active{{display:block}}

/* ── Date filter bar ── */
.filter-bar{{
  background:var(--card);border-bottom:1px solid var(--border);
  padding:10px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap
}}
.filter-label{{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.preset-btns{{display:flex;gap:6px}}
.preset{{
  padding:4px 12px;border-radius:4px;font-size:12px;cursor:pointer;
  border:1px solid var(--border);background:var(--card);color:var(--text);
  transition:background .1s
}}
.preset:hover{{background:#f1f5f9}}
.preset.active{{background:var(--text);color:#fff;border-color:var(--text)}}
.date-inputs{{display:flex;align-items:center;gap:6px;margin-left:auto}}
.date-inputs input{{
  padding:4px 8px;border:1px solid var(--border);border-radius:4px;
  font-size:12px;color:var(--text);background:var(--card)
}}
.apply-btn{{
  padding:4px 12px;background:var(--blue);color:#fff;border:none;
  border-radius:4px;font-size:12px;cursor:pointer
}}

/* ── Main ── */
.main{{max-width:1200px;margin:0 auto;padding:20px 24px}}

/* ── Warning ── */
.warn-box{{
  background:#fefce8;border:1px solid #fbbf24;border-radius:6px;
  padding:10px 14px;font-size:12px;margin-bottom:16px;
  display:flex;align-items:flex-start;gap:10px
}}
.warn-box b{{font-weight:700}}
.warn-steps{{margin-top:4px;color:#92400e;line-height:1.8}}
.warn-steps code{{background:#fef9c3;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:11px}}

/* ── Status banner ── */
.status-banner{{border-radius:8px;padding:14px 20px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between}}
.s-ok{{background:#dcfce7}}.s-over{{background:#fee2e2}}.s-under{{background:#fef3c7}}.s-na{{background:#f1f5f9}}
.status-label{{font-size:18px;font-weight:700}}
.s-ok .status-label{{color:var(--green)}}.s-over .status-label{{color:var(--red)}}
.s-under .status-label{{color:var(--orange)}}.s-na .status-label{{color:var(--muted)}}
.status-right{{text-align:right;font-size:12px;color:var(--muted)}}
.status-big{{font-size:20px;font-weight:700;color:var(--text)}}

/* ── KPI grid ── */
.kpi-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:16px}}
.kpi-card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px}}
.kpi-label{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}}
.kpi-value{{font-size:20px;font-weight:700}}
.kpi-sub{{font-size:11px;color:var(--muted);margin-top:2px}}

/* ── Cards ── */
.card{{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}}
.card-header{{padding:10px 16px;border-bottom:1px solid var(--border);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);display:flex;align-items:center;gap:8px}}
.card-body{{padding:16px}}

/* ── READ ── */
.read-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.read-lbl{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:4px}}

/* ── Funnel ── */
.funnel{{display:flex}}
.fstep{{flex:1;text-align:center;padding:14px 6px;border-right:2px solid var(--bg)}}
.fstep:last-child{{border-right:none}}
.f-total{{background:#eff6ff}}.f-mql{{background:#dcfce7}}.f-disq{{background:#fff7ed}}.f-bot{{background:#fef2f2}}.f-pend{{background:#f8fafc}}
.fnum{{font-size:26px;font-weight:700}}
.flbl{{font-size:11px;color:var(--muted);margin-top:2px}}
.fpct{{font-size:11px;font-weight:600;margin-top:2px}}
.f-total .fnum{{color:var(--blue)}}.f-mql .fnum{{color:var(--green)}}
.f-disq .fnum{{color:var(--orange)}}.f-bot .fnum{{color:var(--red)}}.f-pend .fnum{{color:var(--muted)}}

/* ── Chart ── */
.chart-tabs{{display:flex;gap:6px;margin-bottom:10px}}
.ctab{{padding:3px 10px;border-radius:4px;font-size:11px;cursor:pointer;border:1px solid var(--border);background:var(--card)}}
.ctab.active{{background:var(--text);color:#fff;border-color:var(--text)}}
.chart-wrap{{height:180px}}

/* ── Tables ── */
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:1px solid var(--border)}}
th.r,td.r{{text-align:right}}
td{{padding:8px 12px;border-bottom:1px solid var(--border);font-size:12px}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#f9fafb}}
.td-name{{max-width:260px;word-break:break-word}}
.td-sub{{font-size:11px;color:var(--muted)}}
.td-mql{{font-weight:700;color:var(--green)}}
.td-disq{{color:var(--orange)}}.td-bot{{color:var(--red)}}
.na{{color:var(--muted);font-style:italic}}

/* ── Badges ── */
.badge{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:600}}
.b-mql{{background:#dcfce7;color:#16a34a}}.b-bot{{background:#fee2e2;color:#dc2626}}
.b-disq{{background:#fff7ed;color:#d97706}}.b-pend{{background:#f1f5f9;color:#64748b}}
.b-disq-reason{{font-size:11px;color:var(--muted);margin-left:4px}}

/* ── Creative tab ── */
.creative-kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
.perf-bar{{background:#e5e7eb;border-radius:2px;height:4px;margin-top:4px}}
.perf-fill{{height:4px;border-radius:2px;background:var(--blue)}}

/* ── Var colors ── */
.vover{{color:var(--red);font-weight:600}}.vunder{{color:var(--green);font-weight:600}}

@media(max-width:900px){{
  .kpi-grid{{grid-template-columns:repeat(2,1fr)}}
  .read-grid{{grid-template-columns:1fr}}
  .creative-kpi{{grid-template-columns:repeat(2,1fr)}}
}}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <span class="brand">WorkHero</span>
    <span class="page-title">Meta Ads Dashboard</span>
  </div>
  <div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('overview',this)">Overview</button>
    <button class="tab-btn" onclick="switchTab('creative',this)">Creative Performance</button>
  </div>
  <div class="header-right">
    <span class="meta-status {'meta-ok' if has_meta else 'meta-err'}">{('✓ Meta connected' if has_meta else '✗ Meta token missing')}</span>
    <span class="gen-time">Generated {generated}</span>
    <button class="reload-btn" onclick="window.location.reload()">↻ Reload</button>
  </div>
</div>

<!-- Date filter bar (shared) -->
<div class="filter-bar">
  <span class="filter-label">Date range</span>
  <div class="preset-btns">
    <button class="preset" onclick="setPreset(7,this)">Last 7d</button>
    <button class="preset active" onclick="setPreset(30,this)">Last 30d</button>
    <button class="preset" onclick="setPresetMonth(0,this)">This month</button>
    <button class="preset" onclick="setPresetMonth(-1,this)">Last month</button>
    <button class="preset" onclick="setPreset(90,this)">Last 90d</button>
  </div>
  <div class="date-inputs">
    <input type="date" id="dateFrom" />
    <span style="color:var(--muted)">→</span>
    <input type="date" id="dateTo" />
    <button class="apply-btn" onclick="applyCustom()">Apply</button>
  </div>
</div>

<!-- ════════════════ OVERVIEW TAB ════════════════ -->
<div id="panel-overview" class="panel active">
<div class="main">

  {'''<div class="warn-box">
    <span style="font-size:16px">⚠</span>
    <div>
      <b>Meta spend data unavailable</b> — token expired.<br>
      <div class="warn-steps">
        Drop a fresh token from <code>developers.facebook.com/tools/explorer</code> into Claude Code chat — it rotates automatically in 30 seconds.
      </div>
    </div>
  </div>''' if not has_meta else ''}

  {f\'\'\'<div class="warn-box" style="background:#fef3c7;border-color:#f59e0b;color:#92400e">
    <span style="font-size:16px">⏰</span>
    <div><b>Meta token expires in {token_days_left} days</b> ({token_expiry_str}) — rotate it now to avoid a dashboard outage.<br>
    Drop a fresh token from <code>developers.facebook.com/tools/explorer</code> into Claude Code chat.</div>
  </div>\'\'\' if token_days_left is not None and 0 < token_days_left <= 14 else \'\'}

  <!-- Status banner (updated by JS) -->
  <div id="statusBanner" class="status-banner s-na">
    <div id="statusLabel" class="status-label">Loading...</div>
    <div class="status-right">
      <div id="statusBig" class="status-big"></div>
      <div id="statusSub"></div>
    </div>
  </div>

  <!-- KPI cards -->
  <div class="kpi-grid">
    <div class="kpi-card"><div class="kpi-label">Total Spend</div><div class="kpi-value" id="kpiSpend">—</div><div class="kpi-sub" id="kpiSpendSub"></div></div>
    <div class="kpi-card"><div class="kpi-label">Period Target</div><div class="kpi-value" id="kpiTarget">—</div><div class="kpi-sub" id="kpiTargetSub"></div></div>
    <div class="kpi-card"><div class="kpi-label">Avg Daily Spend</div><div class="kpi-value" id="kpiAvg">—</div></div>
    <div class="kpi-card"><div class="kpi-label">Total MQLs</div><div class="kpi-value" id="kpiMql" style="color:var(--green)">—</div><div class="kpi-sub" id="kpiMqlRate"></div></div>
    <div class="kpi-card"><div class="kpi-label">Cost per MQL</div><div class="kpi-value" id="kpiCpl">—</div></div>
  </div>

  <!-- READ -->
  <div class="card">
    <div class="card-header">READ</div>
    <div class="card-body">
      <div class="read-grid">
        <div><div class="read-lbl">Driver</div><div id="readDriver" style="font-size:13px;line-height:1.6"></div></div>
        <div><div class="read-lbl">Outcome</div><div id="readOutcome" style="font-size:13px;line-height:1.6"></div></div>
      </div>
    </div>
  </div>

  <!-- Funnel -->
  <div class="card">
    <div class="card-header">Form Submission Funnel</div>
    <div class="funnel" id="funnelRow">
      <div class="fstep f-total"><div class="fnum" id="fTotal">—</div><div class="flbl">Submissions</div><div class="fpct" style="color:var(--blue)">100%</div></div>
      <div class="fstep f-mql"><div class="fnum" id="fMql">—</div><div class="flbl">MQLs</div><div class="fpct" id="fMqlPct">—</div></div>
      <div class="fstep f-disq"><div class="fnum" id="fDisq">—</div><div class="flbl">Disqualified</div><div class="fpct" id="fDisqPct">—</div></div>
      <div class="fstep f-bot"><div class="fnum" id="fBot">—</div><div class="flbl">Bot / Spam</div><div class="fpct" id="fBotPct">—</div></div>
      <div class="fstep f-pend"><div class="fnum" id="fPend">—</div><div class="flbl">Pending</div><div class="fpct" id="fPendPct">—</div></div>
    </div>
  </div>

  <!-- Charts -->
  <div class="card">
    <div class="card-header">
      Pace vs Target
      <div class="chart-tabs" style="margin-left:auto">
        <button class="ctab active" onclick="showCtab('spend',this)">Spend</button>
        <button class="ctab" onclick="showCtab('subs',this)">Daily Submissions</button>
      </div>
    </div>
    <div class="card-body">
      <div id="spendChartWrap" class="chart-wrap"><canvas id="spendChart"></canvas></div>
      <div id="subsChartWrap"  class="chart-wrap" style="display:none"><canvas id="subsChart"></canvas></div>
    </div>
  </div>

  <!-- CPL Tracker -->
  <div class="card">
    <div class="card-header">
      CPL Tracker
      <span id="cplStatusBadge" style="margin-left:8px;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600"></span>
      <span style="margin-left:auto;font-size:11px;font-weight:400;color:var(--muted)">Target: ≤$250/MQL</span>
    </div>
    <div class="card-body" style="padding-bottom:8px">
      <div class="chart-wrap"><canvas id="cplChart"></canvas></div>
    </div>
  </div>

  <!-- Campaign table -->
  <div class="card">
    <div class="card-header">Campaign Summary</div>
    <table>
      <thead><tr>
        <th>Campaign</th>
        <th class="r">Spend</th>
        <th class="r">Forms</th>
        <th class="r">MQLs</th>
        <th class="r">MQL %</th>
        <th class="r">CPL</th>
        <th class="r">Disqualified</th>
        <th class="r">Bot/Spam</th>
      </tr></thead>
      <tbody id="campTableBody"></tbody>
    </table>
  </div>

  <!-- Contacts -->
  <div class="card">
    <div class="card-header">Recent Contacts <span style="margin-left:8px;font-weight:400;color:var(--muted)" id="contactCount"></span></div>
    <table>
      <thead><tr>
        <th>Date</th><th>Contact</th><th>Campaign</th><th>Status</th>
      </tr></thead>
      <tbody id="contactTableBody"></tbody>
    </table>
  </div>

</div><!-- /main -->
</div><!-- /overview panel -->

<!-- ════════════════ CREATIVE TAB ════════════════ -->
<div id="panel-creative" class="panel">
<div class="main">

  {'''<div class="warn-box">
    <span style="font-size:16px">⚠</span>
    <div>
      <b>Meta spend data required for creative performance.</b><br>
      <div class="warn-steps">Add your Meta token to <code>config.json</code> and rerun.</div>
    </div>
  </div>''' if not has_ads else ''}

  <!-- Creative KPI cards -->
  <div class="creative-kpi">
    <div class="kpi-card"><div class="kpi-label">Live Creatives</div><div class="kpi-value" id="crCount">—</div><div class="kpi-sub" id="crCountSub"></div></div>
    <div class="kpi-card"><div class="kpi-label">Total Spend (Meta)</div><div class="kpi-value" id="crSpend">—</div></div>
    <div class="kpi-card"><div class="kpi-label">Total MQLs (HubSpot)</div><div class="kpi-value" id="crMqls" style="color:var(--green)">—</div></div>
    <div class="kpi-card"><div class="kpi-label">Avg CPL</div><div class="kpi-value" id="crCpl">—</div></div>
  </div>

  <!-- Campaign filter -->
  <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap" id="campFilterBtns"></div>

  <!-- Creative table -->
  <div class="card">
    <div class="card-header">
      Live Creatives
      <span style="margin-left:8px;font-weight:400;color:var(--muted)" id="adCount"></span>
      <span style="margin-left:auto;font-size:10px;font-weight:400;color:var(--muted)">Funnel data: HubSpot &nbsp;·&nbsp; Spend/Clicks: Meta &nbsp;·&nbsp; CPL = Meta spend ÷ HS MQLs</span>
    </div>
    <table>
      <thead><tr>
        <th>Creative (Ad Name)</th>
        <th>Campaign</th>
        <th class="r">Spend</th>
        <th class="r">Link Clicks</th>
        <th class="r">Forms</th>
        <th class="r">MQLs</th>
        <th class="r">DQs</th>
        <th class="r">Bots</th>
        <th class="r">CPL</th>
      </tr></thead>
      <tbody id="adTableBody"></tbody>
    </table>
  </div>

</div>
</div><!-- /creative panel -->

<script>
// ── Raw data ──
const RAW_CONTACTS   = {json.dumps(raw_contacts)};
const RAW_META_DAILY = {json.dumps(raw_meta_daily)};
const RAW_META_AD_DAILY = {json.dumps(raw_meta_ad_daily)};
const DAILY_BUDGET   = {DAILY_BUDGET};
const MQL_CPL_TARGET = {MQL_CPL_TARGET};
const HAS_META = {json.dumps(has_meta)};

// ── State ──
let currentFrom = null, currentTo = null;
let spendChartInst = null, subsChartInst = null, pieChartInst = null;
let activeCampFilter = 'all';

// ── Tab switching ──
function switchTab(name, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
}}

// ── Date helpers ──
function toISO(d) {{ return d.toISOString().slice(0,10); }}
function parseISO(s) {{ return new Date(s + 'T00:00:00'); }}
function daysBetween(a, b) {{ return Math.round((b-a)/(1000*60*60*24)) + 1; }}

function setPreset(days, btn) {{
  const to = new Date(); to.setHours(0,0,0,0);
  const from = new Date(to); from.setDate(from.getDate() - days + 1);
  applyRange(toISO(from), toISO(to));
  document.querySelectorAll('.preset').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}}

function setPresetMonth(offset, btn) {{
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth() + offset;
  const from = new Date(y, m, 1);
  const to   = new Date(y, m + 1, 0);
  const cap  = new Date(); cap.setHours(0,0,0,0);
  applyRange(toISO(from), toISO(new Date(Math.min(to, cap))));
  document.querySelectorAll('.preset').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}}

function applyCustom() {{
  const f = document.getElementById('dateFrom').value;
  const t = document.getElementById('dateTo').value;
  if (f && t && f <= t) {{
    applyRange(f, t);
    document.querySelectorAll('.preset').forEach(b => b.classList.remove('active'));
  }}
}}

function applyRange(from, to) {{
  currentFrom = from; currentTo = to;
  document.getElementById('dateFrom').value = from;
  document.getElementById('dateTo').value   = to;
  renderOverview();
  renderCreative();
}}

// ── Filter helpers ──
function filterContacts(from, to) {{
  return RAW_CONTACTS.filter(c => c.date >= from && c.date <= to);
}}

function filterMetaDaily(from, to) {{
  return RAW_META_DAILY.filter(r => r.date >= from && r.date <= to);
}}

// ── Format ──
function fmtMoney(v, dec=0) {{
  if (v == null) return '<span class="na">N/A</span>';
  if (v >= 1e6) return '$' + (v/1e6).toFixed(2) + 'M';
  if (v >= 1e3) return '$' + (v/1e3).toFixed(1) + 'k';
  return '$' + v.toFixed(dec);
}}
function fmtPct(n, d) {{ return d > 0 ? (n/d*100).toFixed(0) + '%' : '—'; }}
function fmtVar(v) {{
  if (v == null) return '<span class="na">N/A</span>';
  const s = v >= 0 ? '+' : '';
  const cls = v > 0 ? 'vover' : (v < 0 ? 'vunder' : '');
  return `<span class="${{cls}}">${{s}}${{fmtMoney(Math.abs(v)).replace('$',v<0?'-$':'$').replace('$-$','−$')}}</span>`;
}}

// ── Overview render ──
function renderOverview() {{
  const from = currentFrom, to = currentTo;
  const contacts = filterContacts(from, to);
  const metaRows = filterMetaDaily(from, to);

  const total = contacts.length;
  const mql   = contacts.filter(c => c.status === 'mql').length;
  const bot   = contacts.filter(c => c.status === 'bot').length;
  const disq  = contacts.filter(c => c.status === 'disqualified').length;
  const pend  = contacts.filter(c => c.status === 'pending').length;

  const spend = metaRows.reduce((s,r) => s + r.spend, 0);
  const days  = daysBetween(parseISO(from), parseISO(to));
  const target = days * DAILY_BUDGET;
  const avg   = days > 0 ? spend / days : 0;
  const cpl   = (mql > 0 && spend > 0) ? spend / mql : null;
  const variance = spend > 0 ? spend - target : null;
  const pacingPct = (spend > 0 && target > 0) ? spend / target * 100 : null;

  // Status banner
  let sClass, sLabel;
  if (!HAS_META)           {{ sClass='s-na';    sLabel='Spend data unavailable'; }}
  else if (pacingPct>105)  {{ sClass='s-over';  sLabel='Tracking over budget'; }}
  else if (pacingPct<90)   {{ sClass='s-under'; sLabel='Tracking under budget'; }}
  else                     {{ sClass='s-ok';    sLabel='On pace'; }}

  const banner = document.getElementById('statusBanner');
  banner.className = 'status-banner ' + sClass;
  document.getElementById('statusLabel').textContent = sLabel;
  document.getElementById('statusBig').innerHTML = fmtMoney(spend>0?spend:null) + ' / ' + fmtMoney(target);
  document.getElementById('statusSub').innerHTML = pacingPct
    ? pacingPct.toFixed(1) + '% of target &nbsp;·&nbsp; ' + fmtVar(variance) + ' variance'
    : from + ' → ' + to + ' (' + days + ' days)';

  // KPIs
  document.getElementById('kpiSpend').innerHTML    = fmtMoney(spend > 0 ? spend : null);
  document.getElementById('kpiSpendSub').textContent = spend > 0 ? '' : 'Add Meta token';
  document.getElementById('kpiTarget').innerHTML   = fmtMoney(target);
  document.getElementById('kpiTargetSub').textContent = days + ' days × $' + DAILY_BUDGET;
  document.getElementById('kpiAvg').innerHTML      = spend > 0 ? fmtMoney(avg) : '<span class="na">N/A</span>';
  document.getElementById('kpiMql').textContent    = mql;
  document.getElementById('kpiMqlRate').textContent = total > 0 ? fmtPct(mql, total) + ' MQL rate' : '';
  document.getElementById('kpiCpl').innerHTML      = cpl ? fmtMoney(cpl) : '<span class="na">N/A</span>';

  // Funnel
  document.getElementById('fTotal').textContent = total;
  document.getElementById('fMql').textContent   = mql;
  document.getElementById('fDisq').textContent  = disq;
  document.getElementById('fBot').textContent   = bot;
  document.getElementById('fPend').textContent  = pend;
  document.getElementById('fMqlPct').textContent  = fmtPct(mql,  total);
  document.getElementById('fDisqPct').textContent = fmtPct(disq, total);
  document.getElementById('fBotPct').textContent  = fmtPct(bot,  total);
  document.getElementById('fPendPct').textContent = fmtPct(pend, total);

  // READ
  const byCamp = {{}};
  contacts.forEach(c => {{
    const k = c.campaign;
    if (!byCamp[k]) byCamp[k] = {{total:0,mql:0,disq:0,bot:0}};
    byCamp[k].total++;
    if (c.status==='mql') byCamp[k].mql++;
    if (c.status==='disqualified') byCamp[k].disq++;
    if (c.status==='bot') byCamp[k].bot++;
  }});
  const topCamp = Object.entries(byCamp).sort((a,b)=>b[1].mql-a[1].mql)[0];
  document.getElementById('readDriver').innerHTML = topCamp
    ? `<b>${{topCamp[0]}}</b> is the top performer: <b>${{topCamp[1].mql}} MQLs</b> from ${{topCamp[1].total}} form submissions (${{fmtPct(topCamp[1].mql,topCamp[1].total)}} MQL rate).`
    : 'No data for selected range.';
  document.getElementById('readOutcome').innerHTML =
    `<b>${{total}} form submissions</b> → <b>${{mql}} MQLs</b> (${{fmtPct(mql,total)}} MQL rate). ` +
    (disq || bot ? `${{disq}} disqualified, ${{bot}} bot/spam.` : '') +
    (pend ? ` ${{pend}} pending qualification.` : '');

  // Chart
  buildSpendChart(from, to, metaRows, contacts);
  buildCplChart(from, to, metaRows, contacts);

  // Campaign table
  // Build Meta spend indexed by normalized name
  const metaSpendByNorm = {{}}, metaNameForNorm = {{}};
  metaRows.forEach(r => {{
    const n = normCamp(r.campaign);
    metaSpendByNorm[n] = (metaSpendByNorm[n] || 0) + r.spend;
    if (!metaNameForNorm[n]) metaNameForNorm[n] = r.campaign;
  }});

  // Merge HubSpot rows with Meta spend via fuzzy norm match
  const consumedNorms = new Set();
  const campRows = [];
  Object.entries(byCamp).sort((a,b) => b[1].mql - a[1].mql).forEach(([hsKey, hs]) => {{
    const n = normCamp(hsKey);
    let spend = 0, dispName = hsKey;
    if (metaSpendByNorm[n] !== undefined) {{
      spend = metaSpendByNorm[n]; dispName = metaNameForNorm[n] || hsKey;
      consumedNorms.add(n);
    }} else {{
      for (const [mn, ms] of Object.entries(metaSpendByNorm)) {{
        if (!consumedNorms.has(mn) && (n.includes(mn) || mn.includes(n))) {{
          spend = ms; dispName = metaNameForNorm[mn] || hsKey;
          consumedNorms.add(mn); break;
        }}
      }}
    }}
    campRows.push({{ name: dispName, hs, spend }});
  }});
  // Append Meta-only campaigns that had no HubSpot match
  Object.entries(metaSpendByNorm).forEach(([n, spend]) => {{
    if (!consumedNorms.has(n))
      campRows.push({{ name: metaNameForNorm[n], hs: {{total:0,mql:0,disq:0,bot:0}}, spend }});
  }});

  let campHTML = '';
  campRows.forEach(row => {{
    const hs = row.hs, sp = row.spend;
    const cplC = (hs.mql > 0 && sp > 0) ? fmtMoney(sp/hs.mql) : '—';
    const mqlR = hs.total > 0 ? fmtPct(hs.mql, hs.total) : '—';
    campHTML += `<tr>
      <td class="td-name">${{row.name}}</td>
      <td class="r">${{sp > 0 ? fmtMoney(sp) : '<span class="na">N/A</span>'}}</td>
      <td class="r">${{hs.total}}</td>
      <td class="r td-mql">${{hs.mql}}</td>
      <td class="r">${{mqlR}}</td>
      <td class="r">${{cplC}}</td>
      <td class="r td-disq">${{hs.disq}}</td>
      <td class="r td-bot">${{hs.bot}}</td>
    </tr>`;
  }});
  document.getElementById('campTableBody').innerHTML = campHTML || '<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:20px">No data</td></tr>';

  // Contacts
  const sorted = [...contacts].sort((a,b) => b.date.localeCompare(a.date));
  document.getElementById('contactCount').textContent = `(showing ${{Math.min(sorted.length,50)}} of ${{sorted.length}})`;
  const bmap = {{mql:'b-mql',bot:'b-bot',disqualified:'b-disq',pending:'b-pend'}};
  const lmap = {{mql:'MQL',bot:'Bot/Spam',disqualified:'Disqualified',pending:'Pending'}};
  let ctHTML = '';
  sorted.slice(0,50).forEach(c => {{
    const disqStr = c.disq_reason ? `<span class="b-disq-reason">${{c.disq_reason}}</span>` : '';
    ctHTML += `<tr>
      <td>${{c.date}}</td>
      <td class="td-name" style="font-weight:500">${{c.name}}</td>
      <td class="td-name td-sub">${{c.campaign}}</td>
      <td><span class="badge ${{bmap[c.status]||''}}">${{lmap[c.status]||c.status}}</span>${{disqStr}}</td>
    </tr>`;
  }});
  document.getElementById('contactTableBody').innerHTML = ctHTML || '<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:20px">No contacts</td></tr>';
}}

// ── Spend chart ──
function buildSpendChart(from, to, metaRows, contacts) {{
  // Build date array
  const dates = [];
  const d = new Date(from + 'T00:00:00');
  const end = new Date(to + 'T00:00:00');
  while (d <= end) {{ dates.push(toISO(d)); d.setDate(d.getDate()+1); }}

  const spendByDay = {{}};
  metaRows.forEach(r => {{ spendByDay[r.date] = (spendByDay[r.date]||0) + r.spend; }});

  const subsByDay = {{}};
  contacts.forEach(c => {{ subsByDay[c.date] = (subsByDay[c.date]||0) + 1; }});

  let cumSpend = 0;
  const actualSpend = dates.map(d => {{ cumSpend += spendByDay[d]||0; return Math.round(cumSpend); }});
  const idealSpend  = dates.map((_,i) => (i+1) * DAILY_BUDGET);
  const dailySubs   = dates.map(d => subsByDay[d]||0);
  const labels      = dates.map(d => d.slice(5));  // MM-DD

  // Spend chart
  if (spendChartInst) spendChartInst.destroy();
  spendChartInst = new Chart(document.getElementById('spendChart').getContext('2d'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{ label:'Actual Spend', data: HAS_META ? actualSpend : [],
           borderColor:'#2563eb', backgroundColor:'rgba(37,99,235,.08)',
           fill:true, tension:.3, pointRadius:2 }},
        {{ label:'Ideal ($' + DAILY_BUDGET + '/day)', data:idealSpend,
           borderColor:'#d1d5db', borderDash:[5,4], pointRadius:0, fill:false }}
      ]
    }},
    options:{{ responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{ position:'bottom', labels:{{ font:{{size:11}} }} }} }},
      scales:{{
        y:{{ ticks:{{ callback: v => v>=1000?'$'+(v/1000).toFixed(0)+'k':'$'+v }} }},
        x:{{ ticks:{{ font:{{size:10}}, maxTicksLimit:15 }} }}
      }}
    }}
  }});

  // Subs chart
  if (subsChartInst) subsChartInst.destroy();
  subsChartInst = new Chart(document.getElementById('subsChart').getContext('2d'), {{
    type:'bar',
    data:{{ labels, datasets:[{{ label:'Daily Submissions', data:dailySubs, backgroundColor:'rgba(37,99,235,.6)' }}] }},
    options:{{ responsive:true, maintainAspectRatio:false,
      plugins:{{ legend:{{ position:'bottom', labels:{{ font:{{size:11}} }} }} }},
      scales:{{ x:{{ ticks:{{ font:{{size:10}}, maxTicksLimit:15 }} }} }}
    }}
  }});
}}

let cplChartInst = null;
function buildCplChart(from, to, metaRows, contacts) {{
  const dates = [];
  const d = new Date(from + 'T00:00:00');
  const end = new Date(to + 'T00:00:00');
  while (d <= end) {{ dates.push(toISO(d)); d.setDate(d.getDate()+1); }}

  const spendByDay = {{}};
  metaRows.forEach(r => {{ spendByDay[r.date] = (spendByDay[r.date]||0) + r.spend; }});

  const mqlByDay = {{}};
  contacts.filter(c => c.status === 'mql').forEach(c => {{
    mqlByDay[c.date] = (mqlByDay[c.date]||0) + 1;
  }});

  let cumSpend = 0, cumMql = 0;
  const cplLine = dates.map(d => {{
    cumSpend += spendByDay[d] || 0;
    cumMql   += mqlByDay[d]   || 0;
    return (cumMql > 0 && cumSpend > 0) ? Math.round(cumSpend / cumMql) : null;
  }});
  const targetLine = dates.map(() => MQL_CPL_TARGET);
  const labels = dates.map(d => d.slice(5));

  // Update CPL status badge
  const lastCpl = cplLine.filter(v => v !== null).slice(-1)[0];
  const badge = document.getElementById('cplStatusBadge');
  if (lastCpl != null) {{
    const ok = lastCpl <= MQL_CPL_TARGET;
    badge.textContent = (ok ? '✓ ' : '⚠ ') + '$' + lastCpl + '/MQL';
    badge.style.background = ok ? '#dcfce7' : '#fee2e2';
    badge.style.color = ok ? '#16a34a' : '#dc2626';
  }} else {{
    badge.textContent = 'No spend data';
    badge.style.background = '#f1f5f9';
    badge.style.color = '#64748b';
  }}

  if (cplChartInst) cplChartInst.destroy();
  cplChartInst = new Chart(document.getElementById('cplChart').getContext('2d'), {{
    type: 'line',
    data: {{
      labels,
      datasets: [
        {{
          label: 'Running CPL',
          data: HAS_META ? cplLine : [],
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37,99,235,.08)',
          fill: true,
          tension: 0.3,
          pointRadius: 3,
          spanGaps: true,
        }},
        {{
          label: '$' + MQL_CPL_TARGET + ' target',
          data: targetLine,
          borderColor: '#dc2626',
          borderDash: [6, 4],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{size: 11}} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ' $' + ctx.parsed.y + '/MQL' }} }}
      }},
      scales: {{
        y: {{
          ticks: {{ callback: v => '$' + v }},
          suggestedMin: 0,
        }},
        x: {{ ticks: {{ font: {{size: 10}}, maxTicksLimit: 15 }} }}
      }}
    }}
  }});
}}

function showCtab(type, btn) {{
  document.querySelectorAll('.ctab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('spendChartWrap').style.display = type==='spend' ? '' : 'none';
  document.getElementById('subsChartWrap').style.display  = type==='subs'  ? '' : 'none';
}}

// ── Creative tab render ──
// Normalize a campaign name for fuzzy matching
function normCamp(s) {{
  return (s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}}

function renderCreative() {{
  const from = currentFrom, to = currentTo;

  // ── Step 1: Filter Meta ad-daily rows to selected range ──
  const adDailyInRange = RAW_META_AD_DAILY.filter(r => r.date >= from && r.date <= to);

  // Aggregate by ad name → spend + link_clicks + campaign
  const adMeta = {{}};
  adDailyInRange.forEach(r => {{
    if (!adMeta[r.ad]) adMeta[r.ad] = {{ spend:0, link_clicks:0, campaign:r.campaign, adset:r.adset }};
    adMeta[r.ad].spend       += r.spend;
    adMeta[r.ad].link_clicks += r.link_clicks;
  }});

  // "Live" = had spend > 0 in range
  const liveAds = Object.entries(adMeta)
    .filter(([_, v]) => v.spend > 0)
    .sort((a, b) => b[1].spend - a[1].spend);

  // ── Step 2: Build HubSpot metrics by hs_analytics_source_data_2 ──
  const contacts = filterContacts(from, to);
  const hsBySrc = {{}};
  contacts.forEach(c => {{
    const k = c.campaign;
    if (!hsBySrc[k]) hsBySrc[k] = {{ total:0, mql:0, disq:0, bot:0 }};
    hsBySrc[k].total++;
    if (c.status === 'mql')          hsBySrc[k].mql++;
    if (c.status === 'disqualified') hsBySrc[k].disq++;
    if (c.status === 'bot')          hsBySrc[k].bot++;
  }});

  // ── Step 3: Match Meta campaign → HubSpot source (fuzzy, case-insensitive) ──
  // Also aggregate HubSpot at campaign level so all ads in the same campaign share HS data
  const campHsCache = {{}};
  function getHsForCampaign(metaCampaign) {{
    if (campHsCache[metaCampaign] !== undefined) return campHsCache[metaCampaign];
    const normMeta = normCamp(metaCampaign);
    let best = null;
    for (const [src, data] of Object.entries(hsBySrc)) {{
      const normSrc = normCamp(src);
      if (normSrc === normMeta || normMeta.includes(normSrc) || normSrc.includes(normMeta)) {{
        best = data; break;
      }}
    }}
    campHsCache[metaCampaign] = best;
    return best;
  }}

  // ── Step 4: Campaign filter buttons ──
  const camps = [...new Set(liveAds.map(([_, v]) => v.campaign))].sort();
  const filterDiv = document.getElementById('campFilterBtns');
  filterDiv.innerHTML = '';
  ['all', ...camps].forEach(c => {{
    const btn = document.createElement('button');
    btn.className = 'preset' + (activeCampFilter === c ? ' active' : '');
    btn.textContent = c === 'all' ? 'All campaigns' : c;
    btn.addEventListener('click', function() {{ activeCampFilter = c; renderCreative(); }});
    filterDiv.appendChild(btn);
  }});

  // Apply campaign filter
  const filtered = activeCampFilter === 'all'
    ? liveAds
    : liveAds.filter(([_, v]) => v.campaign === activeCampFilter);

  // ── Step 5: KPIs ──
  const totalSpend = filtered.reduce((s, [_, v]) => s + v.spend, 0);
  // Sum HubSpot MQLs across matched campaigns (deduplicate by campaign)
  const matchedCamps = new Set(filtered.map(([_, v]) => v.campaign));
  let totalMql = 0, totalForms = 0;
  matchedCamps.forEach(camp => {{
    const hs = getHsForCampaign(camp);
    if (hs) {{ totalMql += hs.mql; totalForms += hs.total; }}
  }});
  const avgCpl = totalMql > 0 && totalSpend > 0 ? totalSpend / totalMql : null;

  document.getElementById('crCount').textContent    = filtered.length;
  document.getElementById('crCountSub').textContent = from + ' → ' + to;
  document.getElementById('crSpend').innerHTML      = fmtMoney(totalSpend > 0 ? totalSpend : null);
  document.getElementById('crMqls').textContent     = totalMql || '—';
  document.getElementById('crCpl').innerHTML        = avgCpl ? fmtMoney(avgCpl) : '—';
  document.getElementById('adCount').textContent    = `(${{filtered.length}} live ads)`;

  // ── Step 6: Table rows ──
  let adHTML = '';
  if (filtered.length === 0) {{
    adHTML = `<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:24px">${{
      HAS_META ? 'No active creatives in this date range.' : 'Add Meta token to config.json and rerun.'
    }}</td></tr>`;
  }} else {{
    filtered.forEach(([adName, meta]) => {{
      const hs  = getHsForCampaign(meta.campaign);
      // CPL = this ad's spend / campaign MQLs (best we can do without ad-level attribution)
      const cpl = (hs && hs.mql > 0 && meta.spend > 0) ? Math.round(meta.spend / hs.mql) : null;
      const cplStr = cpl ? fmtMoney(cpl) : '<span class="na">—</span>';
      const cplCls = cpl && cpl > MQL_CPL_TARGET ? 'style="color:var(--red);font-weight:600"' : (cpl && cpl <= MQL_CPL_TARGET ? 'style="color:var(--green);font-weight:600"' : '');

      adHTML += `<tr>
        <td class="td-name">${{adName}}</td>
        <td class="td-sub">${{meta.campaign}}</td>
        <td class="r">${{fmtMoney(meta.spend)}}</td>
        <td class="r">${{meta.link_clicks > 0 ? meta.link_clicks.toLocaleString() : '—'}}</td>
        <td class="r">${{hs ? hs.total : '<span class="na">—</span>'}}</td>
        <td class="r td-mql">${{hs ? hs.mql : '<span class="na">—</span>'}}</td>
        <td class="r td-disq">${{hs ? hs.disq : '<span class="na">—</span>'}}</td>
        <td class="r td-bot">${{hs ? hs.bot  : '<span class="na">—</span>'}}</td>
        <td class="r" ${{cplCls}}>${{cplStr}}</td>
      </tr>`;
    }});
  }}
  document.getElementById('adTableBody').innerHTML = adHTML;
}}

// ── Init ──
(function() {{
  // Default: last 30 days
  const to   = new Date(); to.setHours(0,0,0,0);
  const from = new Date(to); from.setDate(from.getDate() - 29);
  applyRange(toISO(from), toISO(to));
}})();
</script>
</body>
</html>"""

with open(OUTPUT_FILE, "w") as f:
    f.write(html)

print(f"✓  Written → {OUTPUT_FILE}")
print(f"   Open: open {OUTPUT_FILE}\n")
