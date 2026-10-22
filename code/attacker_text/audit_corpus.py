"""Audit the Ransomchats message table before any detector is run.

Input:  <proc_dir>/conversations.csv, <proc_dir>/messages.csv (from parse_ransomchats.py)
Output: <proc_dir>/messages_eligibility.csv   per message: language, length, duplicate, template, eligibility
        <proc_dir>/conversations_eligibility.csv  per conversation: duplicate-file flag, eligible attacker text
        <proc_dir>/template_clusters.csv        near-duplicate clusters with one example each
        <proc_dir>/coverage_by_year.csv         the denominators, by year and half-year
        <proc_dir>/coverage_by_group_year.csv   the same by gang and year
        <proc_dir>/pangram_budget.csv           what a Pangram run would submit
        <proc_dir>/qa_sample.csv                records drawn for manual inspection

Eligibility is decided in this order, and `eligibility_reason` names the first
rule that fails, so the counts in coverage_by_year.csv nest:
  1 role_not_attacker   normalized_role != attacker
  2 role_uncertain      attacker but role_confidence != high
  3 date_unknown        conversation has no defensible year
  4 duplicate_file      the whole file repeats another file in the snapshot (kept: the earlier path)
  5 empty               no text after clean-up
  6 no_prose            under 60% of tokens are alphabetic words, or no sentence-like run
                        (URLs, wallet addresses, file listings, "ok", "?")
  7 non_english         langdetect says another language (texts >= 20 words only; shorter ones
                        get language "und" and are not excluded on language)
  8 too_short           fewer than 50 whitespace-delimited words (Pangram's minimum)
  9 template            member of a near-duplicate cluster that spans 2+ conversations
                        (TF-IDF over character 3-5-grams, cosine >= 0.80, connected components);
                        identical texts reused across chats land here too, since their cosine is 1
 10 exact_duplicate     same normalised text as an earlier message in the same conversation
                        (a re-sent message; cross-conversation repeats are already rule 9)
Messages passing all ten are `pangram_eligible` (primary sample). `pangram_eligible_with_templates`
relaxes rule 9 for the sensitivity analysis; a template text is submitted once and its result
joined to every member. Word bands (50-99, 100-249, 250+) are reported.

Conversation-level text (secondary unit): attacker messages that pass rules 1-7, 9 and 10,
of any length, concatenated in message order with blank lines; usable if >= 50 words.

Languages: langdetect with a fixed seed, so runs are reproducible. It is weak on short
and templated text; the language column is a flag, not a verdict.

Run: python -I code/attacker_text/audit_corpus.py data/processed/attacker_text
"""
import hashlib
import pathlib
import re
import sys

import numpy as np
import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer

DetectorFactory.seed = 0
MIN_WORDS = 50
MIN_WORDS_FOR_LANG = 20
PROSE_SHARE = 0.60
SIM_THRESHOLD = 0.80
NEAR_DUP_MIN_WORDS = 15
YEARS = list(range(2020, 2027))
BANDS = [(50, 99), (100, 249), (250, 10**9)]
WORD = re.compile(r"^[^\W\d_]+[^\W\d_'’-]*$", re.UNICODE)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def prose_share(text: str) -> float:
    toks = text.split()
    return sum(bool(WORD.match(t.strip(".,;:!?\"'()[]"))) for t in toks) / len(toks) if toks else 0.0


def language(text: str, words: int) -> tuple[str, float]:
    if words < MIN_WORDS_FOR_LANG:
        return "und", np.nan
    try:
        best = detect_langs(text)[0]
    except LangDetectException:
        return "und", np.nan
    return best.lang, round(best.prob, 3)


def near_duplicate_clusters(texts: pd.Series) -> pd.Series:
    """Cluster id per index for texts whose cosine similarity on char 3-5-grams >= SIM_THRESHOLD."""
    if len(texts) < 2:
        return pd.Series([None] * len(texts), index=texts.index, dtype="object")
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
    x = vec.fit_transform(texts.map(normalise))
    sim = (x @ x.T).tocoo()
    keep = (sim.data >= SIM_THRESHOLD) & (sim.row != sim.col)
    adj = sim.copy()
    adj.data, adj.row, adj.col = sim.data[keep], sim.row[keep], sim.col[keep]
    n, labels = connected_components(adj.tocsr(), directed=False)
    sizes = np.bincount(labels)
    out = pd.Series([f"t{lab:04d}" if sizes[lab] > 1 else None for lab in labels], index=texts.index, dtype="object")
    return out


def main() -> None:
    proc = pathlib.Path(sys.argv[1])
    conv = pd.read_csv(proc / "conversations.csv", dtype={"half_year": "string"})
    msg = pd.read_csv(proc / "messages.csv", keep_default_na=False, dtype={"text_raw": str, "text_for_analysis": str})
    msg = msg.merge(conv[["conversation_id", "group_name", "source_path", "year", "half_year", "date_confidence", "conversation_date"]], on="conversation_id")
    msg = msg.sort_values(["conversation_date", "source_path", "message_index"], na_position="last").reset_index(drop=True)

    # duplicate files: identical sequence of normalised messages, keep the earliest path
    sig = msg.groupby("conversation_id")["text_for_analysis"].apply(lambda s: hashlib.sha256("\n".join(s.map(normalise)).encode()).hexdigest())
    conv["file_signature"] = conv["conversation_id"].map(sig)
    conv = conv.sort_values("source_path")
    conv["duplicate_of"] = conv.groupby("file_signature")["source_path"].transform("first").where(conv.duplicated("file_signature"), None)
    msg["duplicate_file"] = msg["conversation_id"].map(conv.set_index("conversation_id")["duplicate_of"]).notna()

    text = msg["text_for_analysis"]
    msg["word_count"] = text.str.split().str.len().fillna(0).astype(int)
    msg["character_count"] = text.str.len()
    msg["prose_share"] = text.map(prose_share).round(3)
    msg["has_sentence"] = text.str.contains(r"[^\W\d_]+(?:\s+[^\W\d_'’-]+){2,}", regex=True)
    langs = [language(t, w) for t, w in zip(text, msg["word_count"])]
    msg["language"] = [lang for lang, _ in langs]
    msg["language_confidence"] = [p for _, p in langs]
    msg["word_band"] = pd.cut(msg["word_count"], [0, MIN_WORDS - 1, 99, 249, 10**9], labels=["<50", "50-99", "100-249", "250+"], include_lowest=True).astype(str)
    msg["text_sha256"] = text.map(lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest())
    msg["normalised_sha256"] = text.map(lambda t: hashlib.sha256(normalise(t).encode("utf-8")).hexdigest())

    # near-duplicate / template clusters, over every attacker message of some length, independent of eligibility
    cand = msg[(msg["normalized_role"] == "attacker") & (msg["word_count"] >= NEAR_DUP_MIN_WORDS) & ~msg["duplicate_file"]]
    msg["template_cluster_id"] = None
    msg.loc[cand.index, "template_cluster_id"] = near_duplicate_clusters(cand["text_for_analysis"])
    span = msg.groupby("template_cluster_id")["conversation_id"].nunique()
    msg["template_cluster_conversations"] = msg["template_cluster_id"].map(span)
    msg["is_probable_boilerplate"] = msg["template_cluster_conversations"].fillna(0).ge(2)

    # eligibility in declared order
    reason = pd.Series("", index=msg.index, dtype="object")
    def fail(mask, label):
        reason[(reason == "") & mask] = label
    fail(msg["normalized_role"] != "attacker", "role_not_attacker")
    fail(msg["role_confidence"] != "high", "role_uncertain")
    fail(msg["year"].isna(), "date_unknown")
    fail(msg["duplicate_file"], "duplicate_file")
    fail(msg["word_count"] == 0, "empty")
    fail((msg["prose_share"] < PROSE_SHARE) | ~msg["has_sentence"], "no_prose")
    fail(~msg["language"].isin(["en", "und"]), "non_english")
    fail(msg["word_count"] < MIN_WORDS, "too_short")
    before_template = reason == ""
    fail(msg["is_probable_boilerplate"], "template")
    msg["is_exact_duplicate"] = msg.duplicated(["conversation_id", "normalised_sha256"]) & (msg["word_count"] > 0)
    fail(msg["is_exact_duplicate"], "exact_duplicate")
    msg["eligibility_reason"] = reason.replace("", "eligible")
    msg["pangram_eligible"] = reason == ""
    msg["pangram_eligible_with_templates"] = before_template & ~msg["is_exact_duplicate"]
    # short attacker prose that would be usable inside the conversation-level concatenation
    msg["usable_for_concat"] = (~reason.isin(["role_not_attacker", "role_uncertain", "date_unknown", "duplicate_file", "empty", "no_prose", "non_english"])) & ~msg["is_probable_boilerplate"]
    dup_short = msg[msg["usable_for_concat"]].duplicated("normalised_sha256")
    msg.loc[dup_short[dup_short].index, "usable_for_concat"] = False

    # conversation-level
    cat = msg[msg["usable_for_concat"]].sort_values(["conversation_id", "message_index"])
    cw = cat.groupby("conversation_id").agg(concat_words=("word_count", "sum"), concat_messages=("message_id", "size"),
                                            concat_message_ids=("message_id", lambda s: "|".join(s)))
    conv = conv.merge(cw, on="conversation_id", how="left")
    conv["concat_words"] = conv["concat_words"].fillna(0).astype(int)
    conv["concat_messages"] = conv["concat_messages"].fillna(0).astype(int)
    conv["concat_eligible"] = (conv["concat_words"] >= MIN_WORDS) & conv["duplicate_of"].isna() & conv["year"].notna()
    elig_per_conv = msg[msg["pangram_eligible"]].groupby("conversation_id").size()
    conv["eligible_messages"] = conv["conversation_id"].map(elig_per_conv).fillna(0).astype(int)
    conv["attacker_prose_messages"] = conv["conversation_id"].map(msg[msg["usable_for_concat"]].groupby("conversation_id").size()).fillna(0).astype(int)

    # coverage tables
    att = msg["normalized_role"] == "attacker"
    def coverage(frame_conv, frame_msg, key):
        g = frame_conv.groupby(key, dropna=False)
        m = frame_msg.groupby(key, dropna=False)
        a = frame_msg[frame_msg["normalized_role"] == "attacker"].groupby(key, dropna=False)
        out = pd.DataFrame({
            "source_conversations": g.size(),
            "parsed_conversations": g["parse_status"].apply(lambda s: (s == "ok").sum()),
            "dated_conversations_high": g["date_confidence"].apply(lambda s: (s == "high").sum()),
            "dated_conversations_medium": g["date_confidence"].apply(lambda s: (s == "medium").sum()),
            "duplicate_files": g["duplicate_of"].apply(lambda s: s.notna().sum()),
            "groups": g["group_name"].nunique(),
            "messages": m.size(),
            "attacker_messages": a.size(),
            "attacker_messages_role_high": a["role_confidence"].apply(lambda s: (s == "high").sum()),
            "attacker_prose_messages": a["eligibility_reason"].apply(lambda s: (~s.isin(["role_not_attacker", "role_uncertain", "date_unknown", "duplicate_file", "empty", "no_prose"])).sum()),
            "attacker_prose_english": a["eligibility_reason"].apply(lambda s: (~s.isin(["role_not_attacker", "role_uncertain", "date_unknown", "duplicate_file", "empty", "no_prose", "non_english"])).sum()),
            "attacker_ge50_words": a["eligibility_reason"].apply(lambda s: s.isin(["exact_duplicate", "template", "eligible"]).sum()),
            "attacker_ge50_not_template": a["eligibility_reason"].apply(lambda s: s.isin(["exact_duplicate", "eligible"]).sum()),
            "eligible_messages": a["pangram_eligible"].sum(),
            "eligible_messages_50_99": a.apply(lambda d: (d["pangram_eligible"] & (d["word_band"] == "50-99")).sum()),
            "eligible_messages_100_249": a.apply(lambda d: (d["pangram_eligible"] & (d["word_band"] == "100-249")).sum()),
            "eligible_messages_250plus": a.apply(lambda d: (d["pangram_eligible"] & (d["word_band"] == "250+")).sum()),
            "eligible_words": a.apply(lambda d: d.loc[d["pangram_eligible"], "word_count"].sum()),
            "conversations_with_eligible_message": g["eligible_messages"].apply(lambda s: (s > 0).sum()),
            "groups_with_eligible_message": frame_conv[frame_conv["eligible_messages"] > 0].groupby(key, dropna=False)["group_name"].nunique(),
            "concat_eligible_conversations": g["concat_eligible"].sum(),
            "concat_words": g["concat_words"].sum(),
        }).fillna(0).astype(int)
        for r in ["role_uncertain", "date_unknown", "duplicate_file", "empty", "no_prose", "non_english", "too_short", "template", "exact_duplicate"]:
            out[f"excluded_{r}"] = a["eligibility_reason"].apply(lambda s, r=r: (s == r).sum()).reindex(out.index).fillna(0).astype(int)
        return out.reset_index()

    conv["year_label"] = conv["year"].map(lambda y: "unknown" if pd.isna(y) else ("2026 to Oct 19" if y == 2026 else str(int(y))))
    msg["year_label"] = msg["conversation_id"].map(conv.set_index("conversation_id")["year_label"])
    by_year = coverage(conv, msg, "year_label")
    by_year.insert(0, "period_type", "year")
    conv_h = conv[conv["half_year"].notna()]
    msg_h = msg[msg["half_year"].notna() & (msg["half_year"] != "")]
    by_half = coverage(conv_h, msg_h, "half_year")
    by_half.insert(0, "period_type", "half_year")
    by_half = by_half.rename(columns={"half_year": "year_label"})
    cov = pd.concat([by_year, by_half], ignore_index=True).rename(columns={"year_label": "period"})
    cov.to_csv(proc / "coverage_by_year.csv", index=False)
    coverage(conv, msg, ["group_name", "year_label"]).rename(columns={"year_label": "period"}).to_csv(proc / "coverage_by_group_year.csv", index=False)

    # template clusters
    tc = msg[msg["template_cluster_id"].notna()].groupby("template_cluster_id").agg(
        members=("message_id", "size"), conversations=("conversation_id", "nunique"), groups=("group_name", lambda s: "|".join(sorted(set(s)))),
        years=("year", lambda s: "|".join(sorted({str(int(y)) for y in s if pd.notna(y)}))), median_words=("word_count", "median"),
        example=("text_for_analysis", lambda s: s.iloc[0][:300])).sort_values("members", ascending=False).reset_index()
    tc.to_csv(proc / "template_clusters.csv", index=False)

    # budget: one Pangram billing unit per started 1,000 words per item
    # one Pangram billing unit per started 1,000 words per submitted item; identical texts are submitted once
    def row(sample, frame, words_col="word_count"):
        uniq = frame.drop_duplicates("text_sha256") if "text_sha256" in frame else frame
        words = uniq[words_col]
        return {"sample": sample, "messages": len(frame), "unique_texts": len(uniq), "words": int(words.sum()),
                "billing_units": int(np.ceil(np.maximum(words, 1) / 1000).sum())}
    el = msg[msg["pangram_eligible"]]
    el_t = msg[msg["pangram_eligible_with_templates"]]
    vic = msg[(msg["normalized_role"] == "victim") & (msg["word_count"] >= MIN_WORDS) & (msg["language"].isin(["en", "und"])) & (msg["prose_share"] >= PROSE_SHARE) & msg["year"].notna() & ~msg["duplicate_file"]]
    budget = pd.DataFrame([
        row("A_primary_attacker_messages", el),
        row("A_sensitivity_with_templates", el_t),
        row("B_conversation_concat", conv[conv["concat_eligible"]], "concat_words"),
        row("control_victim_messages_ge50", vic),
    ])
    budget.to_csv(proc / "pangram_budget.csv", index=False)

    # QA sample: oversample 2026, long, uncertain roles/dates, template members
    rng = np.random.default_rng(20261019)
    pools = {
        "2026": msg[(msg["year"] == 2026) & att], "long": msg[att & (msg["word_count"] >= 250)],
        "role_uncertain": msg[(msg["role_confidence"] != "high") | (msg["normalized_role"] == "third_party")],
        "date_unknown": msg[att & msg["year"].isna()], "template": msg[msg["is_probable_boilerplate"]],
        "borderline_prose": msg[att & (msg["prose_share"].between(0.5, 0.7))], "eligible_random": el,
        "victim": msg[msg["normalized_role"] == "victim"],
    }
    picks = []
    for name, pool in pools.items():
        k = min(5 if name != "eligible_random" else 8, len(pool))
        if k:
            picks.append(pool.sample(k, random_state=int(rng.integers(1 << 30))).assign(qa_pool=name))
    qa = pd.concat(picks).drop_duplicates("message_id")
    qa[["qa_pool", "message_id", "group_name", "source_path", "message_index", "year", "date_confidence", "raw_role", "normalized_role",
        "role_confidence", "raw_timestamp", "word_count", "language", "prose_share", "template_cluster_id", "eligibility_reason", "text_for_analysis"]] \
        .assign(reviewer_verdict="", reviewer_note="").to_csv(proc / "qa_sample.csv", index=False)

    cols = ["message_id", "conversation_id", "group_name", "year", "half_year", "date_confidence", "normalized_role", "role_confidence",
            "word_count", "character_count", "word_band", "prose_share", "has_sentence", "language", "language_confidence",
            "text_sha256", "normalised_sha256", "duplicate_file", "is_exact_duplicate", "template_cluster_id",
            "template_cluster_conversations", "is_probable_boilerplate", "eligibility_reason", "pangram_eligible",
            "pangram_eligible_with_templates", "usable_for_concat"]
    msg[cols].to_csv(proc / "messages_eligibility.csv", index=False)
    conv.drop(columns=["year_label"]).to_csv(proc / "conversations_eligibility.csv", index=False)
    print(by_year.set_index("year_label")[["source_conversations", "attacker_messages", "attacker_ge50_words", "eligible_messages", "conversations_with_eligible_message", "concat_eligible_conversations"]].to_string())
    print("\nexclusions among attacker messages:", msg.loc[att, "eligibility_reason"].value_counts().to_dict())
    print("\nbudget:\n", budget.to_string(index=False))


if __name__ == "__main__":
    main()
