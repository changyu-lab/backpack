# Independent SIBRC tools

Run tests: `F:/Anaconda/python.exe -m unittest discover -s tools/sibrc -p "test_*.py"`.
Dependencies: NumPy and SciPy (DCT-II and PCHIP). The currently installed SciPy emits a version-range warning for NumPy 1.24.4; tests pass but use compatible pinned versions for archival reproduction.

## Statistics

`python tools/sibrc/calibrate.py stats --input residuals.bin --metadata provenance.json --output stats.txt`

The dump contains consecutive 32x32 row-major little-endian doubles, no header. Values must be residuals from the same prediction as C++ feature extraction, in 8-bit sample units; pass `--residual-scale 0.25` only for unnormalized 10-bit residuals. Metadata must have `sequences: ["DrivingInCity", "DrivingInCountry"]` (or a nonempty subset). Include source filenames, targets, frame ranges, dump stride, prediction settings, normalization, and exact command in metadata.

For each latitude 0,15,30,45,60,75,85 degrees, horizontally area-resample each residual to M=max(1,floor(32*cos(latitude)+0.5)) samples over the identical footprint. Normalize orthonormal DCT-II coefficients by sqrt(pixel count). Compute centered paired-population covariance and variances across individual raw residual blocks; no averaging of blocks into one sample. rho2=cov(X,Y)^2/(VarX*VarY), g=VarY/VarX. Zero-variance rho2 is zero; absent horizontal coefficients are zero. rho2 cap 1-1e-6 regularizes equatorial perfect correlation; g clamps to [0,1000]. Stats calibration uses the entire development population, separate from model held-out diagnostics. An optional complete-source-frame stats holdout can assess covariance stability in an independently generated dump; it does not substitute coefficient square energy for paired population variance; no evaluation sequences are accepted.

Text format: `SIBRC_STATS_V1`, `7`, then for every node its angle and 1024 lines of `rho2 g`, row-major [v][u]. JSON sidecar records counts, source SHA256, definitions, and regularization. This is an independent controlled-resampling construction, not a claim of recovered manuscript cross-covariance assets.

## Separate I/P RD models

`python tools/sibrc/calibrate.py model --input samples.csv --metadata provenance.json --kind P --output model.P.txt`

CSV columns: poc,ctu,ieff,qp,bits,weighted_mse,area,kind; optional latitude (degrees), run_id, and source_sequence. Every row must identify DrivingInCity or DrivingInCountry in source_sequence, or use that exact source name in sequence when source_sequence is absent. Whole (source_sequence,poc) groups across all QPs/runs form the deterministic final 25% holdout. The fitted model uses the remaining groups only. Filter equatorial samples with `--equator-degrees 15` when required by the experimental setup. Positive bits/distortion only, information floor 1e-12. No I/P fallback: run each kind separately and provide defensible development samples.

Features are [1,x,z,xz,z²,x²], x=(qp-4)*ln2/6, z=ln(max(ieff,1e-12)). Column-scaled least squares with ridge 1e-6 and unpenalized intercept is transformed back to physical feature coefficients. Rate predicts total CTU bits, distortion predicts spherical weighted MSE; the controller multiplies distortion by CTU spherical area. Sidecar includes training domains, whole-picture holdout groups, and held-out log RMSE. No coefficients are inferred from the test sequence.

## Evaluation and recorded execution

`python tools/sibrc/evaluate.py quality --source src8.yuv --recon rec10.yuv --width 3840 --height 1920 --frames 16 --bitstream stream.266 --fps 30 --output quality.json`

Streams planar YUV420 one frame at a time, comparing 8-bit source with little-endian 10-bit reconstruction /4. ERP weights cos(pi*((row+0.5)/height-0.5)). Quality is arithmetic mean of per-picture Y-PSNR / Y-WSPSNR. Actual bps includes the complete Annex-B file. `bd-rate --anchor anchor.json --candidate candidate.json` consumes lists of quality records and integrates PCHIP log(rate) over common quality range only, with no extrapolation. Default quality is Y-WSPSNR.

`python tools/sibrc/experiment.py --manifest jobs.json --output runs.json` executes explicit argument lists without a shell. Manifest contains `jobs`, each with name, command, inputs (hashed before run), outputs (hashed after run), optional trace and expected_pocs, and optional hash_equal pairs (decoder vs encoder reconstruction). Include executable, configs, models, stats, sources in inputs; require output bitstreams and recons. Add explicit decoder jobs for every evaluated stream. Declared outputs must not exist before execution; choose fresh output paths. Captures exact commands, hashes, output, elapsed wall time and return codes; fails on missing output, any POC set different from 0..N-1, decode hash mismatch or failed command. Output records preserve failed runs too.

## Frozen online feature estimator and controller interpretation

Online planar frequency variance uses the observed centered 32x32 residual sample variance multiplied by horizontal/vertical stationary covariance DCT diagonals, divided by1024. Adjacent centered residual covariance estimates each correlation, clipped0..0.99 and rounded to0.01. This substitutes an explicitly documented covariance estimator for the manuscript's SAD-based variance estimator whose numerical parameters were not supplied. Individual frequency multiplicity is1; beta5 and horizontal support round(32cos(latitude)) are fixed. Statistics estimate X/Y cross-correlation and target variance gain independently; gain never multiplies rho² in the IB objective.

Residual prediction uses reconstructed first L0 reference, stride4 SAD, integer displacement coarse[-8,8] step4 followed best-centered[-2,2] refinement bounded[-8,8]. Ties retain the first visited candidate. Intra/no-reference analysis subtracts constant128 in8-bit units. Partial32 blocks replicate border samples. CTU information averages analysis-block contributions; actual spherical distortion weights true CTU pixels only.

Mode0 is off; mode1 dumps every16th32x32 residual block without coding changes; mode2 collects information/bits/distortion without coding changes unless SIBRCCalibrationQP is explicitly set; mode3 controls CTU QP/lambda. Calibration override fixes requested CTU QP, rescales the current VTM lambda by2^((calibrationQP-baseQP)/3), and retains VTM feedback. This is a calibration path using actual VVenC coding, not a claim of the native app's exact constant-QP lambda schedule. Collection CSV records requested and actual inferred QP separately. Native RC remains off; the VTM controller remains active for budgeting and feedback.

Control initially supports10-bit internal luma and both explicit I/P model files. Requested action bounds default[-2,2] and may be set through SIBRCMinOffset/SIBRCMaxOffset. Both bias states start0 perpicture. The chapter's literal corrected-residual EMA is retained; for a constant raw-model multiplicative bias its equilibrium correction is half the log bias, so this formula is not described as an unbiased original-model offset estimator.


## Optional monotonic calibration

Add `--monotonic --equator-degrees 15` to preserve equatorial fit selection while enforcing dlnR/dx <= -1e-6 and dlnD/dx >= 1e-6 throughout the development working domain. The six physical logquadratic coefficients and default unconstrained fit remain unchanged. Column-scaled convex ridge least squares is solved by enumerating all16 active sets of the four affine inequalities and checking primal/dual KKT feasibility. This avoids a reproduced SLSQP line-search failure on expanded development data; the objective and physical coefficients are unchanged. The derivative c1+c3*z+2*c5*x is affine, so constraining the four rectangle corners proves its sign everywhere inside the domain. Solver failure or constraint violation raises an error instead of producing a model.

By default the constraint rectangle is the min/max QP and information over all positive samples of the selected I/P kind in the validated development input, before latitude filtering. Whole (source,poc) train/holdout splitting remains unchanged, and held-out values are never used in the fitting objective; their covariate range only establishes the prescribed working domain. Override the working rectangle explicitly with `--monotonic-domain QP_MIN QP_MAX I_MIN I_MAX`. The sidecar records the constraint domain, source, derivative margin and optimizer, alongside the existing actual training QP/information domains and whole-picture held-out log RMSE. Fit selection and constraint domain are deliberately distinct. No guarantee extends outside the recorded rectangle. Select whether to adopt a frozen constrained model using development diagnostics only.

Local assessment computes original/reconstruction SHA256 while streaming quality samples. It compares reconstructed bytes with the encoder run-record SHA and an independent DecoderApp SHA; this removes redundant multi-gigabyte reads without weakening equality checks. Cached assessment binds source prefix, frame/geometry/fps/target, decoder, trace and run-record provenance.


## Optional final refit on all development samples

`--refit-all` first fits and diagnoses the unchanged whole (source,poc) holdout model, then fits the emitted final coefficients on every permitted development sample of the chosen I/P kind passing the same latitude/positive-value filters. For example, combine `--refit-all --monotonic --equator-degrees 15` after selecting the method using development diagnostics. AerialCity remains rejected regardless of this switch. All QP runs for one source picture remain together during initial validation.

The sidecar retains the original holdout log RMSE and split, and records explicit `holdout_metrics_before_refit`, `holdout_coefficients_before_refit`, `final_fit_samples`, and final QP/information fit domains. These metrics describe the pre-refit model; they are not unseen-data performance of the final all-development model. The final fit uses the same prescribed monotonic working rectangle, automatically covering input development ranges before latitude selection unless explicitly overridden by `--monotonic-domain` (which can prescribe the legal QP range -12..63). The default without `--refit-all` preserves prior coefficients exactly.
