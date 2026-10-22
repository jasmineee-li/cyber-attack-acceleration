"""Fetch Web3 Is Going Great entries tagged theme=hack ("Hack or scam").

There is no documented public API. The site's own server-rendered pages embed
10 entries each in a __NEXT_DATA__ JSON block; we walk them using the site's
own ?id= start-at parameter (the same URL a reader gets when following links).
robots.txt allows all paths (checked 2026-10-18). One request every 3 seconds.

Usage: python3 -I fetch_w3igg.py <out_dir> [theme]
Writes <out_dir>/pages/page_NNN.json (the embedded firstEntries object) and
<out_dir>/entries_<theme>.json (deduplicated list of entries).
"""
import json
import os
import re
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (academic research; low-rate)"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def main():
    out = sys.argv[1]
    theme = sys.argv[2] if len(sys.argv) > 2 else "hack"
    pages = os.path.join(out, "pages_" + theme)
    os.makedirs(pages, exist_ok=True)
    seen = {}
    order = []
    start_id = None
    n = 0
    while True:
        n += 1
        url = f"https://www.web3isgoinggreat.com/?theme={theme}"
        if start_id:
            url += f"&id={start_id}"
        html = get(url)
        m = NEXT_RE.search(html)
        if not m:
            print("no __NEXT_DATA__ on", url, file=sys.stderr)
            break
        data = json.loads(m.group(1))
        fe = data["props"]["pageProps"]["firstEntries"]
        with open(os.path.join(pages, f"page_{n:03d}.json"), "w", encoding="utf-8") as f:
            json.dump({"url": url, "firstEntries": fe}, f, ensure_ascii=False)
        new = 0
        for e in fe["entries"]:
            if e["id"] not in seen:
                seen[e["id"]] = e
                order.append(e["id"])
                new += 1
        last = fe["entries"][-1]["id"] if fe["entries"] else None
        print(f"page {n}: {len(fe['entries'])} entries, {new} new, last={last}, hasNext={fe['hasNext']}", flush=True)
        if not fe["hasNext"] or new == 0 or last is None:
            break
        start_id = last
        time.sleep(3)
    with open(os.path.join(out, f"entries_{theme}.json"), "w", encoding="utf-8") as f:
        json.dump([seen[i] for i in order], f, ensure_ascii=False, indent=0)
    print("total", len(order))


if __name__ == "__main__":
    main()
