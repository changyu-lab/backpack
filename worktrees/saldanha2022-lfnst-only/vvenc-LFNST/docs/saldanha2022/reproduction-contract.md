# Saldanha ISCAS 2022 LFNST-only reproduction contract

Date: 2026-10-06. Status: user approved retrained VVenC adaptation on 2026-10-06. See implementation-plan.md and run-status.md for measured progress.

## Scope and source

User requests an independent branch and a comparison method matching the experiments in the chats `【重点】通测` and `【重点】通测 + stage3`.

Branch: `codex/saldanha2022-lfnst-only`, starting at `43de127`. Native isolated worktree: `C:/Users/hitxi/.codex/worktrees/saldanha2022-lfnst-only/vvenc-LFNST`. The original checkout contains uncommitted work and is not switched or reset. This branch point is an isolation starting point, not yet the verified formal anchor source.

Paper: M. Saldanha et al., DOI 10.1109/ISCAS48785.2022.9938000.
Public institution copy: https://repositorio.pucrs.br/dspace/bitstream/10923/24021/2/Fast_Transform_Decision_Scheme_for_VVC_IntraFrame_Prediction_Using_Decision_Trees.pdf
Downloaded PDF SHA256: fcd7d336ce58d8c1d7bacfea8ae207f42c18d17f7ff7c7e86a7394fbd85783bb.

Full text was extracted and read. Sections IV.A, IV.C, IV.D and V establish WEKA REPTree, depth eight, size 123 for the LFNST model, and a decision made after baseline transform evaluation. The paper provides feature descriptions and aggregate results, but does not provide the complete trained tree, its split thresholds, a serialized model, training sample files, or a code URL. Public searches have not located an author implementation. Consequently exact original-model inference cannot currently be implemented from the paper alone.

## Reproduction alternatives

1. Recommended practical alternative, subject to user choice: retrain the paper's method for VVenC, explicitly label every result `Saldanha2022-LFNST-only-retrained-VVenC`. Freeze the training data, sampling, WEKA version/options, seed, and exported tree before test encoding. Never force the trained tree to have 123 nodes or tune against published speedup figures.
2. Author-model port: use an author-supplied model or code with recorded provenance, after feature semantics are reconciled. Currently blocked by the missing model.
3. Original VTM10 replication: useful for historical verification but does not by itself satisfy the user's same-platform comparison with current VVenC. It also needs a model or retraining. Not the primary requested experiment.

The 14 ERP test sequences must not be used to fit or select thresholds. The paper's eight training sources should be sought first; any substitutions require explicit disclosure. The paper does not fully specify sample counts, seeds or balancing order, so retraining cannot be claimed to reconstruct the original tree exactly.

## Implementation boundary after model choice

Implement only the luminance LFNST decision; no learned MTS pruning. Disable project-specific Lard/Stage1/2/3 pruning in both comparison arms. Keep native encoder heuristics and tools at their matched baseline settings. Do not disable MTS globally merely because the learned comparison is LFNST-only.

Audit VVenC's candidate ordering against the paper's completed baseline search before choosing the hook: a per-mode first DCT result is not automatically equivalent to the best baseline result over the prescribed search scope. Extract features only from completed, causally available baseline decisions. Preserve the baseline decision snapshot before nonzero LFNST overwrites CU/TU state. Do not apply an additional blanket MIP/ISP exclusion inherited from the project's Stage12 path without documenting that deviation.

Required feature mapping audit: width, height, area, width/height, multi-type-tree depth, MIP flag, ISP mode, baseline RD cost, distortion, fractional bits, intra mode, nonzero coefficient count, and absolute coefficient sum. Establish fixed-point bit units, quantized coefficient semantics, TU aggregation, and ISP mode encoding from original source evidence or document assumptions. QP is a balancing variable in the paper and is not listed as an LFNST feature.

## Frozen formal comparison configuration

Evidence: `I:/vvenc-LFNST/backups/S123AB_formal_20261005/run_queue.py` and its snapshot `runner/tools/lard_lfnst/run_skip21_stage12_ra_360lib.py`.

- Input root: `I:/Sequences360`, all 14 matching ERP YUVs, original size/fps/bit depth, 4:2:0.
- QPs: 22, 27, 32, 37; preset medium; QPA 0; mtprofile 0; 32 threads; two repeats.
- AI: 1 frame, IntraPeriod 1, GOPSize 1, DecodingRefreshType 1.
- RA: 32 frames, IntraPeriod 16, GOPSize 16, DecodingRefreshType 1.
- LD: 16 frames, IntraPeriod -1, GOPSize 8, DecodingRefreshType 0, PicReordering 0, POC0IDR 1.
- Fresh paired anchor and comparison on the same machine, build, scheduling regime and input frames. A timing value from another build/host is not a valid paired baseline.
- 360Lib 13.6 WS/S/CPP Y BD-rate, ordinary PSNR, bit rate, and matched TS best/median. Preserve per-case commands, configuration, hashes, timing and metric logs.
- AI is closest to the paper's evaluation; RA/LD apply the method only to intra decisions and are explicitly extension experiments.

The separate latest audit uses AI1, repeat1, four QPs and 14 sequences. Transform timing includes forward/inverse primary transform and LFNST, excludes quantization, and uses matched single-thread runs; it must not silently replace the formal 32-thread timing contract. Keep classifier time separate. Shadow decisions measure same-block wrong-skip and must not be presented as actual time savings.

## Acceptance checks and execution order

1. Resolve model provenance and document training/test disjointness.
2. Audit formal anchor source snapshot versus branch HEAD; freeze source and binary hashes before selecting the exact baseline.
3. Verify exported C++ inference against WEKA on boundary and held-out cases, including missing/nonfinite feature policy.
4. Compile independent off/shadow/on modes. Off and non-pruning shadow must produce identical bitstreams on matched smoke cases.
5. Verify actual nonzero-LFNST search suppression, unchanged MTS policy, no chroma scope expansion, and valid decoded output.
6. Run paired four-QP pilot; then the frozen 14-sequence AI/RA/LD matrix. Do not invent missing BD-rate points.
7. Report deviations and results separately from the paper's published numbers; all measured cells remain empty until actual encodes finish.

No model, encoder modification, completed encode, timing gain, or BD-rate result is claimed by this preparation document.
