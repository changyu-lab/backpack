#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/vvenc_lard_exp
SRC="$ROOT/vvenc-1.12.0-lard-src"
TOOLS="$ROOT/tools"
SEQ=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
SPHERE=/root/vvenc_lard_exp/sphere_655362.txt
OUT="${OUT:-$ROOT/runs/lfnst2nd_aerialcity3840_param_scan}"
LOG_DIR="$ROOT/logs"
QPS="${QPS:-22,27,32,37}"
FRAMES="${FRAMES:-1}"
THREADS="${THREADS:-20}"
PRESET="${PRESET:-medium}"
SKIP_MODES="${SKIP_MODES:-10}"
ZETAS="${ZETAS:-0.1,0.15}"
DELTAS="${DELTAS:-0.25}"
RIDXS="${RIDXS:-1.0}"
CORR_ALPHAS="${CORR_ALPHAS:-0.0,0.1,0.2}"
CORR_DECAYS="${CORR_DECAYS:-2.0}"
CORR_TABLES="${CORR_TABLES:-0}"
THEORY_TABLES="${THEORY_TABLES:-0}"
SAFE_MARGINS="${SAFE_MARGINS:-0.0,0.25,0.5}"
OBS_GATES="${OBS_GATES:--1000000000.0}"
STAGE1_RELAXES="${STAGE1_RELAXES:-1.0}"
STAGE1_RELAX_QPMAPS="${STAGE1_RELAX_QPMAPS:-}"
MAX_CU_QPS="${MAX_CU_QPS:-63}"
MIN_AREAS="${MIN_AREAS:-0}"
MIN_WIDTHS="${MIN_WIDTHS:-0}"
MIN_HEIGHTS="${MIN_HEIGHTS:-0}"
MAX_ASPECTS="${MAX_ASPECTS:-4}"
SHAPE_MASKS="${SHAPE_MASKS:-31}"
EFF_COLS_GATES="${EFF_COLS_GATES:-0}"
EFF_COLS_MINS="${EFF_COLS_MINS:-2}"
EFF_COLS_ONLY="${EFF_COLS_ONLY:-0}"
EFF_COLS_MIN_QPMAPS="${EFF_COLS_MIN_QPMAPS:-}"
MIN_DCT2_COSTS="${MIN_DCT2_COSTS:--1}"
LARD11_MAX_CU_QPS="${LARD11_MAX_CU_QPS:-34}"
LARD11_MIN_AREAS="${LARD11_MIN_AREAS:-64}"
LARD11_MIN_WIDTHS="${LARD11_MIN_WIDTHS:-0}"
LARD11_MIN_HEIGHTS="${LARD11_MIN_HEIGHTS:-0}"
LARD11_MIN_DCT2_COSTS="${LARD11_MIN_DCT2_COSTS:--1}"
PAPER_GRAD_TH1S="${PAPER_GRAD_TH1S:-100}"
PAPER_TH2_SCALES="${PAPER_TH2_SCALES:-12.83}"
PAPER_TH2_OFFSET1S="${PAPER_TH2_OFFSET1S:-17.375}"
PAPER_TH2_OFFSET2S="${PAPER_TH2_OFFSET2S:-57.375}"
LARD13_FUSIONS="${LARD13_FUSIONS:-1}"
MEASURE_ONLY="${MEASURE_ONLY:-0}"
OBS_ONLY="${OBS_ONLY:-0}"
WRITE_STATS="${WRITE_STATS:-0}"
WRITE_COUNTS="${WRITE_COUNTS:-0}"
ANCHOR_CACHE_CSV="${ANCHOR_CACHE_CSV:-}"

mkdir -p "$OUT" "$LOG_DIR"

if [[ ! -s "$SPHERE" ]]; then
  SPHERE=$(find /root -name sphere_655362.txt -type f | head -1)
fi
if [[ -z "${SPHERE:-}" || ! -s "$SPHERE" ]]; then
  echo "sphere_655362.txt not found" >&2
  exit 1
fi
if [[ ! -s "$SEQ" ]]; then
  echo "AerialCity sequence not found: $SEQ" >&2
  exit 1
fi

cd "$SRC"
cmake -S . -B build-lfnst2nd -DCMAKE_BUILD_TYPE=Release
cmake --build build-lfnst2nd --config Release --target vvencFFapp -j "$(nproc)"

EXE="$SRC/bin/release-static/vvencFFapp"
if [[ ! -x "$EXE" ]]; then
  EXE="$SRC/bin/release-shared/vvencFFapp"
fi
if [[ ! -x "$EXE" ]]; then
  echo "vvencFFapp not found after build" >&2
  exit 1
fi

ANCHOR_ARGS=()
if [[ -n "$ANCHOR_CACHE_CSV" ]]; then
  ANCHOR_ARGS=(--anchor-cache-csv "$ANCHOR_CACHE_CSV")
fi

PYTHONPATH="$TOOLS:${PYTHONPATH:-}" python3 "$TOOLS/lard_lfnst_scan_2nd_params.py" \
  --encoder "$EXE" \
  --orig "$SEQ" \
  --width 3840 \
  --height 1920 \
  --fps 30 \
  --sphere-file "$SPHERE" \
  --out-root "$OUT" \
  --qps "$QPS" \
  --frames "$FRAMES" \
  --threads "$THREADS" \
  --preset "$PRESET" \
  --skip-modes "$SKIP_MODES" \
  --zetas "$ZETAS" \
  --deltas "$DELTAS" \
  --ridxs "$RIDXS" \
  --corr-alphas "$CORR_ALPHAS" \
  --corr-decays "$CORR_DECAYS" \
  --corr-tables "$CORR_TABLES" \
  --theory-tables "$THEORY_TABLES" \
  --safe-margins "$SAFE_MARGINS" \
  --obs-gates="$OBS_GATES" \
  --stage1-relaxes "$STAGE1_RELAXES" \
  --stage1-relax-qpmaps "$STAGE1_RELAX_QPMAPS" \
  --max-cu-qps "$MAX_CU_QPS" \
  --min-areas "$MIN_AREAS" \
  --min-widths "$MIN_WIDTHS" \
  --min-heights "$MIN_HEIGHTS" \
  --max-aspects "$MAX_ASPECTS" \
  --shape-masks "$SHAPE_MASKS" \
  --eff-cols-gates "$EFF_COLS_GATES" \
  --eff-cols-mins "$EFF_COLS_MINS" \
  --eff-cols-only "$EFF_COLS_ONLY" \
  --eff-cols-min-qpmaps "$EFF_COLS_MIN_QPMAPS" \
  --min-dct2-costs "$MIN_DCT2_COSTS" \
  --lard11-max-cu-qps "$LARD11_MAX_CU_QPS" \
  --lard11-min-areas "$LARD11_MIN_AREAS" \
  --lard11-min-widths "$LARD11_MIN_WIDTHS" \
  --lard11-min-heights "$LARD11_MIN_HEIGHTS" \
  --lard11-min-dct2-costs "$LARD11_MIN_DCT2_COSTS" \
  --paper-grad-th1s "$PAPER_GRAD_TH1S" \
  --paper-th2-scales "$PAPER_TH2_SCALES" \
  --paper-th2-offset1s "$PAPER_TH2_OFFSET1S" \
  --paper-th2-offset2s "$PAPER_TH2_OFFSET2S" \
  --lard13-fusions "$LARD13_FUSIONS" \
  --measure-only "$MEASURE_ONLY" \
  --obs-only "$OBS_ONLY" \
  "${ANCHOR_ARGS[@]}" \
  $( [[ "$WRITE_STATS" == "1" ]] && printf '%s' --write-stats ) \
  $( [[ "$WRITE_COUNTS" == "1" ]] && printf '%s' --write-counts ) \
  > "$LOG_DIR/lfnst2nd_scan.stdout" \
  2> "$LOG_DIR/lfnst2nd_scan.stderr"

echo "scan summary: $OUT/scan_summary.csv"
