"""Phase 2 Steps 3-4: GPS cleaning + 5 s windowing for Model A (GPS-only step estimator). Read-only on datasets/.
Run from anywhere: python ml/preprocessing/phase2_build_windows.py

Cleaning rules (per track, applied in this order; all counted):
 C1 drop rows with non-finite ms/latitude/longitude.
 C2 stable-sort by ms; drop rows identical in every column (exact duplicates). Rows sharing ms but differing in value are kept.
 C3 drop fixes with confInterval NaN, <0 or > CONF_MAX_M (poor/invalid horizontal accuracy, e.g. 1414 m, 4002 m).
 C4 drop teleport fixes: implied speed dist/max(dt,1 s) to BOTH neighbours (one neighbour at edges) > TELEPORT_MPS; iterated.
 Speed: GPS speed is valid only if finite and >= 0 (-1 and NaN are invalid; never used, never replaced). A fix with invalid speed
        but valid position stays a position fix (used for displacement/path). derived_speed_mps = path/covered duration is derived
        from real fixes only and labelled as such.
 Gaps: gap = interval between consecutive kept fixes > GAP_MAX_S. Windows overlapping a gap are excluded (no interpolation).
Windowing: non-overlapping 5 s windows from max(testStart,0) up to min(testEnd, last steps ms) (alignment decision H0: no shift).
 Target = cum(T_end)-cum(T_start); cum(T)=running max of steps over rows with ms<=T, 0 before first row (monotonicity decision).
Window exclusion order: long_gap_overlap, no_fix, no_valid_speed.
"""
import json
import numpy as np
import pandas as pd
import dryad_io as d

GAP_MAX_S = 10.0
CONF_MAX_M = 50.0
TELEPORT_MPS = 10.0
WIN_MS = 5000.0
MIN_FIXES = 1
BINS = [0, 0.5, 1.0, 1.5, 2.0, np.inf]
LABELS = ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", ">2.0"]
OUT_CSV = d.ROOT / "datasets" / "dryad" / "processed" / "windows_5s.csv"
MET = d.ROOT / "results" / "metrics"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    la1, la2, lo1, lo2 = map(np.radians, (lat1, lat2, lon1, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def teleport_drop(p):
    """Iteratively drop fixes whose implied speed exceeds TELEPORT_MPS to all existing neighbours. Returns (kept df, n_dropped)."""
    n0 = len(p)
    p = p.reset_index(drop=True)
    while len(p) > 2:
        dist = hav(p.latitude.values[:-1], p.longitude.values[:-1], p.latitude.values[1:], p.longitude.values[1:])
        dt = np.maximum(np.diff(p.ms.values) / 1000.0, 1.0)
        v = dist / dt
        bad_link = v > TELEPORT_MPS
        left = np.r_[True, bad_link]    # link to previous is bad (or no previous)
        right = np.r_[bad_link, True]   # link to next is bad (or no next)
        bad = left & right & (np.r_[False, bad_link] | np.r_[bad_link, False])
        if not bad.any():
            break
        # drop only the worst offender per pass to avoid cascading deletions
        score = np.r_[0, v] + np.r_[v, 0]
        score[~bad] = -1
        p = p.drop(index=int(np.argmax(score))).reset_index(drop=True)
    return p, n0 - len(p)


def cum_fn(st):
    st = st.sort_values("ms", kind="stable")
    ms, rm = st.ms.values.astype(float), np.maximum.accumulate(st.steps.values.astype(float))

    def f(T):
        i = np.searchsorted(ms, T, side="right") - 1
        return 0.0 if i < 0 else float(rm[i])
    return f


def bin_label(v):
    if v is None or not np.isfinite(v):
        return "unknown"
    return LABELS[int(np.searchsorted(BINS, v, side="right") - 1)]


md = d.metadata().set_index("testName")
rows, track_rows, win_excl_rows, recon = [], [], [], []
tot = dict(raw_rows=0, c1_nonfinite=0, c2_dup=0, same_ms_diff_value_kept=0, c3_conf=0, c4_teleport=0, kept=0,
           speed_minus1=0, speed_nan=0, speed_invalid_kept_fixes=0, tracks_nonmonotonic_ms=0, tracks_with_dup=0)
gap_counts, gap_sparse, gap_dense = [], [], []
for name, meta in d.model_a_tracks():
    t = d.load_track(name)
    ev, st = t["events"].iloc[0], t["steps"]
    p0 = t["positions"]
    n_raw = len(p0)
    tot["raw_rows"] += n_raw
    sp = pd.to_numeric(p0.speed, errors="coerce")
    tot["speed_minus1"] += int((sp == -1).sum()); tot["speed_nan"] += int(sp.isna().sum())
    nonmono = bool((np.diff(p0.ms.values) < 0).any())
    tot["tracks_nonmonotonic_ms"] += nonmono
    p = p0[np.isfinite(p0[["ms", "latitude", "longitude"]].values).all(axis=1)]
    c1 = n_raw - len(p)
    p = p.sort_values("ms", kind="stable")
    n_before = len(p)
    p = p.drop_duplicates()
    c2 = n_before - len(p)
    tot["tracks_with_dup"] += c2 > 0
    same_ms = int(p.ms.duplicated().sum())
    conf = p.confInterval
    okc = conf.notna() & (conf >= 0) & (conf <= CONF_MAX_M)
    c3 = int((~okc).sum())
    p = p[okc]
    p, c4 = teleport_drop(p)
    sp = pd.to_numeric(p.speed, errors="coerce")
    p = p.assign(speed_ok=(sp.notna() & (sp >= 0)).values)
    tot["c1_nonfinite"] += c1; tot["c2_dup"] += c2; tot["same_ms_diff_value_kept"] += same_ms; tot["c3_conf"] += c3
    tot["c4_teleport"] += c4; tot["kept"] += len(p); tot["speed_invalid_kept_fixes"] += int((~p.speed_ok).sum())
    ms = p.ms.values.astype(float)
    gaps = np.diff(ms) / 1000.0
    gi = np.where(gaps > GAP_MAX_S)[0]
    glist = [(ms[i], ms[i + 1]) for i in gi]
    gap_counts.extend(gaps.tolist())
    sparse = float(np.median(gaps)) > 2.0 if len(gaps) else False
    (gap_sparse if sparse else gap_dense).extend(gaps.tolist())

    ts, te = float(ev.testStart), float(ev.testEnd)
    steps_last = float(st.ms.max())
    start = max(ts, 0.0)
    end = min(te, steps_last)
    nwin = int(np.floor((end - start) / WIN_MS))
    cum = cum_fn(st)
    meta_speed = float(meta["average_walking_speed"])
    # path vs reference inside the cleaned test period
    inside = p[(p.ms >= ts) & (p.ms <= te)]
    path_c = float(hav(inside.latitude.values[:-1], inside.longitude.values[:-1], inside.latitude.values[1:], inside.longitude.values[1:]).sum()) if len(inside) > 1 else 0.0
    ref = float(meta["distanceReference"])
    kept_inc = 0.0
    all_inc = cum(start + nwin * WIN_MS) - cum(start)
    n_ex = {"long_gap_overlap": 0, "no_fix": 0, "no_valid_speed": 0}
    trows = []
    for k in range(nwin):
        a, b = start + k * WIN_MS, start + (k + 1) * WIN_MS
        inc = cum(b) - cum(a)
        if any(g0 < b and g1 > a for g0, g1 in glist):
            n_ex["long_gap_overlap"] += 1; continue
        w = p[(p.ms >= a) & (p.ms < b)]
        if len(w) < MIN_FIXES:
            n_ex["no_fix"] += 1; continue
        v = w.speed[w.speed_ok].values.astype(float)
        if len(v) == 0:
            n_ex["no_valid_speed"] += 1; continue
        dist = hav(w.latitude.values[:-1], w.longitude.values[:-1], w.latitude.values[1:], w.longitude.values[1:])
        one = len(w) < 2
        path = np.nan if one else float(dist.sum())
        disp = np.nan if one else float(hav(w.latitude.values[0], w.longitude.values[0], w.latitude.values[-1], w.longitude.values[-1]))
        covered = (w.ms.values[-1] - w.ms.values[0]) / 1000.0
        trows.append(dict(
            track=name, subject=int(meta["subject"]), win_idx=k, t_start_ms=a, steps_target=inc,
            n_fixes=len(w), n_speed_valid=len(v), displacement_m=disp, path_m=path,
            speed_mean=v.mean(), speed_median=float(np.median(v)), speed_max=v.max(), speed_std=v.std(),
            speed_delta=float(v[-1] - v[0]), conf_mean=float(w.confInterval.mean()),
            coverage_frac=covered / (WIN_MS / 1000.0), covered_dur_s=covered,
            derived_speed_mps=(path / covered if (not one and covered > 0) else np.nan),
            speed_bin_gps=bin_label(v.mean()), speed_bin_ref=bin_label(meta_speed)))
        kept_inc += inc
    df = pd.DataFrame(trows)
    if len(df):  # lagged previous-window features, only when the previous window (k-1) is present in the table
        prev = df.set_index("win_idx")
        for col, new in [("speed_mean", "lag_speed_mean"), ("path_m", "lag_path_m")]:
            df[new] = df.win_idx.map(lambda k: prev[col].get(k - 1, np.nan))
    rows.append(df)
    ratio_raw = None
    tr = dict(track=name, subject=int(meta["subject"]), raw_rows=n_raw, c1_nonfinite=c1, c2_dup=c2, c3_conf=c3,
              c4_teleport=c4, kept_fixes=len(p), nonmonotonic_ms=nonmono, long_gaps=len(glist),
              long_gap_total_s=float(sum(g1 - g0 for g0, g1 in glist) / 1000), n_windows_generated=nwin,
              n_windows_kept=len(df), win_excl=n_ex, path_clean_m=path_c, distanceReference_m=ref,
              path_over_ref_clean=path_c / ref if ref else None, kept_window_frac=len(df) / nwin if nwin else 0.0)
    track_rows.append(tr)
    pre = cum(start)
    tail = float(st.steps.max()) - cum(start + nwin * WIN_MS)
    tot_meta = None if pd.isna(meta["totSteps"]) else float(meta["totSteps"])
    recon.append(dict(track=name, subject=int(meta["subject"]), totSteps_meta=tot_meta, pre_start_steps=pre,
                      sum_all_windows=all_inc, sum_kept_windows=kept_inc, tail_after_last_window=tail,
                      all_windows_plus_pre_tail=pre + all_inc + tail))

W = pd.concat(rows, ignore_index=True)
# distance anomaly flag: raw GPS path/reference outside 0.8-1.25 per alignment check (26 tracks) and cleaned ratio
al = {x["track"]: x for x in json.load(open(d.ROOT / "results/metrics/phase2_alignment_check.json"))["per_track"]}
anom = []
for tr in track_rows:
    raw_ratio = al[tr["track"]]["gps_path_length_m"] / tr["distanceReference_m"]
    tr["path_over_ref_raw_alignment_check"] = raw_ratio
    tr["distance_anomaly_raw"] = bool(raw_ratio < 0.8 or raw_ratio > 1.25)
    c = tr["path_over_ref_clean"]
    tr["distance_anomaly_clean"] = bool(c is not None and (c < 0.8 or c > 1.25))
    if tr["distance_anomaly_raw"]:
        anom.append(tr["track"])
W["distance_anomaly"] = W.track.isin(anom)
W.to_csv(OUT_CSV, index=False)

g = np.array(gap_counts)
pct = {f"p{q}": float(np.percentile(g, q)) for q in (50, 90, 95, 99, 99.5, 99.9)}
agg = {k: int(sum(t["win_excl"][k] for t in track_rows)) for k in ("long_gap_overlap", "no_fix", "no_valid_speed")}
gen = int(sum(t["n_windows_generated"] for t in track_rows))
cleaning = dict(
    parameters=dict(GAP_MAX_S=GAP_MAX_S, CONF_MAX_M=CONF_MAX_M, TELEPORT_MPS=TELEPORT_MPS, WIN_S=WIN_MS / 1000, MIN_FIXES=MIN_FIXES),
    row_counts={k: int(v) for k, v in tot.items()}, n_tracks=len(track_rows),
    tracks_affected=dict(
        nonmonotonic_ms=int(sum(t["nonmonotonic_ms"] for t in track_rows)),
        exact_duplicates=int(sum(t["c2_dup"] > 0 for t in track_rows)),
        conf_filter=int(sum(t["c3_conf"] > 0 for t in track_rows)),
        teleport=int(sum(t["c4_teleport"] > 0 for t in track_rows)),
        long_gaps=int(sum(t["long_gaps"] > 0 for t in track_rows))),
    fix_interval_by_track_rate={nm: {k: float(np.percentile(a, q)) for k, q in (('p50', 50), ('p95', 95), ('p99', 99), ('p99.9', 99.9))} | {'n': len(a), 'n_gt_10s': int((np.array(a) > 10).sum())} for nm, a in (('dense_tracks_median_interval_le_2s', gap_dense), ('sparse_tracks_median_interval_gt_2s', gap_sparse))},
    fix_interval_s_distribution=dict(n=int(len(g)), **pct, max=float(g.max()),
                                     n_gt_5s=int((g > 5).sum()), n_gt_10s=int((g > 10).sum()), n_gt_30s=int((g > 30).sum())),
    gap_threshold_justification="Two receiver regimes: dense tracks (median interval 1 s, p99.9 4.3 s) and sparse-fix tracks (median 4 s, p95 7 s, p99 13 s). Overall median 1 s, p99 about 6 s, p99.9 about 14 s; see fix_interval_by_track_rate for the dense/sparse-fix track groups). 10 s = twice the window length, beyond the sparse-track p95 (7 s) and well beyond the dense-track p99.9, so shorter gaps are normal receiver cadence and are handled with observed fixes only (coverage_frac feature), longer gaps are excluded.",
    long_gaps_total=int(sum(t["long_gaps"] for t in track_rows)),
    confInterval_decision="Recorded per fix; fixes with confInterval>50 m or invalid dropped (quality filter); conf_mean (window mean) is kept as a GPS-only model input because it is a GPS receiver attribute.",
    feature_choice="Absolute lat/lon are anonymized and not used as inputs; only displacement_m, path_m and derived speed are used. Heading and altitude are not used.",
    windows=dict(generated=gen, kept=int(len(W)), excluded=agg, kept_equals_generated_minus_excluded=bool(gen - sum(agg.values()) == len(W))),
    per_track=track_rows)
(MET / "phase2_cleaning_report.json").write_text(json.dumps(cleaning, indent=1))

tracks_no_win = [t["track"] for t in track_rows if t["n_windows_kept"] == 0]
subj_win = W.groupby("subject").size().to_dict()
excl = dict(
    pre_phase2_excluded_tracks={"15_0..15_4": "subject 15 has no GNSS", "8_10": "no metadata row"},
    track_level_exclusions=[{"track": t, "reason": "zero kept windows"} for t in tracks_no_win],
    window_level=dict(generated=gen, kept=int(len(W)), excluded_by_reason=agg,
                      reasons={"long_gap_overlap": f"window overlaps a gap between consecutive kept fixes > {GAP_MAX_S} s (includes GPS stopping early or starting late)",
                               "no_fix": "no kept fix in window (sparse-fix tracks and short dropouts)",
                               "no_valid_speed": "no fix with valid GPS speed (-1/NaN)"},
                      not_generated="windows beyond min(testEnd, last steps ms) or before max(testStart,0) are never created (no step data / outside test period)"),
    fix_level={k: int(v) for k, v in tot.items() if k.startswith("c")},
    distance_anomaly_tracks=dict(
        definition="raw GPS path / distanceReference outside 0.8-1.25 (from phase2_alignment_check.json)",
        tracks=anom, n=len(anom),
        n_still_anomalous_after_cleaning=int(sum(t["distance_anomaly_clean"] for t in track_rows if t["distance_anomaly_raw"])),
        decision="KEPT in train/eval and flagged (windows.distance_anomaly). Window-level cleaning (gap/conf/teleport rules) already removes the corrupted fixes, targets come from steps.csv independent of reference distance, and the ratio is also affected by distanceReference itself. Metrics to be reported both with and without these tracks.",
        per_track={t["track"]: dict(raw=t["path_over_ref_raw_alignment_check"], clean=t["path_over_ref_clean"], long_gaps=t["long_gaps"],
                                    long_gap_total_s=t["long_gap_total_s"], teleport_dropped=t["c4_teleport"], conf_dropped=t["c3_conf"],
                                    kept_window_frac=t["kept_window_frac"]) for t in track_rows if t["distance_anomaly_raw"]}),
    large_end_mismatch_tracks_note="Tracks where one stream stops early (alignment check) lose those windows via long_gap_overlap / no_fix.")
(MET / "phase2_exclusions.json").write_text(json.dumps(excl, indent=1))

R = pd.DataFrame(recon)
R = R[R.totSteps_meta.notna()]
def dist(x):
    x = np.asarray(x, float)
    return dict(n=int(len(x)), mean=float(x.mean()), median=float(np.median(x)), std=float(x.std()), min=float(x.min()), max=float(x.max()),
                p5=float(np.percentile(x, 5)), p25=float(np.percentile(x, 25)), p75=float(np.percentile(x, 75)), p95=float(np.percentile(x, 95)))
e_all = R.sum_all_windows - R.totSteps_meta
e_full = R.all_windows_plus_pre_tail - R.totSteps_meta
e_kept = R.sum_kept_windows - R.totSteps_meta
rec = dict(
    definitions="error = (sum of window increments) - metadata totSteps, per track. sum_all_windows covers [max(testStart,0), start+n*5 s] before exclusions; pre_start_steps = cum at window start; tail = steps after last full window up to final counter max.",
    n_tracks=int(len(R)),
    error_all_windows=dist(e_all), error_all_windows_plus_pre_and_tail=dist(e_full), error_kept_windows=dist(e_kept),
    tracks_all_plus_pre_tail_equals_tot=int((e_full == 0).sum()),
    tracks_abs_error_all_plus_pre_tail_le_1=int((e_full.abs() <= 1).sum()),
    pre_start_steps=dist(R.pre_start_steps), tail_steps=dist(R.tail_after_last_window),
    kept_fraction_of_totSteps=dist(R.sum_kept_windows / R.totSteps_meta),
    kept_window_steps_total=float(R.sum_kept_windows.sum()), totSteps_total=float(R.totSteps_meta.sum()),
    exact_identity_note="all_windows_plus_pre_tail equals the last running-max counter value; it differs from totSteps only by the 1-step exceptions 5_7 and 14_7 documented in step monotonicity analysis.",
    per_track=R.to_dict("records"))
(MET / "phase2_reconciliation.json").write_text(json.dumps(rec, indent=1))

summ = dict(n_windows=int(len(W)), n_tracks=int(W.track.nunique()), n_subjects=int(W.subject.nunique()),
            windows_per_subject={str(k): int(v) for k, v in subj_win.items()},
            steps_target=dist(W.steps_target), steps_target_value_counts={str(int(k)): int(v) for k, v in W.steps_target.value_counts().sort_index().items()},
            speed_bin_gps_counts=W.speed_bin_gps.value_counts().to_dict(), speed_bin_ref_counts=W.speed_bin_ref.value_counts().to_dict(),
            windows_in_distance_anomaly_tracks=int(W.distance_anomaly.sum()),
            lag_available_frac=float(W.lag_speed_mean.notna().mean()),
            model_input_features=["n_fixes", "n_speed_valid", "displacement_m", "path_m", "speed_mean", "speed_median", "speed_max", "speed_std",
                                  "speed_delta", "conf_mean", "coverage_frac", "covered_dur_s", "derived_speed_mps", "lag_speed_mean", "lag_path_m"],
            not_inputs=["steps_target", "track", "subject", "win_idx", "t_start_ms", "speed_bin_gps", "speed_bin_ref", "distance_anomaly"])
(MET / "phase2_windows_summary.json").write_text(json.dumps(summ, indent=1))
print(json.dumps(dict(tot=tot, windows=cleaning["windows"], gap=cleaning["fix_interval_s_distribution"], anomalies=excl["distance_anomaly_tracks"]["n"],
                      still=excl["distance_anomaly_tracks"]["n_still_anomalous_after_cleaning"], tracks_no_win=tracks_no_win,
                      rec_all=rec["error_all_windows"], rec_full=rec["error_all_windows_plus_pre_and_tail"], bins=summ["speed_bin_gps_counts"]), indent=1, default=str))
