#!/usr/bin/env bash
set -euo pipefail

root=/root/VTM-23.0-route-b-3fdec3c
bin="$root/bin/umake/gcc-9.4/x86_64/release/EncoderApp"
seq=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
sph="$root/cfg-360Lib/360Lib/sphere_655362.txt"
out_root=/root/rc360_route_b_20260615/fullres_ablation_fixed/B0_server_same_binary

declare -A target=(
  [22]=18484890
  [27]=4622535
  [32]=2189700
  [37]=1191780
)
declare -A initial_qp=([22]="" [27]="" [32]=34 [37]=42)

mkdir -p "$out_root"
status="$out_root/status.log"
printf '%s START B0 same-binary control\n' "$(date --iso-8601=seconds)" >> "$status"
sha256sum "$bin" > "$out_root/binary_sha256.txt"

pids=()
labels=()
for qp in 22 27 32 37; do
  point_dir="$out_root/QP$qp"
  mkdir -p "$point_dir"
  rm -f "$point_dir/encode.log" "$point_dir/encode.stderr.log" \
        "$point_dir/str.bin" "$point_dir/exit_code.txt"

  args=(
    -c "$root/cfg/encoder_lowdelay_P_vtm.cfg"
    -c "$root/cfg-360Lib/encoder_360_ERP.cfg"
    -c "$root/cfg-360Lib/per-sequence/360/360test_AerialCity.cfg"
    -c "$root/cfg/rc360_ieff_only_ctu_rd_aerialcity3840.cfg"
    -i "$seq"
    -wdt 3840 -hgt 1920 -fr 30 -f 16
    --InputBitDepth=8 --FramesToBeEncoded=16
    --RateControl=1 --LCULevelRateControl=1 --RCLCUSeparateModel=1
    --WaveFrontSynchro=0
    --RC360IBRC=1 --RC360FbTc=0
    --RC360IBRCCtuLevel=1 --RC360IBRCCtuMode=1
    --RC360IBRCModelUpdate=0
    --RC360Uprop=0 --RC360UpropFrame=0 --RC360UpropCtu=0
    --RC360UpropAlpha=0.30 --RC360UpropBeta=0.20
    --RC360UpropMin=0.70 --RC360UpropMax=1.50
    --RC360UpropFrameMin=0.95 --RC360UpropFrameMax=1.05
    --RC360UpropSearchRange=16 --RC360UpropSearchStep=4
    --CodingFaceWidth=3840 --CodingFaceHeight=1920
    --WSPSNR=1 --E2EWSPSNR=1 --SPSNR_NN=1
    --CPP_PSNR=1 --CF_CPP_PSNR=1
    --ViewPortPSNREnable=0 --DynamicViewPortPSNREnable=0
    "--SphFile=$sph"
    -q "$qp" "--TargetBitrate=${target[$qp]}"
    -b "$point_dir/str.bin" -o /dev/null
  )
  if [[ -n "${initial_qp[$qp]}" ]]; then
    args+=("--InitialQP=${initial_qp[$qp]}")
  fi

  printf '%q ' "$bin" "${args[@]}" > "$point_dir/command.txt"
  printf '\n' >> "$point_dir/command.txt"
  (
    set +e
    "$bin" "${args[@]}" > "$point_dir/encode.log" 2> "$point_dir/encode.stderr.log"
    rc=$?
    printf '%d\n' "$rc" > "$point_dir/exit_code.txt"
    exit "$rc"
  ) &
  pid=$!
  printf '%d\n' "$pid" > "$point_dir/pid.txt"
  printf '%s START QP%d pid=%d\n' "$(date --iso-8601=seconds)" "$qp" "$pid" >> "$status"
  pids+=("$pid")
  labels+=("QP$qp")
done

failed=0
for index in "${!pids[@]}"; do
  if wait "${pids[$index]}"; then
    printf '%s DONE %s\n' "$(date --iso-8601=seconds)" "${labels[$index]}" >> "$status"
  else
    printf '%s FAILED %s\n' "$(date --iso-8601=seconds)" "${labels[$index]}" >> "$status"
    failed=1
  fi
done

printf '%s DONE failed=%d\n' "$(date --iso-8601=seconds)" "$failed" >> "$status"
exit "$failed"
