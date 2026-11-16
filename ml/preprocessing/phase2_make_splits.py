"""Phase 2 Step 5: subject-independent train/val/test split (seeded). Reads windows_5s.csv + metadata; writes results/metrics/phase2_splits.json.
Test subjects are for one final evaluation only; hyperparameters are tuned on train+validation (CV by subject inside train+val or the val set)."""
import json, itertools
import numpy as np
import pandas as pd
import dryad_io as d

SEED = 42
N_TRIALS = 20000
W = pd.read_csv(d.ROOT / "datasets/dryad/processed/windows_5s.csv")
md = d.metadata()
md = md[md.testName.isin(W.track.unique())]
info = md.groupby("subject").agg(isPatient=("isPatient", "first"), country=("country", "first"),
                                 mean_speed=("average_walking_speed", "mean"), n_tracks=("testName", "size")).reset_index()
cnt = W.groupby("subject").size().rename("n_windows").reset_index()
info = info.merge(cnt, on="subject")
info["isPatient"] = info.isPatient.astype(str).str.upper().eq("TRUE")
subs = info.subject.tolist()
N = len(subs)
n_test = n_val = int(round(0.15 * N))
n_train = N - n_val - n_test
tot_w = info.n_windows.sum()

def cost(idx_sets):
    c = 0.0
    for idx in idx_sets:
        s = info.iloc[list(idx)]
        c += abs(s.n_windows.sum() / tot_w - len(idx) / N) * 2           # window share ~ subject share
        c += abs(s.isPatient.mean() - info.isPatient.mean())            # patient mix
        c += abs(s.mean_speed.mean() - info.mean_speed.mean()) / info.mean_speed.std()  # walking-speed level
    return c

rng = np.random.default_rng(SEED)
best, best_c = None, np.inf
for _ in range(N_TRIALS):
    perm = rng.permutation(N)
    sets = (perm[:n_train], perm[n_train:n_train + n_val], perm[n_train + n_val:])
    c = cost(sets)
    if c < best_c:
        best, best_c = sets, c
names = ("train", "validation", "test")
split = {n: sorted(int(info.subject.iloc[i]) for i in idx) for n, idx in zip(names, best)}
for a, b in itertools.combinations(names, 2):
    assert not set(split[a]) & set(split[b]), f"subject overlap {a}/{b}"
assert sorted(sum(split.values(), [])) == sorted(int(s) for s in subs)
sm = {s: n for n in names for s in split[n]}
W["split"] = W.subject.map(sm)
assert W.split.notna().all()
for a, b in itertools.combinations(names, 2):
    assert not set(W[W.split == a].subject) & set(W[W.split == b].subject)
stats = {}
for n in names:
    w = W[W.split == n]
    s = info[info.subject.isin(split[n])]
    stats[n] = dict(n_subjects=len(split[n]), n_tracks=int(w.track.nunique()), n_windows=int(len(w)),
                    window_share=float(len(w) / len(W)), patient_fraction=float(s.isPatient.mean()),
                    mean_walking_speed_ref=float(s.mean_speed.mean()),
                    windows_in_distance_anomaly_tracks=int(w.distance_anomaly.sum()),
                    speed_bin_gps_counts=w.speed_bin_gps.value_counts().to_dict(),
                    steps_target_mean=float(w.steps_target.mean()))
out = dict(seed=SEED, method=f"Random subject-level assignment, best of {N_TRIALS} seeded draws minimising imbalance of window share, patient fraction and mean reference walking speed across sets; target sizes {n_train}/{n_val}/{n_test} subjects (about 70/15/15).",
           excluded_subjects={"15": "no GPS"}, subjects=split, stats=stats, imbalance_cost=float(best_c),
           subject_info=info.assign(subject=info.subject.astype(int)).to_dict("records"),
           checks=dict(zero_subject_overlap=True, all_subjects_assigned=True, no_track_in_two_sets=True),
           protocol="Tuning (hyperparameters, feature choices) only on train+validation; test subjects evaluated once with the final fixed configuration.")
(d.ROOT / "results/metrics/phase2_splits.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(dict(subjects=split, stats={k: {x: v[x] for x in ("n_subjects", "n_tracks", "n_windows", "patient_fraction")} for k, v in stats.items()}, cost=best_c), indent=1))
