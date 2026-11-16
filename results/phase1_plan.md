# Phase 1 Plan: Data Acquisition and Inspection

## What Phase 1 implements
- Repository structure for datasets, ML code, Android apps and results.
- Download of three public datasets, kept unmodified in `datasets/<name>/raw`.
- Inspection of every relevant file: structure, missing values, sampling frequency, timestamp format, activity labels, subject identifiers, feature availability.
- A dataset inventory (`datasets/dataset_inventory.md` and `.json`): name, source, version, license, usable subjects, usable recordings, available features, excluded recordings with reasons.
- `docs/dataset_documentation.md` and `docs/research_references.md`.

Phase 1 trains no models and builds no apps.

## Datasets
| Dataset | Role | Source |
|---|---|---|
| Dryad Walking Activity Dataset (Caramaschi et al. 2024), DOI 10.5061/dryad.n2z34tn5q | GPS step estimation, threshold calibration for fusion | https://datadryad.org/dataset/doi%3A10.5061/dryad.n2z34tn5q |
| MotionSense (Malekzadeh et al. 2019) | Activity classifier training | https://github.com/mmalekzadeh/motion-sense |
| UCI HAR Using Smartphones (Anguita et al.) | Activity classifier training and independent evaluation | https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones |

## Rules
- Only real public data. No random, synthetic or fabricated sensor, GPS, label or metric values.
- Original files are never edited. Derived output goes outside `raw/`.
- If a download or feature is unavailable, the gap is reported with manual steps. No substitute data is used.

## Expected output
- `datasets/{dryad,motionsense,uci_har}/raw` with original files, and `docs/` with README and license copies.
- Per-file inspection results and the dataset inventory.
- Honest statement of which datasets and features are present.

## Success criteria
- Each dataset is present and complete, or its absence is documented with exact manual steps.
- Inventory numbers (subjects, recordings, exclusions) come from reading the actual files.
- Sampling frequencies and timestamp formats are measured from the data, not assumed.
- Every feature required by the brief is marked available or unavailable per dataset.
- Raw files are unchanged (sizes and file lists match the sources).
