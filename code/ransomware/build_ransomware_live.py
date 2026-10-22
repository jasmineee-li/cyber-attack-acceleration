"""Build tables of ransomware.live leak-site victims.

Input:  <raw_dir>/ransomware_live/victims/discovered_<YYYY-MM>.json.gz (from fetch_ransomware_live.py)
Output: <out_dir>/ransomware_live_victims.csv    one row per victim post
        <out_dir>/ransomware_live_monthly.csv    counts per month
        <out_dir>/ransomware_live_quarterly.csv  counts per quarter

Every row is a gang's own claim, not a confirmed attack. Two dates:
  discovered = when ransomware.live first saw the post
  attackdate = ransomware.live's estimate of the attack or posting date
Periods are counted both ways: n_disc_* by discovered, n_att_* by attackdate.
`complete` = the calendar period ended before the download date.

The same organization can appear more than once (posted by two gangs, or
reposted). n_*_all counts every post; n_*_unique counts distinct (normalized
name, gang) pairs, keeping the first post. All other columns count unique
posts, so n_*_us + n_*_non_us + n_*_no_country = n_*_unique.

n_*_young_gang counts posts by gangs that ransomware.live first saw less than
365 days earlier; n_*_old_gang the rest. Gangs come and go constantly, so
young gangs supply 40-60% of posts in most quarters.

Country is blank for most posts first seen before 2024 (87% in 2021, 56% in
2023), so n_*_us and n_*_non_us are only comparable from 2024; blanks are in
n_*_no_country.

Tracking really starts in September 2021, when ransomware.live loaded a
backlog of 812 posts; earlier quarters are near empty.

We keep only the fields needed for counting. The free-text description,
screenshot, leak-site link and infostealer fields stay in the raw files.

Run: python -I code/ransomware/build_ransomware_live.py data/raw data/processed
"""
import gzip
import json
import pathlib
import re
import sys

import pandas as pd


def norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def load(raw):
    rows = []
    for f in sorted((raw / "victims").glob("discovered_*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for v in json.load(fh)["victims"]:
                rows.append({
                    "id": v.get("id"),
                    "victim": v.get("victim"),
                    "group": v.get("group"),
                    "discovered": v.get("discovered"),
                    "attackdate": v.get("attackdate"),
                    "country": v.get("country") or None,
                    "activity": v.get("activity") or None,
                    "website": v.get("website") or None,
                    "has_press": bool(v.get("press")),
                })
    df = pd.DataFrame(rows)
    for c in ["discovered", "attackdate"]:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce", format="mixed").dt.tz_localize(None)
    df["lag_days"] = (df["discovered"] - df["attackdate"]).dt.days
    df = df.sort_values(["discovered", "id"]).reset_index(drop=True)
    df["first_post"] = ~df.assign(k=df["victim"].map(norm)).duplicated(["k", "group"])
    first_seen = df.groupby("group")["discovered"].min()
    df["gang_age_days"] = (df["discovered"] - df["group"].map(first_seen)).dt.days
    return df


def counts(df, freq, fetched):
    out = {}
    for tag, col in [("disc", "discovered"), ("att", "attackdate")]:
        out[f"n_{tag}_all"] = df.groupby(df[col].dt.to_period(freq)).size()
        u = df[df["first_post"]]
        g = u.groupby(u[col].dt.to_period(freq))
        out[f"n_{tag}_unique"] = g.size()
        out[f"n_{tag}_us"] = g["country"].apply(lambda s: (s == "US").sum())
        out[f"n_{tag}_non_us"] = g["country"].apply(lambda s: (s.notna() & (s != "US")).sum())
        out[f"n_{tag}_no_country"] = g["country"].apply(lambda s: s.isna().sum())
        out[f"n_{tag}_young_gang"] = g["gang_age_days"].apply(lambda s: (s < 365).sum())
        out[f"n_{tag}_old_gang"] = g["gang_age_days"].apply(lambda s: (s >= 365).sum())
        out[f"n_{tag}_groups"] = g["group"].nunique()
    c = pd.DataFrame(out).fillna(0)
    span = pd.period_range(c.index.min(), c.index.max(), freq=freq)
    c = c.reindex(span, fill_value=0).astype(int)
    c["complete"] = [p.end_time < fetched for p in span]
    c.index = c.index.astype(str)
    c.index.name = "period"
    return c


def main():
    raw = pathlib.Path(sys.argv[1]) / "ransomware_live"
    out = pathlib.Path(sys.argv[2])
    fetched = pd.Timestamp((raw / "fetched_at.txt").read_text().strip()).tz_localize(None)

    df = load(raw)
    print(f"{len(df)} victim posts, {df['first_post'].sum()} distinct (name, gang) pairs, "
          f"{df['attackdate'].isna().sum()} without an attack date")
    df.to_csv(out / "ransomware_live_victims.csv", index=False)
    for name, freq in [("monthly", "M"), ("quarterly", "Q")]:
        c = counts(df, freq, fetched)
        c.reset_index().to_csv(out / f"ransomware_live_{name}.csv", index=False)
        print(f"{name}: {len(c)} periods, {c.index[0]} to {c.index[-1]}")


if __name__ == "__main__":
    main()
