# SIBRC calibration and intra-anchor repair

Authorized by user: execute repairs after cause analysis. Preserve default legacy behavior.

1. Add a failing controller regression: constant raw-model bias must converge to the full log bias, rather than half; retain legacy expectations.
2. Add independent default-off SIBRCBiasRepair and SIBRCIntraAnchor switches. Corrected feedback adds the residual of the already corrected prediction. Anchor bypasses SIBRC on every intra picture and clears controller state to avoid stale feedback. Keep VTM feedback intact.
3. Extend smoke checks for repaired decoding, intra VTM identity, combined zero-strength identity, and default legacy identity.
4. Run CTests, Python tests, encoder build and smoke; run paired four-rate heldout screening with frozen targets and models. Archive results and compare measured bitrate and three spherical metrics. Report unresolved model extrapolation and long-sequence validation explicitly.
