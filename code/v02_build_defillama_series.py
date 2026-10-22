"""Turn DeFiLlama's hacks list into incident-level, monthly and quarterly tables.

Input:  data/raw/defillama/hacks_<SNAPSHOT>.json, tvl_<SNAPSHOT>.json (from v01; the latest
        date-stamped pair is used automatically)
Output: data/processed/defillama_hacks.csv      one row per hack, with our cause group
        data/processed/defillama_monthly.csv    counts and losses per month
        data/processed/defillama_quarterly.csv  counts, losses and TVL per quarter

Cause groups (our own grouping of DeFiLlama's `classification` field):
  code_bug     flaws in the app's own code or design: the attacker needs no stolen secret
  keys_people  stolen keys, phishing/malware, hijacked websites or infrastructure
  other        insider scams (rugpulls), market manipulation, unclassified

Dates are DeFiLlama's hack date (UTC midnight). Amounts are DeFiLlama's USD loss
estimates; 54 records have no amount (or zero) and are counted but carry no loss.

Run: uv run python -I code/v02_build_defillama_series.py  (or: uv run dvc repro)
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

GROUPS = {
    "code_bug": [
        "Access Control", "Protocol Logic", "Token & Share Accounting",
        "Oracle Manipulation", "Input Validation", "Reentrancy",
        "Bridge & Cross-Chain", "Governance",
    ],
    "keys_people": ["Key Compromise", "Frontend & Infrastructure", "Social Engineering"],
    "other": ["Rugpull", "Market Manipulation"],
}
CLASS_TO_GROUP = {c: g for g, cs in GROUPS.items() for c in cs}
BIG = 1_000_000


def load_hacks():
    h = pd.DataFrame(json.loads((RAW / f"hacks_{SNAPSHOT}.json").read_text()))
    seen = set(h["classification"].dropna())
    unknown = seen - set(CLASS_TO_GROUP)
    assert not unknown, f"unmapped DeFiLlama classifications: {unknown}"
    h["date"] = pd.to_datetime(h["date"], unit="s", utc=True).dt.tz_localize(None).dt.normalize()
    h["group"] = h["classification"].map(CLASS_TO_GROUP).fillna("other")
    h["amount_usd"] = pd.to_numeric(h["amount"], errors="coerce")
    h["chain"] = h["chain"].apply(lambda c: ";".join(c) if isinstance(c, list) else c)
    h["is_big"] = h["amount_usd"] >= BIG
    cols = ["date", "name", "group", "classification", "technique", "amount_usd",
            "is_big", "chain", "targetType", "bridgeHack", "returnedFunds", "language"]
    return h[cols].sort_values("date").reset_index(drop=True)


def summarize(h, freq):
    p = h["date"].dt.to_period(freq)
    g = h.groupby(p)
    out = pd.DataFrame({
        "n_all": g.size(),
        "n_code_bug": g["group"].apply(lambda s: (s == "code_bug").sum()),
        "n_keys_people": g["group"].apply(lambda s: (s == "keys_people").sum()),
        "n_other": g["group"].apply(lambda s: (s == "other").sum()),
        "n_big": g["is_big"].sum(),
        "n_big_code_bug": h[h["group"] == "code_bug"].groupby(p)["is_big"].sum(),
        "n_big_keys_people": h[h["group"] == "keys_people"].groupby(p)["is_big"].sum(),
        "loss_usd": g["amount_usd"].sum(),
        "loss_usd_code_bug": h[h["group"] == "code_bug"].groupby(p)["amount_usd"].sum(),
        "median_amount_usd": g["amount_usd"].median(),
    })
    full = pd.period_range(out.index.min(), pd.Period(f"{SNAPSHOT}", freq), freq=freq)
    out = out.reindex(full).fillna({c: 0 for c in out.columns if c != "median_amount_usd"})
    for c in out.columns:
        if c.startswith("n_"):
            out[c] = out[c].astype(int)
    out.index.name = "period"
    # Flag the period that contains the snapshot date: it is incomplete.
    out["complete"] = [p.end_time.normalize() < pd.Timestamp(SNAPSHOT) for p in out.index]
    return out


def tvl_by_quarter():
    t = pd.DataFrame(json.loads((RAW / f"tvl_{SNAPSHOT}.json").read_text()))
    t["date"] = pd.to_datetime(t["date"], unit="s")
    return t.groupby(t["date"].dt.to_period("Q"))["tvl"].mean().rename("tvl_mean_usd")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    h = load_hacks()
    h.to_csv(OUT / "defillama_hacks.csv", index=False)

    m = summarize(h, "M")
    m.to_csv(OUT / "defillama_monthly.csv")

    q = summarize(h, "Q").join(tvl_by_quarter())
    q["n_all_per_10bn_tvl"] = q["n_all"] / (q["tvl_mean_usd"] / 1e10)
    q["n_code_bug_per_10bn_tvl"] = q["n_code_bug"] / (q["tvl_mean_usd"] / 1e10)
    q.to_csv(OUT / "defillama_quarterly.csv")

    print(f"{len(h)} hacks, {h['date'].min().date()} to {h['date'].max().date()}")
    show = ["n_all", "n_code_bug", "n_keys_people", "n_big", "n_big_code_bug",
            "loss_usd", "median_amount_usd", "tvl_mean_usd", "n_code_bug_per_10bn_tvl", "complete"]
    with pd.option_context("display.width", 200, "display.float_format", "{:,.2f}".format):
        print(q.loc["2020Q1":, show])


if __name__ == "__main__":
    main()
