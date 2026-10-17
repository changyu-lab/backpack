#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/vvenc_lard_exp
SRC="$ROOT/vvenc-1.12.0-lard-src"
SEQ=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
SPHERE=/root/VTM-23.0-local-migrated-20260515_150923/cfg-360Lib/360Lib/sphere_655362.txt
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT="${OUT:-$ROOT/runs/skip21_stage1_validation_$RUN_ID}"
THREADS="${THREADS:-20}"
QPS="${QPS:-22,27,32,37}"
PRESET="${PRESET:-medium}"

echo "Skip21 Stage-1 validation OUT=$OUT"

while pgrep -af '(/vvencFFapp|/EncoderApp)' | grep -v "$SRC/bin/release-static/vvencFFapp" >/dev/null; do
  sleep 120
done
sleep 120

cd "$SRC"
cmake -S . -B build-lfnst2nd -DCMAKE_BUILD_TYPE=Release
cmake --build build-lfnst2nd --config Release --target vvencFFapp -j "$(nproc)"
EXE="$SRC/bin/release-static/vvencFFapp"

PYTHONPATH="$ROOT" python3 -m tools.lard_lfnst.run_skip21_stage1_validation \
  --encoder "$EXE" \
  --orig "$SEQ" \
  --sphere-file "$SPHERE" \
  --out-root "$OUT" \
  --qps "$QPS" \
  --threads "$THREADS" \
  --preset "$PRESET" \
  --run-diagnostics

ROOT_RUNS_REAL="$(realpath -m "$ROOT/runs")"
OUT_REAL="$(realpath -m "$OUT")"
case "$OUT_REAL" in
  "$ROOT_RUNS_REAL"/skip21_stage1_validation*)
    ;;
  *)
    echo "Refusing to delete .yuv files: OUT must be under $ROOT_RUNS_REAL/skip21_stage1_validation*, got $OUT_REAL" >&2
    exit 1
    ;;
esac

find "$OUT_REAL" -name '*.yuv' -type f -delete
remaining=$(find "$OUT_REAL" -name '*.yuv' -type f | wc -l)
[[ "$remaining" == 0 ]]
echo "$OUT_REAL"
