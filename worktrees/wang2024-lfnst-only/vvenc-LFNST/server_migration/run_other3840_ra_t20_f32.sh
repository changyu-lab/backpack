#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/vvenc_lard_exp
SRC="$ROOT/vvenc-1.12.0-lard-src"
SEQ_DIR=/root/sequences360_32f
RUN_DIR="$ROOT/runs/other3840_ra_t20_f32"
LOG_DIR="$RUN_DIR/logs"
BS_DIR="$RUN_DIR/bitstreams"
TMP_DIR="$RUN_DIR/tmp_rec"
RAW="$RUN_DIR/raw_results.csv"
PROGRESS="$RUN_DIR/progress.txt"

mkdir -p "$LOG_DIR" "$BS_DIR" "$TMP_DIR"

if [[ ! -f "$PROGRESS" ]]; then
  echo "[START_BATCH] $(date '+%F %T')" > "$PROGRESS"
fi

echo "[WAIT_BUILD] $(date '+%F %T')" >> "$PROGRESS"
while [[ ! -f "$SRC/build_done.flag" ]]; do
  sleep 30
done

EXE="$SRC/bin/release-static/vvencFFapp"
if [[ ! -x "$EXE" ]]; then
  EXE="$SRC/bin/release-shared/vvencFFapp"
fi
if [[ ! -x "$EXE" ]]; then
  echo "[FAIL] vvencFFapp not found after build" >> "$PROGRESS"
  exit 1
fi

declare -A SEQS=(
  [DrivingInCity]="$SEQ_DIR/DrivingInCity_3840x1920_30fps_8bit_420_erp.yuv"
  [DrivingInCountry]="$SEQ_DIR/DrivingInCountry_3840x1920_30fps_8bit_420_erp.yuv"
  [PoleVault_le]="$SEQ_DIR/PoleVault_le_3840x1920_30fps_8bit_420_erp.yuv"
)

echo "[WAIT_SEQUENCES] $(date '+%F %T')" >> "$PROGRESS"
for key in "${!SEQS[@]}"; do
  path="${SEQS[$key]}"
  while [[ ! -s "$path" ]]; do
    sleep 30
  done
done

if [[ ! -f "$RAW" ]]; then
  echo "sequence,preset,set,qp,total_time_sec,bitrate_kbps,y_psnr,u_psnr,v_psnr,yuv_psnr,bitstream_bytes,rec_bytes_deleted,log,bitstream" > "$RAW"
fi

has_result() {
  local seq="$1" preset="$2" set_name="$3" qp="$4"
  awk -F, -v s="$seq" -v p="$preset" -v n="$set_name" -v q="$qp" 'NR>1 && $1==s && $2==p && $3==n && $4==q { found=1 } END { exit found ? 0 : 1 }' "$RAW"
}

csvq() {
  local s="$1"
  s="${s//\"/\"\"}"
  printf '"%s"' "$s"
}

presets=(faster fast medium slow)
qps=(22 27 32 37)
sets=(anchor proposed)

for seq in DrivingInCity DrivingInCountry PoleVault_le; do
  for preset in "${presets[@]}"; do
    for set_name in "${sets[@]}"; do
      for qp in "${qps[@]}"; do
        if has_result "$seq" "$preset" "$set_name" "$qp"; then
          echo "[SKIP] ${seq}_${preset}_${set_name}_qp${qp} already_done $(date '+%F %T')" >> "$PROGRESS"
          continue
        fi

        skip=0
        [[ "$set_name" == "proposed" ]] && skip=1
        tag="${seq}_${preset}_${set_name}_qp${qp}"
        bs="$BS_DIR/${tag}.266"
        rec="$TMP_DIR/${tag}_rec.yuv"
        stdout="$LOG_DIR/${tag}_stdout.txt"
        stderr="$LOG_DIR/${tag}_stderr.txt"

        rm -f "$bs" "$rec" "$stdout" "$stderr"
        echo "[START] $tag $(date '+%F %T')" >> "$PROGRESS"

        "$EXE" \
          -i "${SEQS[$seq]}" \
          -s 3840x1920 \
          -fr 30 \
          -f 32 \
          --preset "$preset" \
          -q "$qp" \
          -t 20 \
          --LFNST 1 \
          --LardLfnstSkip "$skip" \
          --LardLfnstPsi 0.70 \
          --LardLfnstThetaBaseDeg 62 \
          --LardLfnstThetaQpSlopeDeg 8 \
          --LardLfnstNzThr 5.0 \
          --LardLfnstMeanAbsQThr 1.25 \
          --LardLfnstMaxHorzRatio 0.62 \
          -b "$bs" \
          -o "$rec" \
          > "$stdout" 2> "$stderr"

        time_sec=$(grep -oP 'Total Time:\s*\K[0-9.]+' "$stdout" | tail -1)
        read -r bitrate ypsnr upsnr vpsnr yuvpsnr < <(python3 - "$stdout" <<'PY'
import re, sys
text=open(sys.argv[1], errors='replace').read()
m=re.search(r'vvenc \[info\]:\s*\d+\s+a\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', text)
if not m:
    raise SystemExit(1)
print(' '.join(m.groups()))
PY
)
        bs_size=$(stat -c '%s' "$bs")
        rec_size=0
        if [[ -f "$rec" ]]; then
          rec_size=$(stat -c '%s' "$rec")
        fi
        rm -f "$rec"

        {
          printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,' "$seq" "$preset" "$set_name" "$qp" "$time_sec" "$bitrate" "$ypsnr" "$upsnr" "$vpsnr" "$yuvpsnr" "$bs_size" "$rec_size"
          csvq "$stdout"
          printf ','
          csvq "$bs"
          printf '\n'
        } >> "$RAW"

        echo "[DONE] $tag time=$time_sec bitrate=$bitrate ypsnr=$ypsnr recDeleted=$rec_size $(date '+%F %T')" >> "$PROGRESS"
      done
    done
  done
done

echo "[ALL_DONE] $(date '+%F %T')" >> "$PROGRESS"
python3 "$ROOT/calc_summary.py" "$RAW" "$RUN_DIR"
