# Independent VTM RC replay

The reference target compiles the ORIGINAL local VTM RateCtrl.cpp directly with its ACTUAL unmodified source headers. It is a separate executable; only the scripted feedback harness is shared. Configure VTM_SOURCE_DIR to the local source checkout. This proves agreement with the hashed local files in provenance.json, not official VTM tag authentication or complete encoder equivalence.

```
cmake -S test/vtmrc -B test/vtmrc/build -G "Visual Studio 16 2019" -A x64
cmake --build test/vtmrc/build --config Release
python test/vtmrc/check_extraction.py
python test/vtmrc/compare.py
```

Eight scenarios cover GOP4 LD/GOP8 RA, rational 30000/1001 rate, low and ordinary budgets, IRAP/inter, 130x98 partial CTUs, and enabled/disabled CTU model updates. Separate CTU models remain enabled: upstream updateAfterPicture unconditionally reads LCU parameter storage, which is absent when useLCUSeparateModel is false. Integer comparisons are exact; finite doubles use abs 1e-12 plus relative 1e-10. Deliberate integer and double divergences must both be rejected.

The extraction audit verifies reference SHA256 hashes, permits only the documented mechanical substitutions and blank-line/trailing-whitespace formatting, and rejects in-memory arithmetic mutations in both source and header. Replay captures persisted lastLambda, adaptive mode, GOP bit ratios, model validPix/skipRatio, and CTU actualBits/QP/lambda/targetBitsLeft/SSE/MSE.


The runner accepts --build-dir PATH and --config NAME (defaults: this test's build directory and Release). It discovers Windows .exe or platform-native executables under either config-specific or flat build output directories. Replay .txt files are written to the invoking working directory; run from a writable directory. A failed executable run fails verification and is never treated as a successful replay.

## Real AerialCity first-IRAP replay

The `vtmrc_real_reference` and `vtmrc_real_compat` targets consume the same actual feedback fixture, compiled separately against original VTM and extracted controller. After a four-point16-frame AerialCity experiment, run `python tools/vtmrc/aerialcity_replay.py`. It independently computes Walsh SATD from the raw first input frame, preserving per8x8 and perCTU normalization order, and compares both outputs plus live adapter CSV decisions. Defaults are the local ERP input,3840x1920,128CTU,30fps,GOP8LDP,10bit internal and frozen1.6/3.2/6.4/12.8Mbps targets. This check covers picture initialization and firstIRAP CTU decisions/feedback only; picture-final feedback and the remaining15frames are excluded. Deliberate integer divergence is rejected.
