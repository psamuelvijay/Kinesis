"""Build datasets/dataset_inventory.json from results/metrics/inspect_*.json (no values typed by hand except source metadata)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
M = ROOT / "results" / "metrics"
ms = json.loads((M / "inspect_motionsense.json").read_text())
uci = json.loads((M / "inspect_uci_har.json").read_text())
dr = json.loads((M / "inspect_dryad.json").read_text())
dry_ok = dr.get("status") == "available"
inv = {"generated_by": "ml/preprocessing/build_inventory.py", "datasets": [
 {"name": "Dryad walking activity dataset (Caramaschi et al.)",
  "source_url": "https://datadryad.org/dataset/doi%3A10.5061/dryad.n2z34tn5q", "doi": "10.5061/dryad.n2z34tn5q",
  "version": "Dryad version 6, published 2024-11-01", "license": "CC0-1.0",
  "status": "available",
  "metadata_tracks_rows": dr["metadata_tracks"]["rows"], "metadata_subjects": dr["metadata_tracks"]["n_subjects"],
  "usable_subjects": {"gps_and_steps (Model A)": dr["n_subjects_usable_model_A"], "gps_and_motion_and_steps (fusion calibration)": dr["n_subjects_usable_gps_motion_steps"]},
  "usable_recordings": {"gps_and_steps (Model A)": dr["n_usable_model_A"], "gps_and_motion_and_steps (fusion calibration)": dr["n_usable_gps_motion_steps"]},
  "available_features": {f: dr["column_schemas"][f]["columns"] for f in dr["column_schemas"]},
  "excluded_recordings": {"model_A": dr["excluded_tracks_model_A"], "fusion_calibration": dr["excluded_tracks_fusion"]},
  "folder_not_in_metadata": dr["folders_not_in_metadata"],
  "sampling_rates_hz": dr["sampling_rates_summary_hz"],
  "label_sets": None, "inspection": "results/metrics/inspect_dryad.json"},
 {"name": "MotionSense", "source_url": "https://github.com/mmalekzadeh/motion-sense",
  "version": "GitHub master, commit 261cb0d60611a049ab38127738e42cc510ed50f4", "license": "MIT",
  "status": "available",
  "usable_subjects": ms["n_subjects"], "usable_recordings": ms["recordings_in_all_three_streams"],
  "recordings_definition": "one subject x one trial; present in all of A_DeviceMotion, B_Accelerometer, C_Gyroscope",
  "available_features": {"B_Accelerometer": ms["streams"]["B_Accelerometer"]["columns"][1:], "C_Gyroscope": ms["streams"]["C_Gyroscope"]["columns"][1:],
                         "A_DeviceMotion": ms["streams"]["A_DeviceMotion"]["columns"][1:], "subject_info": ms["subjects_info"]["columns"]},
  "excluded_recordings": [], "excluded_note": "None excluded for missing data (0 missing values). All %d recordings have different row counts between the accelerometer stream and the gyroscope stream (see inspect json); they are not sample-aligned." % ms["n_row_count_mismatch"],
  "sampling_rates_hz": {"measured": None, "documented": 50, "note": "no timestamps in files"},
  "label_sets": {"activity_codes": ms["activity_codes"], "recordings_per_activity": ms["recordings_per_activity"]},
  "inspection": "results/metrics/inspect_motionsense.json"},
 {"name": "UCI HAR (Human Activity Recognition Using Smartphones)",
  "source_url": "https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones", "doi": "10.24432/C54S4K",
  "version": "Version 1.0 (UCI page last updated 2024-03-10)", "license": "CC BY 4.0", "status": "available",
  "usable_subjects": uci["n_subjects_total"], "usable_recordings": uci["n_windows_total"],
  "recordings_definition": "pre-segmented 128-sample windows (2.56 s, 50% overlap); continuous recordings not provided",
  "available_features": {"inertial_signals": uci["required_features"]["raw_signal_files"], "feature_vector": "561 features (X_*.txt)"},
  "excluded_recordings": [], "sampling_rates_hz": uci["sampling_rate"],
  "split_provided": {sp: {"windows": d["n_windows"], "subjects": d["n_subjects"]} for sp, d in uci["splits"].items()},
  "label_sets": uci["activity_labels"], "inspection": "results/metrics/inspect_uci_har.json"}]}
(ROOT / "datasets" / "dataset_inventory.json").write_text(json.dumps(inv, indent=2))
print("ok")
