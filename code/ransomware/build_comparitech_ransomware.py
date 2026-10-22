"""Build tables of Comparitech's confirmed ransomware incidents.

Input:  <raw_dir>/comparitech_ransomware/ (from fetch_comparitech_ransomware.py)
Output: <out_dir>/comparitech_ransomware_incidents.csv  one row per incident
        <out_dir>/comparitech_ransomware_monthly.csv    counts per month the attack happened
        <out_dir>/comparitech_ransomware_quarterly.csv  counts per quarter

The incident index is the master list. Detail fields (ransom, records, sources)
come from the monthly observation files; an incident missing from those (two
on 2026-10-19, in 2023-07 and 2024-10, because Comparitech's server errored)
keeps its index fields and has has_detail = False.

"Confirmed" means at least one source besides the gang's own claim. The
confirmation types, strongest first, are: victim_confirmed (the organisation
said so), regulator_filed (a data-breach notice), third_party_reported (news or
research), and defacement_observed (rare). `complete` = the calendar period
ended before the download date. Recent periods are still low even when
complete, because confirmation arrives months after the attack.

Run: python -I code/ransomware/build_comparitech_ransomware.py data/raw data/processed
"""
import json
import pathlib
import sys

import pandas as pd

LEVELS = ["victim_confirmed", "regulator_filed", "third_party_reported"]


def load(raw):
    index = json.loads((raw / "incidents_index.json").read_text())["data"]["items"]
    detail = {}
    for f in sorted((raw / "observations").glob("*.json")):
        for x in json.loads(f.read_text())["data"]["items"]:
            detail[x["slug"]] = x
    extra = set(detail) - {x["slug"] for x in index}
    if extra:
        print(f"WARNING: {len(extra)} incidents in observation files but not in the index")
    rows = []
    for x in index:
        d = detail.get(x["slug"])
        ev = d["evidence"] if d else {}
        imp = d["impact"] if d else {}
        srcs = d["sources"] if d else []
        rows.append({
            "slug": x["slug"],
            "organization_name": x["organization_name"],
            "occurred_month": x["occurred_month"],
            "country": x["country"],
            "admin_area": x["admin_area"],
            "locality": x["locality"],
            "primary_sector": x["primary_sector"],
            "primary_group": x["primary_group"],
            "n_groups": len(d["groups"]) if d else None,
            "evidence_grade": x["evidence_grade"],
            "confirmation_level": ev.get("confirmation_level"),
            "strongest_source_class": ev.get("strongest_source_class"),
            "source_count": ev.get("source_count"),
            "independent_publishers": ev.get("independent_publishers"),
            "records_affected": imp.get("records_affected"),
            "ransom_demanded_usd": imp.get("ransom_demanded_usd"),
            "ransom_paid": imp.get("ransom_paid"),
            "data_stolen_gb": imp.get("data_stolen_gb"),
            "first_retrieved_at": min((s["retrieved_at"] for s in srcs if s.get("retrieved_at")),
                                      default=None),
            "updated_at": d.get("updated_at") if d else None,
            "has_detail": d is not None,
        })
    return pd.DataFrame(rows)


def counts(df, period_col):
    g = df.groupby(period_col)
    out = pd.DataFrame({
        "n_all": g.size(),
        "n_us": g["country"].apply(lambda s: (s == "US").sum()),
        "n_non_us": g["country"].apply(lambda s: (s != "US").sum()),
        "n_named_group": g["primary_group"].apply(lambda s: s.notna().sum()),
    })
    for lvl in LEVELS:
        out[f"n_{lvl}"] = g["confirmation_level"].apply(lambda s, lvl=lvl: (s == lvl).sum())
    us = df[df["country"] == "US"]
    out["n_us_regulator_filed"] = us.groupby(period_col)["confirmation_level"].apply(
        lambda s: (s == "regulator_filed").sum())
    out["n_us_regulator_filed"] = out["n_us_regulator_filed"].fillna(0).astype(int)
    return out


def main():
    raw = pathlib.Path(sys.argv[1]) / "comparitech_ransomware"
    out = pathlib.Path(sys.argv[2])
    fetched = pd.Timestamp((raw / "fetched_at.txt").read_text().strip()).tz_localize(None)

    df = load(raw)
    print(f"{len(df)} incidents, {(~df['has_detail']).sum()} without detail fields")
    df.sort_values(["occurred_month", "slug"]).to_csv(
        out / "comparitech_ransomware_incidents.csv", index=False)

    month = pd.PeriodIndex(df["occurred_month"], freq="M")
    df["month"] = month.astype(str)
    df["quarter"] = month.asfreq("Q").astype(str)

    for name, col, freq in [("monthly", "month", "M"), ("quarterly", "quarter", "Q")]:
        c = counts(df, col)
        span = pd.period_range(c.index.min(), c.index.max(), freq=freq)
        c = c.reindex(span.astype(str), fill_value=0)
        c.index.name = "period"
        c["complete"] = [p.end_time < fetched for p in span]
        c.reset_index().to_csv(out / f"comparitech_ransomware_{name}.csv", index=False)
        print(f"{name}: {len(c)} periods, {span[0]} to {span[-1]}")


if __name__ == "__main__":
    main()
