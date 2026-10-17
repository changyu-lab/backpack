# PoleVault M4 9-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|+1.6829%|+1.7226%|+1.7519%|+4.4261%|
|M4 C1|+1.6859%|+1.7324%|+1.7516%|+4.4374%|
|M4 C3|+2.9178%|+3.1405%|+3.0024%|+5.5562%|
|M4 C4|+3.1146%|+3.2163%|+3.1622%|+5.6905%|

frames.csv has 180 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
