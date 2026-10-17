# Matched RA / 32 coded frames / final results

Verified 2026-10-16. GOP32, NumRefPics=1, frozen SIBRC-thread targets and Anchor reused. Only strip mode1 evaluated. BD-rate percent; lower is better. All 14 sequences complete, 56/56 points independently decoded and matched. No failures. Mean bitrate error 2.494550%, maximum 33.037104%. Four representative mode-off compatibility streams matched the reused Anchor bit-for-bit; this is a limited empirical compatibility gate.

|Resolution|Sequence|PSNR|WS-PSNR|S-PSNR-NN|CPP-PSNR|
|---|---|---:|---:|---:|---:|
|4K|AerialCity|+8.69%|+4.54%|+4.61%|+4.62%|
|4K|DrivingInCity|+7.22%|+5.82%|+5.79%|+5.86%|
|4K|DrivingInCountry|+7.88%|+3.19%|+3.15%|+3.15%|
|4K|PoleVault_le|+6.92%|+2.95%|+2.80%|+3.04%|
|6K|Balboa|+6.15%|+5.55%|+5.52%|+5.54%|
|6K|BranCastle2|-0.18%|-1.53%|-1.48%|-1.54%|
|6K|Broadway|+3.24%|+2.40%|+2.37%|+2.38%|
|6K|Landing2|+0.96%|-2.90%|-2.86%|-2.95%|
|8K|ChairliftRide|+8.57%|+7.34%|+7.32%|+7.31%|
|8K|Gaslamp|+6.22%|-0.09%|+0.22%|-0.21%|
|8K|Harbor|+8.54%|+4.93%|+4.92%|+4.92%|
|8K|KiteFlite|+7.25%|+3.60%|+3.62%|+3.54%|
|8K|SkateboardInLot|+7.50%|+6.67%|+6.64%|+6.66%|
|8K|Trolley|+6.45%|-1.00%|-0.78%|-1.16%|
|All|Average|+6.10%|+2.96%|+2.99%|+2.94%|

|Method|PSNR|WS-PSNR|S-PSNR-NN|CPP-PSNR|
|---|---:|---:|---:|---:|
|Strip-only|+6.10%|+2.96%|+2.99%|+2.94%|
|SIBRC C4|-3.79%|-5.78%|-5.77%|-5.80%|

The requested average <= SIBRC constraint is not met for any of the four metrics. C4 values were recomputed from the archived matched point quality records; all 56 reused Anchor stream identities, targets, frame counts, source-prefix, sphere, and metric tool identities were checked. Do not combine this batch with prior 17-frame results.

Raw method reports and reused Anchor quality: build-gaze/remote-ra/matched32-reports. Remote complete batch: /root/visual_gaze_ra32f_matched_20261015/results. Previous simultaneous workload and disk waits make wall time unsuitable for complexity claims.
