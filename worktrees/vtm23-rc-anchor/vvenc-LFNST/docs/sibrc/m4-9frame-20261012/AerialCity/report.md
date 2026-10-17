# AerialCity M4 9-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|-0.7754%|-0.6601%|-0.8025%|+2.1947%|
|M4 C1|-1.4311%|-1.5615%|-1.4426%|+1.2229%|
|M4 C3|-2.6398%|-2.7142%|-2.6461%|+0.1756%|
|M4 C4|-0.5082%|-0.6312%|-0.5228%|+2.0843%|

frames.csv has 180 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
