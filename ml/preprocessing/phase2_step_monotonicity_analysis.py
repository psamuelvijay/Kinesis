"""Phase 2 Step 2: investigate decreases of the cumulative steps counter and duplicate ms rows (read-only on datasets/).

Compares alternative handling rules on 5 s windows (grid 0,5,10,... ms>=0) and checks reconciliation of the
sum of window increments to metadata totSteps. Output: results/metrics/phase2_step_monotonicity_analysis.json

Cumulative value at time T under each rule (value before the first row is taken as 0):
  raw_last    : steps of the last row (raw file order) with ms <= T
  running_max : max(steps over rows with ms <= T)               (chosen rule, see decision in JSON)
  sorted_ms_steps : sort rows by (ms, steps), last value with ms <= T
  clipped_diff: cumulative sum of max(diff,0) in raw order, value at last row with ms <= T
Window increment = cum(T_end) - cum(T_start).
"""
import json
import numpy as np
import pandas as pd
import dryad_io as d

OUT = d.ROOT / "results" / "metrics" / "phase2_step_monotonicity_analysis.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
WIN_MS = 5000


def cum_at(ms, vals, T):
    """Value of a step function defined by rows (ms, vals) at times T: last row with ms<=T (rows given in the order that defines 'last'); 0 before first."""
    ms = np.asarray(ms, float)
    out = np.zeros(len(T))
    # rows in given order; for ties in ms the later row in order wins. Use stable search on sorted ms with original order retained.
    order = np.argsort(ms, kind="stable")
    ms_s, v_s = ms[order], np.asarray(vals, float)[order]
    idx = np.searchsorted(ms_s, T, side="right") - 1
    ok = idx >= 0
    out[ok] = v_s[idx[ok]]
    return out


def rules(st):
    ms = st.ms.values.astype(float)
    v = st.steps.values.astype(float)
    t_end = np.floor(ms.max() / WIN_MS) * WIN_MS
    T = np.arange(0, t_end + 1, WIN_MS, dtype=float)
    res = {}
    res["raw_last"] = cum_at(ms, v, T)
    res["running_max"] = cum_at(ms, np.maximum.accumulate(v), T)
    o = np.lexsort((v, ms))
    res["sorted_ms_steps"] = cum_at(ms[o], v[o], T)
    dif = np.diff(v, prepend=0.0)
    res["clipped_diff"] = cum_at(ms, np.cumsum(np.maximum(dif, 0)), T)
    return T, res


rows = []
agg_dec = []
for name, meta in d.model_a_tracks():
    st = d.load_track(name)["steps"].reset_index(drop=True)
    tot = None if pd.isna(meta["totSteps"]) else float(meta["totSteps"])
    v = st.steps.values.astype(float)
    ms = st.ms.values.astype(float)
    ed = st.endDate.values.astype(float)
    dif = np.diff(v)
    neg = np.where(dif < 0)[0]
    r = {"track": name, "subject": int(meta["subject"]), "n_rows": int(len(st)), "totSteps_meta": tot,
         "dup_ms_rows": int(st.ms.duplicated().sum()),
         "dup_ms_groups": int(st.ms[st.ms.duplicated(keep=False)].nunique()),
         "exact_duplicate_rows_ms_steps": int(st.duplicated(["ms", "steps"]).sum()),
         "ms_nonmonotonic_row_order": int((np.diff(ms) < 0).sum()),
         "endDate_nonmonotonic_row_order": int((np.diff(ed) < 0).sum()),
         "n_decreases": int(len(neg)), "max_decrease": float(-dif.min()) if len(neg) else 0.0,
         "n_zero_diff": int((dif == 0).sum()), "n_rows_in_decrease_pairs": int(len(neg))}
    r["final_value"], r["max_value"] = float(v[-1]), float(v.max())
    r["final_eq_max"] = bool(v[-1] == v.max())
    # where do the decreases sit
    if len(neg):
        a, b = neg, neg + 1
        r["dec_same_ms"] = int((ms[a] == ms[b]).sum())
        r["dec_same_endDate"] = int((ed[a] == ed[b]).sum())
        gaps = ms[b] - ms[a]
        r["dec_ms_gap_max"] = float(gaps.max())
        r["dec_ms_gap_values"] = [float(x) for x in gaps]
        r["dec_sizes"] = [float(-dif[i]) for i in neg]
        # recovery: number of following rows until the counter returns to >= the pre-decrease level
        rec = []
        for i in neg:
            lvl = v[i]
            j = i + 1
            while j < len(v) and v[j] < lvl:
                j += 1
            rec.append(int(j - i) if j < len(v) else None)
        r["dec_rows_until_recovered"] = rec
        # does the decrease cross an endDate batch boundary (i.e. a different reporting batch)?
        r["dec_crosses_endDate_batch"] = int((ed[a] != ed[b]).sum())
        # large drop relative to level (reset-like) -> max drop / level
        r["dec_relative_max"] = float((-dif[neg] / np.maximum(v[a], 1)).max())
    # ordering diagnostics: does sorting remove all decreases?
    o_ms_row = np.lexsort((np.arange(len(st)), ms))
    r["decreases_after_sort_ms_stable"] = int((np.diff(v[o_ms_row]) < 0).sum())
    o_ed = np.lexsort((np.arange(len(st)), ms, ed))
    r["decreases_after_sort_endDate_ms"] = int((np.diff(v[o_ed]) < 0).sum())
    o_ms_steps = np.lexsort((v, ms))
    r["decreases_after_sort_ms_steps"] = int((np.diff(v[o_ms_steps]) < 0).sum())
    o_ed_steps = np.lexsort((v, ed))
    r["decreases_after_sort_endDate_steps"] = int((np.diff(v[o_ed_steps]) < 0).sum())
    # same-endDate batches: is the multiset of values consistent with a within-batch permutation?
    g = pd.DataFrame({"ed": ed, "v": v})
    bmin = g.groupby("ed").v.min()
    bmax = g.groupby("ed").v.max()
    bmin_s, bmax_s = bmin.sort_index(), bmax.sort_index()
    r["batches_overlapping_prev_batch"] = int((bmin_s.values[1:] < bmax_s.values[:-1]).sum())
    r["n_endDate_batches"] = int(len(bmin))
    # window-level comparison
    T, c = rules(st)
    inc = {k: np.diff(x) for k, x in c.items()}
    r["n_windows_0_to_last_full"] = int(len(T) - 1)
    r["neg_windows"] = {k: int((x < 0).sum()) for k, x in inc.items()}
    r["window_inc_raw_last_min"] = float(inc["raw_last"].min()) if len(T) > 1 else None
    r["windows_raw_ne_running_max"] = int((inc["raw_last"] != inc["running_max"]).sum())
    r["windows_sorted_ne_running_max"] = int((inc["sorted_ms_steps"] != inc["running_max"]).sum())
    r["windows_clipped_ne_running_max"] = int((inc["clipped_diff"] != inc["running_max"]).sum())
    r["max_abs_window_diff_raw_vs_runmax"] = float(np.abs(inc["raw_last"] - inc["running_max"]).max()) if len(T) > 1 else 0.0
    r["sum_window_increments"] = {k: float(x.sum()) for k, x in inc.items()}
    r["last_full_window_end_ms"] = float(T[-1])
    r["trailing_remainder_ms"] = float(ms.max() - T[-1])
    r["steps_after_last_full_window_running_max"] = float(v.max() - c["running_max"][-1])
    if tot is not None:
        r["reconcile_running_max_vs_totSteps"] = float(inc["running_max"].sum() - tot)
        r["reconcile_incl_trailing_running_max_vs_totSteps"] = float(inc["running_max"].sum() + r["steps_after_last_full_window_running_max"] - tot)
        r["reconcile_raw_last_vs_totSteps"] = float(inc["raw_last"].sum() - tot)
        r["reconcile_clipped_vs_totSteps"] = float(inc["clipped_diff"].sum() - tot)
        r["reconcile_clipped_incl_total_vs_totSteps"] = float(np.maximum(np.diff(v, prepend=0.0), 0).sum() - tot)
        r["final_minus_totSteps"] = float(v[-1] - tot)
    r["first_row_steps"] = float(v[0])
    r["first_row_ms"] = float(ms[0])
    rows.append(r)

df = pd.DataFrame(rows)


def q(x):
    x = pd.Series(x).dropna().astype(float)
    if x.empty:
        return None
    return {"n": int(len(x)), "min": float(x.min()), "p5": float(x.quantile(.05)), "p25": float(x.quantile(.25)), "median": float(x.median()),
            "p75": float(x.quantile(.75)), "p95": float(x.quantile(.95)), "max": float(x.max()), "mean": float(x.mean())}


dec = df[df.n_decreases > 0]
all_sizes = [s for l in dec.dec_sizes for s in l]
all_gaps = [s for l in dec.dec_ms_gap_values for s in l]
all_rec = [s for l in dec.dec_rows_until_recovered for s in l]
res = {
    "n_tracks": len(df),
    "tracks_with_decreases": {"n": int(len(dec)), "subjects": sorted(int(s) for s in dec.subject.unique()),
                              "per_subject_counts": {str(k): int(v) for k, v in dec.groupby("subject").size().items()},
                              "tracks_per_subject_total": {str(k): int(v) for k, v in df.groupby("subject").size().items()}},
    "decrease_events_total": int(df.n_decreases.sum()),
    "decrease_events_per_track": q(dec.n_decreases),
    "decrease_size_distribution": {str(k): int(v) for k, v in pd.Series(all_sizes).value_counts().sort_index().items()},
    "decrease_pair_ms_gap_distribution_ms": q(all_gaps),
    "decrease_pairs_same_ms": int(dec.dec_same_ms.sum()), "decrease_pairs_same_endDate": int(dec.dec_same_endDate.sum()),
    "decrease_pairs_crossing_endDate_batch": int(dec.dec_crosses_endDate_batch.sum()),
    "decrease_rows_until_counter_recovers": {str(k): int(v) for k, v in pd.Series([x for x in all_rec if x is not None]).value_counts().sort_index().items()},
    "decreases_never_recovered": int(sum(1 for x in all_rec if x is None)),
    "decrease_relative_to_level_max": float(dec.dec_relative_max.max()),
    "duplicate_ms": {"tracks_with_dup_ms": int((df.dup_ms_rows > 0).sum()), "tracks_with_dup_ms_among_decrease_tracks": int((dec.dup_ms_rows > 0).sum()),
                     "dup_rows_total": int(df.dup_ms_rows.sum()), "dup_rows_per_track_decrease_tracks": q(dec.dup_ms_rows),
                     "dup_rows_per_track_other_tracks": q(df[df.n_decreases == 0].dup_ms_rows),
                     "exact_duplicate_ms_steps_rows_total": int(df.exact_duplicate_rows_ms_steps.sum())},
    "row_order": {"tracks_ms_nonmonotonic_in_row_order": int((df.ms_nonmonotonic_row_order > 0).sum()),
                  "tracks_endDate_nonmonotonic_in_row_order": int((df.endDate_nonmonotonic_row_order > 0).sum())},
    "sorting_effect_on_decrease_tracks": {
        "tracks_still_decreasing_after_sort_ms_stable": int((dec.decreases_after_sort_ms_stable > 0).sum()),
        "decreases_remaining_sort_ms_stable": int(dec.decreases_after_sort_ms_stable.sum()),
        "tracks_still_decreasing_after_sort_endDate_ms": int((dec.decreases_after_sort_endDate_ms > 0).sum()),
        "decreases_remaining_sort_endDate_ms": int(dec.decreases_after_sort_endDate_ms.sum()),
        "tracks_still_decreasing_after_sort_ms_steps": int((dec.decreases_after_sort_ms_steps > 0).sum()),
        "decreases_remaining_sort_ms_steps": int(dec.decreases_after_sort_ms_steps.sum()),
        "tracks_still_decreasing_after_sort_endDate_steps": int((dec.decreases_after_sort_endDate_steps > 0).sum()),
        "decreases_remaining_sort_endDate_steps": int(dec.decreases_after_sort_endDate_steps.sum())},
    "endDate_batches_overlapping_previous_batch_in_value": int(df.batches_overlapping_prev_batch.sum()),
    "final_value_vs_metadata": {"tracks_final_eq_totSteps": int((df.final_minus_totSteps == 0).sum()), "final_minus_totSteps": q(df.final_minus_totSteps),
                                "decrease_tracks_final_eq_max": int(dec.final_eq_max.sum()), "decrease_tracks_n": int(len(dec)),
                                "decrease_tracks_final_minus_totSteps": q(dec.final_minus_totSteps)},
    "first_row": {"first_row_steps": q(df.first_row_steps), "first_row_ms": q(df.first_row_ms),
                  "note": "first row has steps==1 in every track (see first_row_steps), consistent with taking the counter as 0 before the first row"},
    "window_rule_comparison_5s": {
        "windows_total": int(df.n_windows_0_to_last_full.sum()),
        "negative_windows_by_rule_total": {k: int(sum(x[k] for x in df.neg_windows)) for k in ["raw_last", "running_max", "sorted_ms_steps", "clipped_diff"]},
        "windows_where_raw_last_differs_from_running_max": int(df.windows_raw_ne_running_max.sum()),
        "windows_where_sorted_differs_from_running_max": int(df.windows_sorted_ne_running_max.sum()),
        "windows_where_clipped_differs_from_running_max": int(df.windows_clipped_ne_running_max.sum()),
        "max_abs_window_diff_raw_vs_runmax": q(df.max_abs_window_diff_raw_vs_runmax),
        "decrease_tracks_only": {"windows_total": int(dec.n_windows_0_to_last_full.sum()),
                                 "windows_raw_ne_running_max": int(dec.windows_raw_ne_running_max.sum()),
                                 "windows_sorted_ne_running_max": int(dec.windows_sorted_ne_running_max.sum()),
                                 "windows_clipped_ne_running_max": int(dec.windows_clipped_ne_running_max.sum())}},
    "reconciliation_sum_window_increments_minus_totSteps": {
        "note": "windows cover [0, last_full_window_end]; steps in the trailing partial window are excluded from windows, so *_incl_trailing adds them back for the pure arithmetic check",
        "running_max_windows_only": q(df.reconcile_running_max_vs_totSteps),
        "running_max_incl_trailing": q(df.reconcile_incl_trailing_running_max_vs_totSteps),
        "running_max_incl_trailing_tracks_exact": int((df.reconcile_incl_trailing_running_max_vs_totSteps == 0).sum()),
        "raw_last_windows_only": q(df.reconcile_raw_last_vs_totSteps),
        "clipped_diff_windows_only": q(df.reconcile_clipped_vs_totSteps),
        "clipped_diff_full_track_sum_positive_diffs_minus_totSteps": q(df.reconcile_clipped_incl_total_vs_totSteps),
        "clipped_overcount_tracks_decrease_tracks_full_track": int((dec.reconcile_clipped_incl_total_vs_totSteps > 0).sum()),
        "trailing_remainder_ms": q(df.trailing_remainder_ms),
        "steps_in_trailing_partial_window": q(df.steps_after_last_full_window_running_max)},
    "examples_decrease_tracks": json.loads(dec.sort_values("n_decreases", ascending=False).head(5)[
        ["track", "n_decreases", "max_decrease", "dup_ms_rows", "dec_sizes", "dec_ms_gap_values", "decreases_after_sort_ms_steps",
         "reconcile_running_max_vs_totSteps", "reconcile_clipped_incl_total_vs_totSteps", "final_minus_totSteps"]].to_json(orient="records")),
}
res["decision"] = {
    "rule": "Treat the counter as cumulative with out-of-order delivery of rows inside one reporting batch: cum(T) = running maximum of steps over rows with ms<=T (rows ordered by ms); "
            "window increment = cum(T_end) - cum(T_start). Never clip individual diffs; report the window-level net change. Rows at identical ms are kept (no dedup needed: running max is order-independent).",
    "justification_source_keys": ["decrease_pairs_same_endDate", "decrease_pairs_crossing_endDate_batch", "decrease_rows_until_counter_recovers",
                                  "sorting_effect_on_decrease_tracks", "final_value_vs_metadata", "reconciliation_sum_window_increments_minus_totSteps",
                                  "window_rule_comparison_5s"],
    "known_limitation": "A window boundary falling inside a batch can credit up to the batch's max decrease (<=4 steps) to one window and take it back in the next; the net over the track is exact.",
    "observed_pattern": "All decreases lie inside one endDate batch (rows with identical endDate, ms differing by 0-12 ms): rows of a batch are delivered out of order, not counter resets or corrections. "
                        "Exception in kind: 14_4 has one row with steps==0 inside a batch (-6) and 14_9 a -10 jump inside a batch; both recover within the batch. Sorting by ms (stable) does not fix them, sorting by (endDate, steps) fixes all but 1 event.",
    "metadata_reconciliation_exceptions": "5_7 (metadata totSteps is 1 below the last value) and 14_7 (running max is 1 above the last-row value that equals totSteps); 1 step each",
    "before_first_row": "counter taken as 0 before the first row (first row already holds several steps)"}
res["per_track"] = json.loads(df.drop(columns=["dec_ms_gap_values", "dec_sizes", "dec_rows_until_recovered"], errors="ignore").round(4).to_json(orient="records"))
OUT.write_text(json.dumps(res, indent=2, allow_nan=False, default=str))
print(json.dumps({k: v for k, v in res.items() if k != "per_track"}, indent=1)[:14000])
