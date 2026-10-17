# SIBRC on VTM-RC@VVenC: design for review

Source: chapter5_SIBRC_TIP.tex supplied by the user. Its experimental tables are claims to evaluate, not measurements from this platform.

## Goal and baseline

Implement the chapter's conditional-information-bottleneck CTU controller as an optional layer after the unchanged VTM RC decision, before VVenC CTU coding. Default-off must retain anchor bitstream and feedback trace exactly. Preserve native VVenC RC and mechanically extracted VTM RateCtrl arithmetic. Use an isolated feature worktree from the validated compatibility branch, without other research changes.

## Recommended implementation

1. Preanalyse each picture using nonoverlapping 32x32 luma residual blocks and a deterministic bounded integer motion search against available reconstructed reference pictures. Record reference choice/search settings. Specify a deterministic intra fallback rather than assume an unavailable reconstructed reference. Normalize 10-bit residuals to the training scale.
2. Compute effective information from frequency variance, spherical target variance, rounded horizontal support floor(32*cos(latitude)+0.5), and activated IB relevance. Use beta=5, with zero relevance below rho^2<=1/beta and finite guards near rho^2=1. CTU information is the mean of block contributions. Do not silently reuse the old 16x16 eta-adjusted implementation.
3. Load frozen six-coefficient log-quadratic R and D models with feature order [1, ln Q, ln I, ln Q*ln I, (ln I)^2, (ln Q)^2]. Define QP-to-Q mapping and whether R denotes bits or bpp in model metadata. Calibrate on independent development sequences, excluding AerialCity evaluation frames. Record training provenance, domains, normalization and held-out fit errors. Existing VTM coefficients may be diagnostic comparators only when their feature definitions match.
4. Get baseline QP/lambda from VTM. Use finite integer QP offsets, initially [-2,2], configurable and frozen before evaluation. Filter nonzero actions by the chapter's rate/distortion monotonicity conditions. Current CTU uses its VTM QP; future CTUs use picture QP. Solve the remaining predicted budget with a nonnegative bit price, feasible-side bisection, deterministic tie breaks and infeasible-budget fallback to the baseline. This is a discrete approximation, not a claim of globally optimal allocation.
5. Apply QP=QP0+a and lambda=lambda0*2^(a/3). Feed actual bits, actual CU QP and applied lambda to the original VTM controller. Compute actual spherical weighted luma distortion from reconstructed pixels for the independent SIBRC predictor. Do not replace VTM's original distortion feedback semantics.
6. Update per-picture log R/D correction using bounded smoothing. The chapter's residual is against the corrected prediction; reproduce that definition explicitly. Initialize both corrections to zero. Guard zero bits/distortion and log-domain singularities; trace guard/fallback rates. Actual CTU bits debit the budget once only.

## Source gaps and alternatives

The chapter omits numerical R/D coefficients, motion-search settings, action bounds and smoothing bounds. References to rho, spherical target variance and frequency multiplicity are not fully specified by the supplied chapter; related thesis chapters alone do not supply a complete X-Y cross-covariance construction. Resolve these definitions from matching author code/data, or explicitly document independent calibration and adaptations. Do not invent a geometric rho formula and call it an exact reproduction.

Alternative A (recommended): chapter-faithful controller with independently calibrated missing models. Alternative B: mechanically port the existing VTM experimental implementation, documenting its 16x16/eta deviations. Alternative C: simple information-weighted allocation, useful as an ablation but insufficient to represent the full attached method.

## Validation and performance experiment

Unit tests: IB activation/finite boundary behavior; model feature ordering; valid-action filtering; bit-price monotonicity and discrete feasibility; QP/lambda mapping; corrected-prediction bias update; zero/infeasible fallback; one feedback per decision. End-to-end disabled-feature anchor identity; ordered CTU trace; real distortion and bit accounting; deterministic repeat; decode/reconstruction equality.

First smoke: AerialCity ERP 3840x1920, LDP16, four existing targets 1.6/3.2/6.4/12.8Mbps. Run paired anchor and SIBRC using identical binary/config apart from the switch. Strong first-I overshoot at low rates is already documented; do not edit VTM initialization to hide it.

Main fast evaluation: AerialCity ERP LDP128, four targets derived from same-platform constant QP22/27/32/37 runs, then freeze targets for both methods. Add held-out ERP content after initial validation. Hold faster preset, CTU128, QPA off and serial feedback fixed. Report actual whole-file rate, RC rate, mean Y-PSNR and ERP Y-WSPSNR, rate error, CPU/elapsed time, QP/actions/fallback distribution. BDBR uses actual rates, overlapping quality range and shape-preserving interpolation, with no extrapolation. Primary objective is negative WSPSNR BDBR; plain Y-PSNR is secondary and cannot be substituted when WSPSNR regresses. Report failures and confidence/scope honestly; gain is an objective, not guaranteed output.

Ablations: no SIBRC, SATD replacing effective information, geometry-only, full SIBRC; distinguish tuning/dev from held-out evaluation. Do not select favorable points or mix training/evaluation sequences to obtain a negative result. Full14-sequence RA/LDP thesis replication is beyond the initial screening stage.

## Current state

User approved chapter equations with independent calibration. Implementation is underway on codex/sibrc-vtmrc-vvenc in the same isolated checkout. Scalar frequency multiplicity is1. Offline paired statistics use local horizontal area-resampled residuals over the same physical footprint, orthonormal DCT-II /sqrt(pixels), raw centered Pearson correlations and target/planar variance ratio, with explicit numerical caps. This resolves an underdetermined cross-covariance in the manuscript; it is an operational local spherical sampling proxy, not a recovered author joint-covariance table.

Online planar variance is measured centered residual sample variance times separable stationary-covariance DCT diagonals /1024, using measured adjacent correlation clipped0..0.99 and quantized0.01. The supplied SAD estimator lacks numeric calibration parameters; this variance substitution is explicitly disclosed. Coarse/fine search and intra128 fallback are frozen in tools/sibrc/README.md. All source picture groups remain together across QPs in fitting and held-out diagnostics; source sequence identity is validated per CSV row.

Control currently enforces10bit internal luma rather than permitting hardcoded negative QPs at other bit depths. Model .I/.P identities are checked at load. Mode2 fixed-QP calibration rescales the original VTM lambda according to the declared QP-offset mapping; this is not a claim of native CQP lambda schedule equivalence. Mode2 without a calibration override must remain bitstream-identical to anchor.
