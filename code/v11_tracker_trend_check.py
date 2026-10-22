"""Did each crypto-hack tracker's trend speed up in 2026? Numbers for the appendix verdicts.

Input:  the quarterly counts drawn in v10 (data/processed/other_sources_quarterly.csv and
        certik_dashboard_monthly.csv, read through v10's quarterly())
Output: data/processed/tracker_trend_check.csv, one row per tracker

Method. Fit a trend to a tracker's quarterly incident counts up to 2025Q4 and project it to
2026Q2-Q3. Compare the actual 2026Q2-Q3 average with the projection (BlockSec: Q2 only, as
its Q3 is incomplete). To allow for ordinary ups and downs, divide that ratio by the largest
ratio of any pre-2026 quarter to the same trend: the "margin". A margin of 1.1 or more means
2026 is at least 10% further above the trend than any earlier quarter was.

The trend is drawn four ways: a steady growth rate (a straight line through log counts) or a
straight line through the counts, each fitted from 2022Q1 or from 2023Q1 (CertiK and BlockSec
start in 2023, so for them the two start years coincide). Verdict: "acceleration" if the margin
is at least 1.1 in all four, "no clear acceleration" if in none, "unclear" otherwise. The
headline numbers use the steady growth rate from 2022Q1.

Quarters a tracker plainly did not record fully are left out of the fit, like BlockSec's
incomplete 2026Q3: DeFiHackLabs' 2025Q4 (7 incidents against about 50 in each earlier quarter
of 2025; a gap in volunteer effort, see notes/other_crypto_sources.md).

All four versions end at 2025Q4, so a thin 2025 lowers them all. As a check (reported in the
appendix where it matters, not used in the verdict), the margin_*_to2024 columns refit each
version through 2024Q4 only. A straight-line trend that projects zero or fewer incidents for
2026 gives no meaningful margin and is left blank.

Run: uv run python -I code/v11_tracker_trend_check.py  (or: uv run dvc repro)
"""
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))  # -I leaves the script's folder off the path
import v10_fig_trackers_quarterly as v10  # noqa: E402

FIT_END = "2025Q4"
MARGIN = 1.1
GAPS = {"DeFiHackLabs": ["2025Q4"]}  # quarters not fully recorded; left out of the fit
VARIANTS = [("log", "2022Q1"), ("linear", "2022Q1"), ("log", "2023Q1"), ("linear", "2023Q1")]


def fit(d, shape, start, end=FIT_END, gaps=()):
    """Trend fitted from `start` (or the tracker's first quarter) to `end`, at every quarter."""
    t = np.arange(len(d))
    pre = d.loc[start:end].drop(index=list(gaps), errors="ignore")
    tp = np.array([d.index.get_loc(q) for q in pre.index])
    # Earlier quarters 2026 is compared against: always through FIT_END, even when the
    # trend is fitted on fewer of them.
    past_q = d.loc[start:FIT_END].drop(index=list(gaps), errors="ignore")
    tq = np.array([d.index.get_loc(q) for q in past_q.index])
    if shape == "log":
        slope, intercept = np.polyfit(tp, np.log(pre["total"]), 1)
        trend = np.exp(intercept + slope * t)
    else:
        slope, intercept = np.polyfit(tp, pre["total"], 1)
        trend = intercept + slope * t
    post = ["2026Q2"] if d.loc["2026Q3", "partial"] else ["2026Q2", "2026Q3"]
    at = [d.index.get_loc(q) for q in post]
    past = past_q["total"].values / trend[tq]
    ratio = d["total"].iloc[at].mean() / trend[at].mean()
    return {"slope": slope, "pre": pre, "post": post, "trend_avg": trend[at].mean(),
            "ratio": ratio, "past_max": past.max(), "past_max_q": past_q.index[past.argmax()],
            "margin": ratio / past.max() if trend[at].mean() > 0 else float("nan")}


def check(src, d):
    d = d.set_index(d["period"].astype(str))
    assert (d.loc[:FIT_END, "total"] > 0).all(), f"{src}: a zero quarter can't be logged"
    gaps = GAPS.get(src, [])
    runs = [fit(d, shape, start, gaps=gaps) for shape, start in VARIANTS]
    to2024 = [fit(d, shape, start, end="2024Q4", gaps=gaps) for shape, start in VARIANTS]
    valid = [r for r in runs if not np.isnan(r["margin"])]
    hits = sum(r["margin"] >= MARGIN for r in valid)
    verdict = ("acceleration" if hits == len(valid) else
               "no clear acceleration" if hits == 0 else "unclear")
    main = runs[0]
    return {
        "tracker": src, "fit_from": main["pre"].index[0], "fit_to": FIT_END,
        "trend_growth_per_year": round(np.exp(4 * main["slope"]) - 1, 3),
        "compared_quarters": "-".join(main["post"]),
        "actual_avg": round(d.loc[main["post"], "total"].mean(), 1),
        "trend_avg": round(main["trend_avg"], 1),
        "ratio_to_trend": round(main["ratio"], 2),
        "max_past_ratio": round(main["past_max"], 2), "max_past_quarter": main["past_max_q"],
        **{f"margin_{shape}_{start[:4]}": round(r["margin"], 3)
           for (shape, start), r in zip(VARIANTS, runs)},
        "variants_with_acceleration": f"{hits} of {len(valid)}",
        **{f"margin_{shape}_{start[:4]}_to2024": round(r["margin"], 3)
           for (shape, start), r in zip(VARIANTS, to2024)},
        "gaps_left_out": ";".join(gaps),
        "verdict": verdict,
    }


if __name__ == "__main__":
    data = v10.quarterly()
    out = pd.DataFrame([check(src, data[src]) for src, *_ in v10.TRACKERS])
    out.to_csv(ROOT / "data" / "processed" / "tracker_trend_check.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(out.drop(columns=["fit_to", "compared_quarters"]))
