# Frozen development calibration v1

These assets were fitted only with DrivingInCity and DrivingInCountry. AerialCity is excluded from calibration. The JSON sidecars retain raw-data hashes, grouping, domains and held-out errors. Statistics use 4 development frames per sequence; the R/D samples use 16 frames at requested CTU QP 22/27/32/37, separately for I/P. The metadata `frames=4` describes residual-statistics collection, while model sample coverage is recorded by the CSV hash and holdout groups.

This is an explicit independently calibrated adaptation of chapter5_SIBRC_TIP.tex: controlled horizontal area resampling supplies the missing joint X/Y statistics, and measured residual covariance supplies the missing online variance estimator. It does not claim to recover the author's unavailable calibration. See tools/sibrc/README.md and the approved design document for equations and restrictions.

Keep these assets frozen for the initial evaluation. Model fit errors are diagnostic evidence, not evidence of BD-rate gain.
