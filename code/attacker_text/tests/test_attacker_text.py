"""Tests for the Ransomchats parse and audit scripts.

Run: uv run pytest code/attacker_text/tests
The audit tests build a small synthetic corpus in a temporary folder and run both
scripts on it, so they cover the real accounting end to end without the real data.
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys

import pandas as pd
import pytest

HERE = pathlib.Path(__file__).resolve().parent
CODE = HERE.parent
sys.path.insert(0, str(CODE))
import parse_ransomchats as pr  # noqa: E402

LONG = " ".join(f"word{i}" for i in range(60))  # 60 distinct tokens, alphabetic prose


VOCAB = ("the company must decide quickly because our deadline is firm and the data will be published "
         "unless payment arrives soon we offer decryption proof deletion logs and a security report after "
         "settlement your management should weigh reputation legal exposure clients partners employees and "
         "insurance before replying with a serious figure that reflects revenue we already reviewed").split()


def words(n, seed=0):
    """n distinct-looking English words in sentences; different seeds give unrelated texts."""
    import random
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        sent = [rng.choice(VOCAB) for _ in range(rng.randint(8, 14))]
        sent[0] = sent[0].capitalize()
        out.extend(sent[:-1] + [sent[-1] + "."])
    return " ".join(out[:n])


PROSE_49 = words(49, 9)
PROSE_50 = PROSE_49 + " Thanks."


# ---------- parse ----------

def test_role_map_covers_victim_attacker_and_system():
    assert pr.ROLE_MAP["victim"] == ("victim", "high")
    assert pr.ROLE_MAP["client"][0] == "victim"
    assert pr.ROLE_MAP["akira"] == ("attacker", "high")
    assert pr.ROLE_MAP["attacker"][0] == "attacker"
    assert pr.ROLE_MAP["bot"][0] == "third_party"
    assert pr.ROLE_MAP["support"] == ("attacker", "medium")


@pytest.mark.parametrize("raw, kind, expected", [
    ("2025-07-05T12:38:21.265342Z", "full", dt.datetime(2025, 7, 5, 12, 38, 21, 265342)),
    ("2021-04-28T14:55:32+03:00", "full", dt.datetime(2021, 4, 28, 11, 55, 32)),
    ("26.07.2022 16:05:41 UTC", "full", dt.datetime(2022, 7, 26, 16, 5, 41)),
    ("15:25 12.01.2021", "full", dt.datetime(2021, 1, 12, 15, 25)),
    ("10/17/2020, 2:50:24 PM", "full", dt.datetime(2020, 10, 17, 14, 50, 24)),
    ("17/05/2021, 19:05:39", "full", dt.datetime(2021, 5, 17, 19, 5, 39)),
    ("[27/04/2023 09:09]", "full", dt.datetime(2023, 4, 27, 9, 9)),
    ("6 December 2021 08:58 Read", "full", dt.datetime(2021, 12, 6, 8, 58)),
    ("Feb 19, 2026, 1:14 PM", "full", dt.datetime(2026, 2, 19, 13, 14)),
    ("106 days  ago", "relative", None),
    ("1 month ago", "relative", None),
    ("20:15", "no_year", None),
    ("15 Oct, 16:27", "no_year", None),
    ("29 Aug, 22:22 PM [NY time]", "no_year", None),
    ("Admin 11:10:55", "no_year", None),
    ("", "empty", None),
    ("yesterday-ish", "unparsed", None),
])
def test_parse_timestamp(raw, kind, expected):
    parsed, got_kind = pr.parse_timestamp(raw)
    assert got_kind == kind
    assert parsed == expected


def test_relative_days():
    assert pr.relative_days("106 days  ago") == 106
    assert pr.relative_days("2 months ago") == 60
    assert pr.relative_days("5 hours ago") == 0


def test_clean_text_strips_quote_prefix_and_keeps_unicode():
    raw = "> Hello.  You've   reached\n> us ✓ — déjà vu  ok"
    assert pr.clean_text(raw) == "Hello. You've reached\nus ✓ — déjà vu ok"
    assert pr.clean_text("plain") == "plain"
    assert pr.clean_text("Support:\u00a02. Here is the link") == "2. Here is the link"
    assert pr.clean_text("We support: nothing") == "We support: nothing"
    assert pr.clean_text("hi, I\\'m here\\n\\nWhich option?") == "hi, I'm here\n\nWhich option?"
    assert pr.clean_text("offer us.\n4 Attachments\n• Scanned by Gmail") == "offer us."
    assert pr.clean_text("offer us.\n• Scanned by Gmail") == "offer us."


def test_date_from_message_timestamp_beats_filename():
    stamps = [(dt.datetime(2021, 5, 3, 15), "full"), (None, "empty")]
    out = pr.date_conversation("20210305.json", stamps, ["5/3/2021, 3:35:07 PM", ""])
    assert out["conversation_date"] == dt.date(2021, 5, 3)
    assert out["date_source"] == "message_timestamp" and out["date_confidence"] == "high"
    assert out["half_year"] == "2021H1"


def test_filename_date_ambiguous_month_blanks_half_year():
    out = pr.date_conversation("20250112.json", [(None, "empty")], [""])
    assert out["conversation_date"] == dt.date(2025, 1, 12)
    assert out["date_confidence"] == "medium" and out["date_source"] == "filename"
    assert out["half_year"] is None  # 12 Jan or 1 Dec: different halves
    out2 = pr.date_conversation("20250425.json", [(None, "empty")], [""])
    assert out2["half_year"] == "2025H1"


def test_relative_timestamps_crossing_year_lower_confidence():
    out = pr.date_conversation("20210115.json", [(None, "relative")], ["30 days  ago"])
    assert out["date_confidence"] == "low" and out["max_relative_days"] == 30
    out2 = pr.date_conversation("20210415.json", [(None, "relative")], ["30 days  ago"])
    assert out2["date_confidence"] == "medium"


def test_unknown_date():
    out = pr.date_conversation("0001.json", [(None, "empty")], [""])
    assert out["conversation_date"] is None and out["date_confidence"] == "unknown"
    assert out["half_year"] is None


# ---------- end to end on a synthetic corpus ----------

def write_chat(repo, group, name, messages):
    p = repo / group / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"chat_id": "", "messages": messages}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("corpus")
    raw, proc = root / "raw", root / "proc"
    repo = raw / "ransomchats" / "repo"
    msg = lambda party, content, ts="": {"party": party, "content": content, "timestamp": ts}
    template = words(80, 8) + " this is the shared welcome template."
    files = [
        ("Akira", "20260106.json", [msg("Victim", "hello"), msg("Akira", "> " + template), msg("Akira", "> " + words(120, 1)), msg("Victim", "> " + words(70, 2)),
                                    msg("Akira", "> " + PROSE_49), msg("Akira", "> " + PROSE_50), msg("Akira", "https://example.onion/abc 0x" + "f" * 40)]),
        ("Akira", "20250425.json", [msg("Akira", template), msg("Akira", words(55, 3) + " unique sentence here."), msg("Akira", words(55, 3) + " unique sentence here.")]),
        ("Akira", "20250428.json", [msg("Akira", template), msg("Akira", words(55, 3) + " unique sentence here."), msg("Akira", words(55, 3) + " unique sentence here.")]),
        ("Conti", "20210305.json", [msg("Conti", words(60, 4), "5/3/2021, 3:35:07 PM"), msg("Conti", "Ciao, abbiamo cifrato tutti i vostri file e vogliamo " + "parlare di pagamento oggi stesso " * 12, "5/3/2021, 4:00:00 PM")]),
        ("Mallox", "20230427.json", [msg("Support", words(60, 5), "[27/04/2023 09:09]"), msg("BOT", words(60, 6), "[27/04/2023 09:10]")]),
        ("trinity", "0001.json", [msg("trinity", words(60, 7)), msg("victim", "ok")]),
    ]
    entries = []
    for group, name, messages in files:
        p = write_chat(repo, group, name, messages)
        entries.append({"path": f"{group}/{name}", "is_chat": True, "group_folder": group, "sha256": "x", "bytes": p.stat().st_size,
                        "json_parses": True, "first_added_to_repo": "2026-09-19T00:00:00Z", "source_url": "u", "raw_url": "r"})
    (raw / "ransomchats" / "manifest.json").write_text(json.dumps({"commit_sha": "deadbeef", "files": entries}), encoding="utf-8")
    py = sys.executable
    subprocess.run([py, "-I", str(CODE / "parse_ransomchats.py"), str(raw), str(proc)], check=True, capture_output=True)
    subprocess.run([py, "-I", str(CODE / "audit_corpus.py"), str(proc)], check=True, capture_output=True)
    return proc


def test_ids_are_stable_and_text_preserved(corpus):
    m = pd.read_csv(corpus / "messages.csv", keep_default_na=False)
    c = pd.read_csv(corpus / "conversations.csv")
    akira = c[c.source_path == "Akira/20260106.json"].conversation_id.iloc[0]
    assert akira == __import__("hashlib").sha256(b"ransomchats/Akira/20260106.json").hexdigest()[:16]
    first = m[(m.conversation_id == akira) & (m.message_index == 1)].iloc[0]
    assert first.text_raw.startswith("> ") and not first.text_for_analysis.startswith("> ")
    assert m.message_id.is_unique


def test_victim_text_never_in_attacker_sample(corpus):
    e = pd.read_csv(corpus / "messages_eligibility.csv")
    assert (e.loc[e.pangram_eligible, "normalized_role"] == "attacker").all()
    assert (e.loc[e.pangram_eligible_with_templates, "normalized_role"] == "attacker").all()
    assert (e.loc[e.usable_for_concat, "normalized_role"] == "attacker").all()
    assert e[e.normalized_role == "victim"].eligibility_reason.eq("role_not_attacker").all()


def test_word_boundary_and_exclusion_accounting(corpus):
    e = pd.read_csv(corpus / "messages_eligibility.csv").merge(pd.read_csv(corpus / "messages.csv", keep_default_na=False)[["message_id", "text_for_analysis"]])
    r49 = e[e.text_for_analysis == PROSE_49].iloc[0]
    r50 = e[e.text_for_analysis == PROSE_50].iloc[0]
    assert r49.word_count == 49 and r49.eligibility_reason == "too_short"
    assert r50.word_count == 50 and r50.pangram_eligible
    onion = e[e.text_for_analysis.str.startswith("https://example.onion")].iloc[0]
    assert onion.eligibility_reason == "no_prose"
    # every attacker message has exactly one reason, and the counts in coverage_by_year nest
    cov = pd.read_csv(corpus / "coverage_by_year.csv")
    y = cov[(cov.period_type == "year") & (cov.period == "2026 to Oct 19")].iloc[0]
    excl = sum(y[c] for c in cov.columns if c.startswith("excluded_"))
    assert y.attacker_messages == y.eligible_messages + excl
    assert y.attacker_ge50_words >= y.eligible_messages


def test_templates_and_duplicates(corpus):
    e = pd.read_csv(corpus / "messages_eligibility.csv")
    c = pd.read_csv(corpus / "conversations_eligibility.csv")
    # whole-file duplicate: the later path is marked, the earlier kept
    dup = c[c.duplicate_of.notna()]
    assert list(dup.source_path) == ["Akira/20250428.json"] and dup.duplicate_of.iloc[0] == "Akira/20250425.json"
    assert e[e.conversation_id.isin(dup.conversation_id)].eligibility_reason.eq("duplicate_file").all()
    # the welcome template appears in 2 kept conversations -> template in both, counted in the sensitivity sample
    t = e[e.template_cluster_id.notna() & e.is_probable_boilerplate]
    assert t.conversation_id.nunique() == 2 and t.eligibility_reason.eq("template").all()
    assert t.pangram_eligible_with_templates.all() and not t.pangram_eligible.any()
    # a message re-sent inside one conversation is an exact duplicate, not a template
    rep = e[(e.eligibility_reason == "exact_duplicate")]
    assert len(rep) == 1 and not rep.is_probable_boilerplate.iloc[0]


def test_roles_dates_and_language_exclusions(corpus):
    e = pd.read_csv(corpus / "messages_eligibility.csv")
    assert e[e.group_name == "Mallox"].set_index("normalized_role").eligibility_reason.to_dict() == {"attacker": "role_uncertain", "third_party": "role_not_attacker"}
    assert e[(e.group_name == "trinity") & (e.normalized_role == "attacker")].eligibility_reason.eq("date_unknown").all()
    conti = e[e.group_name == "Conti"]
    assert conti.year.eq(2021).all() and conti.date_confidence.eq("high").all()
    assert set(conti.eligibility_reason) == {"eligible", "non_english"}
    assert conti[conti.eligibility_reason == "non_english"].language.iloc[0] == "it"


def test_audit_is_deterministic(corpus):
    e1 = pd.read_csv(corpus / "messages_eligibility.csv")
    subprocess.run([sys.executable, "-I", str(CODE / "audit_corpus.py"), str(corpus)], check=True, capture_output=True)
    e2 = pd.read_csv(corpus / "messages_eligibility.csv")
    pd.testing.assert_frame_equal(e1, e2)


def test_concat_unit_and_budget(corpus):
    c = pd.read_csv(corpus / "conversations_eligibility.csv")
    a = c[c.source_path == "Akira/20260106.json"].iloc[0]
    assert a.concat_eligible and a.concat_words >= 50
    ids = a.concat_message_ids.split("|")
    e = pd.read_csv(corpus / "messages_eligibility.csv").set_index("message_id")
    assert all(e.loc[i, "normalized_role"] == "attacker" and not e.loc[i, "is_probable_boilerplate"] for i in ids)
    b = pd.read_csv(corpus / "pangram_budget.csv").set_index("sample")
    assert b.loc["A_primary_attacker_messages", "billing_units"] == b.loc["A_primary_attacker_messages", "unique_texts"]
    assert b.loc["A_sensitivity_with_templates", "unique_texts"] < b.loc["A_sensitivity_with_templates", "messages"]
