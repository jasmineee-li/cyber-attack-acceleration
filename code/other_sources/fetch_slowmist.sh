#!/bin/bash
# Fetch the public SlowMist Hacked list (hacked.slowmist.io), one HTML page per request.
# No JSON endpoint was found; the site has no robots.txt (404 on 2026-10-18).
# Polite: one request every 3 seconds, single connection.
# Usage: fetch_slowmist.sh <out_dir> <n_pages>
set -euo pipefail
OUT="$1"
N="$2"
mkdir -p "$OUT"
for p in $(seq 1 "$N"); do
  f="$OUT/page_$(printf '%03d' "$p").html"
  if [ -s "$f" ]; then continue; fi
  curl -sS -L -A "Mozilla/5.0 (academic research; low-rate)" \
    -o "$f" "https://hacked.slowmist.io/?c=&page=$p" -w "page $p %{http_code} %{size_download}\n"
  sleep 3
done
date -u > "$OUT/fetched_at.txt"
