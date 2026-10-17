#!/usr/bin/env bash
set -euo pipefail

root=/root/VTM-23.0-route-b-a3
bin="$root/bin/umake/gcc-9.4/x86_64/release/EncoderApp"
seq=/root/sequences360_32f/AerialCity_3840x1920_30fps_8bit_420_erp.yuv
sph="$root/cfg-360Lib/360Lib/sphere_655362.txt"
out_root=/root/rc360_route_b_20260615/fullres_signal_decomposition

declare -A target=(
  [22]=18484890
  [27]=4622535
  [32]=2189700
  [37]=1191780
)
declare -A initial_qp=([22]="" [27]="" [32]=34 [37]=42)

run_case()
{
  local case_name=$1
  local ctu_enabled=$2
  local signal_mode=$3
  local case_dir="$out_root/$case_name"
  local status="$case_dir/status.log"
  local failed=0
  local pids=()
  local labels=()

  mkdir -p "$case_dir"
  printf '%s START case=%s ctu=%s signalMode=%s\n' \
    "$(date --iso-8601=seconds)" "$case_name" "$ctu_enabled" "$signal_mode" >> "$status"

  for qp in 22 27 32 37; do
    local point_dir="$case_dir/QP$qp"
    mkdir -p "$point_dir"
    rm -f "$point_dir/encode.log" "$point_dir/encode.stderr.log" \
          "$point_dir/str.bin" "$point_dir/exit_code.txt"

    local args=(
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
      --RC360Uprop=1 --RC360UpropFrame=0
      "--RC360UpropCtu=$ctu_enabled"
      "--RC360UpropCtuSignalMode=$signal_mode"
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
    local pid=$!
    printf '%d\n' "$pid" > "$point_dir/pid.txt"
    printf '%s START QP%d pid=%d\n' "$(date --iso-8601=seconds)" "$qp" "$pid" >> "$status"
    pids+=("$pid")
    labels+=("QP$qp")
  done

  for index in "${!pids[@]}"; do
    if wait "${pids[$index]}"; then
      printf '%s DONE %s\n' "$(date --iso-8601=seconds)" "${labels[$index]}" >> "$status"
    else
      printf '%s FAILED %s\n' "$(date --iso-8601=seconds)" "${labels[$index]}" >> "$status"
      failed=1
    fi
  done

  printf '%s DONE case=%s failed=%d\n' "$(date --iso-8601=seconds)" "$case_name" "$failed" >> "$status"
  return "$failed"
}

mkdir -p "$out_root"
sha256sum "$bin" > "$out_root/binary_sha256.txt"
run_case A1_analysis_only 0 0
run_case A3_1_u0_only 1 1
run_case A3_2_excess_only 1 2
run_case A3_3_current 1 0
