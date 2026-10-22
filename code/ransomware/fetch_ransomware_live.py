"""Fetch ransomware.live's leak-site victim list through its free PRO API.

ransomware.live records each victim a ransomware gang names on its leak site
(the gang's own claim, not confirmed). The terms (ransomware.live/t&c, checked
2026-10-19) allow non-commercial research with the credit "Source: Ransomware.live",
ask for the keyed API at api-pro.ransomware.live, and forbid publishing the raw
data. Keep these files in the private repo only.

The key goes in the project's .env file (ignored by Git) as
RANSOMWARE_LIVE_API_KEY=..., or in an environment variable of that name.
Get one free at https://www.ransomware.live/my. The script never prints it.

Each victim has two dates: `discovered` (when ransomware.live first saw the
listing) and `attackdate` (its estimate of the attack or posting date). We
download month by month on `discovered`, so each victim appears exactly once;
counts by attack month are built later from the `attackdate` field.

Every response names the account the key belongs to ("client"); we drop
that field before saving, so the files don't carry anyone's email address.

Files saved in <out_dir> (gzipped, because the full list is tens of MB):
  victims/discovered_<YYYY-MM>.json.gz  raw API response for that month
  groups.json.gz, stats.json, sectors.json
  fetch_log.txt, fetched_at.txt

The API allows 60 requests a minute; we send one every 2 seconds.

Usage: python3 -I fetch_ransomware_live.py <out_dir> [first_month, default 2019-01]
"""
import datetime as dt
import gzip
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = "https://api-pro.ransomware.live"
UA = "cyber-ts-research (academic research; low-rate)"


def api_key():
    key = os.environ.get("RANSOMWARE_LIVE_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("RANSOMWARE_LIVE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        sys.exit("No RANSOMWARE_LIVE_API_KEY in the environment or in .env")
    return key


def get(path, key, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "X-API-KEY": key,
                                               "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(int(e.headers.get("Retry-After", "60")))
                continue
            raise


def clean(body):
    """Drop the account field from a response; return (parsed, bytes to save)."""
    d = json.loads(body)
    if isinstance(d, dict):
        d.pop("client", None)
    return d, json.dumps(d, ensure_ascii=False).encode("utf-8")


def write_gz(path, body):
    # mtime=0 so an unchanged response gives a byte-identical file.
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(body)


def months(first, last):
    y, m = map(int, first.split("-"))
    while (y, m) <= last:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    out = pathlib.Path(sys.argv[1])
    first = sys.argv[2] if len(sys.argv) > 2 else "2019-01"
    key = api_key()
    (out / "victims").mkdir(parents=True, exist_ok=True)
    logf = open(out / "fetch_log.txt", "a", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")

    log(f"--- run started {dt.datetime.now(dt.timezone.utc).isoformat()}")
    stats, body = clean(get("/stats", key))
    (out / "stats.json").write_bytes(body)
    time.sleep(2)
    (out / "sectors.json").write_bytes(clean(get("/listsectors", key))[1])
    time.sleep(2)
    write_gz(out / "groups.json.gz", clean(get("/groups", key))[1])
    time.sleep(2)

    today = dt.date.today()
    total = 0
    for y, m in months(first, (today.year, today.month)):
        d, body = clean(get("/victims/", key, {"year": f"{y}", "month": f"{m:02d}",
                                               "date": "discovered"}))
        n = len(d["victims"])
        if n != d.get("count", n):
            log(f"WARNING {y}-{m:02d}: count says {d['count']}, list has {n}")
        total += n
        write_gz(out / "victims" / f"discovered_{y}-{m:02d}.json.gz", body)
        log(f"{y}-{m:02d}  {n} victims")
        time.sleep(2)
    log(f"total {total}; /stats says {stats['stats']['victims']} active victims")
    (out / "fetched_at.txt").write_text(dt.datetime.now(dt.timezone.utc).isoformat() + "\n")


if __name__ == "__main__":
    main()
