"""Classify eligible attacker text with Pangram, with a local cache. NOT run by the pipeline.

Input:  <proc_dir>/messages.csv, messages_eligibility.csv, conversations_eligibility.csv (from audit_corpus.py)
Output: <proc_dir>/pangram_cache/<text_sha256>.<model>.json   one raw API response per submitted text
        <proc_dir>/pangram_results.csv                        one row per (sample, unit_id), joined to the cache

Samples (`--sample`):
  A_primary     attacker messages with pangram_eligible = True (one row per message)
  A_templates   attacker messages with pangram_eligible_with_templates = True; a template text is
                submitted once and its result joined to every member (`n_members` says how many)
  B_concat      one concatenated attacker text per conversation with concat_eligible = True,
                built from `concat_message_ids` in message order, messages separated by a blank line
  victim        victim messages with 50+ words of English prose (not verified human; a comparator only)

Cost control. `--estimate` prints the number of texts, words and billing units (one unit per
started 1,000 words per text, Pangram's bulk rule) and exits without contacting the API.
`--limit N` submits at most N uncached texts (use --limit 3 for a smoke test); `--year 2026`
restricts to conversations of that year and `--seed` shuffles the order so a limited run spreads
across gangs. The results file always covers the whole sample, with `not_submitted` rows. Each text is
cached by (text sha256, model), so re-runs never pay twice. Failures are written to the cache
with `stage` = STAGE_FAILED and listed in the results with `pangram_status` = failed; they are
never replaced by invented scores.

The key is read from PANGRAM_API_KEY in the environment or the project's .env file (ignored
by Git) and is never printed. public_dashboard_link is left False, so no negotiation text is
published to a dashboard. The model is pinned with --model (default pangram-4); the
`version` the API returns is stored with every result, and analyze.py refuses to pool results
whose version differs. On 2026-10-19 the key listed models default, pangram-4 and pangram-4.1,
and model="pangram-4" returned version "4.1".

The flag `pangram_flagged_ai_or_assisted` is Pangram's own document label, `prediction_short`
in {"AI", "Mixed"} (Pangram 4 defines Human as >= 90% of characters human, AI as >= 80% AI,
Mixed otherwise). fraction_ai and fraction_ai_assisted are shares of text, not probabilities.

Usage:
  uv run python -I code/attacker_text/pangram_classify.py data/processed/attacker_text --estimate
  uv run python -I code/attacker_text/pangram_classify.py data/processed/attacker_text --sample A_primary --limit 3
  uv run python -I code/attacker_text/pangram_classify.py data/processed/attacker_text --sample A_primary --sample B_concat
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
PREPROCESSING_VERSION = "v1"
MIN_WORDS = 50
FLAGGED_LABELS = {"AI", "Mixed"}
HUMAN_LABELS = {"Human"}


def api_key() -> str:
    key = os.environ.get("PANGRAM_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("PANGRAM_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        sys.exit("No PANGRAM_API_KEY in the environment or in .env")
    return key


def build_units(proc: pathlib.Path, samples: list[str]) -> pd.DataFrame:
    msg = pd.read_csv(proc / "messages.csv", keep_default_na=False)
    elig = pd.read_csv(proc / "messages_eligibility.csv")
    conv = pd.read_csv(proc / "conversations_eligibility.csv")
    m = msg.merge(elig, on=["message_id", "conversation_id"], suffixes=("", "_e"))
    rows = []
    for sample in samples:
        if sample == "A_primary":
            sub = m[m["pangram_eligible"]]
        elif sample == "A_templates":
            sub = m[m["pangram_eligible_with_templates"]]
        elif sample == "victim":
            sub = m[(m["normalized_role"] == "victim") & (m["word_count"] >= MIN_WORDS) & m["language"].isin(["en", "und"]) & (m["prose_share"] >= 0.6) & m["year"].notna() & ~m["duplicate_file"]]
        elif sample == "B_concat":
            by_id = m.set_index("message_id")["text_for_analysis"]
            for _, c in conv[conv["concat_eligible"]].iterrows():
                ids = c["concat_message_ids"].split("|")
                text = "\n\n".join(by_id[i] for i in ids)
                rows.append({"sample": sample, "unit_id": c["conversation_id"], "conversation_id": c["conversation_id"], "group_name": c["group_name"],
                             "year": c["year"], "text": text, "word_count": len(text.split()), "component_message_ids": c["concat_message_ids"], "n_members": 1})
            continue
        else:
            sys.exit(f"unknown sample {sample}")
        for _, r in sub.iterrows():
            rows.append({"sample": sample, "unit_id": r["message_id"], "conversation_id": r["conversation_id"], "group_name": r["group_name"],
                         "year": r["year"], "text": r["text_for_analysis"], "word_count": r["word_count"], "component_message_ids": r["message_id"], "n_members": 1})
    units = pd.DataFrame(rows)
    units["text_sha256"] = units["text"].map(lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest())
    units["n_members"] = units.groupby(["sample", "text_sha256"])["unit_id"].transform("size")
    return units


def estimate(units: pd.DataFrame) -> None:
    uniq = units.drop_duplicates("text_sha256")
    print(f"{len(units)} units, {len(uniq)} unique texts, {int(uniq['word_count'].sum())} words, "
          f"{int(((uniq['word_count'] - 1) // 1000 + 1).sum())} billing units (1 per started 1,000 words per text)")
    print(units.groupby("sample").agg(units=("unit_id", "size"), unique_texts=("text_sha256", "nunique"), words=("word_count", "sum")).to_string())


def classify(units: pd.DataFrame, cache: pathlib.Path, model: str, limit: int | None, seed: int | None) -> None:
    from pangram import Pangram  # imported here so --estimate works without the SDK installed
    client = Pangram(api_key=api_key())
    cache.mkdir(parents=True, exist_ok=True)
    def done(sha):
        f = cache / f"{sha}.{model}.json"
        if not f.exists():
            return False
        rec = json.loads(f.read_text(encoding="utf-8"))
        return rec.get("error") is None and (rec.get("response") or {}).get("stage") == "STAGE_SUCCESS"
    todo = [r for _, r in units.drop_duplicates("text_sha256").iterrows() if not done(r["text_sha256"])]  # failures are retried
    if seed is not None:  # random order, so --limit gives a spread across gangs rather than the first files alphabetically
        todo = [todo[i] for i in __import__("numpy").random.default_rng(seed).permutation(len(todo))]
    if limit is not None:
        todo = todo[:limit]
    print(f"{len(todo)} uncached texts to submit with model={model}")
    for r in todo:
        record = {"text_sha256": r["text_sha256"], "model_requested": model, "preprocessing_version": PREPROCESSING_VERSION,
                  "submitted_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "word_count": int(r["word_count"]), "attempts": 0}
        for attempt in range(1, 4):
            record["attempts"] = attempt
            try:
                record["response"] = client.predict(r["text"], model=model)
                record["error"] = None
                break
            except Exception as exc:  # the SDK raises on HTTP and timeout errors; keep the message, then retry
                record["error"] = f"{type(exc).__name__}: {exc}"
                time.sleep(5 * attempt)
        (cache / f"{r['text_sha256']}.{model}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.5)


def collect(units: pd.DataFrame, cache: pathlib.Path, model: str, out: pathlib.Path) -> None:
    rows = []
    for _, r in units.iterrows():
        f = cache / f"{r['text_sha256']}.{model}.json"
        base = {k: r[k] for k in ["sample", "unit_id", "conversation_id", "group_name", "year", "word_count", "component_message_ids", "n_members", "text_sha256"]}
        if not f.exists():
            rows.append({**base, "pangram_status": "not_submitted"})
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        resp = rec.get("response") or {}
        ok = rec.get("error") is None and resp.get("stage") == "STAGE_SUCCESS"
        label = resp.get("prediction_short")
        rows.append({**base, "pangram_status": "ok" if ok else "failed", "submitted_at_utc": rec["submitted_at_utc"], "attempts": rec["attempts"],
                     "error": rec.get("error") or resp.get("headline") if not ok else None, "model_requested": rec["model_requested"],
                     "version": resp.get("version"), "headline": resp.get("headline"), "prediction": resp.get("prediction"), "prediction_short": label,
                     "fraction_ai": resp.get("fraction_ai"), "fraction_ai_assisted": resp.get("fraction_ai_assisted"), "fraction_human": resp.get("fraction_human"),
                     "num_ai_segments": resp.get("num_ai_segments"), "num_ai_assisted_segments": resp.get("num_ai_assisted_segments"),
                     "num_human_segments": resp.get("num_human_segments"), "document_confidence": resp.get("document_confidence"),
                     "n_windows": len(resp.get("windows") or []),
                     "pangram_flagged_ai_or_assisted": (label in FLAGGED_LABELS) if ok else None})
    res = pd.DataFrame(rows)
    res.to_csv(out, index=False)
    print(res["pangram_status"].value_counts().to_dict())
    if "version" in res:
        print("versions:", res["version"].dropna().value_counts().to_dict())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("proc_dir")
    ap.add_argument("--sample", action="append", choices=["A_primary", "A_templates", "B_concat", "victim"])
    ap.add_argument("--model", default="pangram-4")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--year", type=int, action="append", help="only units from these conversation years")
    ap.add_argument("--seed", type=int, help="shuffle the submission order with this seed before --limit")
    args = ap.parse_args()
    proc = pathlib.Path(args.proc_dir)
    samples = args.sample or ["A_primary", "A_templates", "B_concat", "victim"]
    units = build_units(proc, samples)
    if args.year:
        units = units[units["year"].isin(args.year)]
    if args.estimate:
        estimate(units)
        return
    cache = proc / "pangram_cache"
    classify(units, cache, args.model, args.limit, args.seed)
    collect(units, cache, args.model, proc / "pangram_results.csv")


if __name__ == "__main__":
    main()
