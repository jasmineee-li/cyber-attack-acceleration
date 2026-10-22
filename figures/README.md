# Figures used in the blog post

Every figure in this folder appears in the post "Have we seen an acceleration in cyberattacks?" (October 2026). Each one is rebuilt by `uv run dvc repro` from the files in `data/`. Figures are listed in the order they appear in the post.

| Post section | File | Script | DVC stage |
|---|---|---|---|
| Crypto, finding 1: recorded hacks accelerated | `fig08_defillama_hacks_per_month.png` | `code/v09_fig_defillama_monthly_hacks.py` | `fig_defillama_monthly_hacks` |
| Crypto, finding 2: most of the rise is smaller thefts | `fig11_defillama_small_hacks_per_month.png`, `fig12_defillama_small_hacks_stolen.png` | same | same |
| Crypto, finding 3: loss per hack did not accelerate | `fig09_defillama_avg_hack_size.png`, `fig10_defillama_total_stolen.png` | same | same |
| Crypto, finding 4: acceleration varies by exploit type | `fig36_defillama_hacks_by_type_accelerated_counts.png`, `fig37_defillama_hacks_by_type_not_accelerated_counts.png` | `code/v13_fig_defillama_hacks_by_type.py` | `fig_defillama_hacks_by_type` |
| Ransomware, finding 1: more groups posting victims | `fig35_ransomware_live_groups_per_quarter.png` | `code/ransomware/fig_ransomware_metr.py` | `fig_ransomware_metr` |
| Ransomware, finding 2: leak-site victims, no acceleration | `fig31_ransomware_live_per_month.png` | same | same |
| Ransomware, finding 3: confirmed attacks did not rise | `fig32_comparitech_ransomware_per_month.png` | same | same |
| Ransomware, finding 4: AI use in negotiations | `attacker_text/pangram_flags_over_time.png` | `code/attacker_text/analyze.py` | `attacker_text_analyze` |
| Appendix A: SlowMist | `fig13_tracker_slowmist.png` | `code/v10_fig_trackers_quarterly.py` | `fig_trackers_quarterly` |
| Appendix A: Comparitech crypto heists | `fig14_tracker_comparitech.png` | same | same |
| Appendix A: CertiK | `fig15_tracker_certik.png` | same | same |
| Appendix A: rekt.news | `fig16_tracker_rekt.png` | same | same |
| Appendix A: Web3 Is Going Great | `fig18_tracker_web3isgoinggreat.png` | same | same |
| Appendix A: BlockSec | `fig19_tracker_blocksec.png` | same | same |

Also produced by the same stages, but not in the post: `fig17_tracker_defihacklabs.png` (a seventh tracker, left out of appendix A because its counts depend on volunteer effort) and `attacker_text/pangram_flags_2025_2026_{quarterly,monthly}.png` (finer-grained views of the Pangram flags; too few 2026 messages to read much into).

Tables cited in the text but not drawn:

| Post section | File | Script |
|---|---|---|
| Appendix A verdicts (trend vs. old peak) | `data/processed/tracker_trend_check.csv` | `code/v11_tracker_trend_check.py` |
| Appendix B: every Pangram-flagged message | `data/processed/attacker_text/pangram_flagged_messages.csv` | built from `pangram_flagged_messages.md` (`code/attacker_text/analyze.py`) |
| Typographic markers (curly apostrophes, non-breaking hyphens) | `data/processed/attacker_text/typography_*.csv` | `code/attacker_text/typography.py` |
