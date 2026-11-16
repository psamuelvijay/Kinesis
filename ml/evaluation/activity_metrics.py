"""Phase 3 Model B evaluation helpers (metrics, confusion matrices, plots)."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support

CLASSES = ["WALKING", "STATIONARY", "OTHER"]
LABELS = [0, 1, 2]


def metrics(y, p):
    y = np.asarray(y); p = np.asarray(p)
    pr, rc, f1, sup = precision_recall_fscore_support(y, p, labels=LABELS, zero_division=0)
    cm = confusion_matrix(y, p, labels=LABELS)
    rown = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    return {
        "n_windows": int(len(y)),
        "accuracy": float(accuracy_score(y, p)),
        "macro_f1": float(f1_score(y, p, labels=LABELS, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, p, labels=LABELS, average="weighted", zero_division=0)),
        "per_class": {c: {"precision": float(pr[i]), "recall": float(rc[i]), "f1": float(f1[i]), "support": int(sup[i])}
                      for i, c in enumerate(CLASSES)},
        "confusion_matrix_counts": cm.tolist(),
        "confusion_matrix_row_normalised": rown.round(6).tolist(),
        "confusion_rows_true_cols_pred": CLASSES,
    }


def per_subject(meta, y, p):
    out = {}
    for s in sorted(meta["subject"].unique()):
        m = (meta["subject"] == s).to_numpy()
        yy, pp = y[m], p[m]
        present = sorted(set(yy.tolist()))
        out[str(int(s))] = {"n_windows": int(m.sum()), "accuracy": float(accuracy_score(yy, pp)),
                            "macro_f1_over_present_classes": float(f1_score(yy, pp, labels=present, average="macro", zero_division=0)),
                            "classes_present": [CLASSES[i] for i in present]}
    return out


def diagnostic_by_original(meta, p):
    """Rows: original activity; columns: predicted class counts and rates."""
    rows = {}
    for a in sorted(meta["orig_short"].unique()):
        m = (meta["orig_short"] == a).to_numpy()
        cnt = np.bincount(p[m], minlength=3)
        rows[a] = {"n": int(m.sum()), **{f"pred_{c}": int(cnt[i]) for i, c in enumerate(CLASSES)},
                   **{f"rate_{c}": float(cnt[i] / m.sum()) for i, c in enumerate(CLASSES)}}
    return rows


def key_error_rates(meta, p):
    """jog/stairs predicted STATIONARY; stationary activities predicted WALKING."""
    def rate(acts, cls):
        m = meta["orig_short"].isin(acts).to_numpy()
        return {"n": int(m.sum()), "n_pred": int((p[m] == cls).sum()), "rate": float((p[m] == cls).mean()) if m.sum() else None}
    return {"jog_ups_dws_predicted_STATIONARY": rate(["jog", "ups", "dws"], 1),
            "sit_std_lay_predicted_WALKING": rate(["sit", "std", "lay"], 0)}


def save_confusion(cm_counts, name, outdir, title):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    cm = np.array(cm_counts)
    pd.DataFrame(cm, index=[f"true_{c}" for c in CLASSES], columns=[f"pred_{c}" for c in CLASSES]).to_csv(outdir / f"{name}_counts.csv")
    rn = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    pd.DataFrame(rn.round(6), index=[f"true_{c}" for c in CLASSES], columns=[f"pred_{c}" for c in CLASSES]).to_csv(outdir / f"{name}_row_normalised.csv")
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.8))
    for a, mat, fmt, t in [(ax[0], cm, "d", "counts"), (ax[1], rn, ".2f", "row-normalised")]:
        a.imshow(mat, cmap="Blues", vmin=0)
        a.set_xticks(range(3)); a.set_yticks(range(3)); a.set_xticklabels(CLASSES, rotation=30); a.set_yticklabels(CLASSES)
        a.set_xlabel("predicted"); a.set_ylabel("true"); a.set_title(t)
        for i in range(3):
            for j in range(3):
                a.text(j, i, format(mat[i, j], fmt), ha="center", va="center", color="black" if mat[i, j] < mat.max() * 0.6 else "white")
    fig.suptitle(title, fontsize=9)
    fig.tight_layout(); fig.savefig(outdir / f"{name}.png", dpi=120); plt.close(fig)
