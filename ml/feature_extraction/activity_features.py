"""Phase 3 Model B features. Identical code for both datasets. Orientation-independent magnitudes only.

Input: windows (n,128,6) = linear acc x,y,z (g) + gyro x,y,z (rad/s). Sampling rate 50 Hz.
Peak parameters (scipy.signal.find_peaks on acceleration magnitude): prominence >= 0.1 g, distance >= 10 samples (0.2 s).
Spectrum: rFFT of the mean-removed acceleration magnitude, DC bin excluded, power = |F|^2 / n.
Spectral entropy: Shannon entropy (log2) of normalised power over bins 1..64, divided by log2(64) (range 0..1).
If total non-DC power is < 1e-12, dominant frequency = 0, spectral energy = 0, entropy = 0 (rule, not imputation).
"""
import numpy as np
from scipy.signal import find_peaks

FS = 50.0
PEAK_PROMINENCE_G = 0.1
PEAK_DISTANCE = 10
FEATURE_NAMES = [
    "acc_mag_mean", "acc_mag_std", "acc_mag_rms", "acc_mag_var", "acc_mag_energy",
    "gyro_mag_mean", "gyro_mag_var",
    "acc_peak_count",
    "acc_dominant_freq_hz", "acc_spectral_energy", "acc_spectral_entropy",
]


def extract_features(W):
    W = np.asarray(W, dtype=np.float64)
    am = np.linalg.norm(W[:, :, 0:3], axis=2)
    gm = np.linalg.norm(W[:, :, 3:6], axis=2)
    n = am.shape[1]
    f = {}
    f["acc_mag_mean"] = am.mean(1)
    f["acc_mag_std"] = am.std(1)
    f["acc_mag_rms"] = np.sqrt((am ** 2).mean(1))
    f["acc_mag_var"] = am.var(1)
    f["acc_mag_energy"] = (am ** 2).sum(1)
    f["gyro_mag_mean"] = gm.mean(1)
    f["gyro_mag_var"] = gm.var(1)
    f["acc_peak_count"] = np.array([len(find_peaks(a, prominence=PEAK_PROMINENCE_G, distance=PEAK_DISTANCE)[0]) for a in am], dtype=float)
    P = np.abs(np.fft.rfft(am - am.mean(1, keepdims=True), axis=1)) ** 2 / n
    freqs = np.fft.rfftfreq(n, d=1.0 / FS)
    P = P[:, 1:]; freqs = freqs[1:]
    tot = P.sum(1)
    ok = tot >= 1e-12
    dom = np.where(ok, freqs[np.argmax(P, axis=1)], 0.0)
    p = np.divide(P, tot[:, None], out=np.zeros_like(P), where=ok[:, None])
    with np.errstate(divide="ignore", invalid="ignore"):
        ent = -np.where(p > 0, p * np.log2(p), 0.0).sum(1) / np.log2(P.shape[1])
    f["acc_dominant_freq_hz"] = dom
    f["acc_spectral_energy"] = np.where(ok, tot, 0.0)
    f["acc_spectral_entropy"] = np.where(ok, ent, 0.0)
    return np.column_stack([f[k] for k in FEATURE_NAMES])
