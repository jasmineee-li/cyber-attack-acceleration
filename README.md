# Have we seen an acceleration in cyberattacks?

Code, data and figures for the blog post of the same name (Cheryl Wu and Jasmine Li, October 2026). <!-- TODO: link to the published post -->

## Layout

```text
code/              Scripts. Numbered v01, v02, ... for the DeFiLlama series;
                   code/other_sources/ for the other crypto trackers,
                   code/ransomware/ for ransomware, code/attacker_text/ for negotiation text
data/raw/          Downloaded source data, one folder per source (see "Data sources and credits")
data/processed/    Tables built from the raw data
figures/           Charts (figures/README.md maps them to the post)
dvc.yaml           Pipeline: which script builds which file from which inputs
dvc.lock           Fingerprints of inputs and outputs from the last pipeline run
pyproject.toml     Python dependencies; uv.lock pins exact versions
```

## Rebuild the tables and figures

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from the project folder:

```sh
uv sync --locked
uv run dvc repro
uv run dvc status      # should say the pipeline is up to date
```

uv installs Python 3.12 and the pinned packages into a local `.venv`. [DVC](https://doc.dvc.org/user-guide/pipelines) reruns only the steps whose inputs changed; `dvc repro --force` reruns everything. All outputs are ordinary Git-tracked files, so there is no `dvc push` or `dvc pull`. Tests: `uv run pytest code/attacker_text/tests`.

## Methods in brief

- **Crypto hacks (figures 8–12, 36, 37).** DeFiLlama's hack list, downloaded 18 October 2026: 1,306 incidents from 2011 on, each with a date, amount and cause. Monthly counts from January 2020; "small" hacks are those under $4.5 million. The exploit-type split fits each of DeFiLlama's 13 cause categories with a trend that may bend once (a negative-binomial fit with a constant growth rate before and after a kink month, profiled over July 2024 to July 2026). A type counts as *accelerated* when the bent trend beats a straight one by more than 4 log-likelihood units, growth is faster after the bend, and some month between October 2025 and June 2026 fits within 2 log-likelihood units of the best bend. Protocol Logic passes this rule but is shown with the types that did not accelerate, by the authors' judgement. The rule and its reasons are in the docstring of `code/v13_fig_defillama_hacks_by_type.py`; the fits come from `code/v27_changepoint_by_class.py`, which uses the model in `code/v21_did_changepoint_events.py`.
- **Other crypto trackers (appendix A, figures 13–19).** Quarterly counts per tracker from 2022. Each tracker's 2026 Q2–Q3 average is compared with the trend of its own 2022–25 counts and with its busiest earlier quarter. The trend test is in `code/v11_tracker_trend_check.py` (four trend versions; "acceleration" only if all four agree). BlockSec publishes with a delay, so its 2026 Q3 is left out.
- **Ransomware (figures 31, 32, 35).** ransomware.live records victims named on gangs' leak sites; counts are by month of posting, and "groups" are gangs that named at least one victim in the quarter. Comparitech's Ransomware Intelligence Platform records only attacks confirmed by a victim statement, breach notice or news report; counts are by month of the attack, so recent months fill in late.
- **AI use in negotiations (figure in `figures/attacker_text/`, appendix B).** The [Casualtek/Ransomchats](https://github.com/Casualtek/Ransomchats) corpus at commit `ba5c3281` (21 September 2026): 276 chats, 12,889 messages, 31 gangs. Attacker messages were kept if they could be dated, were English prose of 50+ words, and were not a template repeated across chats (344 messages); victim messages were scored the same way as a comparator (704). Each text was scored once by Pangram 4.1 (`code/attacker_text/pangram_classify.py`, responses cached in `data/processed/attacker_text/pangram_cache/`). A message is "flagged" when Pangram's document label is AI or Mixed. `code/attacker_text/typography.py` counts curly quotes, em dashes and non-breaking hyphens as a detector-free marker. All flagged messages, with dates and labels, are in `data/processed/attacker_text/pangram_flagged_messages.csv`.

## Refreshing the raw data

Downloading is not part of the pipeline, because it contacts live websites and the lists change over time. Each raw folder records when it was downloaded, in `fetched_at.txt` or in the file name. Keep the request rate low; the scripts wait 2–3 seconds between requests.

- **DeFiLlama:** `uv run python code/v01_fetch_defillama.py` saves a date-stamped pair (`hacks_<date>.json`, `tvl_<date>.json`) in `data/raw/defillama/`; the scripts use the newest pair.
- **SlowMist:** `rm data/raw/slowmist/page_*.html`, then `code/other_sources/fetch_slowmist.sh data/raw/slowmist <pages>` (116 pages in October 2026; the script skips pages already on disk, and page 1 is the newest).
- **Web3 Is Going Great:** `uv run python -I code/other_sources/fetch_w3igg.py data/raw/web3isgoinggreat`, then write today's date into `fetched_at.txt`.
- **Coin prices** (to convert amounts quoted in coins to dollars): `code/other_sources/fetch_prices.sh data/raw/prices_coins_llama`.
- **Downloaded by hand:** rekt.news (the leaderboard page embeds its data as JSON), BlockSec (the public incident page loads from `POST blocksec.com/api/v1/attack/events`), CertiK (monthly figures are embedded in the dashboard page; saved and extracted), DeFiHackLabs (the repository's README files, which list reproduced exploits by month), Comparitech crypto heists (the CSV behind the Datawrapper chart on its heists page; see "Data sources and credits").
- **Comparitech ransomware:** `rm -r data/raw/comparitech_ransomware/observations`, then `uv run python -I code/ransomware/fetch_comparitech_ransomware.py data/raw/comparitech_ransomware` (about 5 minutes; it skips months already on disk, and the newest months grow as attacks get confirmed).
- **ransomware.live:** needs a free API key from ransomware.live/my in `.env` (copy `.env.example`). Then `uv run python -I code/ransomware/fetch_ransomware_live.py data/raw/ransomware_live` and `uv run python -I code/ransomware/build_ransomware_live.py data/raw data/processed`.
- **Ransomchats:** `uv run python -I code/attacker_text/fetch_ransomchats.py data/raw/ransomchats <commit_sha>` (find the current SHA with `git ls-remote https://github.com/Casualtek/Ransomchats main`). Pangram scoring is paid and keyed, so it is not a pipeline stage: with `PANGRAM_API_KEY` in `.env`, `uv run python -I code/attacker_text/pangram_classify.py data/processed/attacker_text --estimate` shows the bill, and `--sample A_primary --sample victim` runs the scoring used in the post. Re-runs are free because responses are cached per text.

After refreshing, run `uv run dvc repro` and commit the changed data, outputs and `dvc.lock` together.

## Data sources and credits

| Source | Used for | Terms, and what is in this repository |
|---|---|---|
| [DeFiLlama hacks](https://defillama.com/hacks) | main crypto series | Raw JSON included. |
| [SlowMist Hacked](https://hacked.slowmist.io/) | appendix A | Saved pages included. |
| [CertiK dashboard](https://www.certik.com/certik-report/dashboard) | appendix A ("Exploit" category) | Saved page and monthly totals included. |
| [rekt.news leaderboard](https://rekt.news/leaderboard/) | appendix A | Saved JSON included. |
| [Web3 Is Going Great](https://www.web3isgoinggreat.com/) | appendix A ("Hack or scam" tag) | Saved entries included. |
| [BlockSec security incidents](https://blocksec.com/security-incident) | appendix A | Saved JSON included. |
| [DeFiHackLabs](https://github.com/SunWeb3Sec/DeFiHackLabs) | exploit classes in the by-type fits | README files included. |
| [Comparitech crypto heists](https://www.comparitech.com/crypto/biggest-cryptocurrency-heists/) | appendix A | Fine for research with credit; **the raw file is not redistributed here**, only quarterly counts. |
| [Ransomware.live](https://www.ransomware.live/) | ransomware figures 31 and 35 | "Source: Ransomware.live". Its terms forbid publishing the raw data, so **only monthly and quarterly counts are included**; anyone with a free key can rebuild them with the scripts above. |
| [Comparitech Ransomware Intelligence Platform](https://ransomware.comparitech.com/) | ransomware figure 32 | "Data from Comparitech Ransomware Intelligence Platform (ransomware.comparitech.com)". Monthly files included. |
| [Casualtek/Ransomchats](https://github.com/Casualtek/Ransomchats) | negotiation text | MIT licence. Pinned copy included. |
| [Pangram](https://www.pangram.com/) | AI-text labels | Cached API responses included. |

Code is MIT-licensed; figures and processed tables are CC BY 4.0 (see `LICENSE`).
