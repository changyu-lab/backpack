# AerialCity M4 17-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|+4.0297%|+3.9547%|+3.9860%|+6.0223%|
|M4 C1|+1.1418%|+1.0465%|+1.1803%|+2.0849%|
|M4 C3|+0.3727%|+0.2344%|+0.3612%|+1.3473%|
|M4 C4|+9.8496%|+9.6939%|+9.7135%|+11.3169%|

frames.csv has 340 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
