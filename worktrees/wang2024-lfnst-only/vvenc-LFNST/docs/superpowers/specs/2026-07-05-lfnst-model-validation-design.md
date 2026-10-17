# LFNST Residual Model Validation Design

## 1. Objective

Add two lightweight model-validation experiments to the LFNST study:

- Experiment 4.1 validates whether the ERP latitude-conditioned horizontal
  prediction-residual correlation model matches encoder residual statistics.
- Experiment 4.2 validates whether the theoretical low-frequency covariance
  table approximates real DCT-II low-frequency covariance and whether its
  response metrics explain real LFNST rate-distortion gain.

This is not the formal parameter-calibration experiment specified in
`docs/superpowers/specs/2026-07-01-task-a-covariance-calibration-design.md`.
It uses two to four representative sequences, QP 22/27/32/37, and one to four
frames per sequence/QP. Its purpose is to establish statistical consistency,
not BD-rate or production speedup.

## 2. Sample Population

Each sample corresponds to one LFNST-eligible luma TU evaluated by the complete
anchor RDO loop. It is a TU-level paired sample, not one row per LFNST
candidate. Each sample contains the no-LFNST pre-transform prediction residual
and the three candidate costs `J0`, `J1`, and `J2` paired under one `sampleId`.

The diagnostic encoder runs with `LFNST=1`, `LardLfnstSkip=15`, and support
zeroing disabled. Skip15 remains a shadow measurement in this configuration;
it does not prune the LFNST candidate loop. Logging must not change candidate
availability, RDO order, selected syntax, or the output bitstream.

The spatial residual is

```text
E(i,j) = org(i,j) - pred(i,j)
```

captured before the primary transform. Original image blocks, reconstructed
residuals, and quantized coefficients are not substitutes for this sample.

## 3. Encoder Instrumentation

### 3.1 Stable sample pairing

A unique 64-bit `sampleId` is created once before evaluating the LFNST
candidate set of an eligible TU. The same ID is retained for all
`lfnstIdx=0/1/2` RDO evaluations of that TU. It is unique within one encoder
process. The same ID is written to:

- `empirical_lfnst_vec.csv`, which stores the no-LFNST primary-transform
  low-frequency vector;
- `motivation_cov.csv`, which stores residual statistics and final paired RDO
  costs.

The runner records a `runId` containing sequence, configured QP, and input
identity. The analyzer joins each sibling log pair by `sampleId` before
concatenation and uses `(runId, sampleId)` as the global key. It rejects
duplicate IDs within a run, missing counterparts, or one-to-many joins. It
does not silently drop unmatched rows.

### 3.2 Center latitude

The TU center latitude is

```text
yc = y0 + H / 2
theta_B = (1/2 - yc / pictureHeight) * pi
absLatDeg = abs(theta_B) * 180 / pi
```

The existing `xLahtpStage1GeomCached()` implementation already uses this
definition. The experiment uses `absLatDeg`, not the top-left position and not
the maximum latitude spanned by the block.

### 3.3 Block residual statistics

Before entering the transform loop, compute the residual mean and centered
residual:

```text
meanE = sum(E) / (W H)
Ec(i,j) = E(i,j) - meanE
```

The horizontal and vertical adjacent correlations are:

```text
rho_h = sum Ec(i,j) Ec(i,j+1)
        / (sqrt(sum Ec(i,j)^2 * sum Ec(i,j+1)^2) + eps)

rho_v = sum Ec(i,j) Ec(i+1,j)
        / (sqrt(sum Ec(i,j)^2 * sum Ec(i+1,j)^2) + eps)

sigma2_res = sum Ec(i,j)^2 / (W H)
```

Each denominator uses exactly the samples appearing in its numerator. Blocks
with non-finite values or effectively zero directional energy are marked
invalid for that directional statistic instead of being forced to zero.

The following fields are added to `motivation_cov.csv`:

```text
sampleId,rho_h_block,rho_v_block,sigma2_res
```

Both traces explicitly carry the LFNST input identity needed to audit the join
and matrix coordinates:

```text
intraMode,modeGroup,lfnstSetIdx,transpose,inputVectorDim,scanOrderId,lfnstInputCoordListHash
```

`lfnstSetIdx` is the transform set selected from the intra mode. Candidate
indices 1 and 2 remain represented by their paired costs and response fields;
there is no separate inferred transform-set field. `scanOrderId` identifies
the `sbSize/inputVectorDim/transpose` scan variant, and
`lfnstInputCoordListHash` is a versioned hash of the ordered `(u,v)` coordinate
list produced by the same collection routine used by the encoder. The analyzer
requires exact agreement with the theoretical coordinate list. The same
`sampleId` and identity fields are added to `empirical_lfnst_vec.csv`.

## 4. Experiment 4.1: Spatial Correlation Validation

### 4.1 Grouping

Use exact groups:

```text
sequence x QP x W x H x latitudeBin
```

Latitude bins are half-open except for the final interval:

```text
[0,15), [15,30), [30,45), [45,60), [60,75), [75,90]
```

The primary block shapes are:

```text
4x4, 4x8, 8x4, 8x8, 8x16, 16x8, 16x16
```

Observed shapes outside this list remain in the coverage table but are not
used in the primary figure. A group with fewer than 200 valid samples is shown
as underfilled and excluded from aggregate claims.

### 4.2 Model fitting

The model is

```text
rho_h_model(theta) = rho0 ** cos(abs(theta))
```

Two estimates are reported:

1. The primary estimate uses the median empirical horizontal correlation in
   the `[0,15)` bin as `rho0`. A slice is excluded from model-curve fitting if
   this value is not strictly inside `(0,1)`, but it remains in empirical trend
   reporting. The estimate is not clipped into the valid interval.
2. A diagnostic weighted least-squares estimate minimizes squared bin-level
   error with group sample counts as weights and constrains `rho0` to
   `(eps,1-eps)`.

The full-data fit is diagnostic only and is not used to make the primary
model-validity claim.

### 4.3 Reported metrics

For every admitted QP/block-size slice, report:

- Spearman correlation between absolute latitude and empirical `rho_h`;
- Spearman correlation between absolute latitude and empirical `rho_v`;
- horizontal model mean absolute error;
- group mean, median, 95% bootstrap confidence interval, and sample count for
  `rho_h` and `rho_v`;
- the primary directional contrast `deltaRho = rho_h - rho_v`;
- the auxiliary ratio `rho_h / rho_v` only where `abs(rho_v) > eps`.

The expected evidence is a clearer positive latitude trend in `rho_h` than in
`rho_v`, with `deltaRho` providing the primary directional heat-table value.
The analysis must report a negative or content-dependent result if that
contrast is absent.

## 5. Experiment 4.2: Low-Frequency Covariance Validation

### 5.1 Theoretical propagation

Retain the existing theoretical chain:

```text
rho_h(theta) -> Sigma_E(theta) -> Sigma_F(theta) -> Sigma_x(theta)
```

For the fixed visualization experiment use:

```text
rho0 = 0.6
rho_ver = 0.6
sigma_e2 = 1
theta = 0, 30, 60, 75 degrees
block size = 4x4, 8x8, 16x16
```

The primary paper figure shows the 8x8 matrices. The 4x4 and 16x16 matrices
are supplementary. Heatmaps use a common scale within each matrix type across
latitude. The claim is systematic covariance reorganization, not monotonic
growth of every off-diagonal term.

### 5.2 Empirical covariance

Join vector and RDO logs by `sampleId`, then group by:

```text
sequence x QP x W x H x modeGroup x lfnstSetIdx x transpose x latitudeBin
```

For each admitted group, use its actual mean absolute latitude when generating
the theoretical covariance. Do not convert the encoder's coarse `latBucket`
to one of `{0,30,60,75}`.

For low-frequency vector `x_n`, compute the mean-centered MLE raw covariance
specified by the experiment:

```text
Sigma_x_emp_raw = (1/N) sum_n (x_n - mean(x)) (x_n - mean(x))^T
```

The `1/N` normalization is intentional and retained from the stated
experimental definition. Frobenius cosine, correlation-normalized `O_x`, and
diagonal dominance are invariant to this global scale. The report labels this
matrix as an MLE covariance and does not present it as an unbiased estimator.

For group mean latitude `theta_g`, construct the theoretical effective-support
operator `D_K(theta_g)` in the exact logged LFNST input coordinate order. The
operator uses the same effective-column rule as the theoretical method. For
the logged coordinate `(u_i,v_i)`, diagonal element `D_K(i,i)` is one when
`u_i` lies inside the effective horizontal support and zero otherwise; all
off-diagonal elements of `D_K` are zero. Then compute both empirical and
theoretical effective covariance:

```text
Sigma_x_emp_eff = D_K(theta_g) Sigma_x_emp_raw D_K(theta_g)
Sigma_x_th_eff  = D_K(theta_g) Sigma_x_th_raw  D_K(theta_g)
```

The primary paper result compares effective covariance because it matches the
latitude-conditioned effective support used by the Stage-2 model. Raw
covariance consistency is retained as a supplementary control. A covariance
group is admitted only when:

```text
N >= max(200, 5 K)
```

where `K` is `inputVectorDim`. Underfilled groups remain in coverage outputs
but are excluded from covariance-consistency claims. The vector dimension is
the valid LFNST input dimension recorded by the trace. `lfnstSetIdx` and
transpose remain in the group key because the transform set and scan order
change the matrix coordinates.

### 5.3 Covariance metrics

The Frobenius cosine is

```text
simF = <Sigma_emp, Sigma_theory>_F
       / (||Sigma_emp||_F ||Sigma_theory||_F + eps)
```

The off-diagonal coupling strength is computed from the covariance-normalized
correlation matrix `R_x`:

```text
O_x = sum_{i != j} abs(R_x(i,j)) / (K (K - 1))
```

The implementation averages all ordered off-diagonal entries exactly once.
`O_x` is not required to increase monotonically with latitude. Diagonal
dominance is also reported to capture energy redistribution not summarized by
`O_x`. Every covariance metric is reported separately for raw and effective
matrices, with effective results designated as primary.

### 5.4 Latitude-shuffle baseline

Shuffle latitude labels only within matching
`sequence/QP/W/H/modeGroup/lfnstSetIdx/transpose` strata. The empirical
covariance group remains unchanged; only the latitude used to generate the
theoretical covariance and effective-support operator is permuted within the
same non-latitude stratum. Use a deterministic seed and repeated permutations.
Report the correct-latitude score, shuffled score distribution, paired
difference, and permutation p-value. Missing latitude groups are not
synthesized.

### 5.5 Link to real LFNST gain

Define per-sample gain as:

```text
deltaJmax = max(J0 - J1, J0 - J2)
normalizedGain = deltaJmax / (abs(J0) + eps)
```

Generate the theoretical response for each group's actual mean latitude,
exact dimensions, LFNST set, and transpose. Validate `Gmax_resp` and
`Umax_off+` using:

- Spearman correlation with raw and normalized gain;
- response-quantile by latitude heat tables;
- ROC AUC for `positiveGain = I[deltaJmax > 0]`, with a bootstrap confidence
  interval and `NA` for a one-class slice;
- candidate top-1 match between the larger candidate-specific theoretical
  response and `argmax_l(J0-Jl)` for `l in {1,2}`, reported against the
  empirical majority-candidate baseline and with ties reported separately;
- sample counts in every displayed cell.

Scatter plots may be emitted as supplementary diagnostics but are not primary
figures.

## 6. Outputs and Figure Layout

The selected layout is the main/supplement hybrid with two composite primary
figures.

Primary figures:

- `fig_4_1_model_validation_overview`: block-size facets showing horizontal
  and vertical latitude trends with 95% confidence intervals, a `deltaRho`
  heat table, and a compact Spearman-H versus Spearman-V summary;
- `fig_4_2_covariance_response_validation`: 8x8 theoretical covariance
  propagation, representative 0-degree and 60-degree empirical/theory
  effective matrices, correct versus shuffled similarity heat tables, and the
  response-quantile versus normalized-gain heat table.

Supplementary outputs contain the 4x4 and 16x16 theoretical propagation,
complete QP/sequence/block-size tables, and optional scatter diagnostics.

Machine-readable outputs include:

```text
sample_pairing_audit.csv
spatial_correlation_coverage.csv
spatial_correlation_by_group.csv
spatial_model_fit_summary.csv
covariance_similarity_by_group.csv
covariance_shuffle_summary.csv
response_rd_summary.csv
response_auc_top1_summary.csv
theory_covariance_matrices.npz
empirical_theory_covariance_matrices.npz
model_validation_summary.md
```

`covariance_similarity_by_group.csv` includes a `covarianceKind` column with
`raw` and `effective` values so the two definitions cannot be conflated.

Figures are exported as vector PDF and 600-DPI PNG at IEEE TIP double-column
width. Sequential maps use perceptually uniform, colorblind-safe palettes;
signed covariance maps use a zero-centered diverging palette. Underfilled
cells are gray and cannot be mistaken for zero-valued measurements.

## 7. Error Handling and Integrity Rules

The analyzer fails on:

- missing required columns;
- duplicate `sampleId` values in either input;
- unmatched or one-to-many sample joins;
- inconsistent dimensions or vector lengths;
- mismatched LFNST set, input scan order, or coordinate-list hash;
- non-finite candidate costs in rows admitted to the RD analysis;
- impossible latitude values;
- an output directory containing incompatible stale schema data.

Invalid zero-energy directional correlations and underfilled groups are
reported explicitly but do not abort otherwise valid analysis.

## 8. Verification Strategy

### 8.1 Python unit tests

Cover:

- exact horizontal and vertical block-correlation formulas;
- zero-energy invalid handling;
- center-latitude boundaries and all six bins;
- exact rectangular shape grouping;
- `199/200` sample threshold behavior;
- `max(200,5K)` covariance threshold behavior for `K=16` and `K=48`;
- mean-centered MLE raw covariance and effective-support covariance;
- Frobenius cosine and `O_x` formula;
- non-monotonic theoretical `O_x` acceptance;
- duplicate, missing, and one-to-many `sampleId` rejection;
- stratified deterministic latitude permutation;
- raw and normalized RD gain, positive-gain AUC, and candidate top-1 match;
- scan-order and coordinate-list hash mismatch rejection;
- expected CSV and figure manifest generation.

### 8.2 Encoder smoke test

Run one frame at one QP and verify:

- both logs are non-empty and schema-compatible;
- every retained `sampleId` has exactly one counterpart;
- all valid `J0/J1/J2` candidates were evaluated;
- residual statistics are finite where directional energy is nonzero;
- under deterministic single-thread settings, logging-enabled and
  logging-disabled bitstream hashes match exactly;
- in a multi-thread smoke test, decoded reconstruction MD5 and syntax-level
  summaries match even if scheduling prevents byte-identical bitstreams.

### 8.3 Figure quality checks

Render every primary figure to PNG, then check for missing glyphs, clipping,
overlapping labels, inconsistent matrix scales, unreadable annotations, and
grayscale ambiguity. PDF export occurs only after the rendered preview passes
visual review.

## 9. Interpretation Rules

The report must distinguish three claims:

1. Horizontal prediction-residual correlation changes with ERP latitude more
   strongly than the vertical control.
2. The theoretical covariance captures real low-frequency covariance better
   than a stratified latitude-shuffle baseline.
3. Theoretical response metrics have a positive association with real LFNST
   RD gain.

These are independent tests. Failure of one cannot be hidden by success of
another. The final report states negative, weak, or content-dependent results
directly and does not tune thresholds after observing the test figures.
