#!/usr/bin/env python3
"""Madaar email verification via Apify actor account56/email-verifier.

Reads ./new_leads.csv, dedupes emails, verifies each unique address by
running the actor through the Apify REST API using the `apify_madar` token
from ./.env (so runs/billing land in the Madaar console).

Resumable: per-email verdicts are cached in ./output/_madaar_verification_cache.json.
"""
import csv, json, sys, time, urllib.request, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CSV_PATH = HERE / "new_leads.csv"
ENV_PATH = HERE / ".env"
OUT = HERE / "output"
CACHE = OUT / "_madaar_verification_cache.json"

ACTOR_ID = "account56~email-verifier"
API = "https://api.apify.com/v2"
BATCH = 200          # emails per actor run
POLL_SECS = 15       # poll interval
RUN_TIMEOUT = 900    # seconds before giving up on a run

def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            env[parts[0]] = " ".join(parts[1:]).strip()
    return env

def api_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def api_post(url: str, token: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def start_run(token: str, emails: list[str]) -> str:
    url = f"{API}/acts/{ACTOR_ID}/runs"
    res = api_post(url, token, {"emails": emails})
    data = res.get("data") or {}
    run_id = data.get("id")
    if not run_id:
        raise RuntimeError(f"start run failed: {res}")
    return run_id

def wait_run(token: str, run_id: str, timeout: int = RUN_TIMEOUT) -> str:
    start = time.time()
    while time.time() - start < timeout:
        url = f"{API}/actor-runs/{run_id}"
        res = api_get(url, token)
        status = (res.get("data") or {}).get("status", "")
        if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
            return status
        time.sleep(POLL_SECS)
    return "TIMED-OUT"

def fetch_items(token: str, run_id: str) -> list[dict]:
    url = f"{API}/actor-runs/{run_id}/dataset"
    res = api_get(url, token)
    dataset_id = (res.get("data") or {}).get("id")
    if not dataset_id:
        return []
    items = []
    offset = 0
    while True:
        u = f"{API}/datasets/{dataset_id}/items?format=json&clean=true&limit=1000&offset={offset}"
        page = api_get(u, token)
        if not page:
            break
        items.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)
    return items

def main():
    env = load_env(ENV_PATH)
    token = env.get("apify_madar") or env.get("apify_madar_token")
    if not token:
        sys.exit("apify_madar token not found in .env")

    if not CSV_PATH.exists():
        sys.exit(f"{CSV_PATH} not found")
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    emails = sorted({(r.get("email") or "").strip().lower() for r in rows if (r.get("email") or "").strip()})
    print(f"input rows: {len(rows)} | unique emails: {len(emails)}", flush=True)

    OUT.mkdir(exist_ok=True)
    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
        print(f"cache has {len(cache)} emails", flush=True)

    pending = [e for e in emails if e not in cache]
    print(f"already verified: {len(emails) - len(pending)} | to verify: {len(pending)}", flush=True)

    for i in range(0, len(pending), BATCH):
        chunk = pending[i : i + BATCH]
        run_id = start_run(token, chunk)
        print(f"batch {i//BATCH + 1}/{(len(pending)-1)//BATCH + 1}: {len(chunk)} emails -> run {run_id}", flush=True)
        status = wait_run(token, run_id)
        print(f"  run status: {status}", flush=True)
        if status == "SUCCEEDED":
            items = fetch_items(token, run_id)
            for it in items:
                em = (it.get("email") or "").strip().lower()
                if em:
                    cache[em] = it
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  fetched {len(items)} records; cache now {len(cache)}", flush=True)
        else:
            for em in chunk:
                cache.setdefault(em, {"error": f"run_{status}", "email": em})
            CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  run {status}; marked {len(chunk)} as error", flush=True)

    missing = [e for e in emails if e not in cache]
    print(f"\ndone. verified: {len(emails) - len(missing)} | missing: {len(missing)}")
    if missing:
        print("missing:", missing)

if __name__ == "__main__":
    main()