# Result file roles

The authoritative final results are `assessment.json`, `frames.csv`, and the eight `rc300_anchor_R1.json` ... `rc300_full_R4.json` point files. Read the Chinese `report_zh.md` or English `report.md` for conventions and conclusions.

`*.native.json`, `*.spsnr_corrected.json` and their provenance sidecars are intermediate evaluator records. At R1 only, the native record supplies the independent legacy CPP values; its S values are not used in final results. All 300 final R1 S values come from the corrected evaluator. R1 CPP values match fresh corrected evaluations exactly at frames 0, 150 and 299. All S/CPP values at R2-R4 use the corrected evaluator.

`corrected_parallel_equivalence_actual3.json` records the initialized evaluator's exact scalar/three-worker comparison on real ERP frames. Older `actual3_*` and `parallel_equivalence_actual3.json` files precede the initialization repair and are historical diagnostics. Evaluation timing under concurrent load is not encoding time.

The original eight encoded streams and original encoding time records remain in the parent experiment directory. No stream was re-encoded for this evaluation. All final reconstruction hashes and Y/WS arrays match the original experiment; failed I-disk evaluation pilots are excluded from results and coding-time comparisons.
