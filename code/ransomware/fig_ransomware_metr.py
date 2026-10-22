"""Ransomware bar graphs in the style of METR's note "LLM contribution to discoveries"
(Tom Cunningham; lib/chart.py in github.com/tecunningham/ai-discovery-data), with every font
5 pt larger, matching code/v09_fig_defillama_monthly_hacks.py (monthly) and
code/v10_fig_trackers_quarterly.py (quarterly).

Input:  data/processed/ransomware_live_monthly.csv          (build_ransomware_live.py)
        data/processed/ransomware_live_quarterly.csv        (same)
        data/processed/comparitech_ransomware_monthly.csv   (build_comparitech_ransomware.py)
Output: figures/fig31_ransomware_live_per_month.png    gang reports: victims posted on leak
                                                       sites, by month ransomware.live first
                                                       saw the post, from 2022-01
        figures/fig32_comparitech_ransomware_per_month.png   confirmed attacks, by month of
                                                       the attack, from 2020-01
        figures/fig35_ransomware_live_groups_per_quarter.png  hacker groups naming at least
                                                       one victim that quarter, from 2022Q1

fig31 starts in 2022 because ransomware.live's tracking began in September 2021 with a
one-off backlog. It counts each (victim, gang) pair once. fig32 stacks US attacks confirmed
by a data-breach notice (red) on all other confirmed attacks (blue); the red part is the kind
of confirmation that arrives last, so recent months are low partly because notices haven't
been filed yet. October 2026 is incomplete (downloaded 19 October), so in the monthly graphs
its bar is outlined and labelled, as in METR's charts. fig35 stops at 2026Q3, the last
complete quarter, as v10 does: a count of distinct groups in a part quarter isn't comparable.
It counts group names as ransomware.live records them, so a renamed gang counts as a new group.

Run: uv run python -I code/ransomware/fig_ransomware_metr.py  (or: uv run dvc repro)
"""
import pathlib

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"

# METR's palette (lib/palette.py): HUMAN blue and AI red.
BLUE = "#2f6cc1"
RED = "#c1442f"
SNAPSHOT = pd.Timestamp("2026-10-19")  # download date of both raw folders
ERA_START = 2026.0

# METR's font sizes, each 5 pt larger.
UP = 5
FS_TITLE, FS_SUBTITLE, FS_AXIS, FS_TICK = 14 + UP, 9.2 + UP, 9.5 + UP, 8.5 + UP
FS_NOTE, FS_SOURCE = 8 + UP, 7.2 + UP

# (input, frequency, start period, figure file, title, subtitle, y label, source line,
#  stacked layers as [(column, colour, legend label or None)], bottom layer first)
FIGURES = [
    ("ransomware_live_monthly.csv", "M", "2022-01", "fig31_ransomware_live_per_month.png",
     "Ransomware victims posted per month",
     "Victims named on hackers' leak sites, by month first seen",
     "Victims posted that month",
     "Source: Ransomware.live (ransomware.live), downloaded 2026-10-19.",
     [("n_disc_unique", BLUE, None)]),
    ("comparitech_ransomware_monthly.csv", "M", "2020-01", "fig32_comparitech_ransomware_per_month.png",
     "Confirmed ransomware attacks per month",
     "By month of the attack; recent months may still grow",
     "Attacks that month",
     "Source: Comparitech Ransomware Intelligence Platform (ransomware.comparitech.com),\n"
     "downloaded 2026-10-19.",
     [("n_other", BLUE, "other confirmation"), ("n_us_regulator_filed", RED, "US breach notice")]),
    ("ransomware_live_quarterly.csv", "Q", "2022Q1", "fig35_ransomware_live_groups_per_quarter.png",
     "Hacker groups posting ransomware victims",
     "Groups naming at least one victim on a leak site that quarter",
     "Groups that quarter",
     "Source: Ransomware.live (ransomware.live), downloaded 2026-10-19.",
     [("n_disc_groups", BLUE, None)]),
]


def series(src, freq, start):
    """Counts per period; monthly runs to the part month, quarterly to the last full quarter."""
    m = pd.read_csv(PROC / src)
    m["period"] = pd.PeriodIndex(m["period"], freq=freq)
    if "n_us_regulator_filed" in m:
        m["n_other"] = m["n_all"] - m["n_us_regulator_filed"]
    end = pd.Period(SNAPSHOT, freq) - (1 if freq == "Q" else 0)
    periods = pd.period_range(start, end, freq=freq)
    m = m.set_index("period").reindex(periods, fill_value=0)
    per_year = 12 if freq == "M" else 4
    sub = periods.month if freq == "M" else periods.quarter
    m["x"] = periods.year + (sub - 0.5) / per_year  # period centre, in years
    m.attrs["per_year"] = per_year
    m.attrs["partial"] = periods[-1].end_time >= SNAPSHOT
    return m


def figure(m, fname, title, subtitle, ylabel, source, layers):
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    fig.suptitle(title, x=0.12, y=0.985, ha="left", fontsize=FS_TITLE, fontweight="bold")
    ax.set_title(subtitle, loc="left", fontsize=FS_SUBTITLE, color="#444444", pad=14)

    per_year = m.attrs["per_year"]
    width = 0.86 / per_year
    bottom = 0
    for col, color, label in layers:
        ax.bar(m["x"], m[col], bottom=bottom, width=width, color=color, label=label, zorder=3)
        bottom = bottom + m[col]
    total = bottom
    if per_year == 12:
        left, right = m["x"].iloc[0] - 1 / 12, m["x"].iloc[-1] + 1.5 / 12
    else:  # v10's quarterly margins
        left, right = m["x"].iloc[0] - 0.5 / 4 - 0.06, m["x"].iloc[-1] + 0.5 / 4 + 0.06
    ax.set_xlim(left, right)
    has_legend = any(label for _, _, label in layers)
    # Quarterly bars reach the top right, so leave room for the era label, as v10 does.
    ylim = total.max() * (1.3 if has_legend else 1.12 if per_year == 12 else 1.24)
    if m.attrs["partial"]:
        # The last month is incomplete: outline its bar and say so, so it doesn't read as a
        # collapse. Note above the last two years of bars, right-aligned over the partial one,
        # below the "Jan 2026 onward" label (top ~10% of the axes), as in v09.
        ax.bar([m["x"].iloc[-1]], [total.iloc[-1]], width=width, facecolor="none",
               edgecolor="#444444", linewidth=1.1, zorder=4)
        note_y = total.iloc[-2 * per_year:].max() * 1.05
        ylim = max(ylim, note_y / 0.74)
        ax.text(right - (right - ERA_START) * 0.025, note_y,
                f"partial month\nthrough {SNAPSHOT:%Y-%m-%d}", fontsize=FS_NOTE,
                color="#555555", ha="right", va="bottom", zorder=5)
    ax.set_ylim(0, ylim)
    # "Jan 2026 onward" band, as in METR's shade_era().
    ax.axvspan(ERA_START, right, color=RED, alpha=0.055, zorder=0)
    ax.text(right - (right - ERA_START) * 0.025, 0.975, "Jan 2026 onward",
            transform=ax.get_xaxis_transform(), fontsize=FS_NOTE, color=RED,
            va="top", ha="right")

    # Axis styling, as in METR's style().
    ax.set_xlabel("Year", fontsize=FS_AXIS)
    ax.set_ylabel(ylabel, fontsize=FS_AXIS)
    ax.grid(color="#d5d5d5", linewidth=0.7, alpha=0.65)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=FS_TICK, color="#777777")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#777777")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
    if has_legend:
        # Upper left, clear of the era label at the top right; top layer listed first.
        h, lab = ax.get_legend_handles_labels()
        ax.legend(h[::-1], lab[::-1], frameon=False, fontsize=FS_NOTE, ncol=2, loc="upper left")

    fig.text(0.12, 0.018, source, fontsize=FS_SOURCE, color="#777777", ha="left")
    # A source that wraps to a second line needs more room below the axis.
    fig.subplots_adjust(left=0.12, right=0.97, top=0.82, bottom=0.21 + 0.04 * source.count("\n"))
    fig.savefig(FIGS / fname, dpi=180, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    FIGS.mkdir(exist_ok=True)
    for src, freq, start, fname, title, subtitle, ylabel, source, layers in FIGURES:
        figure(series(src, freq, start), fname, title, subtitle, ylabel, source, layers)
