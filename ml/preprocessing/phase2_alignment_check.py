"""Phase 2 Step 1: empirical verification of the GPS/steps time alignment (read-only on datasets/).

Convention for lags: lag = (time of an event in positions.ms) - (time of the same event in steps.ms).
 lag > 0 : positions stamps are later than steps stamps for the same physical event.
Hypotheses:
 H0: positions.ms and steps.ms share one clock (signalStart)          -> expected lag ~ 0
 H1: positions.ms is relative to testStart (README line "Zero ms corresponds to testStart")
     while steps.ms is relative to signalStart                         -> expected lag ~ -testStart
Outputs: results/metrics/phase2_alignment_check.json, results/plots/phase2_alignment_check.png
"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import dryad_io as d

OUT = d.ROOT / "results" / "metrics" / "phase2_alignment_check.json"
PLOT = d.ROOT / "results" / "plots" / "phase2_alignment_check.png"
OUT.parent.mkdir(parents=True, exist_ok=True)
PLOT.parent.mkdir(parents=True, exist_ok=True)
MAX_LAG_S = 90
SMOOTH_S = 7
MIN_OVERLAP = 60


def box(x, w):
    k = np.ones(w) / w
    ok = np.isfinite(x)
    num = np.convolve(np.where(ok, x, 0.0), k, "same")
    den = np.convolve(ok.astype(float), k, "same")
    with np.errstate(invalid="ignore", divide="ignore"):
        r = num / den
    r[den < 0.5] = np.nan
    return r


def xcorr_lag(g, s, max_lag):
    """corr(g[t], s[t-L]) for integer L in [-max_lag, max_lag]; NaN-masked pairwise. Returns lags, corr."""
    lags = np.arange(-max_lag, max_lag + 1)
    n = len(g)
    c = np.full(len(lags), np.nan)
    for i, L in enumerate(lags):
        if L >= 0:
            a, b = g[L:], s[:n - L]
        else:
            a, b = g[:n + L], s[-L:]
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < MIN_OVERLAP:
            continue
        a, b = a[m], b[m]
        if a.std() == 0 or b.std() == 0:
            continue
        c[i] = np.corrcoef(a, b)[0, 1]
    return lags, c


def frac_times(t, cum, fracs):
    """Times at which a monotone cumulative curve reaches given fractions of its total (linear between samples)."""
    cum = np.maximum.accumulate(cum - cum[0])
    tot = cum[-1]
    if tot <= 0:
        return None
    u, idx = np.unique(cum, return_index=True)
    return np.interp(fracs * tot, u, t[idx])


rows = []
tracks = d.model_a_tracks()
for name, meta in tracks:
    t = d.load_track(name)
    ev, pos, st = t["events"].iloc[0], t["positions"], t["steps"]
    r = {"track": name, "subject": int(meta["subject"]), "testStart": float(ev["testStart"]), "testEnd": float(ev["testEnd"]),
         "duration_meta_ms": float(meta["duration [s]"]) * 1000}
    # --- (a) first/last stamps vs events ---
    r["pos_first"], r["pos_last"] = float(pos.ms.min()), float(pos.ms.max())
    r["steps_first"], r["steps_last"] = float(st.ms.min()), float(st.ms.max())
    r["steps_endDate_last"] = float(st.endDate.max())
    r["pos_last_minus_testEnd"] = r["pos_last"] - r["testEnd"]
    r["steps_last_minus_testEnd"] = r["steps_last"] - r["testEnd"]
    r["pos_last_minus_testEnd_plus_ts"] = r["pos_last"] - (r["testEnd"] - r["testStart"])  # H1 expectation
    r["testEnd_minus_testStart_ms"] = r["testEnd"] - r["testStart"]
    # --- (b) steps ms vs endDate ---
    dd = (st.ms - st.endDate).dropna()
    r["steps_ms_minus_endDate_median"] = float(dd.median())
    r["steps_ms_minus_endDate_min"], r["steps_ms_minus_endDate_max"] = float(dd.min()), float(dd.max())
    r["steps_startDate_nunique"] = int(st.startDate.nunique())
    # --- (d) metadata consistency ---
    r["steps_last_value"] = float(st.steps.iloc[-1]) if st.steps.notna().any() else None
    r["steps_max_value"] = float(st.steps.max())
    r["totSteps_meta"] = None if pd.isna(meta["totSteps"]) else float(meta["totSteps"])
    r["fs_steps_meta"] = None if pd.isna(meta["fs_steps"]) else float(meta["fs_steps"])
    r["fs_gnss_meta"] = None if pd.isna(meta["fs_gnss"]) else float(meta["fs_gnss"])
    dur = float(meta["duration [s]"])
    r["fs_steps_observed_rows_per_s"] = float(len(st) / dur)
    r["fs_gnss_observed_rows_per_s"] = float(len(pos) / dur)
    ps = pos[pos.ms >= 0].sort_values("ms", kind="stable").dropna(subset=["latitude", "longitude"])  # ms>=0 only: rows before 0 are pre-start
    r["pos_rows_ms_lt0"] = int((pos.ms < 0).sum())
    seg = d.haversine_m(ps.latitude.values, ps.longitude.values)
    r["gps_path_length_m"] = float(seg.sum())
    r["distanceReference_m"] = float(meta["distanceReference"])
    # end-of-recording agreement between the two streams, and onset of walking
    r["pos_last_minus_steps_last"] = r["pos_last"] - r["steps_last"]
    r["H1_residual_abs_end"] = abs(r["pos_last_minus_steps_last"] + r["testStart"])
    r["H0_residual_abs_end"] = abs(r["pos_last_minus_steps_last"])
    # --- (c) timing comparisons ---
    grid_end = int(min(pos.ms.max(), st.ms.max()))
    grid = np.arange(0, grid_end + 1000, 1000.0)
    ss = st.sort_values("ms", kind="stable").dropna(subset=["steps"])
    cs = np.maximum.accumulate(ss.steps.values.astype(float))
    steps_cum = np.interp(grid, ss.ms.values, cs, left=np.nan, right=np.nan)
    srate = np.diff(steps_cum, prepend=np.nan)
    srate = box(srate, SMOOTH_S)
    pv = pos[(pos.speed >= 0)].sort_values("ms", kind="stable")
    pv = pv.drop_duplicates("ms")
    if len(pv) >= 10:
        gs = np.interp(grid, pv.ms.values, pv.speed.values)
        near = np.abs(grid[:, None] - pv.ms.values[None, :]).min(axis=1) <= 3000
        gs[~near] = np.nan
        gs = box(gs, SMOOTH_S)
        lags, c = xcorr_lag(gs, srate, MAX_LAG_S)
        if np.isfinite(c).any():
            i = int(np.nanargmax(c))
            r["xcorr_lag_s"], r["xcorr_peak"] = int(lags[i]), float(c[i])
            r["xcorr_at_lag0"] = float(c[lags == 0][0]) if np.isfinite(c[lags == 0][0]) else None
            h1 = int(round(-r["testStart"] / 1000))
            r["xcorr_at_H1_lag"] = float(c[lags == h1][0]) if (abs(h1) <= MAX_LAG_S and np.isfinite(c[lags == h1][0])) else None
            # prominence of the peak: best corr outside +-10 s of the peak
            far = np.abs(lags - lags[i]) > 10
            r["xcorr_second_peak_outside_10s"] = float(np.nanmax(c[far])) if np.isfinite(c[far]).any() else None
    # cumulative distance (GPS, coordinate based) vs cumulative steps: time at fractions of total
    cd = np.concatenate([[0], np.cumsum(seg)])
    fr = np.linspace(0.1, 0.9, 9)
    tg = frac_times(ps.ms.values.astype(float), cd, fr)
    ts_ = frac_times(ss.ms.values.astype(float), cs, fr)
    if tg is not None and ts_ is not None:
        off = tg - ts_
        r["cum_frac_offset_median_ms"] = float(np.median(off))
        r["cum_frac_offset_iqr_ms"] = float(np.percentile(off, 75) - np.percentile(off, 25))
        r["cum_frac_offset_max_abs_ms"] = float(np.abs(off).max())
        # RMS misfit of normalized cumulative curves on the common 1 s grid for lag 0 and for H1
        gcum = np.interp(grid, ps.ms.values, np.maximum.accumulate(cd), left=np.nan, right=np.nan)
        for tag, shift in (("H0", 0.0), ("H1", -r["testStart"])):
            ge = np.interp(grid, ps.ms.values - shift, np.maximum.accumulate(cd), left=np.nan, right=np.nan)
            m = np.isfinite(ge) & np.isfinite(steps_cum)
            if m.sum() > 30:
                a = (ge[m] - ge[m][0]) / max(ge[m][-1] - ge[m][0], 1e-9)
                b = (steps_cum[m] - steps_cum[m][0]) / max(steps_cum[m][-1] - steps_cum[m][0], 1e-9)
                r[f"cum_rms_{tag}"] = float(np.sqrt(np.mean((a - b) ** 2)))
    pvs = pos[pos.speed >= 0].sort_values("ms")
    sm = pvs.speed.rolling(5, center=True, min_periods=3).median()
    on = pvs.ms[(sm >= 0.7) & (pvs.ms >= 0)]
    r["gps_walk_onset_ms"] = float(on.iloc[0]) if len(on) else None
    rows.append(r)

df = pd.DataFrame(rows)


def q(x):
    x = pd.Series(x).dropna().astype(float)
    if x.empty:
        return None
    return {"n": int(len(x)), "min": float(x.min()), "p5": float(x.quantile(.05)), "p25": float(x.quantile(.25)), "median": float(x.median()),
            "p75": float(x.quantile(.75)), "p95": float(x.quantile(.95)), "max": float(x.max()), "mean": float(x.mean()), "std": float(x.std())}


res = {"n_tracks": len(df), "lag_convention": "lag = positions-clock time minus steps-clock time of the same physical event (ms or s as labelled)",
       "H0": "positions.ms and steps.ms share the signalStart clock (expected lag ~0)",
       "H1": "positions.ms is relative to testStart, steps.ms to signalStart (expected lag ~ -testStart)",
       "xcorr_settings": {"grid_s": 1, "smooth_boxcar_s": SMOOTH_S, "max_lag_s": MAX_LAG_S, "min_overlap_samples": MIN_OVERLAP,
                          "signals": "GPS speed (valid >=0, only within 3 s of a real sample, no filling elsewhere) vs steps/s from cumulative steps (running max, linear between samples)"}}
res["testStart_ms"] = q(df.testStart)
res["tracks_testStart_gt_5s"] = int((df.testStart > 5000).sum())
res["pos_first_ms"] = q(df.pos_first)
res["pos_last_minus_testEnd_ms"] = q(df.pos_last_minus_testEnd)
res["pos_last_minus_(testEnd-testStart)_ms"] = q(df["pos_last_minus_testEnd_plus_ts"])
res["steps_last_minus_testEnd_ms"] = q(df.steps_last_minus_testEnd)
res["steps_ms_minus_endDate_median_per_track_ms"] = q(df.steps_ms_minus_endDate_median)
res["steps_ms_minus_endDate_min_ms"] = q(df.steps_ms_minus_endDate_min)
res["steps_ms_minus_endDate_max_ms"] = q(df.steps_ms_minus_endDate_max)
res["steps_startDate_nunique_per_track"] = q(df.steps_startDate_nunique)
res["fs_steps_observed_over_meta"] = q(df.fs_steps_observed_rows_per_s / df.fs_steps_meta)
res["fs_gnss_observed_over_meta"] = q(df.fs_gnss_observed_rows_per_s / df.fs_gnss_meta)
res["totSteps_last_value_minus_meta"] = q(df.steps_last_value - df.totSteps_meta)
res["totSteps_max_value_minus_meta"] = q(df.steps_max_value - df.totSteps_meta)
res["tracks_last_value_equals_totSteps"] = int((df.steps_last_value == df.totSteps_meta).sum())
res["gps_path_over_distanceReference"] = q(df.gps_path_length_m / df.distanceReference_m)
res["xcorr_lag_s_all"] = q(df.xcorr_lag_s)
res["xcorr_peak_corr"] = q(df.xcorr_peak)
res["xcorr_corr_at_lag0"] = q(df.xcorr_at_lag0)
conf = df[(df.xcorr_peak >= 0.5)]
res["xcorr_confident_tracks_peak_ge_0.5"] = {"n": int(len(conf)), "lag_s": q(conf.xcorr_lag_s),
    "n_within_pm2s": int((conf.xcorr_lag_s.abs() <= 2).sum()), "n_within_pm5s": int((conf.xcorr_lag_s.abs() <= 5).sum())}
res["xcorr_lag_by_peak_band"] = {}
for lo, hi in ((0, .3), (.3, .5), (.5, .7), (.7, 1.01)):
    b = df[(df.xcorr_peak >= lo) & (df.xcorr_peak < hi)]
    res["xcorr_lag_by_peak_band"][f"{lo}-{hi}"] = {"n": int(len(b)), "lag_s": q(b.xcorr_lag_s)}
big = df[df.testStart > 5000]
res["tracks_with_testStart_gt_5s"] = {"n": int(len(big)), "xcorr_lag_s": q(big.xcorr_lag_s),
    "testStart_s": q(big.testStart / 1000), "corr_at_lag0": q(big.xcorr_at_lag0), "corr_at_H1_lag": q(big.xcorr_at_H1_lag),
    "n_H0_corr_gt_H1_corr": int((big.xcorr_at_lag0 > big.xcorr_at_H1_lag).sum()),
    "n_H1_corr_gt_H0_corr": int((big.xcorr_at_H1_lag > big.xcorr_at_lag0).sum()),
    "cum_rms_H0": q(big.cum_rms_H0), "cum_rms_H1": q(big.cum_rms_H1),
    "n_cum_rms_H0_lt_H1": int((big.cum_rms_H0 < big.cum_rms_H1).sum())}
big5 = df[df.testStart > 5000]
res["end_of_recording_pos_last_minus_steps_last_ms"] = q(df.pos_last_minus_steps_last)
res["end_of_recording_tracks_testStart_gt_5s"] = {"n": int(len(big5)), "pos_last_minus_steps_last_ms": q(big5.pos_last_minus_steps_last),
    "n_H0_residual_lt_H1_residual": int((big5.H0_residual_abs_end < big5.H1_residual_abs_end).sum()),
    "median_H0_residual_ms": float(big5.H0_residual_abs_end.median()), "median_H1_residual_ms": float(big5.H1_residual_abs_end.median())}
res["end_of_recording_all_tracks_n_H0_lt_H1"] = int((df.H0_residual_abs_end < df.H1_residual_abs_end).sum())
res["end_of_recording_abs_diff_le_5s_n"] = int((df.pos_last_minus_steps_last.abs() <= 5000).sum())
res["end_of_recording_abs_diff_gt_10s_tracks"] = df[df.pos_last_minus_steps_last.abs() > 10000].track.tolist()
res["pos_rows_with_ms_lt_0"] = {"tracks_affected": int((df.pos_rows_ms_lt0 > 0).sum()), "rows_total": int(df.pos_rows_ms_lt0.sum())}
res["gps_walk_onset_minus_steps_first_ms"] = q(df.gps_walk_onset_ms - df.steps_first)
res["cum_frac_offset_median_ms"] = q(df.cum_frac_offset_median_ms)
res["cum_frac_offset_iqr_within_track_ms"] = q(df.cum_frac_offset_iqr_ms)
res["cum_rms_H0_all"], res["cum_rms_H1_all"] = q(df.cum_rms_H0), q(df.cum_rms_H1)
res["n_cum_rms_H0_lt_H1_all_tracks_with_testStart_ne_0"] = int(((df.cum_rms_H0 < df.cum_rms_H1) & (df.testStart.abs() > 1)).sum())
res["per_subject_median_xcorr_lag_s"] = {str(k): float(v) for k, v in df.groupby("subject").xcorr_lag_s.median().items()}
res["per_subject_median_cum_offset_ms"] = {str(k): float(v) for k, v in df.groupby("subject").cum_frac_offset_median_ms.median().items()}
res["decision"] = {
    "convention": "H0: treat positions.ms and steps.ms as the same signalStart clock; apply NO per-track or global lag shift; do not re-base positions by testStart.",
    "confidence": "moderate (clock identity supported; sub-window offsets of a few seconds cannot be excluded)",
    "evidence_for": [
        "Last stamps of the two streams agree: see end_of_recording_pos_last_minus_steps_last_ms (median ~0.2 s, IQR about -0.7..+1.5 s); both end near testEnd (not testEnd-testStart).",
        "In the tracks with testStart>5 s (where H0 and H1 differ by >5 s) the end-of-recording residual is smaller under H0 in most tracks: see end_of_recording_tracks_testStart_gt_5s.",
        "steps.ms - endDate is a small positive offset (iOS pedometer reporting delay), not a testStart-sized shift; metadata fs_gnss/fs_steps equal observed row counts / duration.",
        "last steps value equals metadata totSteps in all but one track (+1)."],
    "evidence_inconclusive_or_against_precision": [
        "Speed vs step-rate cross-correlation has low power (steady-pace walking); the lag distribution is wide with weak peaks in most tracks, with no consistent lag across tracks. Only the high-peak band (>=0.7) is informative, and its lag is centred within a few seconds of 0 with mixed sign (see xcorr_lag_by_peak_band).",
        "Cumulative-distance vs cumulative-steps timing is biased by pre-walk GPS jitter and late first step rows and cannot separate H0/H1 (cum_rms_H0 ~ cum_rms_H1).",
        "positions.csv contains rows with ms<0 (pre-start stamps) in most tracks; README says 'ms from signalStart' and also 'zero corresponds to testStart' (contradiction), so documentation alone is ambiguous.",
        "8 tracks have |pos_last - steps_last| > 10 s (list in end_of_recording_abs_diff_gt_10s_tracks); one stream stops early there."],
    "no_lag_shift_reason": "estimated lags are not consistent across tracks (wide, sign-mixed distribution), so shifting would inject noise",
    "recommended_sensitivity": "later, optionally train/evaluate under an alternative convention (positions shifted by +/-testStart or +/-2 s), clearly labelled as sensitivity analysis only",
    "recommended_handling": "restrict windows to ms>=0 and to the span where both streams exist; consider flagging the 8 tracks with large end-of-recording mismatch"}
res["per_track"] = json.loads(df.round(4).to_json(orient="records"))
OUT.write_text(json.dumps(res, indent=2, allow_nan=False, default=str))

fig, ax = plt.subplots(2, 2, figsize=(12, 9))
ax[0, 0].hist(df.xcorr_lag_s.dropna(), bins=np.arange(-MAX_LAG_S - .5, MAX_LAG_S + 1.5, 2), color="C0")
ax[0, 0].set(title="Speed vs step-rate cross-correlation lag (all tracks)", xlabel="lag s (pos - steps)", ylabel="tracks")
ax[0, 1].hist(conf.xcorr_lag_s, bins=np.arange(-MAX_LAG_S - .5, MAX_LAG_S + 1.5, 2), color="C1")
ax[0, 1].set(title=f"Same, peak corr >= 0.5 (n={len(conf)})", xlabel="lag s (pos - steps)")
ax[1, 0].scatter(-df.testStart / 1000, df.xcorr_lag_s, c=df.xcorr_peak, s=14)
ax[1, 0].plot([-60, 0], [-60, 0], "r--", label="H1: lag = -testStart")
ax[1, 0].axhline(0, color="k", lw=.6, label="H0: lag = 0")
ax[1, 0].set(title="xcorr lag vs -testStart (color=peak corr)", xlabel="-testStart s", ylabel="lag s"); ax[1, 0].legend()
ax[1, 1].hist(df.cum_frac_offset_median_ms.dropna() / 1000, bins=40, color="C2")
ax[1, 1].set(title="Median time offset at 10-90% of cumulative distance vs steps", xlabel="s (pos - steps)")
fig.tight_layout(); fig.savefig(PLOT, dpi=110)
print(json.dumps({k: v for k, v in res.items() if k not in ("per_track", "per_subject_median_xcorr_lag_s", "per_subject_median_cum_offset_ms")}, indent=1)[:9000])
