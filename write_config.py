import json, os

cfg = {
    "meta_access_token": os.environ["META_ACCESS_TOKEN"],
    "hs_client_id":      os.environ["HS_CLIENT_ID"],
    "hs_client_secret":  os.environ["HS_CLIENT_SECRET"],
    "hs_refresh_token":  os.environ["HS_REFRESH_TOKEN"],
    "daily_budget":      300,
    "mql_cpl_target":    250,
}

open("config.json", "w").write(json.dumps(cfg))
print("config.json written")
