# LFNST residual covariance model validation

This validation is not a coding-speed or BD-rate experiment. It checks whether
the latitude-conditioned residual covariance model produces measurable
second-order structure that is consistent with encoder residual traces.

The current end-to-end entry point is:

```powershell
python tools\lard_lfnst\run_lfnst_model_validation.py `
  --manifest lahtp_runs\model_validation_smoke\model_validation_runs.csv `
  --out-dir lahtp_runs\model_validation_smoke\analysis
```

The legacy 4.2-only entry point remains available:

```powershell
python tools\lard_lfnst\run_lfnst_covariance_model_validation.py --help
```

## Encoder trace contract

The validation uses paired TU-level samples from the Skip15 shadow diagnostic
path. A valid sample has one shared `sampleId` in both files:

- `motivation_cov.csv`: RDO costs `J0/J1/J2`, block metadata, residual
  correlation statistics, and the LFNST input identity.
- `empirical_lfnst_vec.csv`: no-LFNST primary-transform low-frequency vector
  `x00..x47` and the same identity fields.

Required identity fields are:

```text
sampleId,intraMode,modeGroup,lfnstSetIdx,transpose,inputVectorDim,
scanOrderId,lfnstInputCoordListHash
```

The covariance log also records:

```text
rho_h_valid,rho_v_valid,rho_h_block,rho_v_block,sigma2_res
```

The analysis rejects duplicate `sampleId`, unmatched sample sets, scan-hash
mismatches, non-finite costs, invalid latitudes, and nonzero padded vector
entries after `inputVectorDim`.

## Experiment 4.1

Experiment 4.1 validates the spatial residual correlation model before the DCT
step. It uses pre-transform prediction residuals:

```text
E(i,j) = org(i,j) - pred(i,j)
```

For each block, the block mean is removed before computing adjacent horizontal
and vertical correlations. Groups are:

```text
sequence x QP x block size x latitudeBin
```

The primary reported contrast is:

```text
deltaRho = rho_h_block - rho_v_block
```

`rho_h / rho_v` is only an auxiliary value because it becomes unstable when the
vertical denominator is close to zero.

Outputs:

- `spatial_correlation_coverage.csv`
- `spatial_correlation_by_group.csv`
- `spatial_model_fit_summary.csv`
- `fig_4_1_model_validation_overview.png/.pdf`

## Experiment 4.2-A

Experiment 4.2-A generates theoretical matrices offline with:

```text
rho0 = 0.6
rho_ver = 0.6
sigma_e2 = 1.0
theta in {0, 30, 60, 75} degrees
block sizes: 4x4, 8x8, 16x16
```

The propagation chain is:

```text
rho_hor(theta) -> Sigma_E(theta) -> Sigma_F(theta) -> Sigma_x(theta)
```

The expected effect is a systematic covariance reordering with latitude. The
model does not require every off-diagonal entry, or the aggregate off-diagonal
metric, to increase monotonically.

Outputs:

- `theory_covariance_matrices.npz`
- `theory_covariance_metrics.csv`

## Experiment 4.2-B

Experiment 4.2-B compares empirical no-LFNST low-frequency covariance against
the theory table. For each admitted group:

```text
sequence x QP x W x H x modeGroup x lfnstSetIdx x transpose x latitudeBin
```

the empirical covariance uses the MLE normalization from the experiment spec:

```text
Sigma_x = (1 / N) sum_n (x_n - mean(x))(x_n - mean(x))^T
```

Groups must satisfy:

```text
N >= max(200, 5K)
```

The CLI can lower this threshold for smoke tests through
`--spatial-min-samples` and `--covariance-min-factor`.

Both raw covariance and effective-support covariance are reported. The primary
interpretation uses the effective covariance:

```text
D_K(theta) Sigma_x D_K(theta)
```

The low-frequency off-diagonal coupling strength is computed on the correlation
matrix `R_x` as:

```text
O_x = 1 / (K(K-1)) * sum_{i != j} |R_x(i,j)|
```

This is an average over ordered off-diagonal entries. It is useful for
summarizing coupling strength, but it is not expected to be strictly monotonic
with latitude because the DCT/LFNST input projection can redistribute energy
across low-frequency coordinates.

Outputs:

- `covariance_similarity_by_group.csv`
- `covariance_shuffle_summary.csv`
- `empirical_theory_covariance_matrices.npz`
- `fig_4_2_covariance_response_validation.png/.pdf`

## Response-vs-RD validation

The same paired samples also test whether theoretical response scores explain
real LFNST RDO gains. The analysis uses:

```text
delta1 = J0 - J1
delta2 = J0 - J2
deltaJmax = max(delta1, delta2)
normalizedGain = deltaJmax / (abs(J0) + eps)
positiveGain = deltaJmax > 0
```

Candidate top-1 agreement compares the better RDO candidate with the larger
theoretical candidate response `S1Resp/S2Resp`, excluding ties.

Outputs:

- `response_rd_summary.csv`
- `response_auc_top1_summary.csv`
- `model_validation_summary.md`

## Interpretation limits

Passing this validation supports the claim that the latitude-conditioned
second-order model is not an empty derivation. It does not prove final encoder
acceleration or BD-rate improvement. Those remain separate coding-performance
experiments.
