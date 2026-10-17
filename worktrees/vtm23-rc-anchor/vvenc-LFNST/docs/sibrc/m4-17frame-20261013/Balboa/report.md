# Balboa M4 17-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|+0.6598%|+0.8060%|+0.6516%|+0.9065%|
|M4 C1|+0.7873%|+0.9134%|+0.7681%|+0.9708%|
|M4 C3|+0.8589%|+0.9709%|+0.8450%|+1.0824%|
|M4 C4|+0.7002%|+0.8785%|+0.7580%|+0.8914%|

frames.csv has 340 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
