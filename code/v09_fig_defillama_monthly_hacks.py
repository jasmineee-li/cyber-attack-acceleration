"""Monthly DeFiLlama hack graphs, 2020 onward: Python versions of the five "//use" graphs
in code/cheryl's stata checks/check defillama.do, drawn in the style of METR's note
"LLM contribution to discoveries" (Tom Cunningham; lib/chart.py and lib/families.py in
github.com/tecunningham/ai-discovery-data), with every font 5 pt larger.

Input:  data/processed/defillama_hacks_raw.csv (from v08)
Output: figures/fig08_defillama_hacks_per_month.png        number of hacks
        figures/fig09_defillama_avg_hack_size.png          average hack size, $M
        figures/fig10_defillama_total_stolen.png           total stolen, $M
        figures/fig11_defillama_small_hacks_per_month.png  hacks under $4.5M
        figures/fig12_defillama_small_hacks_stolen.png     stolen in hacks under $4.5M, $M

Matches the do-file: every hack counts (the do-file's biggest-hack-per-month removal is
switched off), "small" means under $4.5M (the 75th percentile of amounts since 2020), and
hacks with no amount count in the hack total but not as small. Unlike the Stata graphs,
months with no hacks (only May 2020) are plotted as 0 rather than skipped.
Blue = all hacks, red = small hacks. October 2026 is incomplete (downloaded 18 Oct), so its
bar is hatched (diagonal lines in the bar's colour on white) and labelled.

Run: uv run python -I code/v09_fig_defillama_monthly_hacks.py  (or: uv run dvc repro)
"""
import pathlib

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
FIGS = ROOT / "figures"

# METR's palette (lib/palette.py): HUMAN blue and AI red.
BLUE = "#2f6cc1"
RED = "#c1442f"
START = "2020-01"
SMALL = 4_500_000
SNAPSHOT = pd.Timestamp("2026-10-18")  # download date of the raw files (v01)
ERA_START = 2026.0
SOURCE = "Source: DefiLlama hacks list (api.llama.fi/hacks), downloaded 2026-10-18."

# METR's font sizes, each 5 pt larger.
UP = 5
FS_TITLE, FS_SUBTITLE, FS_AXIS, FS_TICK = 14 + UP, 9.2 + UP, 9.5 + UP, 8.5 + UP
FS_NOTE, FS_SOURCE = 8 + UP, 7.2 + UP


def monthly():
    h = pd.read_csv(PROC / "defillama_hacks_raw.csv")
    h["month"] = pd.PeriodIndex(h["date"], freq="M")
    h = h[h["month"] >= pd.Period(START, "M")]
    assert h["amount"].quantile(0.75) == SMALL, "small-hack cutoff is no longer the 75th percentile"
    h["small"] = h["amount"] < SMALL  # missing amounts compare False, as in Stata
    g = h.groupby("month")
    m = pd.DataFrame({
        "n": g.size(),
        "avg_m": g["amount"].mean() / 1e6,
        "total_m": g["amount"].sum() / 1e6,
        "n_small": g["small"].sum(),
        "small_m": h[h["small"]].groupby("month")["amount"].sum() / 1e6,
    })
    months = pd.period_range(START, pd.Period(SNAPSHOT, "M"), freq="M")
    m = m.reindex(months).fillna({"n": 0, "total_m": 0, "n_small": 0, "small_m": 0})
    m["x"] = months.year + (months.month - 0.5) / 12  # month centre, in years
    return m


# frame(), event_lines(), style() and save() are shared with v12's weekly figure.
def frame(title, subtitle):
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    fig.suptitle(title, x=0.12, y=0.985, ha="left", fontsize=FS_TITLE, fontweight="bold")
    ax.set_title(subtitle, loc="left", fontsize=FS_SUBTITLE, color="#444444", pad=14)
    return fig, ax


def event_lines(ax, events, top):
    """Vertical lines with a legend; events are (x, label, color, linestyle). The lines stop
    just under height `top` (the partial-period note) so they don't run through its text."""
    for x, label, c, ls in events:
        ax.axvline(x, ymax=top / ax.get_ylim()[1] - 0.02, color=c, linestyle=ls,
                   linewidth=1.8, zorder=4.5, label=label)
    if events:
        ax.legend(loc="upper left", frameon=False, fontsize=FS_NOTE, handlelength=2.2)


def hatch_partial(bars, partial, color):
    """Redraw the bars of incomplete periods as diagonal lines in their colour on white, so a
    part period stands apart from the solid complete ones. partial: one flag per bar."""
    for bar, p in zip(bars, partial):
        if p:
            bar.set(facecolor="white", edgecolor=color, hatch="////", linewidth=1.1)


def style(ax, xlabel, ylabel):
    """Axis styling, as in METR's style()."""
    ax.set_xlabel(xlabel, fontsize=FS_AXIS)
    ax.set_ylabel(ylabel, fontsize=FS_AXIS)
    ax.grid(color="#d5d5d5", linewidth=0.7, alpha=0.65)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=FS_TICK, color="#777777")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#777777")


def save(fig, fname):
    fig.text(0.12, 0.018, SOURCE, fontsize=FS_SOURCE, color="#777777", ha="left")
    fig.subplots_adjust(left=0.12, right=0.97, top=0.82, bottom=0.21)
    fig.savefig(FIGS / fname, dpi=180, facecolor="white")
    plt.close(fig)


def figure(m, col, color, title, subtitle, ylabel, fname, events=()):
    """events: (decimal year, label, color, linestyle) for vertical lines; used by v12."""
    fig, ax = frame(title, subtitle)

    width = 0.86 / 12
    bars = ax.bar(m["x"], m[col], width=width, color=color, zorder=3)
    # The last month is incomplete: hatch its bar and say so, so it doesn't read as a collapse.
    hatch_partial(bars, [False] * (len(m) - 1) + [True], color)
    left, right = m["x"].iloc[0] - 1 / 12, m["x"].iloc[-1] + 1.5 / 12
    ax.set_xlim(left, right)
    # The note sits above the recent bars, right-aligned over the partial one, as in
    # METR's NVD chart; beside the short bar it would land on its taller neighbours.
    # The text spans roughly the last two years of bars, so it clears all of them; room is
    # left for it below the "Jan 2026 onward" label (top ~10% of the axes).
    note_y = m[col].iloc[-24:].max() * 1.05
    ax.set_ylim(0, max(m[col].max() * 1.12, note_y / 0.74))
    ax.text(right - (right - ERA_START) * 0.025, note_y,
            f"partial month\nthrough {SNAPSHOT:%Y-%m-%d}", fontsize=FS_NOTE,
            color="#555555", ha="right", va="bottom", zorder=5)
    # "Jan 2026 onward" band, as in METR's shade_era().
    ax.axvspan(ERA_START, right, color=RED, alpha=0.055, zorder=0)
    ax.text(right - (right - ERA_START) * 0.025, 0.975, "Jan 2026 onward",
            transform=ax.get_xaxis_transform(), fontsize=FS_NOTE, color=RED,
            va="top", ha="right")
    event_lines(ax, events, note_y)

    style(ax, "Year", ylabel)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))
    save(fig, fname)


if __name__ == "__main__":
    FIGS.mkdir(exist_ok=True)
    m = monthly()
    figure(m, "n", BLUE, "Crypto hacks per month",
           "Hacks in DefiLlama's list, by month of the hack",
           "Hacks that month", "fig08_defillama_hacks_per_month.png")
    figure(m, "avg_m", BLUE, "Average crypto hack size",
           "Mean reported loss per hack, by month",
           r"Average loss (\$M)", "fig09_defillama_avg_hack_size.png")
    figure(m, "total_m", BLUE, "Total stolen in crypto hacks",
           "Sum of reported losses, by month",
           r"Stolen that month (\$M)", "fig10_defillama_total_stolen.png")
    figure(m, "n_small", RED, "Small crypto hacks per month",
           r"Hacks with a reported loss under \$4.5M (75th percentile since 2020)",
           "Small hacks that month", "fig11_defillama_small_hacks_per_month.png")
    figure(m, "small_m", RED, "Stolen in small crypto hacks",
           r"Sum of losses in hacks under \$4.5M, by month",
           r"Stolen that month (\$M)", "fig12_defillama_small_hacks_stolen.png")
