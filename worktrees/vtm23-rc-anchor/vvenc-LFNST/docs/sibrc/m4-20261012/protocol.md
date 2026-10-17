# M4 runner protocol

Implementation: `run_m4_20261012.py`; tests: `test_m4_protocol.py`.

The runner starts no encoding on import or without an explicit stage. `--all` is the sequential resumable orchestration entry point, to be launched only after root review. Individual stages are `--collect`, `--fit`, `--validate`; collection and validation support `--smoke`.

Frozen assets live in `.worktrees/m4-20261012`: `encoder-m4.exe`, `ldp.cfg`, `stats.txt`, and root-written `build-approved.json` containing the exact `encoder_sha256`. No historical executable or model is overwritten.

1. Collection smoke uses two frames at DrivingInCity/window0/QP17, and the historical frozen C4 executable. New and historical bitstream and VTM trace hashes must be identical, keyed CTU information must match, and C2/4 must match C3. This records `collection-smoke-approved.json` for the current encoder/stat hashes. Smoke directories are separate from formal collection directories.
2. Full collection has 64 jobs: two development sequences, starts0/64/128/192, 16 frames each, QP17/22/27/32/37/42/47/52. Mode2 labels use VTMTargetBitrate5000000 and explicit calibration QP. Collection features all come from each same encoding. Source/window/localPOC/CTU/requestedQP/actualQP/kind identifies a row; all windows192 are held out. Source file SHA, requested/actual QP, run ID, source sequence, and window start are included in every merged row.
3. Fit refuses incomplete jobs, failed POC checks, or changed outputs. `fit-run.json` freezes common input CSV, stats, calibrator, and model outputs. Existing incomplete model outputs require inspection; a resume cannot silently refit. Eight independent model prefixes are C0..C4/plane/geo/satd.
4. Actual fitted C2/C3 controller replay runs the compiled replay executable over the merged CSV. Its JSON, exit status, model provenance SHA, and replay executable SHA form the controller gate. Failure stops orchestration for root review. A mere prediction-equivalence diagnostic is never treated as controller equivalence.
5. Validation smoke encodes two frames for anchor and all eight V2 selectors at the first common rate on each validation sequence. It checks intra-contract diagnostics and decodes spherical metrics. Loader-smoke approval is frozen against encoder/model provenance before formal validation.
6. Formal validation uses AerialCity/PoleVault/BranCastle2, native dimensions,64 frames, fixed offset[-2,+2]. Four historical300-frame CQP targets per sequence are explicitly retained with their source path and hash. Anchor plus C0/C1/C3/C4/plane/geo/SATD gives32 streams per sequence,96 encodes total. C2 is merged after replay and is not counted as an independent frequency shape.

At most two encoders run concurrently. Memory admission reserves700MB plus1.3GB per4K or2GB per6K worker, using available RAM at each stage. Decoding and metric evaluation are serial; each metric uses one worker and only one temporary reconstruction exists at a time. Completed job records require matching commands, hashes and POCs; partial outputs are never overwritten automatically.

Each sequence has2048 per-frame CSV data rows (32×64). Three separate spherical BD-rates use actual Annex-B bitrates; Y-PSNR is supplemental. Each method gets its own panels in the original user style with the precise `M4 C0` etc. legend. Assessments, reports and panels are archived separately; aggregate arithmetic means contain all three sequences. Historical validation sequences are called independent of calibration, not blind tests. No tuning against validation results is performed.

Verification performed before handoff: five unit tests passed; CLI help checked. No batch encoding was launched by this agent.
