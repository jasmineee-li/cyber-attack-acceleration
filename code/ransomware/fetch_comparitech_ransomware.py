"""Fetch Comparitech's confirmed ransomware incidents (ransomware.comparitech.com).

The site publishes every page as JSON under /data (see its /llms.txt). robots.txt
allows /data/ but disallows /api/, /manage/ and /data/evidence/, so this script
never touches those. The licence (/data-license) allows use with the citation
"Data from Comparitech Ransomware Intelligence Platform (ransomware.comparitech.com)".
Checked 2026-10-19. One request every 2 seconds.

Files saved in <out_dir>:
  incidents_index.json        slim list of every confirmed incident (one row each)
  observations_manifest.json  list of months with incidents
  observations/<YYYY-MM>.json full incident documents for that month
                              (same fields as the per-incident pages, so we
                              don't need ~10,000 separate requests)
  status.json, methodology.json, exclusions.json, fields.json   documentation
  fetch_log.txt, fetched_at.txt

Some monthly files return a server error (2023-07 did on 2026-10-19, every
time). For those months the script fetches each incident's own document instead
(/data/incidents/<slug>.json, slugs from the index) and saves them in the same
shape, with "assembled_from_incident_docs": true. Months already on disk are
skipped, so a failed run can be resumed; delete observations/ to refetch all.

Only "confirmed" incidents are public. About two-thirds of the corpus rests on
the attacker's own leak-site claim alone, and Comparitech withholds those.

Usage: python3 -I fetch_comparitech_ransomware.py <out_dir>
"""
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "https://ransomware.comparitech.com"
UA = "cyber-ts-research (academic research; low-rate)"
DOCS = {
    "incidents_index.json": "/data/incidents/index.json",
    "observations_manifest.json": "/data/incidents/observations/manifest.json",
    "status.json": "/data/status/latest.json",
    "methodology.json": "/data/methodology.json",
    "exclusions.json": "/data/exclusions/index.json",
    "fields.json": "/data/fields/index.json",
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def assemble_month(period, index_items, log):
    """Build a month's file from per-incident documents when the monthly file fails."""
    items = []
    for x in index_items:
        if x["occurred_month"] != period:
            continue
        time.sleep(2)
        try:
            items.append(json.loads(get(x["data_url"]))["data"])
        except urllib.error.HTTPError as e:
            log(f"{period}: incident {x['slug']} failed ({e.code}), skipped")
    return json.dumps({"assembled_from_incident_docs": True,
                       "data": {"period": period, "count": len(items), "items": items}},
                      ensure_ascii=False).encode("utf-8")


def main():
    out = pathlib.Path(sys.argv[1])
    (out / "observations").mkdir(parents=True, exist_ok=True)
    logf = open(out / "fetch_log.txt", "a", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")

    for name, path in DOCS.items():
        body = get(BASE + path)
        (out / name).write_bytes(body)
        print(f"{name}  {len(body):,} bytes", flush=True)
        time.sleep(2)

    manifest = json.loads((out / "observations_manifest.json").read_text())["data"]
    index_items = json.loads((out / "incidents_index.json").read_text())["data"]["items"]
    for p in manifest["periods"]:
        path = out / "observations" / f"{p['period']}.json"
        if path.exists():
            continue
        try:
            body = get(p["data_url"])
        except urllib.error.HTTPError as e:
            log(f"{p['period']}: monthly file failed ({e.code}); fetching incidents one by one")
            body = assemble_month(p["period"], index_items, log)
        n = len(json.loads(body)["data"]["items"])
        if n != p["incident_count"]:
            log(f"WARNING {p['period']}: manifest says {p['incident_count']}, file has {n}")
        path.write_bytes(body)
        print(f"{p['period']}  {n} incidents", flush=True)
        time.sleep(2)

    (out / "fetched_at.txt").write_text(dt.datetime.now(dt.timezone.utc).isoformat() + "\n")


if __name__ == "__main__":
    main()
