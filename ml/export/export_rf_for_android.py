"""M2 export: Random Forest (selected Phase 2 model) -> Android asset + golden parity files. Read-only on models/datasets/results.
Run with the project venv:  .venv/Scripts/python.exe ml/export/export_rf_for_android.py

Outputs (new files only):
  android/engine-gps/src/main/assets/gps_rf_model.bin           300-tree RF, binary (little-endian)
  android/engine-gps/src/test/resources/golden_model_vectors.json   held-out feature rows + Python predictions (NaN -> null)
  android/engine-gps/src/test/resources/golden_features.json        raw Dryad fixes + Python Phase 2 window features

Binary layout (all little-endian):
  magic "KRF1" | int32 version=1 | int32 n_trees | int32 n_features
  per tree: int32 n_nodes, then n_nodes records of 29 bytes:
     int32 feature (-2 = leaf) | float64 threshold | int32 left | int32 right | float64 value | uint8 missing_go_to_left
  Prediction = mean over trees of leaf value. Traversal replicates sklearn: x is cast to float32, then
  NaN -> (missing_go_to_left ? left : right); else x32 <= threshold ? left : right (threshold compared as float64).
"""
import ast
import json
import struct
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
import dryad_io as d  # noqa: E402

ASSET = ROOT / "android/engine-gps/src/main/assets/gps_rf_model.bin"
VEC = ROOT / "android/engine-gps/src/test/resources/golden_model_vectors.json"
FEAT = ROOT / "android/engine-gps/src/test/resources/golden_features.json"
FEATURES = json.load(open(ROOT / "ml/models/feature_list.json"))["features"]
cfg = json.load(open(ROOT / "ml/models/training_config.json"))
assert cfg["selected_model"] == "random_forest"

model = joblib.load(ROOT / "ml/models/best_model.joblib")
print(type(model).__name__, "n_estimators", model.n_estimators, "max_depth", model.max_depth,
      "min_samples_leaf", model.min_samples_leaf, "max_features", model.max_features)
assert type(model).__name__ == "RandomForestRegressor"
assert (model.n_estimators, model.max_depth, model.min_samples_leaf, model.max_features) == (300, 8, 5, 1.0)
assert list(model.feature_names_in_) == FEATURES


def num(x):
    return None if x is None or not np.isfinite(x) else float(x)


# ---------------------------------------------------------------- binary asset
buf = bytearray(b"KRF1")
buf += struct.pack("<iii", 1, len(model.estimators_), len(FEATURES))
n_missing_right_nodes = 0
for est in model.estimators_:
    t = est.tree_
    n = t.node_count
    mgl = getattr(t, "missing_go_to_left", None)
    assert mgl is not None, "tree_.missing_go_to_left not available"
    buf += struct.pack("<i", n)
    for i in range(n):
        leaf = t.children_left[i] == -1
        if leaf:
            buf += struct.pack("<idiidB", -2, 0.0, -1, -1, float(t.value[i, 0, 0]), int(mgl[i]))
        else:
            n_missing_right_nodes += int(not mgl[i])
            buf += struct.pack("<idiidB", int(t.feature[i]), float(t.threshold[i]), int(t.children_left[i]),
                               int(t.children_right[i]), float(t.value[i, 0, 0]), int(mgl[i]))
ASSET.parent.mkdir(parents=True, exist_ok=True)
ASSET.write_bytes(bytes(buf))
print("asset", ASSET, len(buf), "bytes; split nodes with missing->right:", n_missing_right_nodes)


# ---------------------------------------------------------------- reference traversal (what Kotlin does) to self-check the format
def parse(b):
    assert b[:4] == b"KRF1"
    _, nt, nf = struct.unpack_from("<iii", b, 4)
    off, trees = 16, []
    for _ in range(nt):
        (n,) = struct.unpack_from("<i", b, off); off += 4
        trees.append([struct.unpack_from("<idiidB", b, off + 29 * i) for i in range(n)])
        off += 29 * n
    assert off == len(b)
    return trees


TREES = parse(bytes(buf))


def predict_asset(x):
    x32 = [np.float32(v) for v in x]
    s = 0.0
    for nodes in TREES:
        i = 0
        while nodes[i][0] != -2:
            f, thr, l, r, _, m = nodes[i]
            v = x32[f]
            i = (l if m else r) if np.isnan(v) else (l if float(v) <= thr else r)
        s += nodes[i][4]
    return s / len(TREES)


# ---------------------------------------------------------------- golden model vectors
W = pd.read_csv(d.ROOT / "datasets/dryad/processed/windows_5s.csv")
P = pd.read_csv(ROOT / "results/metrics/phase2_test_predictions.csv")
T = P.merge(W, on=["track", "win_idx"], suffixes=("", "_w"), validate="1:1")
assert len(T) == len(P)
X = T[FEATURES]
py = model.predict(X)
assert np.allclose(py, T.pred_random_forest.values, atol=1e-9), "model does not reproduce stored phase2 test predictions"
nan_rows = X.isna().any(axis=1).values
rng = np.random.default_rng(42)
idx_nan = np.where(nan_rows)[0]
idx_ok = np.where(~nan_rows)[0]
pick = np.sort(np.r_[idx_nan[:80], rng.choice(idx_ok, size=min(220, len(idx_ok)), replace=False)])
vectors = []
for i in pick:
    row = [num(v) for v in X.iloc[i].values]
    ra = predict_asset([np.nan if v is None else v for v in row])
    assert abs(ra - py[i]) < 1e-9, (i, ra, py[i])
    vectors.append(dict(track=T.track[i], win_idx=int(T.win_idx[i]), features=row, steps_target=num(T.steps_target[i]),
                        python_prediction=float(py[i]), stored_phase2_prediction=float(T.pred_random_forest[i])))
VEC.parent.mkdir(parents=True, exist_ok=True)
json.dump(dict(description="Held-out (test-subject) Phase 2 feature rows with RandomForest predictions from ml/models/best_model.joblib. NaN encoded as JSON null. Feature order = feature_order. Tolerance 1e-6.",
               feature_order=FEATURES, n_rows=len(vectors), n_rows_with_nan=int(sum(None in v["features"] for v in vectors)),
               sklearn_float32_note="sklearn casts inputs to float32 before comparing with float64 thresholds", vectors=vectors),
          open(VEC, "w"), separators=(",", ":"))
print("vectors", len(vectors), "with NaN", sum(None in v["features"] for v in vectors), "total test rows", len(T), "NaN rows", int(nan_rows.sum()))

# ---------------------------------------------------------------- golden features: use real Phase 2 cleaning functions
src = (ROOT / "ml/preprocessing/phase2_build_windows.py").read_text()
tree = ast.parse(src)
keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("hav", "teleport_drop")]
keep += [n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("GAP_MAX_S", "CONF_MAX_M", "TELEPORT_MPS", "WIN_MS")]
ns = {"np": np, "pd": pd}
exec(compile(ast.Module(body=keep, type_ignores=[]), "phase2_build_windows(extract)", "exec"), ns)  # reuse real code without running the whole script
rep = {t["track"]: t for t in json.load(open(ROOT / "results/metrics/phase2_cleaning_report.json"))["per_track"]}
md = d.metadata().set_index("testName")
test_subjects = sorted(set(P.subject))
cands = []
for tr in sorted(set(P.track)):
    r = rep[tr]
    cands.append((tr, r["c3_conf"] + r["c4_teleport"], r["long_gaps"], r["n_windows_kept"]))
chosen = []
for s in test_subjects:  # per test subject: track with most dropped fixes / gaps, but moderate size
    cs = [c for c in cands if c[0].startswith(f"{s}_") and 20 <= c[3] <= 120]
    cs.sort(key=lambda c: (-(c[1] > 0) - (c[2] > 0), -c[1] - c[2], c[3]))
    if cs:
        chosen.append(cs[0][0])
tracks_out = []
for name in chosen:
    t = d.load_track(name)
    ev, st = t["events"].iloc[0], t["steps"]
    p0 = t["positions"]
    # re-run cleaning with the real helper functions, check against Phase 2 report
    p = p0[np.isfinite(p0[["ms", "latitude", "longitude"]].values).all(axis=1)].sort_values("ms", kind="stable").drop_duplicates()
    c = p.confInterval
    p = p[c.notna() & (c >= 0) & (c <= ns["CONF_MAX_M"])]
    p, c4 = ns["teleport_drop"](p)
    r = rep[name]
    assert len(p) == r["kept_fixes"] and c4 == r["c4_teleport"], (name, len(p), r)
    start = max(float(ev.testStart), 0.0)
    end = min(float(ev.testEnd), float(st.ms.max()))
    nwin = int(np.floor((end - start) / ns["WIN_MS"]))
    wins = W[W.track == name].sort_values("win_idx")
    fixes = [[num(a) for a in row] for row in p0[["ms", "latitude", "longitude", "speed", "confInterval"]].itertuples(index=False)]
    tracks_out.append(dict(
        track=name, subject=int(md.loc[name, "subject"]), window_ms=5000, window_grid_start_ms=start, n_windows_generated=nwin,
        cleaning=dict(raw_rows=len(p0), kept_fixes=len(p), dropped_conf=r["c3_conf"], dropped_teleport=r["c4_teleport"], long_gaps=r["long_gaps"]),
        raw_fix_columns=["ms", "latitude", "longitude", "speed_mps", "confInterval_m"], raw_fixes=fixes,
        expected_windows=[dict(win_idx=int(w.win_idx), t_start_ms=float(w.t_start_ms), features=[num(w[f]) for f in FEATURES],
                               rf_prediction=float(model.predict(pd.DataFrame([w[FEATURES].astype(float)]))[0]), steps_target=num(w.steps_target))
                          for _, w in wins.iterrows()]))
    print(name, "fixes", len(fixes), "windows", len(wins), "of", nwin, r["c3_conf"], r["c4_teleport"], r["long_gaps"])
json.dump(dict(description="Raw Dryad GPS fixes (original row order, NaN/-1 speed as in source, NaN -> null) with window features computed by Phase 2 (windows_5s.csv, produced by ml/preprocessing/phase2_build_windows.py). Cleaning: confInterval NaN/<0/>50 dropped, exact duplicates dropped, iterative teleport drop >10 m/s, speed<0/NaN invalid, windows overlapping a >10 s gap between kept fixes excluded, windows with no fix or no valid speed excluded, 5 s non-overlapping windows [start+k*5000, +5000) from window_grid_start_ms, lag_* = previous window k-1 (NaN if absent). Features order = feature_order; NaN -> null.",
               feature_order=FEATURES, tracks=tracks_out), open(FEAT, "w"), separators=(",", ":"))
for p_ in (ASSET, VEC, FEAT):
    print(p_.relative_to(ROOT), p_.stat().st_size)
