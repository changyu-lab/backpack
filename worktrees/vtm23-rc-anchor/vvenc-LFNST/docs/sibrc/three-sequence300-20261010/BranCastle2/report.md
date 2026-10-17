# BranCastle2 ERP 300-frame results

Native resolution, LDP, frozen faster encoder and SIBRC models. Source8/reconstruction10. WS/S-NN/CPP luma means of per-frame dB; actual Annex-B bitrate and common-range PCHIP BD-rate.

|Metric|BD-rate|
|---|---:|
|wspsnr|+1.0736%|
|spsnr|+1.0787%|
|cpppsnr|+1.0534%|
|psnr|+2.0479%|

Timing is elapsed wall time under concurrent jobs, not an isolated encoding-speed benchmark.
Model development sequences: DrivingInCity/DrivingInCountry. DrivingInCity is a development sequence; PoleVault/BranCastle2 are held out.
S-PSNR is the NN variant with 655362 original 360Lib sphere samples. CPP dimensions equal native source resolution; Lanczos3 luma/Lanczos2 chroma, peak1020 at10bits.
Frames.csv contains all2400rows. Figures use Anchor/SIBRC, S-PSNR (dB), transparent backgrounds and inward ticks on all four sides.
