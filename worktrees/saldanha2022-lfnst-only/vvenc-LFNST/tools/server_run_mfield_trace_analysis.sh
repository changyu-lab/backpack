#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/vvenc_lard_exp
SRC_ROOT="$ROOT/vvenc-1.12.0-lard-src"
EXE="$SRC_ROOT/bin/release-static/vvencFFapp"
ANALYZE="$ROOT/tools/lard_lfnst_analyze_trace.py"
YUV=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
OUT="$ROOT/aerialcity_mfield_fullrdo"

mkdir -p "$OUT"

for QP in 22 27 32 37; do
  DIR="$OUT/AerialCity_QP${QP}"
  mkdir -p "$DIR"
  TRACE="$DIR/trace.csv"
  FINAL="$TRACE.final.csv"
  BLOCKS="$DIR/blocks.csv"
  JSON="$DIR/summary.json"
  LOG="$DIR/anchor.log"
  BIT="$DIR/anchor.vvc"
  ANALYZE_LOG="$DIR/analyze.log"

  if [[ ! -s "$FINAL" || ! -s "$TRACE" ]]; then
    rm -f "$TRACE" "$FINAL" "$BIT" "$LOG"
    echo "[$(date '+%F %T')] encode QP=${QP}" | tee -a "$OUT/run.log"
    set +e
    "$EXE" \
      -i "$YUV" -s 3840x1920 -f 1 -fr 30 -q "$QP" \
      -b "$BIT" \
      --InputBitDepth 8 --OutputBitDepth 8 \
      --preset medium --IntraPeriod 1 --GOPSize 1 \
      --PerceptQPA 0 \
      --LardLfnstSkip 0 \
      --LardLfnstTraceFile "$TRACE" > "$LOG" 2>&1
    CODE=$?
    set -e
    if [[ ! -s "$FINAL" || ! -s "$TRACE" ]]; then
      echo "[$(date '+%F %T')] ERROR encode QP=${QP} exit=${CODE}, no complete trace" | tee -a "$OUT/run.log"
      exit 1
    fi
    echo "[$(date '+%F %T')] encode QP=${QP} exit=${CODE}, trace accepted" | tee -a "$OUT/run.log"
  else
    echo "[$(date '+%F %T')] encode QP=${QP} skipped, trace exists" | tee -a "$OUT/run.log"
  fi

  if [[ ! -s "$BLOCKS" ]]; then
    echo "[$(date '+%F %T')] analyze QP=${QP}" | tee -a "$OUT/run.log"
    python3 "$ANALYZE" "$TRACE" --block-csv "$BLOCKS" --json-out "$JSON" > "$ANALYZE_LOG" 2>&1
    echo "[$(date '+%F %T')] analyze QP=${QP} done" | tee -a "$OUT/run.log"
  else
    echo "[$(date '+%F %T')] analyze QP=${QP} skipped, blocks exists" | tee -a "$OUT/run.log"
  fi
done

COMBINED="$OUT/aerialcity_mfield_blocks.csv"
rm -f "$COMBINED"
FIRST=1
for QP in 22 27 32 37; do
  BLOCKS="$OUT/AerialCity_QP${QP}/blocks.csv"
  if [[ "$FIRST" == "1" ]]; then
    cat "$BLOCKS" >> "$COMBINED"
    FIRST=0
  else
    tail -n +2 "$BLOCKS" >> "$COMBINED"
  fi
done

python3 - <<'PY'
from pathlib import Path
out = Path("/root/vvenc_lard_exp/aerialcity_mfield_fullrdo")
rows = []
for qp in (22, 27, 32, 37):
    d = out / f"AerialCity_QP{qp}"
    rows.append((qp, (d/"trace.csv").stat().st_size, (d/"blocks.csv").stat().st_size, (d/"trace.csv.final.csv").stat().st_size))
with (out / "trace_block_summary.csv").open("w") as f:
    f.write("QP,TraceBytes,BlocksBytes,FinalBytes\n")
    for row in rows:
        f.write(",".join(map(str, row)) + "\n")
PY

echo "[$(date '+%F %T')] all done" | tee -a "$OUT/run.log"
