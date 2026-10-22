"""Three tests of whether the 2026 rise in crypto hacks lines up with AI.

1. Difference-in-differences by cause, per tracker. Treated = code-bug exploits, control =
   stolen keys / phishing / infrastructure. Poisson GLM with month fixed effects (absorbs
   anything common to both causes: prices, tracker effort, detection services) and a
   code x post interaction. Quasi-Poisson scale for the standard errors. Also a pre-trend
   test: code x linear time on 2023-01..2025-12 only.
2. Changepoint: for each tracker's monthly code-bug series, a negative-binomial model with
   log-linear trend and a level shift at t0, profiled over t0. Reports the best t0 and the
   set of t0 within 2 log-likelihood units. Run on the keys series as a control, and on
   DeFiLlama's $1M-and-over series as a coverage-robust check. The full profiles and the
   fitted values of the best model are written out for plotting.
3. Event study: weekly DeFiLlama code-bug counts; for each AI release, the OLS slope over
   the W weeks after (weeks +1..+W) minus the OLS slope over the W weeks before (-W..-1),
   in hacks per week per week, averaged over releases. Run at W = 8 and W = 12 (column
   window_weeks in the outputs). A change in slope rather than a
   ratio of levels, so a release sitting on a pre-existing ramp scores zero. The release
   week itself is in neither window. Releases within 7 days merge.
   Placebo: the same statistic for 5,000 random date sets of equal size. Run on every row
   of ai_releases.csv (all, closed, open, gated), on the hand-curated subset in
   data/raw/ai_events_manual/relevant_releases.csv, on a hand-picked 2026 list
   (releases_2026.csv: OpenAI and Anthropic flagships; Kimi, DeepSeek, GLM, Qwen, MiniMax
   open flagships; with placebo dates drawn from 2026 only), on each manual event alone,
   and on coding-agent launches (coding_agent_releases.csv) as a set, one at a time, and
   restricted to OpenAI and Anthropic.
   Overlapping windows and the 2026 trend break are NOT handled; the placebo distribution
   is the only correction, and it is a weak one.

Inputs:  data/processed/defillama_hacks.csv, defillama_monthly.csv, other_sources_incidents_detail.csv,
         certik_dashboard_monthly.csv, ai_releases.csv,
         data/raw/ai_events_manual/events.csv, relevant_releases.csv, releases_2026.csv,
         coding_agent_releases.csv
Outputs: data/processed/did_cause_monthly.csv, did_cause_results.csv,
         changepoint_results.csv, changepoint_profiles.csv, changepoint_fits.csv,
         event_study_results.csv, event_study_profiles.csv

Run: uv run python -I code/v21_did_changepoint_events.py
"""
import pathlib

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
START, END = pd.Period("2023-01", "M"), pd.Period("2026-09", "M")
MONTHS = pd.period_range(START, END, freq="M")
PRE_END = pd.Period("2025-12", "M")
BREAKS = [pd.Period("2026-01", "M"), pd.Period("2026-03", "M")]
TRACKER_END = {"BlockSec": pd.Period("2026-06", "M")}  # Q3 incomplete at fetch time
RNG = np.random.default_rng(0)
N_PLACEBO = 5000
WINDOWS = [8, 12]  # weeks before and after an event; every set is run at each


def monthly_by_cause():
    """Return {tracker: DataFrame(month, code, keys)}."""
    out = {}
    h = pd.read_csv(OUT / "defillama_hacks.csv", parse_dates=["date"])
    h["month"] = h["date"].dt.to_period("M")
    out["DeFiLlama"] = pd.DataFrame({
        "code": h[h["group"] == "code_bug"].groupby("month").size(),
        "keys": h[h["group"] == "keys_people"].groupby("month").size(),
    })
    d = pd.read_csv(OUT / "other_sources_incidents_detail.csv", parse_dates=["date"])
    d["month"] = d["date"].dt.to_period("M")
    for src, name in [("SlowMist Hacked", "SlowMist"), ("Comparitech crypto heists", "Comparitech"),
                      ("BlockSec Security Incidents", "BlockSec")]:
        s = d[d["source"] == src]
        out[name] = pd.DataFrame({
            "code": s[s["category_group"] == "code_exploit"].groupby("month").size(),
            "keys": s[s["category_group"].str.startswith("keys_phishing_infra")].groupby("month").size(),
        })
    c = pd.read_csv(OUT / "certik_dashboard_monthly.csv")
    c["month"] = pd.PeriodIndex(c["month"], freq="M")
    c = c.set_index("month")
    out["CertiK"] = pd.DataFrame({
        "code": c["incidents_Exploit"],
        "keys": c["incidents_Private Key Compromise"] + c["incidents_Wallet Compromise"] + c["incidents_Phishing"],
    })
    for k, v in out.items():
        end = TRACKER_END.get(k, END)
        out[k] = v.reindex(pd.period_range(START, end, freq="M")).fillna(0).astype(int)
    return out


def did(df, brk):
    """Poisson GLM, month FE, code + code*post. Returns dict of estimates."""
    long = df.reset_index(names="month").melt(id_vars="month", var_name="cause", value_name="n")
    long["code"] = (long["cause"] == "code").astype(float)
    long["post"] = (long["month"] >= brk).astype(float)
    X = pd.get_dummies(long["month"].astype(str), prefix="m", dtype=float)
    X["code"] = long["code"]
    X["code_post"] = long["code"] * long["post"]
    res = sm.GLM(long["n"].astype(float), X, family=sm.families.Poisson()).fit(scale="X2")
    b, se = res.params["code_post"], res.bse["code_post"]
    pre = df[df.index < brk]
    post = df[df.index >= brk]
    return {
        "break": str(brk), "did_ratio": float(np.exp(b)), "ci_low": float(np.exp(b - 1.96 * se)),
        "ci_high": float(np.exp(b + 1.96 * se)), "p": float(res.pvalues["code_post"]),
        "pre_code_per_month": pre["code"].mean(), "pre_keys_per_month": pre["keys"].mean(),
        "post_code_per_month": post["code"].mean(), "post_keys_per_month": post["keys"].mean(),
    }


def pretrend(df):
    pre = df[df.index <= PRE_END]
    long = pre.reset_index(names="month").melt(id_vars="month", var_name="cause", value_name="n")
    long["code"] = (long["cause"] == "code").astype(float)
    t = (long["month"].apply(lambda p: p.ordinal) - START.ordinal) / 12.0
    X = pd.get_dummies(long["month"].astype(str), prefix="m", dtype=float)
    X["code"] = long["code"]
    X["code_t"] = long["code"] * t
    res = sm.GLM(long["n"].astype(float), X, family=sm.families.Poisson()).fit(scale="X2")
    b, se = res.params["code_t"], res.bse["code_t"]
    return {"pretrend_ratio_per_year": float(np.exp(b)), "pretrend_ci_low": float(np.exp(b - 1.96 * se)),
            "pretrend_ci_high": float(np.exp(b + 1.96 * se)), "pretrend_p": float(res.pvalues["code_t"])}


class FitDiverged(Exception):
    """The likelihood has no maximum: e.g. a kink two months before the end of a series whose
    last months are all zero, where the post-kink slope runs to minus infinity."""


def _nb_fit(y, X):
    """NB2 fit. Newton (the default) returns NaN on series that are mostly zeros, e.g. Bridge &
    Cross-Chain; then start from a Nelder-Mead solution instead."""
    r = sm.NegativeBinomial(y, X).fit(disp=0, maxiter=200)
    if np.isnan(r.llf):
        start = sm.NegativeBinomial(y, X).fit(disp=0, maxiter=2000, method="nm")
        if np.isnan(start.llf):
            raise FitDiverged
        r = sm.NegativeBinomial(y, X).fit(disp=0, maxiter=200, start_params=start.params)
        if np.isnan(r.llf):
            r = start
    return r


def _one_break(y, label, extra, name):
    """NB2 with log-linear trend plus one break regressor extra(t_years, t0_years), profiled
    over t0 in 2024-07..2026-07. `name` is the column for exp(break coefficient). A t0 whose
    likelihood diverges (FitDiverged) gets NaN in the profile and is skipped.

    Returns (summary dict, profile DataFrame, fitted DataFrame)."""
    y = y.astype(float)
    t = np.arange(len(y)) / 12.0
    X0 = sm.add_constant(t)
    ll0 = _nb_fit(y.values, X0).llf
    rows, fits = [], {}
    for t0 in pd.period_range("2024-07", "2026-07", freq="M"):
        if t0 not in y.index:
            continue
        X = np.column_stack([X0, extra(t, y.index.get_loc(t0) / 12.0)])
        try:
            r = _nb_fit(y.values, X)
        except FitDiverged:  # recorded as an unfitted month; it cannot be the best t0
            rows.append({"series": label, "t0": str(t0), "llf": float("nan"), name: float("nan"),
                         "trend_ratio_per_year": float("nan")})
            continue
        rows.append({"series": label, "t0": str(t0), "llf": r.llf, name: float(np.exp(r.params[2])),
                     "trend_ratio_per_year": float(np.exp(r.params[1]))})
        fits[str(t0)] = r.predict(X)
    prof = pd.DataFrame(rows)
    prof["llf_rel"] = prof["llf"] - prof["llf"].max()
    best = prof.loc[prof["llf"].idxmax()]
    within2 = prof[prof["llf_rel"] >= -2]["t0"].tolist()
    summary = {"series": label, "best_t0": best["t0"], name: best[name],
               "trend_ratio_per_year": best["trend_ratio_per_year"], "llf": best["llf"],
               "lr_vs_no_break": 2 * (best["llf"] - ll0),
               "t0_within_2ll": f"{within2[0]}..{within2[-1]}" if within2 else ""}
    fit = pd.DataFrame({"series": label, "month": y.index.astype(str), "observed": y.values,
                        "fitted": fits[best["t0"]]})
    return summary, prof, fit


def changepoint(y, label):
    """Step: level shift at t0 (rate multiplies by shift_ratio, slope unchanged)."""
    return _one_break(y, label, lambda t, t0: (t >= t0).astype(float), "shift_ratio")


def kink(y, label):
    """Acceleration: slope change at t0, continuous there. The growth factor per year is
    trend_ratio_per_year before t0 and trend_ratio_per_year * kink_ratio_per_year after."""
    return _one_break(y, label, lambda t, t0: np.maximum(0.0, t - t0), "kink_ratio_per_year")


def weekly_code_bug():
    h = pd.read_csv(OUT / "defillama_hacks.csv", parse_dates=["date"])
    h = h[h["group"] == "code_bug"]
    w = h.groupby(h["date"].dt.to_period("W-SUN")).size()
    weeks = pd.period_range("2022-07", END.end_time, freq="W-SUN")
    return w.reindex(weeks).fillna(0).astype(int)


def merge_dates(dates, min_gap_days=7):
    kept = []
    for d in sorted(dates):
        if not kept or (d - kept[-1]).days >= min_gap_days:
            kept.append(d)
    return kept


def window_counts(w, d, win):
    """Weekly counts from win weeks before to win weeks after the event week (inclusive)."""
    i = w.index.get_loc(pd.Period(d, "W-SUN"))
    return w.iloc[i - win:i + win + 1].values


def slope_weights(win):
    """OLS slope of win equally spaced points = weights @ y."""
    x = np.arange(win) - (win - 1) / 2
    return x / (x ** 2).sum()


def slopes(c, win):
    """(pre slope, post slope) of a window of weekly counts, in hacks per week per week.
    Pre is weeks -win..-1, post is +1..+win; the event week is in neither."""
    sw = slope_weights(win)
    return float(sw @ c[:win]), float(sw @ c[win + 1:])


def event_stat(w, dates, win):
    """Mean over events of post slope minus pre slope."""
    changes = []
    for d in dates:
        pre, post = slopes(window_counts(w, d, win), win)
        changes.append(post - pre)
    return float(np.mean(changes))


def event_study(w, dates, label, win, placebo_lo="2023-03-01"):
    """placebo_lo: random placebo dates are drawn from placebo_lo to the end of the window.
    For sets restricted to 2026, pass 2026-01-01 so the placebo shares the events' period."""
    dates = merge_dates([pd.Timestamp(d) for d in dates])
    lo, hi = pd.Timestamp(placebo_lo), (END.end_time - pd.Timedelta(weeks=win + 1)).normalize()
    dates = [d for d in dates if lo <= d <= hi]
    obs = event_stat(w, dates, win)
    span_days = (hi - lo).days
    placebo = np.array([
        event_stat(w, [lo + pd.Timedelta(days=int(x)) for x in RNG.integers(0, span_days, size=len(dates))], win)
        for _ in range(N_PLACEBO)
    ])
    prof = np.mean([window_counts(w, d, win) for d in dates], axis=0)
    profile = pd.DataFrame({"event_set": label, "window_weeks": win, "rel_week": np.arange(-win, win + 1),
                            "mean_hacks_per_week": prof, "scaled_to_pre_mean": prof / prof[:win].mean()})
    pre_slope, post_slope = slopes(prof, win)  # OLS is linear, so slopes of the mean profile = mean of slopes
    result = {"event_set": label, "window_weeks": win, "n_events": len(dates), "slope_pre": pre_slope,
              "slope_post": post_slope, "slope_change": obs, "placebo_p_one_sided": float((placebo >= obs).mean()),
              "placebo_slope_change_p05": float(np.quantile(placebo, 0.05)),
              "placebo_slope_change_p95": float(np.quantile(placebo, 0.95))}
    return result, profile


def main():
    by = monthly_by_cause()
    long = pd.concat([v.assign(tracker=k) for k, v in by.items()]).reset_index(names="month")
    long.to_csv(OUT / "did_cause_monthly.csv", index=False)

    rows = []
    for name, df in by.items():
        pt = pretrend(df)
        for brk in BREAKS:
            rows.append({"tracker": name, **did(df, brk), **pt})
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "did_cause_results.csv", index=False)

    series = []
    for name, df in by.items():
        series += [(df["code"], f"{name} code"), (df["keys"], f"{name} keys")]
    big = pd.read_csv(OUT / "defillama_monthly.csv", index_col="period")
    big.index = pd.PeriodIndex(big.index, freq="M")
    big = big.reindex(MONTHS).fillna(0)
    series += [(big["n_big_code_bug"], "DeFiLlama code >= $1M"), (big["n_big_keys_people"], "DeFiLlama keys >= $1M")]
    cps, profs, fits = [], [], []
    for y, label in series:
        s, p, f = changepoint(y, label)
        cps.append(s)
        profs.append(p)
        fits.append(f)
    cp = pd.DataFrame(cps)
    cp.to_csv(OUT / "changepoint_results.csv", index=False)
    pd.concat(profs).to_csv(OUT / "changepoint_profiles.csv", index=False)
    pd.concat(fits).to_csv(OUT / "changepoint_fits.csv", index=False)

    rel = pd.read_csv(OUT / "ai_releases.csv", parse_dates=["date"])
    cur = pd.read_csv(RAW / "ai_events_manual" / "relevant_releases.csv", parse_dates=["date"])
    man = pd.read_csv(RAW / "ai_events_manual" / "events.csv", parse_dates=["date"])
    agents = pd.read_csv(RAW / "ai_events_manual" / "coding_agent_releases.csv", parse_dates=["date"])
    w = weekly_code_bug()
    sets = [
        ("all rows", rel["date"]),
        ("all rows: closed", rel[rel["tier"] == "closed_major"]["date"]),
        ("all rows: open weights", rel[rel["tier"] == "open_major"]["date"]),
        ("all rows: gated", rel[rel["tier"] == "gated"]["date"]),
        ("curated", cur["date"]),
        ("curated: closed", cur[cur["tier"] == "closed"]["date"]),
        ("curated: open weights", cur[cur["tier"] == "open"]["date"]),
        ("curated: gated", cur[cur["tier"] == "gated"]["date"]),
    ] + [(f"manual: {r['event'][:50]}", [r["date"]]) for _, r in man.iterrows()]
    sets += [("coding agents", agents["date"])] + [(f"agent: {r['short']}", [r["date"]]) for _, r in agents.iterrows()]
    oa = agents[agents["org"].isin(["OpenAI", "Anthropic"])]
    sets += [("agents: OpenAI+Anthropic", oa["date"]), ("agents: Anthropic", oa[oa["org"] == "Anthropic"]["date"]),
             ("agents: OpenAI", oa[oa["org"] == "OpenAI"]["date"])]
    sets = [(label, dates, "2023-03-01") for label, dates in sets]
    y26 = pd.read_csv(RAW / "ai_events_manual" / "releases_2026.csv", parse_dates=["date"])
    sets += [(f"2026: {tier}", y26[y26["tier"] == tier]["date"], "2026-01-01") for tier in ["closed", "open", "gated"]]
    results, profiles = [], []
    for win in WINDOWS:
        for label, dates, placebo_lo in sets:
            r, p = event_study(w, dates, label, win, placebo_lo)
            results.append(r)
            profiles.append(p)
    es = pd.DataFrame(results)
    es.to_csv(OUT / "event_study_results.csv", index=False)
    pd.concat(profiles).to_csv(OUT / "event_study_profiles.csv", index=False)

    with pd.option_context("display.width", 250, "display.max_columns", 30, "display.float_format", "{:,.3f}".format):
        print("== DiD by cause (ratio = post/pre change in code relative to keys)")
        print(res[["tracker", "break", "did_ratio", "ci_low", "ci_high", "p", "pre_code_per_month",
                   "post_code_per_month", "pre_keys_per_month", "post_keys_per_month",
                   "pretrend_ratio_per_year", "pretrend_ci_low", "pretrend_ci_high"]].to_string(index=False))
        print("\n== Changepoint (NB with trend + level shift)")
        print(cp.to_string(index=False))
        print("\n== Event study (DeFiLlama code-bug, weekly; slope change in hacks/week per week; 8-week windows)")
        print(es[es["window_weeks"] == 8].drop(columns="window_weeks").to_string(index=False))


if __name__ == "__main__":
    main()
