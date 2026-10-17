#!/usr/bin/env bash
set -euo pipefail

ROOT=${ROOT:-/root/vvenc_lard_exp}
SRC_ROOT=${SRC_ROOT:-$ROOT/vvenc-1.12.0-lard-src}
EXE=${EXE:-$SRC_ROOT/bin/release-static/vvencFFapp}
TOOLS=${TOOLS:-$ROOT/tools}
LABELS=${LABELS:-$TOOLS/lard_lfnst_ablation_experiments.py}
OUT=${OUT:-$ROOT/ablation_logging_platform}
YUV_ROOT=${YUV_ROOT:-/root/sequences360_32f}
THREADS=${THREADS:-20}
PRESET=${PRESET:-medium}
QPS=${QPS:-22,27,32,37}

mkdir -p "$OUT"

IFS=',' read -r -a QP_ARR <<< "$QPS"
SEQS=(
  "AerialCity|$YUV_ROOT/AerialCity_3840x1920_30fps_8bit_420_erp.yuv|3840x1920|30"
  "DrivingInCity|$YUV_ROOT/DrivingInCity_3840x1920_30fps_8bit_420_erp.yuv|3840x1920|30"
  "DrivingInCountry|$YUV_ROOT/DrivingInCountry_3840x1920_30fps_8bit_420_erp.yuv|3840x1920|30"
  "PoleVault_le|$YUV_ROOT/PoleVault_le_3840x1920_30fps_8bit_420_erp.yuv|3840x1920|30"
)

echo "[$(date '+%F %T')] ablation anchor start" | tee -a "$OUT/run.log"

for item in "${SEQS[@]}"; do
  IFS='|' read -r SEQ YUV SIZE FPS <<< "$item"
  if [[ ! -s "$YUV" ]]; then
    echo "[$(date '+%F %T')] ERROR missing $YUV" | tee -a "$OUT/run.log"
    exit 1
  fi
  for QP in "${QP_ARR[@]}"; do
    DIR="$OUT/${SEQ}_QP${QP}"
    mkdir -p "$DIR"
    TRACE="$DIR/trace.csv"
    TRACE_GZ="$DIR/trace.csv.gz"
    LABEL_CSV="$DIR/labels.csv"
    LABEL_JSON="$DIR/labels_summary.json"
    LOG="$DIR/anchor.log"
    BIT="$DIR/anchor.vvc"

    if [[ ! -s "$TRACE" && ! -s "$TRACE_GZ" ]]; then
      rm -f "$TRACE" "$TRACE_GZ" "$BIT" "$LOG"
      echo "[$(date '+%F %T')] encode seq=$SEQ QP=$QP" | tee -a "$OUT/run.log"
      set +e
      "$EXE" \
        -i "$YUV" -s "$SIZE" -f 1 -fr "$FPS" -q "$QP" \
        -b "$BIT" \
        --InputBitDepth 8 --OutputBitDepth 8 \
        --preset "$PRESET" --IntraPeriod 1 --GOPSize 1 \
        --PerceptQPA 0 --TargetBitrate 0 \
        --Threads "$THREADS" \
        --LardLfnstSkip 0 \
        --LardLfnstTraceFile "$TRACE" > "$LOG" 2>&1
      CODE=$?
      set -e
      if [[ ! -s "$TRACE" ]]; then
        echo "[$(date '+%F %T')] ERROR encode seq=$SEQ QP=$QP exit=$CODE no trace" | tee -a "$OUT/run.log"
        exit 1
      fi
      echo "[$(date '+%F %T')] encode seq=$SEQ QP=$QP exit=$CODE trace accepted" | tee -a "$OUT/run.log"
    else
      echo "[$(date '+%F %T')] encode seq=$SEQ QP=$QP skipped" | tee -a "$OUT/run.log"
    fi

    if [[ ! -s "$LABEL_CSV" ]]; then
      if [[ ! -s "$TRACE" && -s "$TRACE_GZ" ]]; then
        gzip -dk "$TRACE_GZ"
      fi
      echo "[$(date '+%F %T')] labels seq=$SEQ QP=$QP" | tee -a "$OUT/run.log"
      python3 "$LABELS" build-labels --traces "$TRACE" --seq "$SEQ" --out-csv "$LABEL_CSV" --summary-json "$LABEL_JSON"
      echo "[$(date '+%F %T')] labels seq=$SEQ QP=$QP done" | tee -a "$OUT/run.log"
    else
      echo "[$(date '+%F %T')] labels seq=$SEQ QP=$QP skipped" | tee -a "$OUT/run.log"
    fi

    if [[ -s "$TRACE" && ! -s "$TRACE_GZ" ]]; then
      gzip -f "$TRACE"
    fi
    rm -f "$BIT"
  done
done

COMBINED="$OUT/ablation_anchor_labels.csv"
rm -f "$COMBINED"
FIRST=1
for item in "${SEQS[@]}"; do
  IFS='|' read -r SEQ YUV SIZE FPS <<< "$item"
  for QP in "${QP_ARR[@]}"; do
    LABEL_CSV="$OUT/${SEQ}_QP${QP}/labels.csv"
    if [[ "$FIRST" == "1" ]]; then
      cat "$LABEL_CSV" >> "$COMBINED"
      FIRST=0
    else
      tail -n +2 "$LABEL_CSV" >> "$COMBINED"
    fi
  done
done

python3 - <<'PY'
from pathlib import Path
import csv, json
out = Path("/root/vvenc_lard_exp/ablation_logging_platform")
rows = list(csv.DictReader((out / "ablation_anchor_labels.csv").open(newline="")))
summary = {
    "rows": len(rows),
    "lfnstRdoTested": sum(r["lfnstRdoTested"] == "True" for r in rows),
    "positiveGain": sum(r["positiveGain"] == "True" for r in rows),
    "wastedRdo": sum(r["wastedRdo"] == "True" for r in rows),
    "seqs": sorted(set(r["seq"] for r in rows)),
    "qps": sorted(set(r["QP"] for r in rows)),
}
(out / "ablation_anchor_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
PY

tar -czf "$OUT/ablation_anchor_labels_and_logs.tar.gz" -C "$OUT" \
  ablation_anchor_labels.csv ablation_anchor_summary.json run.log \
  $(find "$OUT" -maxdepth 1 -type d -name '*_QP*' -printf '%f/labels.csv %f/labels_summary.json %f/anchor.log ')

echo "[$(date '+%F %T')] ablation anchor done" | tee -a "$OUT/run.log"
