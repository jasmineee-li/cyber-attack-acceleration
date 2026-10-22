#!/bin/bash
# Biweekly USD prices for native coins, used only to convert DeFiHackLabs "Lost: N ETH/BNB/..." strings to USD.
# Source: DeFiLlama coins API (free, no key): https://coins.llama.fi/chart/<coin>?start=..&span=..&period=14d
# The API caps a request at 500 data points, so one coin per request.
# Usage: fetch_prices.sh <out_dir>
set -euo pipefail
OUT="$1"
mkdir -p "$OUT"
rm -f "$OUT"/chart_*.json
for c in ethereum binancecoin bitcoin matic-network avalanche-2 fantom solana arbitrum optimism crypto-com-chain hyperliquid eos tron ripple; do
  curl -sS -A "Mozilla/5.0 (academic research; low-rate)" \
    -o "$OUT/chart_${c}.json" \
    "https://coins.llama.fi/chart/coingecko:${c}?start=1483228800&span=260&period=14d" -w "$c %{http_code} %{size_download}\n"
  sleep 2
done
date -u > "$OUT/fetched_at.txt"
