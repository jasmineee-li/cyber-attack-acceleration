"""Monthly DeFiLlama hacks by exploit type, Jan 2023 - Sep 2026, split by whether the type
ACCELERATED (its growth rate rose) in late 2025 or 2026. Counts only: fig38/fig39 (v14) show
the same split with the fitted trend-plus-kink curve and a note in each panel. Descends from
the last two graphs in code/cheryl's stata checks/check defillama.do, in the style of
fig08-fig12 (v09).

Input:  data/processed/defillama_hacks_raw.csv (from v08)
        data/processed/changepoint_by_class_results.csv (kink fits, from v27)
Output: figures/fig36_defillama_hacks_by_type_accelerated_counts.png      6 types
        figures/fig37_defillama_hacks_by_type_not_accelerated_counts.png  7 types

The kink model (v21.kink): log-rate = a + b*t + d*max(0, t - t0), a negative-binomial fit
with the kink month t0 profiled over Jul 2024 - Jul 2026. The rate's growth factor per year
is exp(b) before t0 and exp(b + d) after; d > 0 is acceleration.

A type counts as accelerated when all three hold:
  1. the kink improves on a plain trend by more than LR_MIN (2 x log-likelihood, 1 df;
     about p < 0.05 for a fixed t0, less for a profiled one),
  2. the slope after the kink is steeper than before (d > 0), and
  3. some month in Oct 2025 - Jun 2026 is within 2 log-likelihood units of the best kink.
Rule 3 uses the near-equivalent window rather than the best month alone because a kink's
timing is weakly identified: a continuous bend fitted to a series that jumps in early 2026
can land its best t0 months before the jump (Access Control and Token & Share Accounting
best-fit Aug 2025, Bridge & Cross-Chain Jul 2024, each with 2026 months fitting nearly as
well). Governance and Market Manipulation have too few hacks to fit (under 25) and go in the
second figure untested; Governance's counts do rise (2 a month from Jun 2026, after 5 single
hacks over 2023-2025).

The rule is overridden for the types in NOT_ACCELERATED, which go in the second figure by the
authors' judgement. Protocol Logic passes all three tests, but the authors read it as not
accelerating (23 Oct 2026).

As in the do-file: months with no hacks of a type are 0, each panel has its own y-axis, and
October 2026 (data to the 16th) is left out. The one hack with no classification (Locus
Finance, 2026-10-07) is outside the window.

Run: uv run python -I code/v13_fig_defillama_hacks_by_type.py  (or: uv run dvc repro)
"""
import math
import pathlib
import sys

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))  # -I leaves the script's folder off the path
import v09_fig_defillama_monthly_hacks as v09  # noqa: E402

START, END = "2023-01", "2026-09"
COLS = 4
FIT = "#D98F6E"  # fitted line, as in fig29
LR_MIN = 4.0
ACCEL_WINDOW = pd.period_range("2025-10", "2026-06", freq="M")
NOT_ACCELERATED = {"Protocol Logic"}  # judged not accelerated, whatever the rule says


def kink_results():
    """v27's fits per DeFiLlama type, indexed by type, largest type first."""
    res = pd.read_csv(v09.PROC / "changepoint_by_class_results.csv")
    res = res[res["source"] == "DeFiLlama"].set_index("classification")
    return res.loc[res["n_total"].sort_values(ascending=False).index]


def accelerated(r):
    if pd.isna(r["lr_kink_vs_no_break"]):
        return False
    lo, hi = (pd.Period(m, "M") for m in r["kink_t0_within_2ll"].split(".."))
    return (r["lr_kink_vs_no_break"] > LR_MIN and r["kink_ratio_per_year"] > 1
            and lo <= ACCEL_WINDOW[-1] and hi >= ACCEL_WINDOW[0])


def split(res):
    """(types that accelerated, types that did not), each largest type first."""
    assert NOT_ACCELERATED <= set(res.index), f"unknown type in {NOT_ACCELERATED}"
    flags = res.apply(accelerated, axis=1) & ~res.index.isin(NOT_ACCELERATED)
    return list(res.index[flags]), list(res.index[~flags])


def monthly_by_type(types):
    """Hacks per month per classification over the window; months with none are 0."""
    h = pd.read_csv(v09.PROC / "defillama_hacks_raw.csv")
    h["month"] = pd.PeriodIndex(h["date"], freq="M")
    months = pd.period_range(START, END, freq="M")
    h = h[h["month"].isin(months)]
    assert h["classification"].notna().all(), "unclassified hack inside the window"
    counts = h.groupby(["month", "classification"]).size().unstack(fill_value=0)
    counts = counts.reindex(index=months, columns=types, fill_value=0)
    assert counts.sum().sum() == len(h), "every hack in the window must be in one panel"
    counts.index = months.year + (months.month - 0.5) / 12  # month centre, in years
    return counts


def grid(counts, types, title, subtitle, fname, fits=None, notes=None):
    """One panel per type. fits: {type: fitted values on counts.index}, drawn in orange over
    the counts; notes: {type: text}, a second title line under the type's name (v14)."""
    fits, notes = fits or {}, notes or {}
    rows = math.ceil(len(types) / COLS)
    head = 0.55 if notes else 0  # extra height per row for the note line under each title
    fig, axes = plt.subplots(rows, COLS, figsize=(13, (3.3 + head) * rows + 1.6), squeeze=False)
    fig.suptitle(title, x=0.05, y=0.985, ha="left", fontsize=v09.FS_TITLE, fontweight="bold")
    fig.text(0.05, 0.985 - 0.5 / fig.get_figheight(), subtitle, ha="left", va="top",
             fontsize=v09.FS_SUBTITLE, color="#444444")
    x = counts.index
    left, right = x[0] - 0.5 / 12, x[-1] + 0.5 / 12
    for ax, t in zip(axes.flat, types):
        ax.plot(x, counts[t], color=v09.BLUE, linewidth=1.6, zorder=3)
        if t in fits:
            ax.plot(x, fits[t], color=FIT, linewidth=2.4, zorder=4)
        ax.axvspan(v09.ERA_START, right, color=v09.RED, alpha=0.055, zorder=0)
        ax.set_title(t, loc="left", fontsize=v09.FS_AXIS, fontweight="bold",
                     pad=36 if notes else 6)
        if t in notes:
            ax.text(0, 1.03, notes[t], transform=ax.transAxes, fontsize=v09.FS_NOTE - 2,
                    color="#444444", ha="left", va="bottom", linespacing=1.15)
        ax.set_xlim(left, right)
        ax.set_ylim(0, max(counts[t].max(), 1) * 1.12)
        v09.style(ax, "", "Hacks that month" if ax in axes[:, 0] else "")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    for ax in axes.flat[len(types):]:
        ax.set_visible(False)
    fig.text(0.05, 0.012, v09.SOURCE, fontsize=v09.FS_SOURCE, color="#777777", ha="left")
    fig.subplots_adjust(left=0.05, right=0.985, top=1 - (1.25 + head) / fig.get_figheight(),
                        bottom=0.9 / fig.get_figheight(), hspace=0.5 + 0.25 * bool(notes),
                        wspace=0.34)
    fig.savefig(v09.FIGS / fname, dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    v09.FIGS.mkdir(exist_ok=True)
    res = kink_results()
    accel, flat = split(res)
    counts = monthly_by_type(accel + flat)
    sub = "Hacks in DefiLlama's list per month. Shaded: Jan 2026 onward."
    grid(counts, accel, "Crypto hack types that accelerated in late 2025 or 2026", sub,
         "fig36_defillama_hacks_by_type_accelerated_counts.png")
    grid(counts, flat, "Crypto hack types that did not accelerate", sub,
         "fig37_defillama_hacks_by_type_not_accelerated_counts.png")
    print("accelerated:", accel)
    print("not:", flat)
