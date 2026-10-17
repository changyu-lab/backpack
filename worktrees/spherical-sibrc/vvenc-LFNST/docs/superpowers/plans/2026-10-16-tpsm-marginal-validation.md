# TPSM marginal temporal-importance validation

User authorized the previously proposed CTU perturbation experiment. Use existing isolated branch.

- Add strict ordered record/replay of picture QP/lambda and final requested CTU QP/lambda; defaults off. Replay must override all decisions, including picture initialization. Perturb exactly one non-intra CTU by +/-1 QP with corresponding lambda factor2^(offset/3). Do not alter any other scheduled decision. Re-encoding may change mode decisions, filtering, motion choices and actual bits; those are included outcomes, not frozen.
- Regression first: parser ordering/dimensions/finite values/exhaustion; zero probe identity; exactly one scheduled action differs; disabled path unchanged. Record/replay and TPSM strength0 must match normal repaired SIBRC bitstreams.
- Remote experiment: AerialCity 4K LDP GOP16 65 frames, R2 target818855bps from300-frame log, frozen v1 models and repairs. Baseline uses TPSM mode2 strength0 to observe time weights without changing SIBRC objective. Verify baseline matches prior65-frame SIBRC R2 bitstream.
- Select twelve CTUs at POC16 across low/middle/high temporal weight strata, without observing perturbation outcomes. Prefer complete valid histories; if insufficient diversity, report and stop rather than manufacture groups. Freeze ids/weights/geometry/information/selection hashes. Run +/-1 QP per CTU.
- Measure original/decoded final reconstruction spherical luma SSE for every frame. Report current-frame and strictly-future-frame error reductions, total bits, affected-frame bits, future coding bits. Future SSE response per unit current-frame SSE change estimates observed temporal amplification; normalize future change by baseline frame MSE as a PSNR-objective sensitivity check. Negative future benefit and negative extra-bit cases remain in output; do not divide by nonpositive cost. Use all frame-global differences to include moving influence and within-frame interactions; do not label them motion-isolated causal derivatives.
- Test whether high weights rank high observed future benefits using Spearman and a permutation null; small stratified one-frame sample is diagnostic, not proof or generalization. Cost-controlled matched CTUs are optional followup, not assumed validated.
- Review, independent decode/hash validation, archive source/tools/commands/metrics and limitations. No model tuning or deployment.

## Pre-outcome feasibility adjustment

Local baseline65R2 matched the prior remote bitstream. POC16 has only1 eligible high-weight CTU, failing the four-per-stratum gate; no probes had been run. Baseline-only diversity audit found POC8 counts26 low/43 neutral/4 high, versus POC16 counts32/37/1. Use POC8 with56 strictly future frames. Other surveyed checkpoints24/32/40/48 are recorded; no perturbation outcome informed this choice. This changes sampling feasibility, not the algorithm or model.
