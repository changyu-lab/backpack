# Default 360-degree evaluation

All subsequent SIBRC ERP experiments must report **WS-PSNR, S-PSNR-NN and CPP-PSNR**, with per-picture luma arrays and four-point BD-rates. Ordinary Y-PSNR remains a supplementary metric. Missing S/CPP tools are an error; do not silently publish WS-only results. The default `evaluate.py quality` computes all three. `quality(..., spherical=False)` is reserved for hashing or explicit diagnostic use.

`main.cpp` is a thin file adapter compiled with the original VTM project's unmodified `source/Lib/Lib360/*.cpp` and `CommonLib.lib`. It does not approximate CPP by bilinear interpolation of an error plane. Input is 8-bit ERP YUV420, reconstruction is 10-bit little-endian YUV420, with chroma location 2. Standard `sphere_655362.txt` provides S-PSNR-NN samples. The NN object also calls `initCFSPSNR()` to explicitly initialize projection metadata read by 360Lib's enabled fisheye branches. CPP dimensions equal input ERP dimensions, with original Lanczos3 luma / Lanczos2 chroma filters, clipping and integer rounding. Both metrics use peak 1020 at 10 bits, corresponding to 255 at 8 bits. Identity uses 360Lib's 999.99 sentinel.

Build on Windows with MSVC 2019 and the existing VTM CommonLib release library:

```
cmake -S tools/sibrc/metrics360 -B build-vtmrc/metrics360-parallel -G "Visual Studio 16 2019" -A x64 -DVTM=I:/001-IBRC-exps/VTM-23.0-paper-scc-rc
cmake --build build-vtmrc/metrics360-parallel --config Release --parallel 4
```

Override executable or sphere paths with `SIBRC_METRICS360_EXE` / `SIBRC_SPHERE_FILE`. `SIBRC_METRIC_WORKERS` selects 1..4 independent picture workers (default 2). Each worker owns its original 360Lib metric/geometry objects; per-picture sums retain the original operation order. Record executable/sphere SHA256 for every evaluation. Sequence qualities are the arithmetic mean of per-picture PSNR in dB, matching the existing experiment convention. BD-rate uses actual complete Annex-B bitrate and common-quality-range PCHIP log-rate integration without extrapolation.

Frame bitrate plots use encoder POC bits multiplied by frame rate; parameter-set/header differences from total Annex-B size are recorded separately. Include all frames, including the first I-frame. Decoder reconstructions must match previously recorded hashes before extending old results.

The `evaluate.py bd-rate` CLI also computes the three default metric BD-rates together when `--quality-key` is omitted. An explicit quality key retains single-metric output.
