# BranCastle2 M4 17-frame results

Native ERP, LDP faster preset, shared historical 300-frame CQP targets; actual Annex-B rates for BD-rate. Fixed offset [-2,2]. C0/C1/C3/C4 are frequency weight variants; plane/geo/SATD are separate references. C2/C3 are scale-equivalent and merged only after fitted controller replay.

|Method|WS-PSNR|S-PSNR-NN|CPP-PSNR|Y-PSNR|
|---|---:|---:|---:|---:|
|M4 C0|-1.6802%|-1.6969%|-1.6474%|-0.8281%|
|M4 C1|-1.6936%|-1.6851%|-1.6720%|-0.8537%|
|M4 C3|-1.6872%|-1.6850%|-1.6590%|-0.8350%|
|M4 C4|-1.6282%|-1.6071%|-1.6172%|-0.8480%|

frames.csv has 340 data rows. DrivingInCity/Country are calibration sequences. These validation sequences have historical results and are independent of calibration, not blind tests.
Timing is wall time under concurrent encoders; metrics use one worker and one reconstruction at a time. WS/S-NN/CPP means use original 360Lib conventions and native dimensions; Y-PSNR is supplemental.
