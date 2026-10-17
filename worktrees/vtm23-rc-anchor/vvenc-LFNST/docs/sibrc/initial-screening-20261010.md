# SIBRC initial screening, 2026-10-10

AerialCity ERP3840x1920,16 frames,LDP, VVenC1.12.0 faster, strict serial VTM RC compatibility anchor. Frozen independent development calibration v1; no AerialCity fitting.

Initial outcome: WS-PSNR BD-rate **+4.3368%**, ordinary luma PSNR BD-rate **+5.7061%**. Positive means worse; the requested gain has not been achieved in this screening.

|Method|Target Mbps|Actual AnnexB Mbps|Y WSPSNR dB|Y PSNR dB|Rate error %|Fallback CTUs|
|---|---:|---:|---:|---:|---:|---:|
|smoke_anchor_R1|1.600|2.418495|34.701429|35.467962|51.156|—|
|smoke_full_R1|1.600|2.457405|34.511672|35.291284|53.588|6867|
|smoke_anchor_R2|3.200|3.284355|35.280671|36.016283|2.636|—|
|smoke_full_R2|3.200|3.330390|34.986929|35.741544|4.075|6839|
|smoke_anchor_R3|6.400|6.405465|38.314404|39.014506|0.085|—|
|smoke_full_R3|6.400|6.407580|38.313895|38.955679|0.118|1725|
|smoke_anchor_R4|12.800|12.807060|39.315712|39.980841|0.055|—|
|smoke_full_R4|12.800|12.822150|39.372989|39.955918|0.173|1370|

All 8 streams independently decoded; decoded reconstruction SHA256 equals encoder reconstruction. Full per-job commands, exe/config/model/input hashes, exact16POCs, bitstream/reconstruction hashes and picture qualities are retained in I:\vvenc-LFNST\.worktrees\sibrc-experiment-data-20261009-v2.

Quality is average picture luma PSNR or ERP cosine-row WSPSNR, normalized10bit reconstruction to8bit; BD-rate uses PCHIP of log actual AnnexB rate over shared quality range, without extrapolation. RC NAL accounting is separate. Low targets exhibit first-I-frame budget overshoot on this16-frame clip.

Time measurements were taken while other encodes and disk-heavy assessments overlapped. Do not interpret them as a controlled algorithm overhead comparison.

Developer-only diagnostics: equatorial training extrapolates poorly to high latitude, and some predicted distortion slopes have wrong sign. Optional monotonic calibration v2 is separate and not yet an evaluation result. It retains the six-term model and equatorial fitting.

Completed verification:39/39 original regression tests;2/2 pureSIBRC tests; 17/17 tool tests, including optional monotonic calibration and cache provenance checks. Independent original RC replay:4,200 records/13,192 fields across8scenarios, plus exact extraction/SHA audit. Native RateCtrl and extracted VTM arithmetic have not been changed. Default-off and collection-only bitstream/RC-trace identity passed on16-frame R3.

128-frame four-point main experiment pending; do not quote this screening as a general sequence result or as a VTM-engine result.
