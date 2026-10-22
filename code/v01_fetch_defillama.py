"""Fetch DeFiLlama's hacks list and total-value-locked (TVL) history.

Sources (free, no key):
  https://api.llama.fi/hacks                   one record per hack
  https://api.llama.fi/v2/historicalChainTvl   daily TVL summed across all chains (USD)

Output: data/raw/defillama/hacks_<YYYY-MM-DD>.json, tvl_<YYYY-MM-DD>.json
(stamped with the fetch date, so later fetches don't overwrite earlier snapshots).

Run: uv run python code/v01_fetch_defillama.py
"""
import datetime as dt
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "defillama"
URLS = {
    "hacks": "https://api.llama.fi/hacks",
    "tvl": "https://api.llama.fi/v2/historicalChainTvl",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    for name, url in URLS.items():
        req = urllib.request.Request(url, headers={"User-Agent": "cyber-ts-research"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
        path = OUT / f"{name}_{stamp}.json"
        path.write_bytes(body)
        print(f"{path.relative_to(ROOT)}  {len(body):,} bytes")


if __name__ == "__main__":
    main()
