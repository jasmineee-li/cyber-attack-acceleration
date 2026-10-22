"""Download the Ransomchats corpus at a pinned Git commit, with a provenance manifest.

Ransomchats (https://github.com/Casualtek/Ransomchats, MIT licence) holds real
ransomware negotiations, anonymised by the maintainer, as one JSON file per chat
under a folder per gang. We clone the repository, check out the requested
commit, copy the chat files (plus README, LICENSE, chat_index.json) into
<out_dir>/repo/, and write <out_dir>/manifest.json with, for every file:
the path, its sha256, size, and the date of the commit that first added it
(an upper bound on when the chat happened, never the chat's own date).

Nothing is altered. The .git folder is not kept; the commit SHA in the
manifest pins the snapshot. The chats are public and anonymised, but keep the
repository private all the same, as the README asks for the other raw folders.

Usage: uv run python -I code/attacker_text/fetch_ransomchats.py data/raw/ransomchats <commit_sha>
Needs git on PATH and network access. Re-running with the same SHA rewrites the same files.
"""
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

UPSTREAM = "https://github.com/Casualtek/Ransomchats"
KEEP_TOP = {"README.md", "LICENSE", "chat_index.json"}


def git(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def first_added(repo: pathlib.Path) -> dict[str, str]:
    """Map each path to the author date of the oldest commit that added it."""
    log = git("log", "--diff-filter=A", "--name-only", "--format=COMMIT %aI", "--", "*.json", cwd=repo)
    added: dict[str, str] = {}
    date = None
    for line in log.splitlines():
        if line.startswith("COMMIT "):
            date = line.split(" ", 1)[1]
        elif line.strip():
            added[line.strip()] = date  # log is newest first, so the last write wins = oldest
    return added


def main() -> None:
    out_dir, sha = pathlib.Path(sys.argv[1]), sys.argv[2]
    if len(sha) != 40:
        sys.exit("Pass the full 40-character commit SHA")
    retrieved_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "Ransomchats"
        subprocess.run(["git", "clone", "--quiet", UPSTREAM, str(repo)], check=True)
        git("checkout", "--quiet", sha, cwd=repo)
        commit_date = git("log", "-1", "--format=%cI", cwd=repo).strip()
        added = first_added(repo)
        dest = out_dir / "repo"
        if dest.exists():
            shutil.rmtree(dest)
        files = []
        for src in sorted(repo.rglob("*")):
            rel = src.relative_to(repo)
            if not src.is_file() or ".git" in rel.parts:
                continue
            is_chat = src.suffix == ".json" and len(rel.parts) == 2 and rel.parts[0] != "parsers"
            if not (is_chat or str(rel) in KEEP_TOP):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            data = src.read_bytes()
            parse_ok = True
            if is_chat:
                try:
                    json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    parse_ok = False
            files.append({
                "path": str(rel),
                "is_chat": is_chat,
                "group_folder": rel.parts[0] if is_chat else None,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "json_parses": parse_ok,
                "first_added_to_repo": added.get(str(rel)),
                "source_url": f"{UPSTREAM}/blob/{sha}/{rel}",
                "raw_url": f"https://raw.githubusercontent.com/Casualtek/Ransomchats/{sha}/{rel}",
            })
    manifest = {
        "upstream": UPSTREAM,
        "commit_sha": sha,
        "commit_date": commit_date,
        "retrieved_at_utc": retrieved_at,
        "license": "MIT (LICENSE file copied); chats are anonymised by the maintainer unless the victim was publicly named",
        "n_files": len(files),
        "n_chat_files": sum(f["is_chat"] for f in files),
        "n_chat_files_failed_json": sum(f["is_chat"] and not f["json_parses"] for f in files),
        "files": files,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "fetched_at.txt").write_text(f"{retrieved_at}\ncommit {sha}\n")
    print(f"{manifest['n_chat_files']} chat files, {manifest['n_chat_files_failed_json']} failed to parse, commit {sha[:8]} ({commit_date})")


if __name__ == "__main__":
    main()
