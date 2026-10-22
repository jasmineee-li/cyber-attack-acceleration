"""Normalise the Ransomchats snapshot into one conversation table and one message table.

Input:  <raw_dir>/ransomchats/manifest.json and repo/<Group>/<chat>.json (from fetch_ransomchats.py)
Output: <out_dir>/conversations.csv  one row per source file
        <out_dir>/messages.csv       one row per message, text kept exactly as stored

Every chat file has the same shape, {"chat_id", "messages": [{"party", "content",
"timestamp"}], optional "from"}, but the sender labels and timestamp formats differ
by gang, because each was converted from a different chat platform by a different
parser (see parsers/ upstream). This script makes those differences explicit.

Roles. `party` is mapped through ROLE_MAP, a hand-written table of every label in
the snapshot. Labels for the victim side are "Victim", "victim" and "Client". Most
attacker labels are the gang's own name; "Attacker", "threat_actor" and
"Anonymous" are the labels some contributed files use for the gang side; "Support",
"hiervos"/"Hervios" are the operator handles shown on Mallox's chat. "BOT" (Mallox's
automated price/discount notices) and "File:" (an attachment line) are mapped to
`third_party` and never count as attacker text. An unseen label stops the script
rather than being guessed.

Dates. A conversation's date is the earliest message timestamp that carries a
year (date_source = message_timestamp, confidence high). Many gangs' platforms
show no year ("20:15", "15 Oct, 16:27", "9 days ago") or no timestamp at all
(Akira, trinity); for those we fall back to a YYYYMMDD prefix in the file name
(date_source = filename, confidence medium). Checked against the 64 files that
have both, the file-name date equals the first message date in 57 and never
differs in year; the 5 Conti mismatches are day/month swaps. So the year from a
file name is trustworthy, the month is not when the day is 12 or less, and
`half_year` is filled only when both readings fall in the same half. Relative
timestamps ("106 days ago") mean the chat began that long before the capture, so
for those files we record the largest offset and lower confidence to `low` if it
reaches back across a year boundary. Files with neither (trinity, nova, Alp-001,
one Akira file) get date_confidence = unknown and stay out of the time series;
their `repo_added_at` is an upper bound only.

Text. `text_raw` is the stored string, untouched. `text_for_analysis` is the
minimal deterministic clean-up PREPROCESSING_VERSION describes: turn non-breaking
spaces into spaces, turn the literal "\\n", "\\t", "\\'" and '\\"' escapes that four
LockBit "Leaked2025" files carry into the characters they stand for, drop the
leading "Support:" sender label and the trailing Gmail "N Attachments / Scanned by
Gmail" footer on SilentRansomGroup's emails that Conti's parser
left inside 342 gang-side messages, strip the "> " quote prefix the Akira/Pear
parser left on every line, collapse runs of spaces and tabs to one space,
collapse 3+ newlines to 2, strip the ends. Nothing is translated, corrected or
expanded.

Run: python -I code/attacker_text/parse_ransomchats.py data/raw data/processed/attacker_text
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

import pandas as pd

PREPROCESSING_VERSION = "v1"
CUTOFF = dt.date(2026, 10, 19)

# raw party label (stripped, lower-cased) -> (normalized_role, role_confidence)
ROLE_MAP = {
    "victim": ("victim", "high"),
    "client": ("victim", "high"),           # Cloak's platform calls the victim "Client"
    "bot": ("third_party", "high"),         # Mallox automated notices
    "file:": ("third_party", "high"),       # attachment line parsed as a sender
    "attacker": ("attacker", "high"),
    "threat_actor": ("attacker", "high"),
    "anonymous": ("attacker", "medium"),    # Cloak's platform label for the gang side
    "support": ("attacker", "medium"),      # Mallox operator persona
    "hiervos": ("attacker", "medium"),      # Mallox operator handle (three spellings)
    "hervios": ("attacker", "medium"),
}
ATTACKER_LABELS = {
    "akira", "alp-001", "avaddon", "avos", "babuk", "black basta", "blackmatter", "conti",
    "darkside", "dragonforce", "hive", "hunters", "nightspire", "noescape", "pear", "qilin",
    "revil", "ransomhub", "ranzy", "rsw", "srg", "fog", "kairos", "lockbit 3.0", "lockbit3.0",
    "mountlocker", "nova", "orova", "settra", "trinity",
}
ROLE_MAP.update({k: ("attacker", "high") for k in ATTACKER_LABELS})

# strptime patterns that carry a year, in the order tried. Conti files use both
# "10/17/2020, 2:50:24 PM" (month first, 12-hour) and "17/05/2021, 19:05:39" (day first, 24-hour).
YEAR_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S UTC", "%d.%m.%Y %H:%M:%S", "%H:%M %d.%m.%Y", "%a, %d %b %Y %H:%M:%S GMT",
    "%m/%d/%Y, %I:%M:%S %p", "%d/%m/%Y, %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "[%d/%m/%Y %H:%M]", "%d %B %Y %H:%M",
    "%A, %d %B %Y %H:%M:%S", "%b %d, %Y, %I:%M %p",
]
RELATIVE = re.compile(r"^(\d+)\s+(minute|hour|day|month)s?\s+ago,?$")
NO_YEAR = re.compile(r"^(Admin \d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}(\s*[ap]m)?|\d{1,2} \w+,? \d{1,2}:\d{2}( [AP]M)?( \[NY time\])?|\w+day, \d{1,2}:\d{2})$")


def parse_timestamp(raw: str) -> tuple[dt.datetime | None, str]:
    """Return (naive UTC-ish datetime or None, kind) where kind is full / no_year / relative / empty / unparsed."""
    t = re.sub(r" Read$", "", raw.replace("\u202f", " ").strip())  # Hive appends a read receipt
    if not t:
        return None, "empty"
    for fmt in YEAR_FORMATS:
        try:
            parsed = dt.datetime.strptime(t, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(dt.UTC).replace(tzinfo=None)
        return parsed, "full"
    if RELATIVE.match(t):
        return None, "relative"
    if NO_YEAR.match(t):
        return None, "no_year"
    return None, "unparsed"


def relative_days(raw: str) -> int:
    m = RELATIVE.match(raw.strip())
    n, unit = int(m.group(1)), m.group(2)
    return {"minute": 0, "hour": 0, "day": n, "month": 30 * n}[unit]


def clean_text(raw: str) -> str:
    text = raw.replace("\u00a0", " ").replace("\u202f", " ")
    # four LockBit "Leaked2025" files were double-escaped on conversion: newlines, tabs and quotes are literal \n \t \' \"
    text = text.replace("\\n", "\n").replace("\\t", "\t").replace("\\'", "'").replace('\\"', '"')
    text = re.sub(r"^Support:\s*", "", text)  # Conti's chat UI label for the gang side, left in by its parser
    text = re.sub(r"(\n\s*\d+ Attachments?\s*)?(\n\s*•?\s*Scanned by Gmail\s*)?$", "", text)  # Gmail footer on SRG emails
    lines = [re.sub(r"^> ?", "", line) for line in text.split("\n")]
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def filename_date(name: str) -> dt.date | None:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", name)
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def half_year(d: dt.date) -> str:
    return f"{d.year}H{1 if d.month <= 6 else 2}"


def date_conversation(fname: str, stamps: list[tuple[dt.datetime | None, str]], raw_stamps: list[str]) -> dict:
    full = [p for p, kind in stamps if kind == "full"]
    kinds = {kind for _, kind in stamps}
    out = {"first_message_at": None, "last_message_at": None, "max_relative_days": None, "notes_on_metadata": []}
    if full:
        first, last = min(full), max(full)
        d = first.date()
        out.update(conversation_date=d, date_precision="day", date_source="message_timestamp",
                   date_confidence="high", first_message_at=first, last_message_at=last, half_year=half_year(d))
        if len(full) < len(stamps):
            out["notes_on_metadata"].append(f"{len(stamps) - len(full)} of {len(stamps)} messages lack a dated timestamp")
        return out
    fd = filename_date(fname)
    if fd is None:
        out.update(conversation_date=None, date_precision="unknown", date_source="none", date_confidence="unknown", half_year=None)
        out["notes_on_metadata"].append("no dated timestamp and no date in file name; timestamp kinds: " + ",".join(sorted(kinds)))
        return out
    out.update(conversation_date=fd, date_precision="day", date_source="filename", date_confidence="medium")
    swapped = dt.date(fd.year, fd.day, fd.month) if fd.day <= 12 else fd
    out["half_year"] = half_year(fd) if half_year(swapped) == half_year(fd) else None
    if fd.day <= 12:
        out["notes_on_metadata"].append("file-name month/day ambiguous (day<=12); year is safe either way")
    if "relative" in kinds:
        offset = max(relative_days(r) for r in raw_stamps if RELATIVE.match(r.strip()))
        out["max_relative_days"] = offset
        out["notes_on_metadata"].append(f"relative timestamps: chat began up to {offset} days before the file-name date")
        if (fd - dt.timedelta(days=offset)).year != fd.year:
            out["date_confidence"] = "low"
            out["half_year"] = None
    elif "no_year" in kinds:
        out["notes_on_metadata"].append("timestamps lack a year; file-name date used")
    elif kinds <= {"empty"}:
        out["notes_on_metadata"].append("no timestamps; file-name date used")
    return out


def main() -> None:
    raw_dir, out_dir = pathlib.Path(sys.argv[1]) / "ransomchats", pathlib.Path(sys.argv[2])
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    conv_rows, msg_rows = [], []
    for f in manifest["files"]:
        if not f["is_chat"]:
            continue
        path = f["path"]
        conv_id = hashlib.sha256(f"ransomchats/{path}".encode("utf-8")).hexdigest()[:16]
        data = json.loads((raw_dir / "repo" / path).read_text(encoding="utf-8"))
        msgs = data["messages"]
        stamps, raw_stamps, counts = [], [], {"attacker": 0, "victim": 0, "third_party": 0, "unknown": 0}
        for i, m in enumerate(msgs):
            raw_role = m["party"]
            key = raw_role.strip().lower()
            if key not in ROLE_MAP:
                sys.exit(f"Unmapped party label {raw_role!r} in {path}; add it to ROLE_MAP")
            role, role_conf = ROLE_MAP[key]
            counts[role] += 1
            raw_ts = m.get("timestamp", "")
            parsed, kind = parse_timestamp(raw_ts)
            stamps.append((parsed, kind))
            raw_stamps.append(raw_ts)
            text_raw = m["content"]
            msg_rows.append({
                "message_id": f"{conv_id}-{i:04d}", "conversation_id": conv_id, "message_index": i,
                "raw_role": raw_role, "normalized_role": role, "role_confidence": role_conf,
                "raw_timestamp": raw_ts, "timestamp_kind": kind, "parsed_timestamp": parsed,
                "text_raw": text_raw, "text_for_analysis": clean_text(text_raw),
                "has_attachment_field": "attachment" in m,
            })
        dated = date_conversation(pathlib.Path(path).name, stamps, raw_stamps)
        notes = dated.pop("notes_on_metadata")
        if data.get("from"):
            notes.append(f"contributed via {data['from']}")
        if data.get("chat_id") and data["chat_id"] != pathlib.Path(path).stem and "\n" not in data["chat_id"]:
            notes.append(f"chat_id field: {data['chat_id']}")
        cd = dated["conversation_date"]
        conv_rows.append({
            "conversation_id": conv_id, "source_repo": "Casualtek/Ransomchats", "source_path": path,
            "source_url": f["source_url"], "source_commit": manifest["commit_sha"], "source_sha256": f["sha256"],
            "repo_added_at": f["first_added_to_repo"], "group_name": f["group_folder"],
            **dated,
            "year": cd.year if cd else None,
            "after_cutoff": bool(cd and cd > CUTOFF),
            "total_messages": len(msgs), "attacker_messages": counts["attacker"], "victim_messages": counts["victim"],
            "third_party_messages": counts["third_party"], "unknown_role_messages": counts["unknown"],
            "timestamp_kinds": ",".join(sorted({k for _, k in stamps})),
            "notes_on_metadata": "; ".join(notes), "parse_status": "ok",
        })
    out_dir.mkdir(parents=True, exist_ok=True)
    conv = pd.DataFrame(conv_rows).sort_values(["group_name", "source_path"])
    msg = pd.DataFrame(msg_rows)
    conv.to_csv(out_dir / "conversations.csv", index=False)
    msg.to_csv(out_dir / "messages.csv", index=False)
    print(f"{len(conv)} conversations, {len(msg)} messages; date confidence: {conv['date_confidence'].value_counts().to_dict()}")
    print("messages by role:", msg["normalized_role"].value_counts().to_dict())
    print("timestamp kinds:", msg["timestamp_kind"].value_counts().to_dict())


if __name__ == "__main__":
    main()
