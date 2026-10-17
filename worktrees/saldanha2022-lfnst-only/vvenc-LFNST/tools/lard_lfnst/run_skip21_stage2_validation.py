#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


ANCHOR_ADDITIONAL = "LFNST=1 LardLfnstSkip=0"

PROFILES = {
    "ANCHOR_SELF_COMPARE": ANCHOR_ADDITIONAL,
    "S1_E15_noLat_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=6",
    "S2_D1_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=0",
    "S2_D2_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=1",
    "S2_D3_only": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2",
    "S2_D3_noLatRho06": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Theory=1",
    "S2_D3_NoLookup": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=1",
    "S2_D3_NullLookup": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=2",
    "S2_D3_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Debug=0",
    "S2_D4_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=3 LardLfnst21Stage2Debug=0",
    "S2_D5_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=4 LardLfnst21Stage2Debug=0",
    "S2_D6_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=5 LardLfnst21Stage2Debug=0",
    "S2_D7_compact": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=6 LardLfnst21Stage2Debug=0",
    "S2_D6_noGmax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=7 LardLfnst21Stage2Debug=0",
    "S2_V2_A1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=8 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S2_V2_A2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=9 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S2_V2_B1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=10 LardLfnst21Stage2HighCostMode=2 LardLfnst21Stage2Debug=0",
    "S2_V2_B2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=11 LardLfnst21Stage2HighCostMode=2 LardLfnst21Stage2Debug=0",
    "S2_V2_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S2_V2_C2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=13 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_E15_noLat_D1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=3 LardLfnst21Profile=6 LardLfnst21Stage2Profile=0",
    "S12_E15_noLat_D2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=3 LardLfnst21Profile=6 LardLfnst21Stage2Profile=1",
    "S12_A_E15_noLat_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=6 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_B_E12_noLat_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S123_Thin45": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=0",
    "S123_ThinMed45": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=1",
    "S123_Low45_All": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=2",
    "S123_Q22_Low60_All": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=3",
    "S123_Q22_Low75_All": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=4",
    "S123_Q22_AllLat_All": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=1 LardLfnst21Stage3Profile=5",
    "S123B_RDMax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=2 LardLfnst21Stage3RdProfile=2",
    "S123AB_Low45_RDMax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=3 LardLfnst21Stage3Profile=2 LardLfnst21Stage3RdProfile=2",
    "S123AB_Q22All_RDMax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=3 LardLfnst21Stage3Profile=5 LardLfnst21Stage3RdProfile=3",
    "S123AB_Q22All_RDMax_noS2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=13 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=3 LardLfnst21Stage3Profile=5 LardLfnst21Stage3RdProfile=3",
    "S123AB_Q22All_RDMax_noS1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=23 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=3 LardLfnst21Stage3Profile=5 LardLfnst21Stage3RdProfile=3",
    "S123AB_Q22All_RDMax_noS1_noLatRho06": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=23 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage2Theory=1 LardLfnst21Stage3Mode=3 LardLfnst21Stage3Profile=5 LardLfnst21Stage3RdProfile=3",
    "R1_RDE_REAL_M2HIGHTIME5_noS2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=13 LardLfnst21Profile=5 LardLfnst21Stage2Profile=0 LardLfnst21Stage3RdeMode=2 LardLfnst21Stage3RdeProfile=0 LardLfnst21Stage3RdeModel=1",
    "R1_RDE_REAL_M2HIGHTIME5_noS1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=23 LardLfnst21Profile=5 LardLfnst21Stage2Profile=0 LardLfnst21Stage3RdeMode=2 LardLfnst21Stage3RdeProfile=0 LardLfnst21Stage3RdeModel=1",
    "R1_RDE_REAL_M2HIGHTIME5_noS1_noLatRho06": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=23 LardLfnst21Profile=5 LardLfnst21Stage2Profile=0 LardLfnst21Stage2Theory=1 LardLfnst21Stage3RdeMode=2 LardLfnst21Stage3RdeProfile=0 LardLfnst21Stage3RdeModel=1",
    "R1_RDE_REAL_M2HIGHTIME5": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=3 LardLfnst21Profile=5 LardLfnst21Stage2Profile=0 LardLfnst21Stage3RdeMode=2 LardLfnst21Stage3RdeProfile=0 LardLfnst21Stage3RdeModel=1",
    "R1_STAGE1_ONLY_noRDE": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=5 LardLfnst21Stage3RdeMode=0",
    "R1_STAGE2_ONLY_noRDE": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=0 LardLfnst21Stage3RdeMode=0",
    "R1_STAGE2_D3_ONLY_noRDE": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage3RdeMode=0",
    "R1_STAGE2_D3_noLatRho06_ONLY_noRDE": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=2 LardLfnst21Stage2Profile=2 LardLfnst21Stage2Theory=1 LardLfnst21Stage3RdeMode=0",
    "S123ABR_Low45_RDMax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=4 LardLfnst21Stage3Profile=2 LardLfnst21Stage3RdProfile=2",
    "S123ABR_Q22All_RDMax": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=123 LardLfnst21Profile=5 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=4 LardLfnst21Stage3Profile=5 LardLfnst21Stage3RdProfile=3",
    "S12_C_E10_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=2 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_D_E12_noLat_D3HC1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=5 LardLfnst21Stage2Profile=2 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_E_E12_noLat_A1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=5 LardLfnst21Stage2Profile=8 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_F_E12_noLat_B1HC2": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=5 LardLfnst21Stage2Profile=10 LardLfnst21Stage2HighCostMode=2 LardLfnst21Stage2Debug=0",
    "S12_G_E15_noLat_D3HC1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=6 LardLfnst21Stage2Profile=2 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_H_E12_noLat_H64L5_D3HC1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=7 LardLfnst21Stage2Profile=2 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_I_E15_noLat_H64L5_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=8 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_J_E12_noLat_H64L4_D3HC1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=9 LardLfnst21Stage2Profile=2 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
    "S12_K_E15_noLat_H64L4_C1": "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=10 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0",
}
DEFAULT_PROFILES = "R1_STAGE1_ONLY_noRDE,R1_STAGE2_D3_ONLY_noRDE,R1_STAGE2_D3_noLatRho06_ONLY_noRDE"


def _qps_arg(qps: Sequence[int]) -> str:
    return ",".join(str(qp) for qp in qps)


def _parse_qps(text: str) -> list[int]:
    return [int(value.strip()) for value in text.split(",") if value.strip()]


def _parse_profiles(text: str) -> list[str]:
    names = [value.strip() for value in text.split(",") if value.strip()]
    if not names:
        raise ValueError("at least one Stage2 profile is required")
    unknown = [name for name in names if name not in PROFILES]
    if unknown:
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}; known: {', '.join(PROFILES)}")
    return names


def timing_command(
    encoder: str | Path,
    orig: str | Path,
    sphere_file: str | Path,
    out_root: str | Path,
    qps: Sequence[int],
    threads: int,
    preset: str,
    profile_name: str,
    frames: int,
    repeats: int,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tools.lard_lfnst.run_skip18_paired_repeats",
        "--encoder",
        str(encoder),
        "--orig",
        str(orig),
        "--sphere-file",
        str(sphere_file),
        "--out-root",
        str(out_root),
        "--qps",
        _qps_arg(qps),
        "--frames",
        str(frames),
        "--repeats",
        str(repeats),
        "--threads",
        str(threads),
        "--preset",
        preset,
        "--target-profile",
        "0",
        "--anchor-additional",
        ANCHOR_ADDITIONAL,
        "--proposed-additional",
        PROFILES[profile_name],
    ]


def run_validation(args: argparse.Namespace) -> dict[str, Any]:
    qps = _parse_qps(args.qps)
    profile_names = _parse_profiles(args.profiles)
    args.out_root.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, Any] = {}
    for profile_name in profile_names:
        profile_out = args.out_root / profile_name / "timing"
        profile_out.mkdir(parents=True, exist_ok=True)
        cmd = timing_command(
            encoder=args.encoder,
            orig=args.orig,
            sphere_file=args.sphere_file,
            out_root=profile_out,
            qps=qps,
            threads=args.threads,
            preset=args.preset,
            profile_name=profile_name,
            frames=args.frames,
            repeats=args.repeats,
        )
        subprocess.run(cmd, check=True)
        summaries[profile_name] = json.loads((profile_out / "summary.json").read_text(encoding="utf-8"))

    summary = {
        "configuration": {
            "profiles": profile_names,
            "profile_additional": {name: PROFILES[name] for name in profile_names},
            "qps": qps,
            "frames": args.frames,
            "repeats": args.repeats,
            "threads": args.threads,
            "preset": args.preset,
        },
        "profiles": summaries,
    }
    out_json = args.out_root / "skip21_stage2_validation_summary.json"
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--orig", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", default="22,27,32,37")
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--preset", default="medium")
    parser.add_argument(
        "--profiles",
        default=DEFAULT_PROFILES,
    )
    args = parser.parse_args()

    summary = run_validation(args)
    print(json.dumps(summary["configuration"], indent=2, sort_keys=True))
    print(f"summary={args.out_root / 'skip21_stage2_validation_summary.json'}")


if __name__ == "__main__":
    main()
