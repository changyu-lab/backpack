# Zhao et al. SPL2022 / VTM23 reproduction

Implementation and first-sequence scope: AerialCity LD16, GOP8, IP=-1, skip0; target rates21449445/5428335/2510730/1369185bps. No other sequences submitted. Native logs reused, never re-encoded for formal results.

## Artifacts
- `SOURCE_BINARY_IDENTITY.json`, `SOURCE_FILES_SHA256.json`, `complete.diff`, `zhao2022_source.tar.gz`, `bin/`: isolated source, complete changes and binaries.
- `extract_zhao2022_features.py`: orthonormal DCT spatial/temporal extraction; coding-domain original before TF.
- `run_zhao2022_ldp.py`: explicit sequence/config/rate runner, PID/command/exit/RSS/time/hash receipts; refuses overwrites and requires resource admission.
- `remote_build_and_run.py`: controlled old36016 deployment/build. Hidden password, no stored credential. `--launch-aerialcity` only after `--shared-slot-confirmed`; otherwise build only. Current SSH key was rejected, so this script has NOT been executed.
- `features/AerialCity`: frozen16×630 CTU features, preprocessed once for all rates.
- `protocol`, `INPUT_PROTOCOL_IDENTITY.json`: historical-log-matched candidate configuration; explicit provenance limits retained.
- `native_points.csv`: four existing Native points and actual-rate errors.
- `formal/AerialCity/run_manifest.json`: PREPARED only, no formal processes started.
- `analyze_results.py`: canonical `paper_evidence/metrics.py` BD-rate, actual rates, monotonicity and common overlap, no extrapolation. Until four completed Zhao receipts exist, `bd_rate.json` says PENDING.

## Build
Isolated checkout: `C:/Users/hitxi/.codex/worktrees/zhao2022-spl-repro/VTM-23.0`, initial import443099753b90c249df89e7e030746a8d41c37192. Existing RC360 switches are explicitly disabled and mutually excluded with Zhao. No canonical source or frozen result modified.

```
cmake -S . -B build_zhao -G "Visual Studio 16 2019" -A x64 -DEXTENSION_360_VIDEO=ON
cmake --build build_zhao --config Release --target EncoderApp --parallel 2
```

Linux source archive supports the same CMake Release/360 build. The remote launcher preserves source hash and validates the existing AerialCity first16-frame input hash before running. Its first batch is conservative single-job admission; concurrent submission must use MASTER's measured shared capacity, not a competing permanent queue.

## Run
Use commands recorded as argument arrays in `formal/AerialCity/run_manifest.json`. Runner supports any explicitly named sequence and four supplied rates; prepare corresponding coding-domain original features first. Formal AerialCity must retain source3840×1920→coding4432×2216,10bit,ERPzero rotation,Y5/C4,TFpast4/future0/strengthFrame8=.2 and historical dynamic viewport856×856.

```
python remote_build_and_run.py --shared-slot-confirmed --launch-aerialcity
```
This needs an actually authorized old-host account/session and MASTER slot admission. Do not send passwords in chat. The default remote source is `/data/360seqFull_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv`.

## Current limitation
Formal four-point results are not available. Local host has about2.7GiB available against prior4K jobs~11.3GiB RSS. Old36016 key authentication was rejected; new11045 is reserved for05. No formal BD-rate can yet be claimed. See reproduction_report.md and MASTER_HANDOFF.md.
