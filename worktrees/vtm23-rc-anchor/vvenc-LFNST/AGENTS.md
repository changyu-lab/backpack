# Experiment defaults

For this isolated VTM-RC@VVenC / SIBRC project, subsequent performance experiments report **WS-PSNR, S-PSNR-NN, CPP-PSNR** by default. Use `tools/sibrc/evaluate.py quality`, which computes all three and records per-frame luma arrays. Preserve ordinary Y-PSNR as a supplementary diagnostic. Use the original 360Lib S/CPP implementation with the recorded spherical sample file and projection parameters; document any metric convention change. Four-point comparisons use actual bitrate and report a separate BD-rate for each metric. See `tools/sibrc/metrics360/README.md`.
