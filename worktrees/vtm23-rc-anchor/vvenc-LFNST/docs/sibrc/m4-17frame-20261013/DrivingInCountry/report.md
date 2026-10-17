# DrivingInCountry M4 17-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C4|+4.7616%|+4.7504%|+4.6430%|+7.5047%|

frames.csv has 136 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.

This sequence is part of model calibration and is a development sequence.
