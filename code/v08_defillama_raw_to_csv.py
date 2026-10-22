"""Write DeFiLlama's raw JSON files as flat CSVs, for reading in Stata or Excel.

Input:  data/raw/defillama/hacks_<SNAPSHOT>.json, tvl_<SNAPSHOT>.json (from v01; the latest
        date-stamped pair is used automatically)
Output: data/processed/defillama_hacks_raw.csv  one row per hack, every field DeFiLlama gives
        data/processed/defillama_tvl_raw.csv    one row per day, total DeFi TVL in USD

Unlike defillama_hacks.csv (from v02), nothing is dropped or added: no cause group, and the
`source`, `defillamaId` and `parentProtocolId` fields are kept. Changes are only for flat files:
  date        added as YYYY-MM-DD (UTC); DeFiLlama's original Unix seconds kept as date_unix
  chain       list of chains joined with ";" (e.g. "Ethereum;Arbitrum")
  bridgeHack  1/0 instead of true/false
  missing     blank cells

Stata (tested in StataNow 19.5; case(preserve) keeps names like bridgeHack from being lowercased):
        import delimited using "data/processed/defillama_hacks_raw.csv", ///
            varnames(1) case(preserve) asdouble bindquote(strict) encoding(utf-8) clear
        gen hack_date = date(date, "YMD")
        format hack_date %td

Run: uv run python -I code/v08_defillama_raw_to_csv.py  (or: uv run dvc repro)
"""
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "defillama"
OUT = ROOT / "data" / "processed"
# The newest fetch from v01, e.g. "2026-10-18".
SNAPSHOT = sorted(RAW.glob("hacks_*.json"))[-1].stem.split("_", 1)[1]
assert (RAW / f"tvl_{SNAPSHOT}.json").exists(), f"missing tvl_{SNAPSHOT}.json"


def with_iso_date(df):
    df = df.rename(columns={"date": "date_unix"})
    df.insert(0, "date", pd.to_datetime(df["date_unix"], unit="s").dt.strftime("%Y-%m-%d"))
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    h = with_iso_date(pd.DataFrame(json.loads((RAW / f"hacks_{SNAPSHOT}.json").read_text())))
    h["chain"] = h["chain"].apply(lambda c: ";".join(c) if isinstance(c, list) else c)
    h["bridgeHack"] = h["bridgeHack"].astype(int)
    h = h.sort_values(["date_unix", "name"], kind="stable").reset_index(drop=True)
    h.to_csv(OUT / "defillama_hacks_raw.csv", index=False)

    t = with_iso_date(pd.DataFrame(json.loads((RAW / f"tvl_{SNAPSHOT}.json").read_text())))
    t.to_csv(OUT / "defillama_tvl_raw.csv", index=False)

    print(f"snapshot {SNAPSHOT}: {len(h)} hacks, {len(t)} TVL days")
    print("hack columns:", ", ".join(h.columns))


if __name__ == "__main__":
    main()
