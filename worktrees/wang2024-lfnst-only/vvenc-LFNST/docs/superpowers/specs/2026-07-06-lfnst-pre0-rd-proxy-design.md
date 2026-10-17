# LFNST Pre-J0 Differential RD Proxy Design

## Goal

Build a deployable `B_pre0` model that predicts the full-RDO differential gains

`DeltaJ_l = J0 - Jl`, for `l in {1,2}`,

using only information available before the `J0/J1/J2` candidate loop. When both non-zero candidates are conservatively predicted to have no gain, the encoder may reduce `{0,1,2}` to `{0}` before any candidate RDO starts.

The work has two phases:

1. collect and validate strictly pre-J0 features in shadow mode, then fit and audit the proxy offline;
2. export Safe, Main, and Aggressive gates and run real encoding validation.

No post-J0 gate is part of this design.

## Information boundary

Training labels come from complete candidate RDO:

`DeltaJ_l_true = J0 - Jl`.

All model inputs are frozen before entering the LFNST candidate loop. The feature path must not read:

- `J0`, `J1`, or `J2`;
- actual candidate quantized coefficients;
- CABAC bits or contexts produced by a candidate;
- reconstructed candidate residuals or distortion;
- `actualY*`, `distCost*`, or any equivalent post-candidate field.

The encoder stores the frozen feature record before `J0` and appends the full-RDO labels only after the loop. The log schema identifies the feature timing as `pre0`.

The first implementation deliberately computes an isolated probe rather than moving or sharing existing RDO state. This may repeat one primary transform in shadow mode, but makes the timing boundary testable and prevents the probe from changing the baseline coding path.

## Probe architecture

### Placement

The probe runs after the current intra mode, TU geometry, LFNST set, transpose flag, prediction, and residual are known, but before the `lfnstIdx=0,1,2` loop.

Only supported luma TUs enter the probe. Unsupported shapes, transform modes, ISP/MIP cases, unavailable prediction buffers, or any arithmetic mismatch fall back to the complete candidate set.

### Primary transform

The probe computes the primary-transform low-frequency vector `x` from `E=org-pred` using the transform type and integer arithmetic that a non-zero LFNST candidate will use. It must not blindly reuse the no-LFNST result because implicit-MTS behavior for `lfnstIdx=0` can differ from the non-zero-candidate primary transform.

The probe is exposed through a read-only `TrQuant` interface. It owns separate scratch storage and must not overwrite coefficient buffers, transform caches, CABAC state, TU flags, or reconstruction buffers.

### Candidate projection and pseudo quantization

For each non-zero candidate, the probe computes

`z_l = S_l x`

with the encoder's integer LFNST matrix, shift, rounding, scan order, zero-out count, set, and transpose semantics.

It then computes a scalar pseudo-quantized vector

`qhat_l = round(z_l / Qstep)`.

The baseline proxy uses `z_0=x` and the same scalar pseudo quantizer. This is named **matrix-exact scalar pseudo quantization**: the primary/LFNST arithmetic is exact relative to the candidate path, but the scalar quantizer is not claimed to reproduce RDOQ, dependent quantization, or CABAC decisions.

### Arithmetic parity audit

In shadow collection, the encoder compares the frozen probe `x` and `S_l x` against the actual primary-transform LFNST input and LFNST output later produced by each full-RDO candidate. Equality is checked element by element with explicit dimensions and identity fields.

Rows with any parity mismatch are reported but excluded from model fitting. Real pruning is disabled for any runtime sample that fails the same eligibility or identity checks.

## Feature bank

Each training sample is `(TU,l)` for `l in {1,2}`.

### Residual features

- residual variance `sigma2_res`;
- horizontal and vertical correlations `rho_h`, `rho_v`;
- `rho_h-rho_v`;
- `latBin` and absolute latitude.

### Primary low-frequency features

- `Ex = sum_i x_i^2`;
- pseudo-quantized `x` non-zero count;
- pseudo last position;
- `sum_i log(1+abs(qhat_0_i))`.

### Candidate differential pseudo-quant features

- `deltaDhat_l = Dhat_0-Dhat_l`, where `Dhat_l=sum_i(z_l_i-Qstep*qhat_l_i)^2`;
- `lambda*deltaNnz_l`;
- `lambda*deltaLast_l`;
- `lambda*deltaNcg_l`;
- `lambda*deltaLogLevel_l`;
- `lambda*deltaNgt1_l`;
- `lambda*deltaNgt2_l`.

Coefficient-group and last-position definitions use the same retained response order in training and online inference.

### Theory features

- `O_x`;
- `chi_diag`;
- candidate `G_l_resp`;
- candidate `U_l_offplus`;
- `G_l_resp-G_0_resp`.

Theory features are lookup values indexed by the same block geometry, latitude model, set, transpose flag, response dimension, and scan identity used online. Offline joins and online lookup must resolve to the same table entry. Missing entries cause a full-RDO fallback.

### Context features

- QP as a continuous value and optionally a coarse bin;
- `log2W`, `log2H`;
- `modeGroup`, `setIdx`, `transpose`, `candidate`.

Exact QP is not part of the group-bias key. This avoids an unseen-QP fallback reproducing the earlier QP34 failure.

## Models

The first study compares three transparent candidate-level regressors:

1. global Ridge;
2. boundary-weighted Ridge, with larger weight near `DeltaJ_l_true=0`;
3. Huber regression.

The main structure is global slopes plus hierarchical group bias. The most specific bias key is

`(W,H,modeGroup,setIdx,transpose,latBin)`.

When a group is underfilled or unseen, inference backs off through progressively broader keys and finally a global bias. The model implementation records which fallback level was used.

The feature allowlist is explicit. The fitter rejects unknown post-RDO feature names rather than silently accepting all numeric columns.

## Validation and safety margins

The target collection set is at least AerialCity, DrivingInCity, and Harbor at QP 19, 24, 29, and 34 over multiple frames.

Every outer validation run separates:

- training data for fitting slopes and biases;
- calibration data for selecting one-sided margins;
- test data for final reporting only.

Required outer audits include leave-one-sequence-out, leave-one-QP-out, and held-out-frame validation. No threshold or margin is retuned on the test partition.

For TU `b`, define the one-sided maximum underprediction error

`u_b = max_l(DeltaJ_l_true - DeltaJhat_l)`.

Margins are calibrated from this TU-level quantity, not from mean candidate error. Margin keys use hierarchical fallback when sample counts are insufficient.

The online skip rule is

`max_l(DeltaJhat_l + m_g) <= 0  =>  {0,1,2}->{0}`.

Three margin profiles are exported:

- Safe: target validation risk at or below 1%;
- Main: target validation risk at or below 3%;
- Aggressive: target validation risk at or below 5%.

These risk levels are calibration targets, not hard go/no-go constraints. Main coverage, aggregate test risk, per-QP risk, QP34 risk, and per-size risk are monitored and reported. They do not block shadow or real encoding validation in the first exploration. Later tuning may introduce deployment constraints after empirical TS/BD behavior is known.

The only hard correctness requirements before real pruning are:

- every inference feature is demonstrably available before `J0`;
- the probe passes the required arithmetic/identity checks;
- unsupported or unknown cases fall back to `{0,1,2}`.

## Boundary error analysis

For `e_l=DeltaJ_l_true-DeltaJhat_l`, report by QP, size, latBin, and set/transpose:

- sample count;
- mean error;
- P95 and P99 one-sided error;
- predicted-skip count and coverage;
- false-skip count;
- `P(max_l DeltaJ_l_true>0 | predicted skip)`;
- margin fallback level.

The same report is produced for Safe, Main, and Aggressive profiles. Sparse groups remain visible and are not silently dropped.

## Outputs

Shadow collection produces:

- a pre0 feature/full-RDO label CSV;
- a probe-versus-actual parity CSV or compact parity columns;
- eligibility and fallback counters;
- probe time counters separated into primary transform, LFNST projection, pseudo quantization, theory lookup, and prediction.

Offline fitting produces:

- split-level R2, AUC, top-1, coverage, and risk metrics;
- `boundary_error_by_qp.csv`;
- `boundary_error_by_size.csv`;
- `boundary_error_by_latbin.csv`;
- `boundary_error_by_set_transpose.csv`;
- Safe/Main/Aggressive model and margin tables;
- an explicit feature/timing manifest.

Real encoding produces per-profile:

- wall-clock time saving;
- Y/U/V BDBR and bitrate deltas;
- gate invocation, skip, fallback, and parity-failure counts;
- measured pre0 gate overhead;
- metrics by QP, size, latitude, set, and transpose.

## Implementation phases

### Phase 1: strict pre0 shadow collection

Add the isolated probe, pre-loop call site, frozen feature record, after-loop label append, parity audit, and timing counters. Verify that shadow mode produces identical bitstreams to baseline.

### Phase 2: offline fitting and audit

Build the dedicated `B_pre0` fitter with an explicit deployable feature allowlist, Ridge/weighted-Ridge/Huber comparisons, hierarchical bias and margin fallback, strict train/calibration/test splits, and boundary reports.

### Phase 3: remote data collection

Collect the multi-sequence, multi-frame, four-QP dataset on the remote server. Run parity and feature-timing audits before accepting rows for fitting.

### Phase 4: real three-profile validation

Export the selected model family and Safe/Main/Aggressive margins into compact encoder tables. Enable real `{0,1,2}->{0}` pruning only for eligible, parity-safe samples and measure TS/BD plus gate overhead.

### Phase 5: optimization

Only after real validation, consider caching the pre0 primary transform for reuse by the normal candidate path. This optimization is separate from the correctness study and must retain bit-exact regression tests.

## Testing

- Static/source tests verify that the pre0 call is before the LFNST candidate loop and that post-RDO fields are absent from the feature interface.
- C++ probe tests cover transform identity, scan/transpose/set selection, response dimensions, zero-out behavior, pseudo-quant boundary rounding, and unsupported fallback.
- Shadow smoke encodes compare bitstreams and RD summaries against baseline.
- Runtime parity tests compare probe and actual `x/S_lx` element by element.
- Python tests cover feature allowlisting, leakage rejection, candidate labels, hierarchical bias fallback, train/calibration/test isolation, one-sided margin calibration, risk/coverage, and boundary tables.
- Remote smoke runs precede full collection and real encoding sweeps.

## Success interpretation

The first exploration does not require a minimum Main coverage or a hard per-QP risk threshold. Results are interpreted jointly:

- offline coverage/risk indicates statistical promise;
- arithmetic parity establishes deployability;
- real TS measures whether early pruning repays probe cost;
- BDBR measures practical safety.

If coverage is low or QP34 risk is high, those observations guide later feature, grouping, or margin refinement. They do not justify reintroducing post-J0 features into `B_pre0`.
