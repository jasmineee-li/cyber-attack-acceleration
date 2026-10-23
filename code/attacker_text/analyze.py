"""Pangram flag rates on attacker messages, by period, with conversation-cluster bootstrap.

Input:  <proc_dir>/pangram_results.csv (from pangram_classify.py), messages.csv, conversations_eligibility.csv,
        pangram_cache/ (for the window-level labels of flagged messages)
Output: <proc_dir>/pangram_trends_by_year.csv   one row per period x sample x cut: numerators, denominators, CI
        <proc_dir>/pangram_trends_by_period.csv the three-period table (2020-22, 2023-24, 2025-26) used in the memo
        <proc_dir>/pangram_flagged_messages.md  every flagged message in full, with Pangram's window labels
        figures/attacker_text/pangram_flags_over_time.png          by year, 2020 to 2026
        figures/attacker_text/pangram_flags_2025_2026_quarterly.png by quarter, Jan 2025 to Mar 2026
        figures/attacker_text/pangram_flags_2025_2026_monthly.png   by month, Jan 2025 to Mar 2026 (sparse; for inspection)
Samples present in the results file are each summarised: A_primary (attacker messages) always,
victim (the comparator) when it has been run. They are never pooled.

The flag is Pangram's own document label: prediction_short in {AI, Mixed}; Human is the rest.
Rates are messages flagged / messages scored. The interval is a percentile bootstrap that
resamples conversations (not messages), 2,000 draws, so repeated messages from one
negotiation do not count as independent evidence. Bins with fewer than 10 conversations
are marked underpowered in the tables.

Cuts, each reported separately: all eligible messages; without the two SilentRansomGroup
chats that supply most of 2026; 100+ words only; message-timestamp-dated conversations only.
Results from more than one Pangram `version` are refused, not pooled.

Also reported: the median of fraction_ai + fraction_ai_assisted (a share of text, not a probability).

Run: python -I code/attacker_text/analyze.py data/processed/attacker_text
"""
import json
import pathlib
import sys

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIGS = ROOT / "figures" / "attacker_text"
# METR's palette and font sizes (each 5 pt larger), as in code/v09_fig_defillama_monthly_hacks.py.
BLUE, RED, GRAY, AXIS_GRAY, GRID_GRAY = "#2f6cc1", "#c1442f", "#444444", "#777777", "#d5d5d5"
UP = 5
FS_TITLE, FS_SUBTITLE, FS_PANEL, FS_AXIS, FS_TICK, FS_NOTE = 14 + UP, 9.2 + UP, 11 + UP, 9.5 + UP, 8.5 + UP, 7.2 + UP
MIN_CONVERSATIONS = 10
PERIODS = {"2020-2022": [2020, 2021, 2022], "2023-2024": [2023, 2024], "2025-2026": [2025, 2026]}
rng = np.random.default_rng(20261019)
# Dropped from the figure only (the tables keep it): a 2021 Conti victim's formally worded request to
# remove a deadline, labelled Mixed at low confidence. Pre-ChatGPT, so a false positive; see the memo.
FIGURE_EXCLUDED = {"519094c72735db8e-0033"}
# The quarterly and monthly figures stop here: after March 2026 the archive has no victim messages
# and only 2 attacker messages (Aug 2026, neither flagged). The yearly figure keeps them.
RECENT_END = "2026-03"


def cluster_bootstrap(flags: pd.Series, clusters: pd.Series, draws: int = 2000) -> tuple[float, float]:
    groups = [flags[clusters == c].to_numpy() for c in clusters.unique()]
    n = len(groups)
    rates = []
    for _ in range(draws):
        pick = rng.integers(0, n, n)
        sample = np.concatenate([groups[i] for i in pick])
        rates.append(sample.mean())
    return float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))


def summarise(df: pd.DataFrame, key: str, label: str, cut: str) -> pd.DataFrame:
    rows = []
    for period, g in df.groupby(key, sort=True):
        n_conv = g["conversation_id"].nunique()
        row = {"period": period, "cut": cut, "sample": label, "conversations": n_conv, "groups": g["group_name"].nunique(),
               "messages_scored": len(g), "failed": int((g["pangram_status"] != "ok").sum()),
               "n_human": int((g["prediction_short"] == "Human").sum()), "n_mixed": int((g["prediction_short"] == "Mixed").sum()),
               "n_ai": int((g["prediction_short"] == "AI").sum()), "n_flagged": int(g["flag"].sum()),
               "flag_share": g["flag"].mean(), "median_fraction_ai_plus_assisted": g["ai_share"].median(),
               "p90_fraction_ai_plus_assisted": g["ai_share"].quantile(0.9), "underpowered": n_conv < MIN_CONVERSATIONS}
        row["ci_low"], row["ci_high"] = cluster_bootstrap(g["flag"], g["conversation_id"]) if n_conv >= 2 else (np.nan, np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def prepare(res: pd.DataFrame, conv: pd.DataFrame, msg_ts: pd.Series) -> pd.DataFrame:
    ok = res[res["pangram_status"] == "ok"].copy()
    # Message timestamp where the archive has one (several formats), else the conversation's date.
    stamped = pd.to_datetime(msg_ts.reindex(ok["unit_id"]).replace("", None).to_numpy(), format="mixed", errors="coerce", utc=True).tz_localize(None)
    ok["date"] = pd.Series(stamped, index=ok.index).fillna(pd.to_datetime(ok["conversation_id"].map(conv["conversation_date"])))
    ok["flag"] = ok["prediction_short"].isin(["AI", "Mixed"]).astype(int)
    ok["ai_share"] = ok["fraction_ai"] + ok["fraction_ai_assisted"]
    ok["year"] = ok["year"].astype(int)
    ok["period"] = ok["year"].map({y: p for p, ys in PERIODS.items() for y in ys})
    ok["date_confidence"] = ok["conversation_id"].map(conv["date_confidence"])
    ok["year_label"] = ok["year"].map(lambda y: "2026 to Oct 19" if y == 2026 else str(y))
    return ok


def cuts_for(ok: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "all": ok,
        "without_SilentRansomGroup": ok[ok["group_name"] != "SilentRansomGroup"],
        "100plus_words": ok[ok["word_count"] >= 100],
        "message_timestamp_dated": ok[ok["date_confidence"] == "high"],
    }


def style_bar_panel(ax, title: str, color: str, labels: list[str], label_size: float) -> None:
    ax.set_title(title, loc="left", fontsize=FS_PANEL, fontweight="bold", color=color, pad=10)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, fontsize=label_size)
    ax.set_xlim(-0.6, len(labels) - 0.4)
    ax.tick_params(axis="x", pad=46, color=AXIS_GRAY)
    ax.tick_params(axis="y", labelsize=FS_TICK, color=AXIS_GRAY)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(axis="y", color=GRID_GRAY, linewidth=0.7, alpha=0.65)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(AXIS_GRAY)


def bar(ax, i: int, share: float, color: str, partial: bool, note: str, note_size: float, width: float = 0.62) -> None:
    if partial:  # hatched in its colour on white, as the incomplete month is in the DefiLlama charts
        ax.bar(i, share, width=width, facecolor="white", edgecolor=color, hatch="////", linewidth=1.3, zorder=3)
    else:
        ax.bar(i, share, width=width, color=color, zorder=3)
    ax.text(i, -0.07, note, ha="center", va="top", fontsize=note_size, color=AXIS_GRAY, transform=ax.get_xaxis_transform())


def draw_panel(ax, y: pd.DataFrame, order: list[str], title: str, color: str) -> None:
    for i, p in enumerate(order):
        r = y.loc[p]
        bar(ax, i, r["flag_share"], color, p.startswith("2026"), f"{int(r['n_flagged'])}/{int(r['messages_scored'])}\n{int(r['conversations'])} chats", FS_NOTE)
    style_bar_panel(ax, title, color, [p[:4] for p in order], FS_TICK)


def figure_header(fig, title: str, subtitle: str) -> None:
    fig.suptitle(title, x=0.065, y=0.985, ha="left", fontsize=FS_TITLE, fontweight="bold")
    fig.text(0.065, 0.91, subtitle, fontsize=FS_SUBTITLE, color=GRAY, va="top")


def draw_recent(panels: dict[str, pd.DataFrame], version: str, freq: str, fname: str) -> None:
    """Flag share by quarter ("Q") or month ("M"), January 2025 to RECENT_END. Monthly bins hold a handful of messages each."""
    monthly = freq == "M"
    bins = pd.period_range("2025-01", RECENT_END, freq=freq)
    if monthly:
        labels = [p.strftime("%b\n%Y") if p.month == 1 else p.strftime("%b") for p in bins]
    else:
        labels = [f"Q{p.quarter}\n{p.year}" if p.quarter == 1 else f"Q{p.quarter}" for p in bins]
    fig, axes = plt.subplots(1, 2, figsize=(16 if monthly else 14, 6.0), sharey=True)
    figure_header(fig, "AI-flagged share of ransomware negotiation messages, 2025 to 2026",
                  f"Messages Pangram {version} labels AI or Mixed, by {'month' if monthly else 'quarter'}. One 2021 victim message, a false positive, is excluded.")
    for ax, sample, color, title in zip(axes, ["A_primary", "victim"], [RED, BLUE], ["Attacker messages", "Victim messages"]):
        ok = panels[sample]
        ok = ok[(ok["date"] >= "2025-01-01") & ~ok["unit_id"].isin(FIGURE_EXCLUDED)]
        g = ok.groupby(ok["date"].dt.to_period(freq)).agg(n=("flag", "size"), k=("flag", "sum"), chats=("conversation_id", "nunique")).reindex(bins)
        for i, (n, k, chats) in enumerate(zip(g["n"], g["k"], g["chats"])):
            if np.isnan(n):
                bar(ax, i, 0, color, False, "no\nmsgs", FS_NOTE - 3)
            else:
                note = f"{int(k)}/{int(n)}" if monthly else f"{int(k)}/{int(n)}\n{int(chats)} chats"
                bar(ax, i, k / n, color, False, note, FS_NOTE - 3 if monthly else FS_NOTE, width=0.72)
        style_bar_panel(ax, title, color, labels, FS_TICK - 3 if monthly else FS_TICK)
    axes[0].set_ylim(0, 1.0 if monthly else 0.5)
    axes[0].set_ylabel("Share of messages flagged", fontsize=FS_AXIS)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.78, bottom=0.19, wspace=0.08)
    fig.savefig(FIGS / fname, dpi=180, facecolor="white")
    plt.close(fig)


def flagged_listing(ok: pd.DataFrame, proc: pathlib.Path, texts: pd.Series, model: str) -> str:
    out = []
    for _, r in ok[ok["flag"] == 1].sort_values(["year", "group_name"]).iterrows():
        rec = json.loads((proc / "pangram_cache" / f"{r['text_sha256']}.{model}.json").read_text(encoding="utf-8"))["response"]
        out.append(f"## {r['group_name']}, {int(r['year'])}, {int(r['word_count'])} words, {r['sample']} ({r['unit_id']})\n\n"
                   f"Label **{r['prediction_short']}**, fraction_ai {r['fraction_ai']:.2f}, fraction_ai_assisted {r['fraction_ai_assisted']:.2f}. "
                   f"Headline: {rec['headline']}\n")
        for w in rec["windows"]:
            out.append(f"> **[{w['label']}, {w['confidence']} confidence, score {w['ai_assistance_score']:.2f}]** {w['text'].strip()}\n")
        out.append("")
    return "\n".join(out)


def main() -> None:
    proc = pathlib.Path(sys.argv[1])
    res = pd.read_csv(proc / "pangram_results.csv")
    versions = res.loc[res["pangram_status"] == "ok", "version"].astype(str).unique()
    if len(versions) != 1:
        sys.exit(f"Results come from more than one Pangram version {versions}; re-run or stratify before pooling")
    model = res.loc[res["pangram_status"] == "ok", "model_requested"].iloc[0]
    print("status:", res.groupby("sample")["pangram_status"].value_counts().to_dict())
    conv = pd.read_csv(proc / "conversations_eligibility.csv").set_index("conversation_id")
    messages = pd.read_csv(proc / "messages.csv", keep_default_na=False).set_index("message_id")
    texts = messages["text_for_analysis"]

    samples = [s for s in ["A_primary", "victim"] if (res["sample"] == s).any()]
    by_year, by_period, listing = [], [], []
    panels = {}
    for sample in samples:
        ok = prepare(res[res["sample"] == sample], conv, messages["parsed_timestamp"])
        cuts = cuts_for(ok) if sample == "A_primary" else {"all": ok}
        by_year += [summarise(d, "year_label", sample, c) for c, d in cuts.items()]
        by_period += [summarise(d, "period", sample, c) for c, d in cuts.items()]
        panels[sample] = ok
        listing.append(f"# Flagged messages: {sample}\n\n" + flagged_listing(ok, proc, texts, model))
        print(f"\n=== {sample}: Pangram version {versions[0]}, {len(ok)} messages scored ===")
        print(by_period[-len(cuts)][["period", "conversations", "groups", "messages_scored", "n_human", "n_mixed", "n_ai", "flag_share", "ci_low", "ci_high"]].to_string(index=False))
        if sample == "A_primary":
            print("\nby gang:")
            print(ok.groupby(["period", "group_name"]).agg(conversations=("conversation_id", "nunique"), messages=("flag", "size"), flagged=("flag", "sum")).to_string())
    by_year = pd.concat(by_year, ignore_index=True)
    by_period = pd.concat(by_period, ignore_index=True)
    by_year.to_csv(proc / "pangram_trends_by_year.csv", index=False)
    by_period.to_csv(proc / "pangram_trends_by_period.csv", index=False)
    (proc / "pangram_flagged_messages.md").write_text("\n".join(listing), encoding="utf-8")

    order = ["2020", "2021", "2022", "2023", "2024", "2025", "2026 to Oct 19"]
    fig, axes = plt.subplots(1, len(samples), figsize=(6.6 * len(samples) + 0.8, 6.0), sharey=True, squeeze=False)
    figure_header(fig, "AI-flagged share of ransomware negotiation messages",
                  f"Messages Pangram {versions[0]} labels AI or Mixed, by year. One 2021 victim message, a false positive, is excluded.")
    top = 0.3
    for ax, sample, color, title in zip(axes[0], samples, [RED, BLUE], ["Attacker messages", "Victim messages"]):
        shown = panels[sample][~panels[sample]["unit_id"].isin(FIGURE_EXCLUDED)]
        y = summarise(shown, "year_label", sample, "figure").set_index("period").reindex(order).fillna({"flag_share": np.nan})
        present = [p for p in order if not np.isnan(y.loc[p, "flag_share"])]
        draw_panel(ax, y, present, title, color)
        top = max(top, float(np.nanmax(y["flag_share"])) * 1.25)
    axes[0][0].set_ylim(0, top)
    axes[0][-1].text(0.98, 0.97, "2026 is partial:\nthrough Oct 19", transform=axes[0][-1].transAxes, fontsize=FS_NOTE,
                     color="#555555", ha="right", va="top")
    axes[0][0].set_ylabel("Share of messages flagged", fontsize=FS_AXIS)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.78, bottom=0.19, wspace=0.08)
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / "pangram_flags_over_time.png", dpi=180, facecolor="white")
    plt.close(fig)
    if "victim" in panels:
        draw_recent(panels, versions[0], "Q", "pangram_flags_2025_2026_quarterly.png")
        draw_recent(panels, versions[0], "M", "pangram_flags_2025_2026_monthly.png")

if __name__ == "__main__":
    main()
