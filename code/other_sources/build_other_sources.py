"""Standardize non-DeFiLlama crypto-hack incident lists into one CSV and quarterly counts.

Usage:
  python3 -I build_other_sources.py <raw_dir> <processed_dir> [--exclude name,name,...]

<raw_dir> is data/raw (one sub-directory per source). Outputs in <processed_dir>:
  other_sources_incidents.csv          source,date,name,amount_usd,category_raw,chain,url
  other_sources_incidents_detail.csv   same + amount_raw, amount_method, category_group, source_id
  other_sources_quarterly.csv          counts per source x quarter, 2020Q1-2026Q4
  certik_dashboard_monthly.csv         CertiK dashboard monthly stats by attack type (aggregate, not incidents)
  comparitech_crypto_quarterly.csv     the Comparitech rows of other_sources_quarterly.csv, kept separately

--exclude names sources (keys of SOURCES) whose raw folder is absent, so they are not read.
Comparitech's raw file may not be redistributed, so a build that excludes it takes the
Comparitech quarterly counts from comparitech_crypto_quarterly.csv, written by a build that
included it. Any other excluded source simply drops out of every output.

All inputs are treated as untrusted data: parsed with regex/json/csv only, never executed.
"""
import bisect
import csv
import datetime as dt
import glob
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amount_parse import parse_lost  # noqa: E402

RAW = sys.argv[1]
OUT = sys.argv[2]
EXCLUDE = set()
if len(sys.argv) > 3:
    if sys.argv[3] != "--exclude" or len(sys.argv) != 5:
        sys.exit(__doc__)
    EXCLUDE = set(sys.argv[4].split(","))
os.makedirs(OUT, exist_ok=True)

# ----------------------------------------------------------------------------- prices
PRICE_FILES = {"ETH": "ethereum", "BNB": "binancecoin", "BTC": "bitcoin", "MATIC": "matic-network",
               "AVAX": "avalanche-2", "FTM": "fantom", "SOL": "solana", "ARB": "arbitrum", "OP": "optimism",
               "CRO": "crypto-com-chain", "HYPE": "hyperliquid", "EOS": "eos", "TRX": "tron", "XRP": "ripple"}
PRICES = {}
for sym, cg in PRICE_FILES.items():
    f = os.path.join(RAW, "prices_coins_llama", f"chart_{cg}.json")
    if not os.path.exists(f):
        continue
    d = json.load(open(f))["coins"]
    pts = sorted((p["timestamp"], p["price"]) for v in d.values() for p in v["prices"])
    PRICES[sym] = ([t for t, _ in pts], [p for _, p in pts])


def price_on(sym, date):
    if sym not in PRICES:
        return None
    ts, ps = PRICES[sym]
    t = dt.datetime(date.year, date.month, date.day, tzinfo=dt.timezone.utc).timestamp()
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None  # before the coin's price history begins
    if t - ts[i] > 60 * 86400 and i == len(ts) - 1:
        return ps[i]  # stale but nearest (e.g. MATIC renamed POL in 2024-25)
    return ps[i]


def to_usd(text, date):
    """Return (amount_usd or None, method string)."""
    v, unit, note = parse_lost(text)
    if v is None:
        return None, note
    if unit in ("USD", "ASSUMED_USD"):
        return v, f"{unit.lower()}:{note}"
    if unit and not unit.startswith("OTHER") and unit in PRICES:
        p = price_on(unit, date)
        if p:
            return v * p, f"converted:{unit}@{p:.4g}"
        return None, f"no_price:{unit}"
    return None, f"unconverted:{unit}"


# ----------------------------------------------------------------------------- category grouping
SCAM = re.compile(r"rug|scam|ponzi|exit|fraud|honeypot|insider|perpetrator|pump", re.I)
KEYS = re.compile(r"private key|key leak|key compromis|keys? (?:were )?(?:stolen|leak)|compromised private|"
                  r"account compromis|wallet stolen|wallet compromis|hot wallet|phish|social engineer|dns|domain|"
                  r"privilege compromis|admin privilege|endpoint|malicious code injection|human error|"
                  r"front-?end|supply[- ]chain|malware|malicious software|trojan|information leak|mnemonic|seed|"
                  r"sim card|credential|discord|telegram|twitter|x account|hijack|server|internal system|"
                  r"permission stolen|ransomware|unauthori[sz]ed access|address poisoning|signer|multisig|"
                  r"third[- ]party|cloud|insider manipulation|infrastructure|wallet|validator compromise",
                  re.I)
CODE = re.compile(r"contract|vulnerab|flash ?loan|reentran|re-entran|price manipulation|oracle|logic|overflow|"
                  r"underflow|access control|input validation|unverified user input|rounding|precision|reward|"
                  r"mint|replay|signature|governance|bridge|arbitrary|donation|liquidity|reserve manipulation|"
                  r"exploit|random number|roll ?back|transaction congestion|fake eos|hard_fail|false top-up|"
                  r"transfer error|accounting|storage collision|slippage|missing state|misconfig|calculation|"
                  r"price dependency|business|k value|upgradab|compatib|sandwich|deflationary|unsafe math|"
                  r"incorrect|uninitiali|lack of|unchecked|validation|bypass|share price|inflation|"
                  r"skim|burn|dividend|approval|callback|self-?destruct|delegatecall|unprotected|"
                  r"permissionless|spot price|twap|erc-?4626|erc-?777|erc-?404|software flaw|ownership override",
                  re.I)


def group_of(cat, default="other_unknown"):
    c = cat or ""
    if not c.strip() or c.strip().lower() in ("unknown", "-", "others", "other", "miscellaneous", "n/a"):
        return default
    if SCAM.search(c):
        return "scam_rugpull"
    if KEYS.search(c):
        return "keys_phishing_infra"
    if CODE.search(c):
        return "code_exploit"
    if re.search(r"51%|double spend|ddos|dos attack|downtime|sybil", c, re.I):
        return "consensus_dos_other"
    return default


rows = []


def add(source, date, name, amount, cat, chain, url, amount_raw="", amount_method="", group=None, sid=""):
    if date is None:
        return
    rows.append({
        "source": source,
        "date": date.isoformat(),
        "name": re.sub(r"\s+", " ", html.unescape(name or "")).strip(),
        "amount_usd": "" if amount is None else f"{amount:.2f}",
        "category_raw": re.sub(r"\s+", " ", html.unescape(cat or "")).strip(),
        "chain": chain or "",
        "url": url or "",
        "amount_raw": re.sub(r"\s+", " ", amount_raw or "").strip()[:300],
        "amount_method": amount_method,
        "category_group": group if group is not None else group_of(cat),
        "source_id": sid,
    })


# ----------------------------------------------------------------------------- DeFiHackLabs
EXPLORERS = [("optimistic.etherscan", "Optimism"), ("etherscan.io", "Ethereum"), ("bscscan", "BSC"),
             ("polygonscan", "Polygon"), ("arbiscan", "Arbitrum"), ("basescan", "Base"), ("ftmscan", "Fantom"),
             ("snowtrace", "Avalanche"), ("snowscan", "Avalanche"), ("lineascan", "Linea"), ("blastscan", "Blast"),
             ("sonicscan", "Sonic"), ("berascan", "Berachain"), ("mantlescan", "Mantle"), ("cronoscan", "Cronos"),
             ("gnosisscan", "Gnosis"), ("moonscan", "Moonbeam"), ("era.zksync", "zkSync"), ("scrollscan", "Scroll"),
             ("explorer/tx/eth/", "Ethereum"), ("explorer/tx/bsc/", "BSC"), ("explorer/tx/arbitrum/", "Arbitrum"),
             ("explorer/tx/base/", "Base"), ("explorer/tx/polygon/", "Polygon"), ("explorer/tx/optimism/", "Optimism"),
             ("explorer/tx/avax/", "Avalanche"), ("explorer/tx/ftm/", "Fantom"), ("explorer/tx/blast/", "Blast"),
             ("explorer/tx/sonic/", "Sonic"), ("explorer/tx/linea/", "Linea"), ("explorer/tx/mantle/", "Mantle")]
CHAIN_WORDS = ["Ethereum", "BSC", "BNB Chain", "Polygon", "Arbitrum", "Base", "Optimism", "Avalanche", "Fantom",
               "Sonic", "Linea", "Blast", "Mantle", "Berachain", "Gnosis", "Cronos", "zkSync", "Scroll", "Unichain",
               "HyperEVM", "Sei", "Katana", "Plasma", "Monad", "Abstract", "Ink", "Soneium", "Mode"]


def chain_from_text(t):
    tl = t.lower()
    for k, v in EXPLORERS:
        if k in tl:
            return v
    m = re.search(r"\bon (" + "|".join(re.escape(w) for w in CHAIN_WORDS) + r")\b", t)
    if m:
        return "BSC" if m.group(1) == "BNB Chain" else m.group(1)
    return ""


def dhl():
    base = os.path.join(RAW, "defihacklabs")
    main = open(os.path.join(base, "README.md"), encoding="utf-8").read()
    # canonical index (the README's own "List of Past DeFi Incidents"; 894 entries on 2026-10-18)
    s, e = main.find("## List of Past DeFi Incidents"), main.find("### Transaction debugging tools")
    index = re.findall(r"^\[(\d{8}) ([^\]]+)\]\(([^)]*)\)", main[s:e], re.M)
    files = {"README.md": main}
    for f in sorted(glob.glob(os.path.join(base, "past_*_README.md"))):
        files[os.path.basename(f)] = open(f, encoding="utf-8").read()
    details = {}
    for fname, txt in files.items():
        if fname == "README.md":
            txt = txt[txt.find("### List of DeFi Hacks & POCs"):]
        parts = re.split(r"^(### \d{8} .*)$", txt, flags=re.M)
        for i in range(1, len(parts), 2):
            hdr, body = parts[i], parts[i + 1]
            m = re.match(r"### (\d{8}) (.*?)(?: - (.*))?$", hdr.strip())
            d8, nm, cause = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
            lost = ""
            lm = re.search(r"^\W*#*\s*\**\s*Lost\s*:?\**\s*(.*)$", body, re.M | re.I)
            if lm:
                lost = lm.group(1)
            link = ""
            lk = re.search(r"Link reference[^\n]*\n+\s*(https?://\S+)", body)
            if lk:
                link = lk.group(1).rstrip(")")
            details.setdefault(d8, []).append({"name": nm, "cause": cause, "lost": lost, "body": body,
                                               "file": fname, "link": link})
    used = set()
    n_missing = 0

    def gh_anchor(hdr):
        a = re.sub(r"[^\w\- ]", "", hdr.strip().lower())
        return a.replace(" ", "-")

    anchors = {}
    for k8, cs in details.items():
        for j, c in enumerate(cs):
            anchors.setdefault(gh_anchor(k8 + " " + c["name"] + (" - " + c["cause"] if c["cause"] else "")),
                               []).append((k8, j))
    for d8, iname, href in index:
        frag = href.split("#")[-1].lower()
        hit = [x for x in anchors.get(frag, []) if x not in used]
        if hit:
            k8, pick = hit[0]
            cands = details[k8]
        else:
            k8 = d8
            cands = details.get(d8, [])
            pick = None
        key = re.sub(r"[^a-z0-9]", "", iname.lower())
        for j, c in (enumerate(cands) if pick is None else []):
            ck = re.sub(r"[^a-z0-9]", "", c["name"].lower())
            if (k8, j) not in used and (ck == key or key.startswith(ck[:6]) or ck.startswith(key[:6])):
                pick = j
                break
        if pick is None:  # same name within +-10 days (index and header dates sometimes differ)
            d0 = dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:]))
            for off in range(-10, 11):
                k2 = (d0 + dt.timedelta(days=off)).strftime("%Y%m%d")
                for j, c in enumerate(details.get(k2, [])):
                    ck = re.sub(r"[^a-z0-9]", "", c["name"].lower())
                    if (k2, j) not in used and ck[:6] == key[:6]:
                        k8, cands, pick = k2, details[k2], j
                        break
                if pick is not None:
                    break
        if pick is None:
            for j, c in enumerate(cands):
                if (k8, j) not in used:
                    pick = j
                    break
        date = dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:]))
        if pick is None:
            n_missing += 1
            print("DeFiHackLabs index entry without detail section:", d8, iname, href)
            cause = re.sub(r"^#\d{8}-[^-]+---", "", href.split("#")[-1]).replace("-", " ")
            add("DeFiHackLabs", date, iname, None, cause, "",
                "https://github.com/SunWeb3Sec/DeFiHackLabs/blob/main/" + href.lstrip("#"),
                "", "no_detail_section", group="code_exploit", sid=d8 + " " + iname)
            continue
        used.add((k8, pick))
        c = cands[pick]
        if re.search(r"no exploit occurred|disclosure only", c["lost"], re.I):
            continue  # not an incident
        amt, meth = to_usd(c["lost"], date)
        url = "https://github.com/SunWeb3Sec/DeFiHackLabs/blob/main/" + (
            href if href.startswith("past/") else "README.md" + href)
        grp = group_of(c["cause"], default="code_exploit")
        if grp == "other_unknown":
            grp = "code_exploit"
        add("DeFiHackLabs", date, iname, amt, c["cause"][:300], chain_from_text(c["lost"] + "\n" + c["body"]),
            url, c["lost"], meth, group=grp, sid=d8 + " " + iname)
    extra = [(d8, c["name"]) for d8, cs in details.items() for j, c in enumerate(cs) if (d8, j) not in used]
    print(f"DeFiHackLabs: index={len(index)} detail-sections-not-in-index={extra} index-without-detail={n_missing}")


# ----------------------------------------------------------------------------- SlowMist Hacked
def slowmist():
    n = 0
    for f in sorted(glob.glob(os.path.join(RAW, "slowmist", "page_*.html"))):
        h = open(f, encoding="utf-8").read()
        for li in re.findall(r'<li>\s*<span class="time">(.*?)</li>', h, re.S):
            date_s = li.split("</span>")[0].strip()
            try:
                date = dt.date.fromisoformat(date_s)
            except ValueError:
                print("SlowMist bad date", date_s)
                continue
            tgt = re.search(r"Hacked target: </em>(.*?)</h3>", li, re.S)
            meth = re.search(r"Attack method: </em>(.*?)</span>", li, re.S)
            amt = re.search(r"Amount of loss: </em>(.*?)</span>", li, re.S)
            ref = re.search(r'class="link-reference"><a href="([^"]*)"', li)
            amt_s = re.sub(r"\s+", " ", html.unescape(amt.group(1))).strip() if amt else ""
            usd, how = (None, "unknown") if amt_s in ("", "-") else to_usd(amt_s, date)
            if amt_s.strip() == "0":
                usd, how = 0.0, "reported_zero"
            add("SlowMist Hacked", date, tgt.group(1) if tgt else "", usd,
                html.unescape(meth.group(1).strip()) if meth else "", "", ref.group(1) if ref else "",
                amt_s, how)
            n += 1
    print("SlowMist:", n)


# ----------------------------------------------------------------------------- SolidityScan Web3HackHub
def solidityscan():
    n = 0
    for f in sorted(glob.glob(os.path.join(RAW, "solidityscan_hackhub", "page_*.json"))):
        for r in json.load(open(f))["data"]:
            date = dt.date.fromisoformat(r["date"][:10])
            ref = (r.get("reference") or "").split(",")[0].strip()
            amt = r.get("amount_in_usd")
            if str(r.get("amount") or "").strip() in ("", "-") and not amt:
                amt = None  # "-" means unknown; the API reports it as 0
            cat = f"{(r.get('attacked_method') or '').strip()} | {(r.get('category') or '').strip()}"
            add("SolidityScan Web3HackHub", date, r.get("target"), float(amt) if amt not in (None, "") else None,
                cat, r.get("chain") or "", ref, str(r.get("amount") or ""), "usd:api_amount_in_usd",
                group=group_of(r.get("attacked_method") or ""))
            n += 1
    print("SolidityScan:", n)


# ----------------------------------------------------------------------------- BlockSec
CHAIN_IDS = {1: "Ethereum", 56: "BSC", 42161: "Arbitrum", 8453: "Base", 10: "Optimism", 137: "Polygon",
             43114: "Avalanche", 59144: "Linea", 146: "Sonic", 80094: "Berachain", 5000: "Mantle", 324: "zkSync",
             81457: "Blast", 250: "Fantom", 369: "PulseChain", 2222: "Kava", 252: "Fraxtal", 42220: "Celo",
             480: "World Chain", 5464: "Saga", 999: "HyperEVM", 130: "Unichain", 143: "Monad", 25: "Cronos",
             100: "Gnosis", 1101: "Polygon zkEVM", 534352: "Scroll", 34443: "Mode"}


def blocksec():
    n = 0
    for f in sorted(glob.glob(os.path.join(RAW, "blocksec", "page_*.json"))):
        for r in json.load(open(f)).get("list", []):
            date = dt.datetime.fromtimestamp(r["date"] / 1000, tz=dt.timezone.utc).date()
            chains = "|".join(CHAIN_IDS.get(c, f"chainid:{c}") for c in r.get("chainIds", []))
            loss = r.get("loss")
            add("BlockSec Security Incidents", date, r.get("project"), float(loss) if loss not in (None, "") else None,
                r.get("rootCause"), chains, f"https://blocksec.com/security-incident/{r['id']}",
                str(loss), "usd:api_loss", sid=str(r["id"]))
            n += 1
    print("BlockSec:", n)


# ----------------------------------------------------------------------------- rekt.news leaderboard
def rekt():
    h = open(os.path.join(RAW, "rekt_news", "leaderboard.html"), encoding="utf-8").read()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    lb = json.loads(m.group(1))["props"]["pageProps"]["leaderboard"]
    n = 0
    for r in lb:
        ds = r["rekt"]["date"]
        try:
            mo, da, yr = ds.split("/")
            yr = int(yr) + (2000 if int(yr) < 100 else 0)  # one entry is written "11/12/22"
            date = dt.date(yr, int(mo), int(da))
        except ValueError:
            print("rekt.news bad incident date:", r["title"], ds)
            continue
        tags = [t for t in r.get("tags", []) if t.lower() not in ("rekt", "r3kt")]
        add("rekt.news leaderboard", date, r["title"], float(r["rekt"]["amount"]), "|".join(tags), "",
            "https://rekt.news/" + r["slug"], str(r["rekt"]["amount"]), "usd:leaderboard",
            group=group_of("|".join(tags) + " " + r.get("excerpt", "")[:0]))
        n += 1
    print("rekt.news:", n)


# ----------------------------------------------------------------------------- Web3 Is Going Great
W3_KEYS = re.compile(r"phish|private key|compromised|social engineer|drainer|seed phrase|hot wallet|"
                     r"supply chain|malware|front-?end|dns|sim[- ]swap|impersonat|wrench|kidnap|address poisoning",
                     re.I)
W3_CODE = re.compile(r"exploit|flash loan|bug|vulnerab|smart contract|oracle|reentr|price manipulation|"
                     r"governance attack|minted|mint ", re.I)
W3_SCAM = re.compile(r"rug|scam|ponzi|exit|fraud|pig butcher|pump", re.I)


def w3igg():
    e = json.load(open(os.path.join(RAW, "web3isgoinggreat", "entries_hack.json"), encoding="utf-8"))
    for x in e:
        yy, mm, dd = (int(v) for v in x["date"].split("-")[:3])
        date = dt.date(yy, mm, dd)
        themes = x.get("filters", {}).get("theme", [])
        sa = x.get("scamAmountDetails", {}) or {}
        amt = sa.get("total") if sa.get("hasScamAmount") else None
        title = html.unescape(x.get("title", ""))
        title = re.sub(r"<[^>]+>", "", title)
        cat = "theme:" + ",".join(themes)
        if x.get("collection"):
            cat += " | collection:" + ",".join(x["collection"])
        if "rugPull" in themes or W3_SCAM.search(title):
            grp = "scam_rugpull"
        elif W3_KEYS.search(title):
            grp = "keys_phishing_infra"
        elif "bug" in themes or W3_CODE.search(title):
            grp = "code_exploit"
        else:
            grp = "other_unknown"
        add("Web3 Is Going Great (hack/scam)", date, x.get("shortTitle") or title, float(amt) if amt else None,
            cat, ",".join(x.get("filters", {}).get("blockchain", [])),
            "https://www.web3isgoinggreat.com/?id=" + (x.get("readableId") or x["id"]),
            json.dumps(sa)[:200] if sa else "", "usd:scamAmountDetails.total", group=grp, sid=x["id"])
    print("W3IGG:", len(e))


# ----------------------------------------------------------------------------- Comparitech
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}


def comparitech():
    f = os.path.join(RAW, "comparitech", "datawrapper_gT7C8_v288_dataset.csv")
    n = 0
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        try:
            date = dt.date(int(r["Year"]), MONTHS[r["Month"].strip()], 1)  # month precision only
        except (KeyError, ValueError):
            print("Comparitech bad date", r.get("Month"), r.get("Year"))
            continue
        a = (r.get("Amount Stolen (USD)") or "").replace(",", "").replace("$", "").strip()
        try:
            amt = float(a) if a else None
        except ValueError:
            amt = None
        cat = f"{r.get('Type of Attack', '').strip()} | {r.get('Platform Type', '').strip()}"
        t = r.get("Type of Attack", "").strip().lower()
        grp = {"exploit": "code_exploit", "flash loan": "code_exploit", "price oracle/price manipulation": "code_exploit",
               "reetrancy attack": "code_exploit", "governance attack": "code_exploit",
               "hack": "keys_phishing_infra_or_unspecified", "third party": "keys_phishing_infra",
               "malware": "keys_phishing_infra", "insider": "scam_rugpull",
               "51% attack": "consensus_dos_other"}.get(t, "other_unknown")
        add("Comparitech crypto heists", date, r.get("Company Name"), amt, cat, "", r.get("Link #1", ""),
            r.get("Amount Stolen (USD)", ""), "usd:Amount Stolen (USD); date=first of month", group=grp)
        n += 1
    print("Comparitech:", n)


# ----------------------------------------------------------------------------- ChainSec
def chainsec():
    h = open(os.path.join(RAW, "chainsec", "defi-hacks.html"), encoding="utf-8").read()
    n = 0
    for card in re.findall(r'<article class="exchange-timeline-card">(.*?)</article>', h, re.S):
        ds = re.search(r'exchange-timeline-date">(.*?)</p>', card)
        nm = re.search(r"<h2>(.*?)</h2>", card, re.S)
        desc = re.search(r"</h2>\s*<p>(.*?)</p>", card, re.S)
        amt = re.search(r"Amount stolen:</strong>\s*(?:<!-- -->)?(.*?)</p>", card, re.S)
        src = re.search(r'Source:</strong>\s*<a href="([^"]*)"', card)
        if ds is None and nm is not None:  # a few legacy cards carry the date inside the heading
            ds = re.search(r"\(([A-Z][a-z]+ \d{1,2}, \d{4})\)", nm.group(1))
        try:
            date = dt.datetime.strptime(ds.group(1).strip(), "%B %d, %Y").date()
        except (AttributeError, ValueError):
            print("ChainSec bad date", ds.group(1) if ds else None)
            continue
        a = re.sub(r"<[^>]+>", "", amt.group(1)).strip() if amt else ""
        v = a.replace("$", "").replace(",", "").strip()
        try:
            usd = float(v)
        except ValueError:
            usd = None
        d = re.sub(r"<[^>]+>", "", html.unescape(desc.group(1))) if desc else ""
        add("ChainSec DeFi exploits", date, re.sub(r"\*\*\(.*?\)\*\*|<[^>]+>", "", nm.group(1)).strip() if nm else "", usd,
            d[:200], "", src.group(1) if src else "", a, "usd:page", group=group_of(d, default="code_exploit"))
        n += 1
    print("ChainSec:", n)


# ----------------------------------------------------------------------------- Zenodo DeFi crime dataset (2017-2022)
def zenodo():
    f = os.path.join(RAW, "zenodo_defi_crime_landscape", "Dataset_OpenAccess_JofCyberSec_v2.csv")
    n = bad = 0
    for r in csv.DictReader(open(f, encoding="utf-8-sig", errors="replace")):
        ds = (r.get("Event date") or "").strip()[:10]
        date = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%B %d, %Y", "%d %B %Y", "%b %d, %Y"):
            try:
                date = dt.datetime.strptime(ds, fmt).date()
                break
            except ValueError:
                pass
        if date is None:
            bad += 1
            continue
        a = (r.get("Stolen amount USD") or "").replace(",", "").replace("$", "").strip()
        try:
            amt = float(a) if a else None
        except ValueError:
            amt = None
        cat = " | ".join(x for x in [r.get("General tactic", ""), r.get("Specific tactic", ""),
                                     "actor:" + r.get("Implication of actor", ""), r.get("Paper category", "")] if x)
        url = r.get("REKT URL") or r.get("SlowMist URL") or r.get("ChainSec URL") or ""
        add("Zenodo DeFi crime dataset (2017-2022)", date, r.get("DeFi actor involved"), amt, cat, "", url,
            r.get("Stolen amount USD", ""), "usd:dataset", sid=r.get("unique_key", ""))
        n += 1
    print("Zenodo:", n, "unparsed dates:", bad)


# ----------------------------------------------------------------------------- CertiK dashboard (aggregate)
def certik_monthly():
    f = os.path.join(RAW, "certik_dashboard", "dashboard_2026-10-18.html")
    h = open(f, encoding="utf-8").read()
    i = h.find("statistics:{") + len("statistics:")
    depth = 0
    for k in range(i, len(h)):
        if h[k] == "{":
            depth += 1
        elif h[k] == "}":
            depth -= 1
            if depth == 0:
                break
    js = re.sub(r"([{,])([a-zA-Z_][a-zA-Z0-9_]*):", r'\1"\2":', h[i:k + 1]).replace("void 0", "null")
    d = json.loads(js)
    types = sorted({t["name"] for m in d["monthlyStats"] for t in m["byType"]})
    out = []
    for m in d["monthlyStats"]:
        km = m["keyMetrics"]
        row = {"month": m["value"], "total_incidents": km["totalIncidents"], "total_losses_usd": km["totalLosses"],
               "adjusted_losses_usd": km["adjustedTotalLosses"], "median_loss_usd": km["medianLossPerIncident"],
               "is_current_month": m["isCurrentMonth"]}
        bt = {t["name"]: t for t in m["byType"]}
        for t in types:
            row[f"incidents_{t}"] = bt.get(t, {}).get("incidents", 0)
            row[f"losses_{t}"] = bt.get(t, {}).get("losses", 0)
        out.append(row)
    with open(os.path.join(OUT, "certik_dashboard_monthly.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("CertiK dashboard months:", len(out), "data updated", d["dataUpdatedAt"])
    return out


# ----------------------------------------------------------------------------- run
SOURCES = {"dhl": dhl, "slowmist": slowmist, "solidityscan": solidityscan, "blocksec": blocksec, "rekt": rekt,
           "w3igg": w3igg, "comparitech": comparitech, "chainsec": chainsec, "zenodo": zenodo}
# Sources whose raw data may not be redistributed: their quarterly counts are written to a
# separate file by a build that includes them, and read back by a build that excludes them.
RESTRICTED = {"comparitech": ("Comparitech crypto heists", "comparitech_crypto_quarterly.csv")}
unknown = EXCLUDE - SOURCES.keys()
if unknown:
    sys.exit(f"--exclude names unknown sources: {sorted(unknown)}; known: {sorted(SOURCES)}")
for name, fn in SOURCES.items():
    if name in EXCLUDE:
        print(f"{name}: excluded")
    else:
        fn()
certik = certik_monthly()

rows.sort(key=lambda r: (r["source"], r["date"], r["name"]))
COLS = ["source", "date", "name", "amount_usd", "category_raw", "chain", "url"]
with open(os.path.join(OUT, "other_sources_incidents.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
with open(os.path.join(OUT, "other_sources_incidents_detail.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS + ["category_group", "amount_raw", "amount_method", "source_id"])
    w.writeheader()
    w.writerows(rows)

# ----------------------------------------------------------------------------- quarterly
TODAY = dt.date(2026, 10, 18)
LAST_UPDATE = {  # last date each source covers (newest incident, or stated update date)
    "ChainSec DeFi exploits": dt.date(2026, 4, 30),   # page says "Updated: 2026-04-30"
    "Comparitech crypto heists": dt.date(2026, 9, 30),  # month-level dates; September 2026 is the last month
}
quarters = [f"{y}Q{q}" for y in range(2020, 2027) for q in range(1, 5)]


def qof(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def qstart(q):
    return dt.date(int(q[:4]), 3 * (int(q[-1]) - 1) + 1, 1)


def qend(q):
    y, n = int(q[:4]), int(q[-1])
    return (dt.date(y + (n == 4), 1 if n == 4 else 3 * n + 1, 1) - dt.timedelta(days=1))


by_src = {}
for r in rows:
    by_src.setdefault(r["source"], []).append(r)
qrows = []
for src, rs in sorted(by_src.items()):
    dates = sorted(dt.date.fromisoformat(r["date"]) for r in rs)
    first, last = dates[0], LAST_UPDATE.get(src, dates[-1])
    for q in quarters:
        qr = [r for r in rs if qof(dt.date.fromisoformat(r["date"])) == q]
        with_amt = [r for r in qr if r["amount_usd"] != ""]
        ge1m = [r for r in with_amt if float(r["amount_usd"]) >= 1e6]
        code = [r for r in qr if r["category_group"] == "code_exploit"]
        code_ge1m = [r for r in code if r["amount_usd"] != "" and float(r["amount_usd"]) >= 1e6]
        if qend(q) < first:
            cov = "before_coverage"
        elif qstart(q) > last:
            cov = "after_last_update"
        elif qend(q) > last or q == qof(TODAY):
            cov = "partial"
        else:
            cov = "full"
        qrows.append({"source": src, "quarter": q, "n_incidents": len(qr), "n_with_amount": len(with_amt),
                      "n_ge_1m": len(ge1m), "n_code_exploit": len(code), "n_code_exploit_ge_1m": len(code_ge1m),
                      "coverage": cov, "last_date": last.isoformat()})
QCOLS = list(qrows[0].keys())
for name, (src, fname) in RESTRICTED.items():
    path = os.path.join(OUT, fname)
    if name in EXCLUDE:
        if not os.path.exists(path):
            sys.exit(f"{name} is excluded but {path} is missing; build it once with the raw data present")
        with open(path, newline="") as fh:
            extra = list(csv.DictReader(fh))
        assert extra and all(r["source"] == src for r in extra) and list(extra[0].keys()) == QCOLS, path
        qrows += extra
        print(f"{name}: {len(extra)} quarterly rows read from {fname}")
    else:
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=QCOLS)
            w.writeheader()
            w.writerows(r for r in qrows if r["source"] == src)
qrows.sort(key=lambda r: (r["source"], r["quarter"]))
with open(os.path.join(OUT, "other_sources_quarterly.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=QCOLS)
    w.writeheader()
    w.writerows(qrows)
print("rows:", len(rows), "quarterly rows:", len(qrows))
