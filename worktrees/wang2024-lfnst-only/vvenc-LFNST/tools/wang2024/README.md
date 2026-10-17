# Wang2024 LFNST-only comparison

User-approved implementation and remote launch: 2026-10-07.
Paper: IEEE SPL31,366-370, DOI10.1109/LSP.2024.3350989.
This is a printed-formula port, not author source code or a replication of the
paper's original VVenC1.8.0 performance table.

## Implementation

`source/Lib/CommonLib/WangLfnst.h` implements equations1-4. Full DCT-II bottom
and right TU borders are used before LFNST/quantization. TH1=100 applies only
to kernel2. TH2=max(0,12.83*QPstep-17.375/-57.375) for kernels1/2, with
inclusive >=. QPstep=2^((codingQP-4)/6), interpreted from standard QP mapping
and the paper's TableI, without internal bit-depth offset.

Mode environment: WANG_LFNST_MODE=off|shadow|on (default off).
Optional WANG_LFNST_AUDIT writes aggregate counters; optional
WANG_LFNST_VERIFY_PRIMARY checks each decision against an independently
computed full current-TU DCT-II. Neither diagnostic is enabled in formal timing.

Non-ISP reuses the current prediction mode's full primary gradients. If native
LFNST0 uses implicit DST7, a separate DCT-II is computed. ISP computes each
current TU's full DCT-II because earlier sub-TU reconstructions depend on the
kernel. Native LFNST-specific reduced transform borders must not be used.
Native primary-transform >32 zero-out is retained in the full-DCT helper.
Rejected candidates remain invalid; they are not forced zero residuals.
Native best-mode/CABAC restoration and other transform heuristics are preserved.
No blanket MIP/ISP exclusion; no chroma pruning.

## Baseline provenance

The branch starts at43de127, then imports the matched matrix9 source snapshot
from backups/Stage123_AI_WrongSkip_20261005/src. baseline_source_sha256.json
records640 files; the remote original source matched all640 before smoke.
Differences from Git HEAD include this formal baseline import. Only TrQuant.h,
TrQuant.cpp, IntraSearch.cpp and the new WangLfnst.h add the Wang rule relative
to that source. Both arms explicitly use LFNST=1 LardLfnstSkip=0.
Frozen evaluator helpers are imported from that snapshot's runner_tools.tar.gz.

## Verification

See verification_20261007.json for hashes and counts. Remote Release build and
standalone C++ predicate test passed. Five Python contract/resume tests passed.
Full-border and implicit-MTS regressions failed before their fixes and passed
afterwards, with independent per-candidate full-DCT verification.

Smoke: fast/medium/slow AI1 and medium RA16/LDP16. In each, original=off=shadow
bitstream AND reconstruction SHA256. On skips nonzero-LFNST candidates. Native
ISP and MIP coverage verified across presets. VTM independent decoding of the
enabled AI bitstream exactly matches the encoder reconstruction. 360Lib quality
evaluation passed. Independent review reported no substantive remaining findings.

## Remote experiment

Host: rycpu2.9gpu.com:36016.
Root: /data/wang2024_lfnst_only_20261007.
Initial runner PID:1600690; launch confirmed with live AI and RA encoders.
Run: `cd /data/wang2024_lfnst_only_20261007 && python3 -m tools.wang2024.run_matrix`.
Resumable; completion and timing caches include binary/evaluator/option identity.
`--dry-run` writes126 groups/1008 formal encodes. No duplicate active launch.

fast/medium/slow x AI/RA/LDP;14 ERP sequences;QP22/27/32/37;threads1;
AI1 frame, RA16/GOP16, LDP16/GOP8 with P-frame cfg;repeat1. Two workers use
CPUs18/20. Existing experiments remain active. This host is shared, including
another32-thread comparison; timing reports must retain this scheduling context.
Formal and transform-instrumented timings are separate encodes. Instrumented
bitstream hashes must equal formal hashes. REC YUV is removed only after
all360Lib quality metrics and validated manifest are saved. Disk floor8GiB.

Results: results/plan.json, progress.json and per-preset/config/sequence logs,
metrics, manifests, summary.json, extra_metrics.json and complete.json.
No full-matrix performance result is claimed at launch.
