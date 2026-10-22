"""Quarterly incidents in the seven other crypto-hack trackers, one figure each, for the
article's appendix: fig04_crypto_sources_quarterly.png split into separate graphs (DeFiLlama
left out) and drawn in the style of METR's note "LLM contribution to discoveries" (Tom
Cunningham; lib/chart.py and lib/families.py in github.com/tecunningham/ai-discovery-data),
with every font 5 pt larger, like v09.

Input:  data/processed/other_sources_quarterly.csv    (code/other_sources/build_other_sources.py)
        data/processed/certik_dashboard_monthly.csv   (same)
Output: figures/fig13_tracker_slowmist.png ... fig19_tracker_blocksec.png (order of TRACKERS)

Bars are stacked: incidents of $1M or more (blue) under the rest (red: under $1M, or no
amount given where a tracker leaves some blank), so a bar's full height is all incidents. CertiK's dashboard gives only
monthly totals by type, so its bars are one colour (slate, METR's colour for a count with no
split) and count the "Exploit" type. Range 2022Q1 to 2026Q3, the last complete quarter, on
the same x-axis in every graph; CertiK and BlockSec start in 2023. A quarter a tracker has
not fully published (BlockSec's 2026Q3) is outlined and labelled, as in METR's charts.

Run: uv run python -I code/v10_fig_trackers_quarterly.py  (or: uv run dvc repro)
"""
import pathlib

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"

# METR's palette (lib/palette.py): HUMAN blue, AI red, UNATTRIBUTED slate.
BLUE = "#2f6cc1"
RED = "#c1442f"
SLATE = "#37474f"
START, END = pd.Period("2022Q1", "Q"), pd.Period("2026Q3", "Q")
ERA_START = 2026.0
DOWNLOADED = "2026-10-18"
CERTIK = "CertiK"

# METR's font sizes, each 5 pt larger.
UP = 5
FS_TITLE, FS_SUBTITLE, FS_AXIS, FS_TICK = 14 + UP, 9.2 + UP, 9.5 + UP, 8.5 + UP
FS_NOTE, FS_SOURCE = 8 + UP, 7.2 + UP

# (source in other_sources_quarterly.csv, figure file, title, subtitle, source site).
# Order and descriptions follow Table 1 of article/draft.md.
TRACKERS = [
    ("SlowMist Hacked", "fig13_tracker_slowmist.png", "SlowMist Hacked",
     "Blockchain security incidents, including scams", "hacked.slowmist.io"),
    ("Comparitech crypto heists", "fig14_tracker_comparitech.png", "Comparitech crypto heists",
     "Hacks of exchanges, coins and DeFi apps", "comparitech.com"),
    (CERTIK, "fig15_tracker_certik.png", "CertiK incident dashboard",
     "Incidents in its \"Exploit\" category; no split by size", "certik.com"),
    ("rekt.news leaderboard", "fig16_tracker_rekt.png", "rekt.news leaderboard",
     "Incidents it wrote articles about", "rekt.news"),
    ("DeFiHackLabs", "fig17_tracker_defihacklabs.png", "DeFiHackLabs",
     "Code exploits that volunteers reproduce", "github.com/SunWeb3Sec/DeFiHackLabs"),
    ("Web3 Is Going Great (hack/scam)", "fig18_tracker_web3isgoinggreat.png",
     "Web3 Is Going Great", "One editor's selection of hacks and scams", "web3isgoinggreat.com"),
    ("BlockSec Security Incidents", "fig19_tracker_blocksec.png", "BlockSec security incidents",
     r"Incidents with losses of \$100,000 or more", "blocksec.com"),
]


def quarterly():
    """One frame per tracker: quarter, x (quarter centre in years), big, rest, partial."""
    o = pd.read_csv(PROC / "other_sources_quarterly.csv")
    o["period"] = pd.PeriodIndex(o["quarter"], freq="Q")
    o = o[(o["period"] >= START) & (o["period"] <= END) & (o["coverage"] != "before_coverage")]
    out = {}
    for src, *_ in TRACKERS:
        if src == CERTIK:
            continue
        s = o[o["source"] == src]
        assert len(s), f"missing source: {src}"
        assert (s["coverage"] != "after_last_update").all(), f"{src} stopped updating"
        out[src] = pd.DataFrame({
            "period": s["period"].values,
            "big": s["n_ge_1m"].values,
            "rest": (s["n_incidents"] - s["n_ge_1m"]).values,
            "no_amount": (s["n_incidents"] - s["n_with_amount"]).values,
            "partial": (s["coverage"] == "partial").values,
        })

    c = pd.read_csv(PROC / "certik_dashboard_monthly.csv")
    c = c[~c["is_current_month"]]
    c["period"] = pd.PeriodIndex(c["month"], freq="M").asfreq("Q")
    cq = c.groupby("period").agg(n=("incidents_Exploit", "sum"), months=("month", "size"))
    cq = cq[(cq.index >= START) & (cq.index <= END)]
    out[CERTIK] = pd.DataFrame({"period": cq.index, "big": float("nan"), "rest": cq["n"].values,
                                "no_amount": 0, "partial": (cq["months"] < 3).values})
    for d in out.values():
        d["x"] = d["period"].dt.year + (d["period"].dt.quarter - 0.5) / 4
        d["total"] = d["big"].fillna(0) + d["rest"]
    return out


def last_covered(src):
    """Last date the source covers, which is how build_other_sources.py dates a partial quarter."""
    o = pd.read_csv(PROC / "other_sources_quarterly.csv", usecols=["source", "last_date"])
    dates = o.loc[o["source"] == src, "last_date"].unique()
    assert len(dates) == 1, f"{src}: {dates}"
    return dates[0]


def figure(d, src, fname, title, subtitle, site):
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    fig.suptitle(title, x=0.12, y=0.985, ha="left", fontsize=FS_TITLE, fontweight="bold")
    ax.set_title(subtitle, loc="left", fontsize=FS_SUBTITLE, color="#444444", pad=14)

    width = 0.86 / 4
    if d["big"].notna().any():
        ax.bar(d["x"], d["big"], width=width, color=BLUE, label=r"\$1M or more", zorder=3)
        # rekt.news and BlockSec give an amount for every incident in range.
        rest = r"under \$1M or no amount" if d["no_amount"].sum() else r"under \$1M"
        ax.bar(d["x"], d["rest"], bottom=d["big"], width=width, color=RED, label=rest,
               zorder=3)
    else:
        ax.bar(d["x"], d["rest"], width=width, color=SLATE, zorder=3)

    left, right = START.year - 0.06, END.year + END.quarter / 4 + 0.06
    ax.set_xlim(left, right)
    ylim = d["total"].max() * 1.24
    if d["partial"].any():
        # A part quarter's bar is outlined and labelled so it doesn't read as a collapse. The
        # label sits above the last two years of bars, right-aligned over the part bar, below
        # the "Jan 2026 onward" label (top ~10% of the axes).
        p = d[d["partial"]].iloc[-1]
        ax.bar([p["x"]], [p["total"]], width=width, facecolor="none", edgecolor="#444444",
               linewidth=1.1, zorder=4)
        note_y = d["total"].iloc[-8:].max() * 1.05
        ylim = max(ylim, note_y / 0.74)
        ax.text(right - (right - ERA_START) * 0.025, note_y,
                f"partial quarter\nthrough {last_covered(src)}", fontsize=FS_NOTE,
                color="#555555", ha="right", va="bottom", zorder=5)
    ax.set_ylim(0, ylim)

    # "Jan 2026 onward" band, as in METR's shade_era().
    ax.axvspan(ERA_START, right, color=RED, alpha=0.055, zorder=0)
    ax.text(right - (right - ERA_START) * 0.025, 0.975, "Jan 2026 onward",
            transform=ax.get_xaxis_transform(), fontsize=FS_NOTE, color=RED,
            va="top", ha="right")

    # Axis styling, as in METR's style().
    ax.set_xlabel("Year", fontsize=FS_AXIS)
    ax.set_ylabel("Incidents that quarter", fontsize=FS_AXIS)
    ax.grid(color="#d5d5d5", linewidth=0.7, alpha=0.65)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=FS_TICK, color="#777777")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#777777")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
    if ax.get_legend_handles_labels()[0]:
        # Two columns at upper left, clear of the era label at the top right (as in METR).
        ax.legend(frameon=False, fontsize=FS_NOTE, ncol=2, loc="upper left")

    fig.text(0.12, 0.018, f"Source: {site}, downloaded {DOWNLOADED}.", fontsize=FS_SOURCE,
             color="#777777", ha="left")
    fig.subplots_adjust(left=0.12, right=0.97, top=0.82, bottom=0.21)
    fig.savefig(FIGS / fname, dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    FIGS.mkdir(exist_ok=True)
    data = quarterly()
    for src, fname, title, subtitle, site in TRACKERS:
        figure(data[src], src, fname, title, subtitle, site)
