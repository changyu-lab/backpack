# Wang 2024 LFNST-only: reproduction design

Status: paper and configuration resolved; design ready for review. No encoder
implementation or Wang experiment has started. This document supersedes
`docs/wang2024_lfnst_only_reproduction.md` where the preparation record differs.

## Source and isolation

User supplied the five-page paper at
`G:/02_papers/paper5/VVC_Intra_Coding_Complexity_Optimization_Based_on_Early_Skipping_of_the_Secondary_Transform.pdf`.
SHA256: `208b218e4bceab45ead46d96ad7b3caa34a5cc6fd8ab1bee3d17e2476521f140`.
Text extracted from all pages; equations on printed pages 367-368 checked
against rendered pages. DOI: 10.1109/LSP.2024.3350989.

Independent branch `codex/wang2024-lfnst-only` exists at initial base
`43de1271d850d30535b50d128de19fcffb52ca45`. Attach a separate workspace to
that branch for implementation. The original checkout has unrelated edits
and must remain intact. The branch base is not yet the verified formal source;
import and hash the source snapshot used by the reference matrix9 experiment.
This draft is currently in the original checkout and is not committed.

## Verified rules

Let C denote the unquantized DCT-II primary-transform coefficient matrix of
the current TU, with height m and width n. Use the full TU borders, not the
LFNST top-left input region, quantized coefficients, or residual pixels.

```
grad2 = sum(i=1..m-1, abs(C[i,n-1] - C[i-1,n-1]))
grad1 = grad2 + sum(j=1..n-1, abs(C[m-1,j] - C[m-1,j-1]))
TH1   = 100
TH2_1 = max(0, 12.83 * QPstep - 17.375)
TH2_2 = max(0, 12.83 * QPstep - 57.375)

skip LFNST1 iff grad2 >= TH2_1
skip LFNST2 iff grad2 >= TH2_2 OR grad1 <= TH1
```

Preserve inclusive comparisons. Never apply TH1 to LFNST1, reuse TH2_1
for both kernels, or skip LFNST0. Thresholds are frozen before ERP testing.

The paper does not explicitly define QPstep. Use the standard interpretation
`2^((QP-4)/6)`, agreeing with Table I's approximate QP17/27/37/47 values
4.5/14.25/45/144. Use the current coding QP before the encoder's internal
bit-depth offset, and document this mapping as an interpretation rather than
claiming recovery of author source code. No coefficients are normalized by
TU area; the printed equations specify raw sums.

## Implementation boundaries

Recommended approach: port the printed rules into the matched VVenC formal
source. An alternative is a historical VVenC1.8.0 replication, but it cannot
replace the requested same-platform comparison. There is no need for a
trained classifier or tuned heuristic.

Implement independent off/shadow/on modes. Disable custom Lard/Stage1/2/3
pruning in both arms, preserving native MTS/TS/LFNST heuristics and settings.
Scope the new rule to luma LFNST candidates. Capture DCT-II coefficients before
LFNST and quantization, including native cached-transform paths. Never read
a temporary buffer after another transform candidate has overwritten it.

Make separate kernel decisions for the current intra prediction mode and TU.
A skipped candidate must have invalid search cost; do not encode a forced
zero residual. Preserve the original best-mode reconstruction and CABAC
restoration when the final candidate is skipped. Do not inherit blanket
MIP/ISP exclusions from the project's Stage1/2 logic. For multi-TU paths,
evaluate the current TU and stop a rejected candidate through the native
invalid-cost path; do not average gradients or reuse another TU's residual.

Audit counters are optional and bounded, with no trace output in formal
timing. Shadow mode computes decisions without pruning. The core predicate
must be independently testable.

## User-approved experiment configuration

Reference chat: `01a083b4-8fea-78d2-bb77-e9705cfaa2d8`,
title `【重点】通测 + stage3`.
Reference runner: `backups/Stage123_AI_WrongSkip_20261005/matrix9.py`.

User chose the old queue and then explicitly set `repeat=1`:

- fast/medium/slow x AI/RA/LDP; all fourteen ERP sequences.
- QP22/27/32/37; one encoder thread; repeat1.
- AI1 frame; RA16 frames/GOP16; LDP16 frames/GOP8 with the old P-frame cfg.
- Preserve remaining matrix9 encoder options and input metadata.
- Fresh paired anchor and Wang runs on the same host/build/scheduling regime.

Total: 126 sequence/preset/config groups, 504 paired RD points, 1008 timed
anchor/proposed encodes, before separately instrumented transform-time copies.
Do not import Saldanha's different medium/32-thread experiment configuration.

Report total encoding TS, separate transform TS_T if supported by the source,
planar PSNR and 360Lib WS/S/CPP Y BD-BR and BD-PSNR. Reuse the reference
evaluator, sphere data and aggregation. Verify timing-copy bitstreams. Delete
REC YUV only after all quality metrics for it are successfully saved.
Keep new output directories and resumable manifests; do not interrupt other
experiments. Check free space and retain commands, hashes and logs.

The paper used VVenC1.8.0, medium/fast, AI/RA, 65 frames and 22 JVET sequences.
This is a formula-based matched-platform ERP reproduction; slow and LDP are
extensions. Do not claim reproduction of the paper's numerical table.

## Verification and execution

1. Isolate workspace; import and hash formal source; verify disabled baseline.
2. Test gradient extraction and predicate boundaries, QPstep, rectangular TUs,
   transform caching, candidate independence, ISP/MIP and state restoration.
3. Compile. Off versus original and shadow versus off must match bitstreams.
   On must demonstrate real nonzero-LFNST skipping and valid reconstruction.
4. Verify quality evaluation and REC cleanup ordering on a smoke case.
5. Freeze sources/binaries/options; dry-run the 1008-encode matrix; launch the
   resumable paired experiment with disk checks and an independent output root.
6. Report actual completed results and distinguish them from queued/running
   jobs. Do not claim speedup from shadow decisions or missing RD points.

Design review precedes implementation. Formula and experiment inputs are now
resolved; no additional heuristic choice or training-data approval is needed.
