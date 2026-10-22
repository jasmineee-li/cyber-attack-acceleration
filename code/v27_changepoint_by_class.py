"""Changepoint per bug class: did every kind of exploit step up together in 2026, or only some?

Runs the trend-plus-one-step model from v21 on monthly counts for
  (a) each of DeFiLlama's 13 cause classifications, and
  (b) DeFiHackLabs incidents grouped into six classes by keywords in their free-text cause.
DeFiHackLabs is the relabel-free cross-check: its causes were written at the time, whereas
DeFiLlama re-labelled 515 old entries in its summer-2026 backfill.

Each series is also fitted with v21's kink model (slope change at t0, no jump), the
"acceleration" reading of the same question: the step asks whether the level jumped, the
kink whether the growth rate changed. Both have the same number of parameters, so their
log-likelihoods (llf_step, llf_kink) say which shape fits a series better.

Series with fewer than MIN_TOTAL incidents over 2023-01..2026-09 are listed but not fitted.

Inputs:  data/processed/defillama_hacks.csv, other_sources_incidents_detail.csv
Outputs: data/processed/changepoint_by_class_results.csv   step and kink summaries per class
         data/processed/changepoint_by_class_profiles.csv, _fits.csv            step model
         data/processed/changepoint_by_class_kink_profiles.csv, _kink_fits.csv  kink model

Run: uv run python -I code/v27_changepoint_by_class.py
"""
import pathlib
import re
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v21_did_changepoint_events import MONTHS, changepoint, kink  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
MIN_TOTAL = 25
DHL_CLASSES = [  # first match wins
    ("reentrancy", re.compile(r"reentran", re.I)),
    ("price / oracle manipulation", re.compile(r"price|oracle|flash ?loan|pool manipulation|slippage|sandwich", re.I)),
    ("access control / arbitrary call", re.compile(r"access control|arbitrary|external call|uninitiali|proxy|signature|replay|misconfig|permission|owner", re.I)),
    ("input validation", re.compile(r"validat|unchecked|input", re.I)),
    ("logic / accounting", re.compile(r"logic|precis|round|inflation|reflection|rebas|dividend|reward|burn|mint|integer|overflow|underflow|storage|accounting|calculation|share", re.I)),
]


def dhl_class(cause):
    for name, rx in DHL_CLASSES:
        if rx.search(cause or ""):
            return name
    return "other / unlabelled"


def monthly(df, col):
    df = df[(df["month"] >= MONTHS[0]) & (df["month"] <= MONTHS[-1])]
    out = {}
    for k, g in df.groupby(col):
        out[k] = g.groupby("month").size().reindex(MONTHS).fillna(0).astype(int)
    return out


def main():
    h = pd.read_csv(OUT / "defillama_hacks.csv", parse_dates=["date"])
    h["month"] = h["date"].dt.to_period("M")
    groups = dict(zip(h["classification"], h["group"]))
    d = pd.read_csv(OUT / "other_sources_incidents_detail.csv", parse_dates=["date"])
    d = d[d["source"] == "DeFiHackLabs"].copy()
    d["month"] = d["date"].dt.to_period("M")
    d["cls"] = d["category_raw"].apply(dhl_class)

    series = [("DeFiLlama", k, groups.get(k, "other"), s) for k, s in monthly(h, "classification").items()]
    series += [("DeFiHackLabs", k, "code_bug" if k != "other / unlabelled" else "other", s) for k, s in monthly(d, "cls").items()]

    results, profiles, fits, kprofiles, kfits = [], [], [], [], []
    for source, cls, group, s in sorted(series, key=lambda x: -x[3].sum()):
        label = f"{source}: {cls}"
        row = {"source": source, "classification": cls, "group": group, "n_total": int(s.sum()),
               "n_2025_per_month": float(s.loc["2025-01":"2025-12"].mean()),
               "n_2026q2q3_per_month": float(s.loc["2026-04":"2026-09"].mean())}
        if s.sum() < MIN_TOTAL:
            row.update({"best_t0": "", "shift_ratio": float("nan"), "lr_vs_no_break": float("nan"),
                        "t0_within_2ll": "", "llf_step": float("nan"),
                        "kink_t0": "", "kink_ratio_per_year": float("nan"),
                        "slope_before_per_year": float("nan"), "slope_after_per_year": float("nan"),
                        "lr_kink_vs_no_break": float("nan"), "kink_t0_within_2ll": "",
                        "llf_kink": float("nan"), "note": f"fewer than {MIN_TOTAL} incidents, not fitted"})
        else:
            summary, prof, fit = changepoint(s, label)
            row.update({k: summary[k] for k in ("best_t0", "shift_ratio", "lr_vs_no_break", "t0_within_2ll")})
            row["llf_step"] = summary["llf"]
            ksummary, kprof, kfit = kink(s, label)
            row.update({"kink_t0": ksummary["best_t0"], "kink_ratio_per_year": ksummary["kink_ratio_per_year"],
                        "slope_before_per_year": ksummary["trend_ratio_per_year"],
                        "slope_after_per_year": ksummary["trend_ratio_per_year"] * ksummary["kink_ratio_per_year"],
                        "lr_kink_vs_no_break": ksummary["lr_vs_no_break"],
                        "kink_t0_within_2ll": ksummary["t0_within_2ll"], "llf_kink": ksummary["llf"]})
            row["note"] = ""
            profiles.append(prof)
            fits.append(fit)
            kprofiles.append(kprof)
            kfits.append(kfit)
        results.append(row)
    res = pd.DataFrame(results)
    res.to_csv(OUT / "changepoint_by_class_results.csv", index=False)
    pd.concat(profiles).to_csv(OUT / "changepoint_by_class_profiles.csv", index=False)
    pd.concat(fits).to_csv(OUT / "changepoint_by_class_fits.csv", index=False)
    pd.concat(kprofiles).to_csv(OUT / "changepoint_by_class_kink_profiles.csv", index=False)
    pd.concat(kfits).to_csv(OUT / "changepoint_by_class_kink_fits.csv", index=False)
    print("DeFiHackLabs class sizes:", d["cls"].value_counts().to_dict())
    with pd.option_context("display.width", 220, "display.float_format", "{:,.2f}".format):
        print(res.to_string(index=False))


if __name__ == "__main__":
    main()
