# Saldanha2022 retrained VVenC LFNST-only implementation plan

User approved retraining on 2026-10-06. Execute continuously using subagent-driven-development for independent tooling, with parent integration and review.

Goal: add an auditable LFNST decision tree comparison and run the frozen comparison contract.

Architecture: start from the verified Windows formal source snapshot; insert a causally available per-intra-candidate baseline feature snapshot into VVenC's native transform search. Keep native TS/MTS ordering. This is a declared adaptation of the paper's VTM search scope, not original-model equivalence. Train actual WEKA REPTree with max depth8 on planar sequences; export full-precision nodes and infer in C++. Off/collect/shadow/on modes are selected by environment per standalone encoder process to avoid changes to public configuration ABI.

Tech stack: C++11, VS2019 Release /utf-8 LTO OFF, Python standard library, Java/WEKA, existing 360Lib evaluation runner.

- [ ] Import source/include differences from backups/S123AB_rebuild_20261004/src, record hashes, build unmodified off baseline.
- [ ] Add tests for full-precision numeric splits, class ties, malformed model rejection, missing/nonfinite fail-open, and wrong-skip accounting. Compile missing header test to establish failure before implementation.
- [ ] Implement source/Lib/EncoderLib/SaldanhaLfnst.h: validate and load node model once; immutable inference; synchronized bounded feature CSV and aggregate counts; environment mode validation. Missing model in on/shadow is an error, never a silent no-op.
- [ ] In IntraSearch.cpp capture all13 features after finite baseline luma RDO and before nonzero LFNST; sum quantized luma coefficients across valid TUs for ISP. Gate only nonzero LFNST loop candidates with continue, preserving save/restore endpoints and native MTS heuristics. Label collection using final bestLfnstIdx in that same search.
- [ ] Implement tools/saldanha2022 training/export CLI with deterministic balancing, explicit sequence split and hard ERP14 exclusion; train genuine WEKA REPTree and verify exported predictions including boundaries.
- [ ] Use original available Kimono/ParkScene plus disclosed planar substitutes if remaining original eight sources are absent; reserve a full sequence for validation, freeze model before any ERP comparison. Record first-frame scope and source hashes.
- [ ] Smoke test off versus original baseline and off versus collect/shadow bitstreams; test actual on-mode candidate suppression and decode or independent reconstruction validity.
- [ ] Add resumable matched experiment runner using formal config snapshot and 360Lib metrics, paired anchor/on per repeat, explicit manifests and non-overwriting result roots. Dry-run contract validation before launch.
- [ ] Run pilot four-QP AI and complete/launch formal14 sequence AI/RA/LD comparison as resources permit; record actual run state and never report pending jobs as measured.
- [ ] Independent spec/code review, fix findings, verify tests and commit isolated branch. Final report contains measured results and any remaining active experiments.

Concrete verification: C++ test executable must print PASS; `python -m unittest discover -s tools/saldanha2022 -p 'test_*.py'` must pass; smoke bitstream SHA256 must match; every completed metric cell must have its original encoder and360Lib logs.
