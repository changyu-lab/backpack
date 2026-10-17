# Fixed-model beta experiment final interpretation

144 new streams +24 reused B5 +24 reused Anchor; 192 comparisons, 6144 frame rows. Audit PASS. The model is frozen to the current common-sample B5 I/P model. All beta results and negative ordinary-Y outcomes remain in summary.json.

Mean spherical BD-rate stays negative for beta 2..20; mean S ranges -6.0975% to -6.4876%, best beta8. Recalibrated mean S spans about .268 percentage points, fixed model spans .390 points. This supports limited parameter stability of the tested RA32 pipeline, not necessity of the IB form.

On identical mode2 encoded training samples, feature correlations with B5 remain above .999994 Pearson (I/P), and aggregate feature means vary moderately. This indicates near-identical ranking / approximately scaled representations; it does not measure per-frequency activation. Descriptor means: I beta2 2274.8736, beta5 2361.8528, beta20 2393.6583; P 423.6280,442.0194,448.7454.

On fixed-model closed-loop validation streams, selected offset agreement with B5 is 85.84..87.12% for other beta values (12.88..14.16% changed), pooled across 640000 matched CTUs per beta. Agreement includes intra and fallback CTUs. Configured +/-2 boundary hit rate is 35.73..36.32%, fallback rate49.42..50.10%. High fallback incidence limits interpretation of raw agreement as evidence for identical optimization decisions. Different reconstruction/RC states prevent purely causal attribution of each difference to beta.

Online rate/distortion log prediction errors are pooled by valid CTU count in mechanism-aggregate.json. Predicted SSE is compared with weighted_mse*area, rate with actual CTU bits. These predictions contain online feedback correction. Positive finite values only; exclusions retained in detailed mechanism JSON.

No per-band activation counts or rho vectors were logged, so active-frequency-band proportion is unavailable. No aggregate-zero surrogate is reported. City/Country are development sequences; RA is a truncated 32-frame GOP and LDP-calibrated P model is applied to non-I.
