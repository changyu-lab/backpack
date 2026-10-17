#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/vvenc_lard_exp
SRC="$ROOT/vvenc-1.12.0-lard-src"
TOOLS="$ROOT/tools"
SEQ=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
SPHERE="$ROOT/sphere_655362.txt"
OUT="${OUT:-$ROOT/runs/skip18_v4_real_repeats_$(date +%Y%m%d_%H%M%S)}"
REPEATS="${REPEATS:-5}"
TARGET_PROFILE="${TARGET_PROFILE:-0}"

test -s "$SEQ"
if [[ ! -s "$SPHERE" ]]; then
  SPHERE=$(find /root -name sphere_655362.txt -type f | head -1)
fi
test -s "$SPHERE"
mkdir -p "$OUT"

cd "$SRC"
cmake -S . -B build-lfnst2nd -DCMAKE_BUILD_TYPE=Release
cmake --build build-lfnst2nd --config Release --target vvencFFapp -j "$(nproc)"

EXE="$SRC/bin/release-static/vvencFFapp"
test -x "$EXE"

cd "$ROOT"
PYTHONPATH="$ROOT:$TOOLS:${PYTHONPATH:-}" python3 \
  "$TOOLS/lard_lfnst/run_skip18_paired_repeats.py" \
  --encoder "$EXE" \
  --orig "$SEQ" \
  --sphere-file "$SPHERE" \
  --out-root "$OUT" \
  --qps 22,27,32,37 \
  --repeats "$REPEATS" \
  --frames 4 \
  --threads 20 \
  --preset medium \
  --target-profile "$TARGET_PROFILE" \
  > "$OUT/eval.stdout"

find "$OUT" -type f -name '*.yuv' -delete
echo "$OUT"
