#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mode="${1:-full}"
out_root="${OUT_ROOT:-$repo_root/lahtp_runs/sjtu_patch_stretch_12_2}"
sequence_root="${SEQUENCE_ROOT:-/root/SJTU8K360sequence/first100f}"
encoder="${ENCODER:-$repo_root/bin/release-static/vvencapp}"
width="${WIDTH:-3840}"
height="${HEIGHT:-1920}"
frames="${FRAMES:-100}"

mkdir -p "$out_root"

stretch_name() {
  local value="$1"
  echo "${value//./p}"
}

if [[ "$mode" == "smoke" ]]; then
  splits=("validation")
  stretches=("1" "2")
  qps=("32")
  analysis_args=("--max-blocks-per-trace" "20000")
else
  splits=("train" "validation")
  stretches=("1" "1.15" "1.41" "2" "3.86" "5")
  qps=("22" "27" "32" "37")
  analysis_args=()
fi

python3 "$repo_root/tools/lard_lfnst_patch_stretch_12_2.py" generate \
  --sequence-root "$sequence_root" \
  --out-dir "$out_root" \
  --source-width "$width" \
  --source-height "$height" \
  --source-frames "$frames" \
  --splits "${splits[@]}" \
  --stretch "${stretches[@]}"

mkdir -p "$out_root/bin" "$out_root/logs" "$out_root/traces"
summary="$out_root/encode_summary.csv"
if [[ ! -f "$summary" ]]; then
  echo "split,s,qp,input,bitstream,trace,log,seconds" > "$summary"
fi

for split in "${splits[@]}"; do
  for s in "${stretches[@]}"; do
    s_file="$(stretch_name "$s")"
    input="$out_root/sequences/sjtu_${split}_patch256_s${s_file}_512x512_16f.yuv"
    for qp in "${qps[@]}"; do
      tag="${split}_s${s_file}_qp${qp}"
      bitstream="$out_root/bin/${tag}.266"
      trace="$out_root/traces/${tag}.csv"
      log="$out_root/logs/${tag}.log"
      if [[ -s "$bitstream" && -s "$trace" ]] && grep -q "^${split},${s},${qp}," "$summary"; then
        echo "[skip] $tag"
        continue
      fi
      echo "[encode] $tag"
      start="$(date +%s)"
      "$encoder" \
        --preset medium \
        -i "$input" \
        -s 512x512 \
        -r 30 \
        -c yuv420 \
        -q "$qp" \
        --qpa 0 \
        -f 16 \
        -ip 1 \
        --mtprofile 0 \
        --threads 1 \
        --additional "LardLfnstTraceFile=$trace LardLfnstSkip=0" \
        -o "$bitstream" > "$log" 2>&1
      end="$(date +%s)"
      echo "$split,$s,$qp,$input,$bitstream,$trace,$log,$((end - start))" >> "$summary"
    done
  done
done

python3 "$repo_root/tools/lard_lfnst_patch_mechanism_12_2.py" \
  --run-root "$out_root" \
  --manifest-dir "$out_root/manifests" \
  --out-dir "$out_root/analysis" \
  "${analysis_args[@]}"
