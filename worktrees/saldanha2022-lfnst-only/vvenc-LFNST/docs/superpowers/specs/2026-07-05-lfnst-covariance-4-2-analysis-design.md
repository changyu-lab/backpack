# Experiment 4.2 LFNST Low-Frequency Covariance Validation Design

## 1. Objective

Implement the formal Experiment 4.2 analysis for validating whether the
theoretical covariance propagation

```text
Sigma_E(M,N,theta) -> Sigma_F(M,N,theta) -> Sigma_x(K,theta)
```

matches the real low-frequency input statistics seen by LFNST in VVenC.

The experiment compares theoretical and empirical low-frequency covariance
structure, then checks whether theory-derived response metrics align with real
LFNST RDO gains.

This design intentionally reuses the existing encoder logs instead of adding a
new encoder-side logger.

## 2. Selected Approach

Use the existing two-log architecture:

- `LardLfnst2ndVecFile` provides the pre-LFNST, pre-quantization primary
  transform input vector `x00..x47`.
- `LardLfnstCovLog` provides RDO costs and residual statistics, including
  `J0`, `J1`, `J2`, `bestIdx`, `rho_h_block`, `rho_v_block`, and `sigma2_res`.

The formal 4.2 analysis will be implemented as an offline Python workflow. The
encoder is not changed unless later validation proves the current logs cannot
be joined or grouped reliably.

## 3. Existing Inputs

### 3.1 Vector log

The existing `LardLfnst2ndVecFile` CSV contains:

```text
poc,x,y,w,h,qp,sampleId,intraMode,lfnstSetIdx,inputVectorDim,
scanOrderId,lfnstInputCoordListHash,lfnstSet,sbSize,zeroOutSize,
trSize,transposeFlag,absLatDeg,thetaMaxDeg,modeGroup,sizeGroup,
latBucket,sbClass,inputEnergy,x00,...,x47
```

The `x00..x47` values are the primary-transform low-frequency coefficients
before LFNST and before quantization. Only the first `trSize` values are active:

```text
trSize = 16 for 4x4 LFNST input
trSize = 48 for 8x8 LFNST input
```

### 3.2 Covariance/RDO log

The existing covariance log contains:

```text
POC,x,y,W,H,QP,actualCuQp,modeGroup,latBin,absLatDeg,
setIdx,transpose,J0,J1,J2,bestIdx,kIn,outN,sbSize,
sampleId,intraMode,lfnstSetIdx,inputVectorDim,scanOrderId,
lfnstInputCoordListHash,rho_h_block,rho_v_block,sigma2_res,
rdoValid0,rdoValid1,rdoValid2
```

Only rows with finite `J0`, `J1`, and `J2` are used for RDO-gain metrics.

## 4. Canonical Group Key

The formal group key is:

```text
QP x blockSize x latBin x lfnstSetIdx x transpose
```

In concrete CSV fields:

```text
qp/QP, w/W, h/H, latBin, lfnstSetIdx/setIdx, transposeFlag/transpose
```

The analyzer must normalize legacy/new field names into one canonical schema:

```text
qp, w, h, latBin, setIdx, transpose, K, Kz
```

`K` is the LFNST input dimension from `trSize` or `inputVectorDim`.

`Kz` is the zero-out retained response count:

```text
Kz = 8  for 4x4 or 8x8 blocks
Kz = 16 otherwise
```

Groups below `--min-samples` are written to the coverage table but excluded
from formal covariance and rank metrics.

## 5. Empirical Covariance

For each admitted group, the analyzer reads the first `K` vector components:

```text
x_b = [x00, x01, ..., x(K-1)]^T
```

It applies the same latitude mask used by the theory path:

```text
x_b <- D_K(theta) x_b
```

The empirical covariance is mean-centered:

```text
Sigma_emp = 1 / (n - 1) sum_b (x_b - mean_x)(x_b - mean_x)^T
```

The implementation uses streaming sums:

```text
sum_x   += x
sum_xxT += x x^T
n       += 1
```

Then:

```text
Sigma_emp = (sum_xxT - n mean_x mean_x^T) / (n - 1)
```

The empirical covariance is converted to a correlation matrix:

```text
R_emp(i,j) = Sigma_emp(i,j) / (sqrt(Sigma_emp(i,i) Sigma_emp(j,j)) + eps)
```

Dimensions with inactive mask entries or near-zero variance are excluded from
rank metrics and off-diagonal metrics.

## 6. Theoretical Covariance

For each admitted group, the theory path uses the same:

- block size `(M,N)`;
- latitude-bin center `theta`;
- LFNST scan order;
- input dimension `K`;
- transpose flag;
- LFNST set index;
- latitude mask.

It constructs:

```text
Sigma_E = sigma_e2 * (R_ver_N kron R_hor_M,theta)

Sigma_F = sigma_e2 *
          (C_N R_ver_N C_N^T) kron
          (C_M R_hor_M,theta C_M^T)

Sigma_x = Sigma_F[xi_K, xi_K]
Sigma_x = D_K(theta) Sigma_x D_K(theta)
```

The theory covariance is also converted to correlation form:

```text
R_th(i,j) = Sigma_th(i,j) / (sqrt(Sigma_th(i,i) Sigma_th(j,j)) + eps)
```

`sigma_e2` can use group mean `sigma2_res` where available, but all formal
structure comparisons use correlation matrices so the scale is not decisive.

## 7. Formal Metrics

### 7.1 Normalized covariance error

Full matrix:

```text
NCE_full = ||R_emp - R_th||_F / (||R_emp||_F + eps)
```

Off-diagonal matrix:

```text
NCE_off = ||Off(R_emp) - Off(R_th)||_F / (||Off(R_emp)||_F + eps)
```

Both are reported. `NCE_off` is the preferred paper metric because LFNST gain is
driven mainly by joint low-frequency correlation.

### 7.2 Covariance rank correlation

For each group:

```text
r_emp = upper_triangle_offdiag(R_emp)
r_th  = upper_triangle_offdiag(R_th)
rho_rank_cov = Spearman(r_emp, r_th)
```

If either vector is constant or has fewer than two finite entries, the group is
reported with `rho_rank_cov = NaN` and `rank_valid = 0`.

### 7.3 Response metric rank correlation

For both empirical and theoretical covariance, compute:

```text
O_x
chi_diag
G_max_resp
U_max_off+
```

Then compute cross-group Spearman correlations:

```text
Spearman(O_x_th, O_x_emp)
Spearman(chi_diag_th, chi_diag_emp)
Spearman(G_max_resp_th, G_max_resp_emp)
Spearman(U_max_off+_th, U_max_off+_emp)
```

### 7.4 Top-1 candidate match

For each group, theory scores candidates 1 and 2:

```text
S_l_th = G_l_resp_th
```

Optional CLI support may allow:

```text
S_l_th = G_l_resp_th + lambda_U * U_l_off+_th
```

The theoretical winner is:

```text
l*_th = argmax_l S_l_th
```

The RDO winner is:

```text
DeltaJ_l = mean_g(J0 - J_l)
l*_rdo = argmax_l DeltaJ_l
```

The match is:

```text
Match_g = I[l*_th == l*_rdo]
```

Only groups with:

```text
max_l DeltaJ_l > 0
```

contribute to formal `Top1Match`.

### 7.5 Real LFNST gain relation

For each block:

```text
DeltaJmax = J0 - min(J1, J2)
```

For each group:

```text
P_positive_gain = P(DeltaJmax > 0 | g)
mean_DeltaJmax = mean_g(DeltaJmax)
```

The analyzer reports:

```text
Spearman(G_max_resp_th, P_positive_gain)
Spearman(U_max_off+_th, P_positive_gain)
Spearman(O_x_th, P_positive_gain)
Spearman(chi_diag_th, P_positive_gain)
```

### 7.6 Low-gain reliability curve

The low-gain score is:

```text
S_low =
  z(-O_x)
+ z(chi_diag)
+ z(-G_max_resp)
+ z(-U_max_off+)
```

The curve bins groups by `S_low` and reports:

```text
P(DeltaJmax <= 0)
```

An increasing curve supports the low-gain criterion.

## 8. Outputs

The analysis directory will contain:

```text
covariance_group_metrics.csv
response_group_metrics.csv
rdo_gain_group_metrics.csv
metric_rank_correlations.csv
top1_candidate_match.csv
low_gain_reliability_curve.csv
covariance_validation_summary.csv
empirical_theory_covariance_matrices.npz
fig_4_2_covariance_heatmaps.png/.pdf
fig_4_2_nce_by_size_lat.png/.pdf
fig_4_2_response_vs_gain.png/.pdf
fig_4_2_low_gain_reliability.png/.pdf
```

Existing outputs from `run_lfnst_covariance_model_validation.py` remain
available for backward compatibility.

## 9. Implementation Boundaries

The first implementation pass only modifies offline Python analysis and tests.

It does not:

- change the encoder decision path;
- add a new encoder logger;
- change LFNST candidate evaluation;
- alter existing skip policies.

Encoder changes are allowed only if tests show the current logs cannot support
stable group join or required fields are missing in real traces.

## 10. Verification Strategy

Unit tests cover:

- canonical field-name normalization;
- streaming covariance accumulation;
- correlation conversion with zero-variance masking;
- `NCE_full` and `NCE_off`;
- Spearman handling for valid and constant vectors;
- response metric calculation from empirical and theoretical covariance;
- top-1 candidate match;
- `DeltaJmax`, `P_positive_gain`, and low-gain reliability bins;
- CLI output contracts.

A smoke test runs the analyzer on a synthetic vector log and synthetic RDO log
with known covariance and known candidate winner.

No claim of experiment completion is made until the focused tests pass.

## 11. Self-Review

- Scope is limited to Experiment 4.2 low-frequency covariance validation.
- The selected approach matches the confirmed plan: reuse existing vector and
  covariance/RDO logs, implement formal metrics offline.
- Field naming ambiguity is resolved by a canonical schema.
- The design distinguishes this low-frequency validation from the separate
  Task A spatial residual covariance calibration.
- There are no placeholder requirements or undefined metrics.
