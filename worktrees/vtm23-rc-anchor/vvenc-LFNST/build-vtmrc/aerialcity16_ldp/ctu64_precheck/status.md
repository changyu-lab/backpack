# AerialCity ERP16 LDP paired experiment

VVenC four points complete and decoded. FirstIRAP actual-feedback replay: both independent kernels and live adapter agree on64824fields total. VTM fresh16frame same-input baselines running; final paired result is pending.

The current frozen ERP target grid is1.6/3.2/6.4/12.8Mbps (source paper_evidence/config.json). Historical16-frame CQP-derived targets differ and used4432x2216 resampling, so their reported rates are not directly comparable to this3840x1920 raw-input run.

| Target Mbps | VVenC actual RC Mbps | Error % | Mean Y PSNR dB |
|---:|---:|---:|---:|
|1.6|2.451225|53.201563|36.205615|
|3.2|3.314415|3.575469|36.593466|
|6.4|6.402765|0.043203|39.029219|
|12.8|12.806580|0.051406|39.968911|

Short low-rate overshoot is visible. At1.6Mbps, originalRC firstIRAP target is1287078bits while whole16frame budget is853333bits. Do not claim universally equal closed-loop rates or long-sequence convergence from the kernel-equivalence result.
