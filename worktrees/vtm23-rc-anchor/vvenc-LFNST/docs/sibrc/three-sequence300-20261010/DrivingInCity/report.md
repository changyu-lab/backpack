# DrivingInCity ERP 300-frame results

Native resolution, LDP, frozen faster encoder and SIBRC models. Source8/reconstruction10. WS/S-NN/CPP luma means of per-frame dB; actual Annex-B bitrate and common-range PCHIP BD-rate.

|Metric|BD-rate|
|---|---:|
|wspsnr|+2.0824%|
|spsnr|+2.3198%|
|cpppsnr|+2.0723%|
|psnr|+2.7990%|

Timing is elapsed wall time under concurrent jobs, not an isolated encoding-speed benchmark.
Model development sequences: DrivingInCity/DrivingInCountry. DrivingInCity is a development sequence; PoleVault/BranCastle2 are held out.
S-PSNR is the NN variant with 655362 original 360Lib sphere samples. CPP dimensions equal native source resolution; Lanczos3 luma/Lanczos2 chroma, peak1020 at10bits.
Frames.csv contains all2400rows. Figures use Anchor/SIBRC, S-PSNR (dB), transparent backgrounds and inward ticks on all four sides.
