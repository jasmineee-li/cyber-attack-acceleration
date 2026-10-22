"""Parse free-text loss strings (e.g. DeFiHackLabs "Lost:" lines) into (number, unit).

parse_lost(text) -> (value, unit, note)
  value: float or None
  unit:  'USD' for dollar-like units (USD, $, USDT, USDC, DAI, BUSD, ...),
         a coin symbol such as 'ETH', 'BNB', 'BTC' for native coins we can price,
         'ASSUMED_USD' when a number with a k/M/B suffix has no unit at all,
         'OTHER:<token>' for other tokens (not converted), or None.
"""
import re

SUFFIX = {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "b": 1e9, "B": 1e9,
          "thousand": 1e3, "million": 1e6, "billion": 1e9, "mn": 1e6, "bn": 1e9}
SUF_RE = r"([kKmMbB](?![a-zA-Z])|(?i:thousand|million|billion)\b|mn\b|bn\b)"

USD_UNITS = {"USD", "USDT", "USDC", "DAI", "BUSD", "USDC.E", "USDBC", "FRAX", "TUSD", "USDE",
             "CRVUSD", "GHO", "LUSD", "USDS", "PYUSD", "USD0", "USD1", "FDUSD", "SUSD", "DOLA",
             "MIM", "USDM", "USDX", "DOLLARS", "USDT0", "BSC-USD", "AXLUSDC", "USDB", "US", "BUSDT"}

# coin symbol -> canonical symbol used for pricing
COINS = {"ETH": "ETH", "WETH": "ETH", "STETH": "ETH", "WSTETH": "ETH", "EETH": "ETH", "WEETH": "ETH",
         "BNB": "BNB", "WBNB": "BNB",
         "BTC": "BTC", "WBTC": "BTC", "BTCB": "BTC", "CBBTC": "BTC",
         "MATIC": "MATIC", "WMATIC": "MATIC", "POL": "MATIC",
         "AVAX": "AVAX", "WAVAX": "AVAX",
         "FTM": "FTM", "WFTM": "FTM",
         "SOL": "SOL", "WSOL": "SOL",
         "ARB": "ARB", "OP": "OP",
         "CRO": "CRO", "WCRO": "CRO",
         "TRX": "TRX", "CELO": "CELO", "GLMR": "GLMR", "MOVR": "MOVR", "ONE": "ONE",
         "HT": "HT", "OKT": "OKT", "METIS": "METIS", "KAVA": "KAVA", "SUI": "SUI",
         "S": "S", "WS": "S", "SEI": "SEI", "HYPE": "HYPE", "WHYPE": "HYPE", "MNT": "MNT", "XDAI": "USD",
         "EOS": "EOS", "XRP": "XRP"}

NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
# number, optional range "-89", optional suffix, optional unit
PAT = re.compile(
    NUM + r"(?:\s*(?:-|–|~|to)\s*" + NUM + r")?\s*" + SUF_RE + r"?\+?\s*(?:\(\s*)?(\$?\s*[A-Za-z][A-Za-z0-9\.\-]*)?")


def _suf(x):
    return SUFFIX.get((x or "").lower() if x and len(x) > 2 else (x or ""), 1)


def _num(s):
    s = s.strip()
    if re.fullmatch(r"\d+,\d{1,2}", s):  # "1,6" European decimal comma
        return float(s.replace(",", "."))
    return float(s.replace(",", ""))


def parse_lost(text):
    if not text:
        return None, None, "empty"
    t = text.replace(" ", " ").replace("～", "~").replace("＄", "$")
    t = re.sub(r"\*\*|`", "", t)
    # dollar sign directly before number: "$7M", "~$1,6M", "$ 490K"
    m = re.search(r"\$\s*" + NUM + r"\s*" + SUF_RE + r"?", t)
    if m is None:
        m = re.search(r"\$\s*(\.\d+)\s*" + SUF_RE + r"?", t)
    dollar_first = m.start() if m else None
    best = None
    best_end = None
    for mm in PAT.finditer(t):
        a, _b, suf, unit = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
        # skip numbers that are clearly part of words like "0x..", years in prose, tx hashes
        pre = t[max(0, mm.start() - 2):mm.start()]
        if pre.endswith("0x") or re.match(r"[A-Za-z_]", pre[-1:] or " "):
            continue
        if re.search(r"[A-Za-z]-$", t[max(0, mm.start() - 4):mm.start()]):  # e.g. "ERC-20"
            continue
        best = (mm.start(), a, suf, unit)
        best_end = mm.end()
        break
    if dollar_first is not None and (best is None or dollar_first <= best[0] + 2):
        v = _num(m.group(1)) * _suf(m.group(2))
        return v, "USD", "dollar_sign"
    if best is None:
        return None, None, "no_number"
    _, a, suf, unit = best
    v = _num(a) * _suf(suf)
    u = (unit or "").replace("$", "").strip().upper().rstrip(".")
    after = t[best_end:best_end + 4] if best_end else ""
    if u == "" and after.lstrip().startswith("$"):
        return v, "USD", "trailing_dollar"
    if u in USD_UNITS:
        return v, "USD", "usd_unit"
    if u in COINS:
        return v, COINS[u], "coin_unit"
    if u == "" or u in {"IN", "AND", "WORTH", "OF", "LOST", "NET", "TOTAL", "APPROX", "ON", "FROM", "TO",
                        "PROFIT", "ACROSS", "VIA", "WHICH", "THE"}:
        if suf:
            return v, "ASSUMED_USD", "suffix_no_unit"
        if v >= 1000:
            return v, "ASSUMED_USD", "plain_number_no_unit"
        return None, None, "number_no_unit"
    if m is not None:
        v2 = _num(m.group(1)) * _suf(m.group(2))
        return v2, "USD", "dollar_sign_after_other_token"
    return v, "OTHER:" + u, "other_token"


if __name__ == "__main__":
    import sys
    for line in sys.stdin:
        print(repr(line.strip()[:80]), parse_lost(line))
