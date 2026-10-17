# PoleVault M4 17-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|+9.1654%|+9.2205%|+9.2825%|+12.4522%|
|M4 C1|+9.2495%|+9.2420%|+9.3472%|+12.5395%|
|M4 C3|+9.3083%|+9.4084%|+9.3985%|+12.6826%|
|M4 C4|+10.0668%|+9.9770%|+10.1553%|+13.3934%|

frames.csv has 340 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
