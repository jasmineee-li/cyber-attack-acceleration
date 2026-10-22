"""Detector-free typography markers in the Ransomchats messages: em dashes, non-breaking hyphens, narrow
no-break spaces and curly apostrophes, by period, role and gang, and their overlap with Pangram's labels.

Rationale: chat boxes type ASCII hyphens, straight quotes and ordinary spaces. U+2014 (em dash) is the
best-known house-style marker of GPT-family output; U+2011 (non-breaking hyphen) and U+202F (narrow
no-break space) have been reported as ChatGPT output artifacts in 2025; U+2019 (curly apostrophe) is
produced by any rendered web interface, including chatbots, and by phones. None proves authorship; a
before/after jump restricted to the 2025-26 attacker side is the signal, and absence in 2020-24 is the control.

Reads <proc_dir>/messages.csv, conversations.csv and pangram_results.csv (if present).
Writes <proc_dir>/typography_by_period.csv, typography_by_gang_2025_26.csv and typography_marked_messages.csv.

Usage: uv run python -I code/attacker_text/typography.py data/processed/attacker_text
"""
import pathlib
import sys
import unicodedata

import pandas as pd

MARKERS = {"em_dash": "—", "nb_hyphen": "‑", "narrow_nbsp": " ", "curly_apostrophe": "’"}
MIN_WORDS = 5  # ignore "ok", file names and the like


def main() -> None:
    proc = pathlib.Path(sys.argv[1])
    msg = pd.read_csv(proc / "messages.csv", dtype=str, keep_default_na=False)
    conv = pd.read_csv(proc / "conversations.csv", dtype=str, keep_default_na=False)
    df = msg.merge(conv[["conversation_id", "group_name", "year"]], on="conversation_id")
    df = df[(df["year"] != "") & df["normalized_role"].isin(["attacker", "victim"])].copy()
    df["year"] = df["year"].astype(float).astype(int)
    df["period"] = pd.cut(df["year"], [2019, 2022, 2024, 2026], labels=["2020-22", "2023-24", "2025-26"])
    df["words"] = df["text_raw"].str.split().str.len()
    df = df[df["words"] >= MIN_WORDS]
    for name, ch in MARKERS.items():
        df[name] = df["text_raw"].str.contains(ch, regex=False)
    df["any_gpt_marker"] = df[["em_dash", "nb_hyphen", "narrow_nbsp"]].any(axis=1)

    results = proc / "pangram_results.csv"
    if results.exists():
        r = pd.read_csv(results, dtype=str, keep_default_na=False)
        r = r[r["pangram_status"] == "ok"]
        label = dict(zip(r["unit_id"], r["prediction_short"]))
        df["pangram_label"] = df["message_id"].map(label).fillna("not scored")
    else:
        df["pangram_label"] = "not scored"

    def table(g: pd.core.groupby.DataFrameGroupBy) -> pd.DataFrame:
        t = g.agg(messages=("message_id", "size"), chats=("conversation_id", "nunique"),
                  em_dash=("em_dash", "sum"), nb_hyphen=("nb_hyphen", "sum"), narrow_nbsp=("narrow_nbsp", "sum"),
                  curly_apostrophe=("curly_apostrophe", "sum"), any_gpt_marker=("any_gpt_marker", "sum"))
        marked = df[df["any_gpt_marker"]].groupby(g.keys, observed=True)["conversation_id"].nunique()
        t["chats_with_gpt_marker"] = marked.reindex(t.index).fillna(0).astype(int)
        t["gpt_marker_share"] = (t["any_gpt_marker"] / t["messages"]).round(4)
        return t.reset_index()

    by_period = table(df.groupby(["normalized_role", "period"], observed=True))
    by_period.to_csv(proc / "typography_by_period.csv", index=False)
    recent = df[df["period"] == "2025-26"]
    by_gang = table(recent.groupby(["normalized_role", "group_name"], observed=True)).sort_values(["normalized_role", "any_gpt_marker"], ascending=[True, False])
    by_gang.to_csv(proc / "typography_by_gang_2025_26.csv", index=False)

    marked = df[df["any_gpt_marker"]].copy()
    marked["code_points"] = marked["text_raw"].map(
        lambda t: ";".join(sorted({f"U+{ord(c):04X} {unicodedata.name(c, '?')}" for c in t if ord(c) > 127})))
    cols = ["message_id", "conversation_id", "group_name", "year", "normalized_role", "words", "pangram_label", "code_points", "text_raw"]
    marked.sort_values(["year", "group_name", "message_id"])[cols].to_csv(proc / "typography_marked_messages.csv", index=False)

    print(by_period.to_string(index=False))
    print()
    print(by_gang[by_gang["any_gpt_marker"] > 0].to_string(index=False))
    print()
    print(marked.groupby(["normalized_role", "pangram_label"], observed=True).size().rename("marked messages by Pangram label").to_string())


if __name__ == "__main__":
    main()
