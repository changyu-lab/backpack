# BranCastle2 M4 9-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|+0.9657%|+0.9562%|+0.9371%|+1.4093%|
|M4 C1|+0.9472%|+0.9685%|+0.9082%|+1.3908%|
|M4 C3|+0.9506%|+0.9603%|+0.9153%|+1.3944%|
|M4 C4|+0.9704%|+0.9629%|+0.9614%|+1.3601%|

frames.csv has 180 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
