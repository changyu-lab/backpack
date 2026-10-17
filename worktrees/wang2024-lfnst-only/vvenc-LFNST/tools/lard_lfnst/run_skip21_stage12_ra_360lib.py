#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from tools.lard_360_metrics import bdrate, parse_log
from tools.lard_lfnst.official_360lib_metrics import run_360lib_metrics, sha256_file
from tools.lard_lfnst.run_skip21_stage12_erp14_configs import (
    parse_csv_list,
    parse_qps,
    parse_sequence,
    paired_schedule,
    run_cmd,
    sha256,
    summarize_timing,
    write_csv,
)
from tools.lard_lfnst.run_skip21_stage2_validation import ANCHOR_ADDITIONAL, PROFILES


FORMAL_PROFILES = {
    "S12_A_E15_noLat_C1",
    "S12_B_E12_noLat_C1",
    "S12_C_E10_C1",
    "S12_D_E12_noLat_D3HC1",
    "S12_E_E12_noLat_A1",
    "S12_F_E12_noLat_B1HC2",
    "S12_G_E15_noLat_D3HC1",
    "S12_Q1_LowA_HighB",
    "S12_Q2_LowA_HighD",
    "S12_Q3_LowB_HighD",
    "S12_Q2_H64L5",
    "S12_Q2_H64L4",
    "S12_Q2_H64L4_QPlo",
    "S123_Low45_All",
    "S123_Q22_AllLat_All",
    "S123_Q22_Low75_All",
    "S123_Q22_Low60_All",
    "S123AB_Q22All_RDMax",
    "S123AB_Low45_RDMax",
    "S123ABR_Q22All_RDMax",
    "S123ABR_Low45_RDMax",
    "A0_Current",
    "A1_OpenS1_E15NoLat",
    "A2_OpenS2_D3",
    "A3_OpenS2_NoGmax",
    "A4_TSMax_Q22All",
    "B1_S1_Support85",
    "B2_S1_Support100",
    "B3_S2_Ox18_NoDiag",
    "B4_S2_AllTheory",
    "B5_S12_TSMax",
    "B6A_S1_E70",
    "B6B_S12_E70",
    "B6C_S123_E70",
    "E0_B6B_base",
    "E1_B6B_QP22_27_pushS1",
    "E2_B6B_QP22_27_pushS2",
    "E3_B6B_all_pushS2",
    "E4_B6B_QP22_27_only",
    "C2_B6B_seqPolicy8",
    "C3_B6Hybrid14",
    "B6_S1_Support70",
    "B7_S1_Support75",
    "B8_S1_Support80",
    "B9_S1_Support90",
}
QP_ADAPTIVE_PROFILES = {
    "S12_Q1_LowA_HighB": {
        22: PROFILES["S12_A_E15_noLat_C1"],
        27: PROFILES["S12_A_E15_noLat_C1"],
        32: PROFILES["S12_B_E12_noLat_C1"],
        37: PROFILES["S12_B_E12_noLat_C1"],
    },
    "S12_Q2_LowA_HighD": {
        22: PROFILES["S12_A_E15_noLat_C1"],
        27: PROFILES["S12_A_E15_noLat_C1"],
        32: PROFILES["S12_D_E12_noLat_D3HC1"],
        37: PROFILES["S12_D_E12_noLat_D3HC1"],
    },
    "S12_Q3_LowB_HighD": {
        22: PROFILES["S12_B_E12_noLat_C1"],
        27: PROFILES["S12_B_E12_noLat_C1"],
        32: PROFILES["S12_D_E12_noLat_D3HC1"],
        37: PROFILES["S12_D_E12_noLat_D3HC1"],
    },
    "S12_Q2_H64L5": {
        22: PROFILES["S12_I_E15_noLat_H64L5_C1"],
        27: PROFILES["S12_I_E15_noLat_H64L5_C1"],
        32: PROFILES["S12_H_E12_noLat_H64L5_D3HC1"],
        37: PROFILES["S12_H_E12_noLat_H64L5_D3HC1"],
    },
    "S12_Q2_H64L4": {
        22: PROFILES["S12_K_E15_noLat_H64L4_C1"],
        27: PROFILES["S12_K_E15_noLat_H64L4_C1"],
        32: PROFILES["S12_J_E12_noLat_H64L4_D3HC1"],
        37: PROFILES["S12_J_E12_noLat_H64L4_D3HC1"],
    },
    "S12_Q2_H64L4_QPlo": {
        22: PROFILES["S12_K_E15_noLat_H64L4_C1"],
        27: PROFILES["S12_K_E15_noLat_H64L4_C1"],
        32: PROFILES["S12_D_E12_noLat_D3HC1"],
        37: PROFILES["S12_D_E12_noLat_D3HC1"],
    },
    "E1_B6B_QP22_27_pushS1": {
        22: "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=8 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=0",
        27: "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=12 LardLfnst21Profile=8 LardLfnst21Stage2Profile=12 LardLfnst21Stage2HighCostMode=1 LardLfnst21Stage2Debug=0 LardLfnst21Stage3Mode=0",
        32: PROFILES["E0_B6B_base"],
        37: PROFILES["E0_B6B_base"],
    },
    "E2_B6B_QP22_27_pushS2": {
        22: PROFILES["E3_B6B_all_pushS2"],
        27: PROFILES["E3_B6B_all_pushS2"],
        32: PROFILES["E0_B6B_base"],
        37: PROFILES["E0_B6B_base"],
    },
    "E4_B6B_QP22_27_only": {
        22: PROFILES["E0_B6B_base"],
        27: PROFILES["E0_B6B_base"],
        32: ANCHOR_ADDITIONAL,
        37: ANCHOR_ADDITIONAL,
    },
}
SEQUENCE_ADAPTIVE_PROFILES = {
    "C2_B6B_seqPolicy8": {
        # Best TS/WS choice from the repeat=1 E0-E4 targeted screen.
        "AerialCity": QP_ADAPTIVE_PROFILES["E1_B6B_QP22_27_pushS1"],
        "Balboa": QP_ADAPTIVE_PROFILES["E2_B6B_QP22_27_pushS2"],
        "ChairliftRide": QP_ADAPTIVE_PROFILES["E4_B6B_QP22_27_only"],
        "DrivingInCity": QP_ADAPTIVE_PROFILES["E2_B6B_QP22_27_pushS2"],
        "Gaslamp": QP_ADAPTIVE_PROFILES["E4_B6B_QP22_27_only"],
        "Harbor": PROFILES["E0_B6B_base"],
        "Landing2": PROFILES["E3_B6B_all_pushS2"],
        "SkateboardInLot": PROFILES["E3_B6B_all_pushS2"],
    },
    "C3_B6Hybrid14": {
        # C2 choices for the 8 weak B6 sequences; original B6 for the remaining 6.
        "AerialCity": QP_ADAPTIVE_PROFILES["E1_B6B_QP22_27_pushS1"],
        "Balboa": QP_ADAPTIVE_PROFILES["E2_B6B_QP22_27_pushS2"],
        "BranCastle2": PROFILES["B6_S1_Support70"],
        "Broadway": PROFILES["B6_S1_Support70"],
        "ChairliftRide": QP_ADAPTIVE_PROFILES["E4_B6B_QP22_27_only"],
        "DrivingInCity": QP_ADAPTIVE_PROFILES["E2_B6B_QP22_27_pushS2"],
        "DrivingInCountry": PROFILES["B6_S1_Support70"],
        "Gaslamp": QP_ADAPTIVE_PROFILES["E4_B6B_QP22_27_only"],
        "Harbor": PROFILES["E0_B6B_base"],
        "KiteFlite": PROFILES["B6_S1_Support70"],
        "Landing2": PROFILES["E3_B6B_all_pushS2"],
        "PoleVault_le": PROFILES["B6_S1_Support70"],
        "SkateboardInLot": PROFILES["E3_B6B_all_pushS2"],
        "Trolley": PROFILES["B6_S1_Support70"],
    },
}
OFFICIAL_METRIC_KEYS = tuple(
    f"360Lib13_6_{metric}_{component}"
    for metric in ("PSNR", "S", "WS", "CPP")
    for component in ("Y", "U", "V")
)
OFFICIAL_360LIB_FIELDS = OFFICIAL_METRIC_KEYS
REQUIRED_ACCEPTANCE_BDBR_KEYS = (
    "360Lib13_6_WS_Y_BDBR_pct",
    "360Lib13_6_S_Y_BDBR_pct",
    "360Lib13_6_CPP_Y_BDBR_pct",
)


def frames_for_ra(ra_gop: int) -> int:
    if ra_gop <= 0:
        raise ValueError(f"RA GOP must be positive, got {ra_gop}")
    return 2 * ra_gop


ra_frames = frames_for_ra


def normalize_encode_config(encode_config: str) -> str:
    config = encode_config.upper()
    if config not in {"RA", "LD", "AI"}:
        raise ValueError(f"unknown encode config: {encode_config}")
    return config


def frames_for_config(encode_config: str, *, ra_gop: int, ld_gop: int, ai_frames: int) -> int:
    config = normalize_encode_config(encode_config)
    if config == "RA":
        return frames_for_ra(ra_gop)
    if config == "LD":
        if ld_gop <= 0:
            raise ValueError(f"LD GOP must be positive, got {ld_gop}")
        return 2 * ld_gop
    if ai_frames <= 0:
        raise ValueError(f"AI frames must be positive, got {ai_frames}")
    return ai_frames


def encoder_config_options(encode_config: str, *, ra_gop: int, ld_gop: int) -> list[str]:
    config = normalize_encode_config(encode_config)
    if config == "RA":
        return ["--IntraPeriod", str(ra_gop), "--GOPSize", str(ra_gop), "--DecodingRefreshType", "1"]
    if config == "LD":
        return [
            "--IntraPeriod",
            "-1",
            "--GOPSize",
            str(ld_gop),
            "--DecodingRefreshType",
            "0",
            "--PicReordering",
            "0",
            "--POC0IDR",
            "1",
        ]
    return ["--IntraPeriod", "1", "--GOPSize", "1", "--DecodingRefreshType", "1"]


def case_paths(run_dir: Path, kind: str) -> dict[str, Path]:
    return {
        "bitstream": run_dir / f"{kind}.vvc",
        "reconstruction": run_dir / f"{kind}_rec.yuv",
        "log": run_dir / f"{kind}.log",
        "360lib_log": run_dir / f"{kind}_360lib.log",
        "official_metrics_json": run_dir / f"{kind}_official_360lib_metrics.json",
        "manifest": run_dir / f"{kind}_case_manifest.json",
    }


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _completion_candidates(run_dir: Path, kind: str | None) -> tuple[list[Path], list[Path], list[Path]]:
    if kind is None:
        return (
            [run_dir / "case_manifest.json"],
            [run_dir / "official_360lib_metrics.json"],
            sorted(run_dir.glob("*.log")),
        )
    paths = case_paths(run_dir, kind)
    return (
        [paths["manifest"]],
        [paths["official_metrics_json"]],
        [paths["log"]],
    )


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _official_metrics_are_valid(official: dict[str, Any], expected_frames: int) -> bool:
    if official.get("backend") != "360Lib13_6":
        return False
    try:
        if int(official["frame_count"]) != expected_frames:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return all(_is_finite_number(official.get(key)) for key in OFFICIAL_METRIC_KEYS)


def _official_hashes_match_expected(official: dict[str, Any], expected: dict[str, object]) -> bool:
    expected_hashes = expected.get("hashes")
    if not isinstance(expected_hashes, dict):
        return True
    required_hashes = (
        ("executable_sha256", "convert360_sha256"),
        ("sphere_sha256", "sphere_sha256"),
    )
    for official_key, expected_key in required_hashes:
        if expected_key in expected_hashes and official.get(official_key) != expected_hashes[expected_key]:
            return False
    return True


def _numeric_conflicts(left: Any, right: Any) -> bool:
    if not _is_finite_number(left) or not _is_finite_number(right):
        return True
    return float(left) != float(right)


def _manifest_conflicts_with_official(
    manifest: dict[str, Any],
    official: dict[str, Any],
    expected: dict[str, object],
    kind: str | None,
) -> bool:
    if "backend" in manifest and manifest["backend"] != official["backend"]:
        return True

    expected_frames = int(expected["frames"])
    for key, expected_value in expected.items():
        if key == "hashes":
            manifest_hashes = manifest.get("hashes")
            if not isinstance(expected_value, dict) or not isinstance(manifest_hashes, dict):
                return True
            for hash_key, expected_hash in expected_value.items():
                if manifest_hashes.get(hash_key) != expected_hash:
                    return True
            continue
        if key not in manifest:
            return True
        if key == "frames":
            try:
                if int(manifest[key]) != expected_frames:
                    return True
            except (TypeError, ValueError):
                return True
        elif manifest[key] != expected_value:
            return True

    if "frame_count" in manifest:
        try:
            if int(manifest["frame_count"]) != expected_frames:
                return True
        except (TypeError, ValueError):
            return True

    if kind is not None and "kind" in manifest and manifest["kind"] != kind:
        return True

    sources = [manifest]
    nested = manifest.get("official_metrics")
    if isinstance(nested, dict):
        sources.append(nested)
    for source in sources:
        if "backend" in source and source["backend"] != official["backend"]:
            return True
        if "frame_count" in source:
            try:
                if int(source["frame_count"]) != expected_frames:
                    return True
            except (TypeError, ValueError):
                return True
        for key in OFFICIAL_METRIC_KEYS:
            if key in source and _numeric_conflicts(source[key], official[key]):
                return True
    return False


def case_is_complete(run_dir: Path, expected: dict[str, object], kind: str | None = None) -> bool:
    manifest_candidates, official_candidates, log_candidates = _completion_candidates(run_dir, kind)
    manifest_path = _first_existing(manifest_candidates)
    official_path = _first_existing(official_candidates)
    log_path = _first_existing(log_candidates)
    if manifest_path is None or official_path is None or log_path is None:
        return False

    manifest = _load_json(manifest_path)
    official = _load_json(official_path)
    if manifest is None or official is None:
        return False

    expected_frames = int(expected["frames"])
    if not _official_metrics_are_valid(official, expected_frames):
        return False
    if not _official_hashes_match_expected(official, expected):
        return False
    return not _manifest_conflicts_with_official(manifest, official, expected, kind)


def cleanup_successful_case(bitstream: Path, reconstruction: Path, keep_bitstreams: bool) -> None:
    reconstruction.unlink(missing_ok=True)
    if not keep_bitstreams:
        bitstream.unlink(missing_ok=True)


def cleanup_after_manifest_validation(
    bitstream: Path,
    reconstruction: Path,
    *,
    keep_bitstreams: bool,
    manifest_valid: bool,
) -> bool:
    if not manifest_valid:
        return False
    cleanup_successful_case(bitstream, reconstruction, keep_bitstreams)
    return True


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def load_external_profiles(path: Path | None) -> list[str]:
    """Register calibrated profiles without hard-coding a data-derived risk margin in source."""
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError(f"{path}: expected non-empty object key 'profiles'")
    loaded: list[str] = []
    for name, additional in profiles.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(additional, str) or not additional.strip():
            raise ValueError(f"{path}: profile names and additional strings must be non-empty strings")
        PROFILES[name] = additional
        FORMAL_PROFILES.add(name)
        loaded.append(name)
    return loaded

def validate_profiles(profile_names: list[str]) -> list[str]:
    if not profile_names:
        raise ValueError("at least one profile is required")
    known_profiles = set(PROFILES) | set(QP_ADAPTIVE_PROFILES) | set(SEQUENCE_ADAPTIVE_PROFILES)
    unknown = [name for name in profile_names if name not in known_profiles]
    non_formal = [name for name in profile_names if name in known_profiles and name not in FORMAL_PROFILES]
    if unknown:
        raise ValueError(f"unknown profile(s): {', '.join(unknown)}")
    if non_formal:
        raise ValueError(f"non-formal profile(s): {', '.join(non_formal)}; use formal RA profiles only")
    return profile_names


def parse_formal_profiles(text: str) -> list[str]:
    return validate_profiles(parse_csv_list(text))


def _additional_from_qp_spec(profile_name: str, spec: str | dict[int, str], qp: int) -> str:
    if isinstance(spec, dict):
        try:
            return spec[int(qp)]
        except KeyError as exc:
            raise ValueError(f"QP-adaptive profile {profile_name} has no command for QP{qp}") from exc
    return spec


def proposed_additional_for_qp(profile_name: str, qp: int, sequence_name: str | None = None) -> str:
    if sequence_name is not None and profile_name in SEQUENCE_ADAPTIVE_PROFILES:
        sequence_map = SEQUENCE_ADAPTIVE_PROFILES[profile_name]
        try:
            sequence_spec = sequence_map[str(sequence_name)]
        except KeyError as exc:
            raise ValueError(f"sequence-adaptive profile {profile_name} has no command for {sequence_name}") from exc
        return _additional_from_qp_spec(profile_name, sequence_spec, qp)
    if profile_name in QP_ADAPTIVE_PROFILES:
        return _additional_from_qp_spec(profile_name, QP_ADAPTIVE_PROFILES[profile_name], qp)
    return PROFILES[profile_name]


def profile_additional_manifest(profile_name: str, qps: list[int], sequences: list[str] | None = None) -> str | dict[str, Any]:
    if profile_name in SEQUENCE_ADAPTIVE_PROFILES:
        if sequences is None:
            sequences = sorted(SEQUENCE_ADAPTIVE_PROFILES[profile_name])
        return {
            str(sequence): {
                str(qp): proposed_additional_for_qp(profile_name, qp, str(sequence))
                for qp in qps
            }
            for sequence in sequences
        }
    if profile_name in QP_ADAPTIVE_PROFILES:
        return {str(qp): proposed_additional_for_qp(profile_name, qp) for qp in qps}
    return PROFILES[profile_name]


def case_additional_with_optional_audit(
    additional: str,
    *,
    kind: str,
    qp: int,
    run_dir: Path,
    args: argparse.Namespace,
) -> str:
    if not bool(getattr(args, "lfnst21_audit", False)):
        return additional
    audit_base = run_dir / f"audit_{kind}_qp{int(qp)}"
    try:
        audit_arg = os.path.relpath(audit_base, Path.cwd())
    except ValueError:
        audit_arg = str(audit_base)
    return f"{additional} LardLfnst21AuditFile={audit_arg}"


def discover_sequences(seq_root: Path, sequence_filter: str, expect_count: int | None) -> list[dict[str, Any]]:
    sequences = [parse_sequence(path) for path in sorted(seq_root.glob("*_erp.yuv"))]
    if sequence_filter:
        pattern = re.compile(sequence_filter)
        sequences = [seq for seq in sequences if pattern.search(str(seq["name"]))]
    if not sequences:
        if sequence_filter:
            raise RuntimeError(f"sequence filter matched no ERP sequences: {sequence_filter}")
        raise RuntimeError(f"found no ERP sequences under {seq_root}")
    if not sequence_filter and expect_count is not None and expect_count >= 0 and len(sequences) != expect_count:
        raise RuntimeError(f"expected {expect_count} ERP sequences under {seq_root}, found {len(sequences)}")
    return sequences


def case_run_dir(out_root: Path, profile_name: str, sequence_name: str, qp: int, repeat: int) -> Path:
    if ".." in Path(profile_name).parts or ".." in Path(sequence_name).parts:
        raise ValueError(f"case run dir is outside out-root: {profile_name}/{sequence_name}")
    path = out_root / profile_name / sequence_name / f"QP{qp}" / f"repeat{repeat}"
    resolved_root = out_root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"case run dir is outside out-root: {path}")
    return path


def validate_formal_qps(qps: list[int]) -> list[int]:
    sorted_qps = sorted(int(qp) for qp in qps)
    if sorted_qps != [22, 27, 32, 37]:
        raise ValueError(f"formal RA run requires QPs 22,27,32,37, got {qps}")
    if len(set(sorted_qps)) != len(sorted_qps):
        raise ValueError(f"formal RA QPs must be unique, got {qps}")
    return qps


def _validate_regular_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist or is not a file: {path}")
    return path


def _validate_executable_file(path: Path, label: str) -> Path:
    path = _validate_regular_file(path, label)
    has_execute_bit = bool(path.stat().st_mode & 0o111)
    if os.name == "nt" and (path.suffix.lower() in {".exe", ".bat", ".cmd"} or has_execute_bit):
        return path
    if os.name != "nt" and has_execute_bit:
        return path
    raise PermissionError(f"{label} is not executable: {path}")


def _validate_out_root(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    if not resolved.name or resolved == resolved.parent:
        raise ValueError(f"refusing unsafe out-root: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"out-root exists but is not a directory: {path}")
    parent = resolved.parent
    if not parent.exists():
        raise ValueError(f"out-root parent does not exist: {parent}")
    return resolved


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    encoder = _validate_executable_file(args.encoder, "encoder")
    convert360 = _validate_executable_file(args.convert360, "360convert")
    sphere_file = _validate_regular_file(args.sphere_file, "sphere file")
    out_root = _validate_out_root(args.out_root)
    qps = validate_formal_qps(parse_qps(args.qps))
    profiles = parse_formal_profiles(args.profiles)
    encode_config = normalize_encode_config(args.encode_config)
    frames = frames_for_config(encode_config, ra_gop=args.ra_gop, ld_gop=args.ld_gop, ai_frames=args.ai_frames)
    sequences = discover_sequences(args.seq_root, args.sequence_filter, args.expect_count)
    too_short = [f"{seq['name']}({seq['available_frames']}f)" for seq in sequences if int(seq["available_frames"]) < frames]
    if too_short:
        raise RuntimeError(f"{encode_config} requires {frames} frames, but sequence(s) are too short: {', '.join(too_short)}")
    return {
        "encoder": encoder,
        "convert360": convert360,
        "sphere_file": sphere_file,
        "out_root": out_root,
        "qps": qps,
        "profiles": profiles,
        "encode_config": encode_config,
        "frames": frames,
        "sequences": sequences,
    }


def build_encoder_command(
    *,
    encoder: Path,
    seq: dict[str, Any],
    qp: int,
    frames: int,
    encode_config: str,
    ra_gop: int,
    ld_gop: int,
    threads: int,
    preset: str,
    additional: str,
    bitstream: Path,
    reconstruction: Path,
) -> list[str]:
    return [
        str(encoder),
        "--preset",
        preset,
        "-i",
        str(seq["path"]),
        "-s",
        f"{seq['width']}x{seq['height']}",
        "-r",
        str(seq["fps"]),
        "--InputChromaFormat",
        "420",
        "--InputBitDepth",
        str(seq["bitdepth"]),
        "-q",
        str(qp),
        "--qpa",
        "0",
        "-f",
        str(frames),
        "--mtprofile",
        "0",
        "--threads",
        str(threads),
        *encoder_config_options(encode_config, ra_gop=ra_gop, ld_gop=ld_gop),
        "--additional",
        additional,
        "-b",
        str(bitstream),
        "-o",
        str(reconstruction),
    ]


def _manifest_path_for_resume(run_dir: Path, kind: str) -> Path:
    candidates, _, _ = _completion_candidates(run_dir, kind)
    path = _first_existing(candidates)
    return path if path is not None else case_paths(run_dir, kind)["manifest"]


def case_expected_contract(
    *,
    encoder: Path,
    convert360: Path,
    seq: dict[str, Any],
    qp: int,
    repeat: int,
    kind: str,
    additional: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    encode_config = normalize_encode_config(args.encode_config)
    frames = frames_for_config(encode_config, ra_gop=args.ra_gop, ld_gop=args.ld_gop, ai_frames=args.ai_frames)
    return {
        "backend": "360Lib13_6",
        "encode_config": encode_config,
        "profile": str(getattr(args, "profile_name", "")),
        "kind": kind,
        "QP": qp,
        "repeat": repeat,
        "sequence": str(seq["name"]),
        "width": int(seq["width"]),
        "height": int(seq["height"]),
        "fps": int(seq["fps"]),
        "bitdepth": int(seq["bitdepth"]),
        "frames": frames,
        "gop": args.ra_gop,
        "ld_gop": args.ld_gop,
        "ai_frames": args.ai_frames,
        "additional": additional,
        "hashes": {
            "encoder_sha256": sha256_file(encoder),
            "convert360_sha256": sha256_file(convert360),
            "sphere_sha256": sha256_file(args.sphere_file),
        },
    }


def run_encode_case(
    *,
    encoder: Path,
    convert360: Path,
    seq: dict[str, Any],
    run_dir: Path,
    qp: int,
    repeat: int,
    kind: str,
    additional: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    encode_config = normalize_encode_config(args.encode_config)
    frames = frames_for_config(encode_config, ra_gop=args.ra_gop, ld_gop=args.ld_gop, ai_frames=args.ai_frames)
    expected = case_expected_contract(
        encoder=encoder,
        convert360=convert360,
        seq=seq,
        qp=qp,
        repeat=repeat,
        kind=kind,
        additional=additional,
        args=args,
    )
    paths = case_paths(run_dir, kind)
    if getattr(args, "resume", False) and case_is_complete(run_dir, expected, kind=kind):
        manifest = _load_json(_manifest_path_for_resume(run_dir, kind))
        if manifest is None:
            raise RuntimeError(f"complete case has unreadable manifest: {run_dir}")
        cleanup_successful_case(paths["bitstream"], paths["reconstruction"], bool(args.keep_bitstreams))
        return manifest

    run_dir.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        path.unlink(missing_ok=True)

    command = build_encoder_command(
        encoder=encoder,
        seq=seq,
        qp=qp,
        frames=frames,
        encode_config=encode_config,
        ra_gop=args.ra_gop,
        ld_gop=args.ld_gop,
        threads=args.threads,
        preset=args.preset,
        additional=additional,
        bitstream=paths["bitstream"],
        reconstruction=paths["reconstruction"],
    )
    seconds = run_cmd(command, paths["log"])
    bitrate, ord_y, ord_u, ord_v, ord_yuv = parse_log(paths["log"])
    bitstream_size = paths["bitstream"].stat().st_size
    bitstream_hash = sha256(paths["bitstream"])

    official_metrics = run_360lib_metrics(
        executable=convert360,
        original=Path(seq["path"]),
        reconstruction=paths["reconstruction"],
        sphere_file=args.sphere_file,
        width=int(seq["width"]),
        height=int(seq["height"]),
        fps=int(seq["fps"]),
        frames=frames,
        original_bitdepth=int(seq["bitdepth"]),
        reconstruction_bitdepth=int(getattr(args, "rec_bitdepth", 10)),
        log_path=paths["360lib_log"],
        parsed_json_path=paths["official_metrics_json"],
    )

    manifest: dict[str, Any] = {
        **expected,
        "command": command,
        "Seconds": seconds,
        "Kbps": bitrate,
        "Bytes": bitstream_size,
        "SHA256": bitstream_hash,
        "ORD_Y": ord_y,
        "ORD_U": ord_u,
        "ORD_V": ord_v,
        "ORD_YUV": ord_yuv,
        "official_metrics": official_metrics,
        "paths": {name: str(path) for name, path in paths.items()},
        "hashes": {
            **expected["hashes"],
            "bitstream_sha256": bitstream_hash,
        },
    }
    for key in OFFICIAL_METRIC_KEYS:
        if key in official_metrics:
            manifest[key] = official_metrics[key]
    atomic_write_json(paths["manifest"], manifest)

    if not case_is_complete(run_dir, expected, kind=kind):
        raise RuntimeError(f"case did not validate after manifest write: {run_dir} kind={kind}")
    cleanup_successful_case(paths["bitstream"], paths["reconstruction"], bool(args.keep_bitstreams))
    return manifest


def _row_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    row = {
        "repeat": manifest["repeat"],
        "QP": manifest["QP"],
        "kind": manifest["kind"],
        "Seconds": manifest["Seconds"],
        "Kbps": manifest["Kbps"],
        "Bytes": manifest["Bytes"],
        "SHA256": manifest["SHA256"],
        "ORD_Y": manifest["ORD_Y"],
        "ORD_U": manifest["ORD_U"],
        "ORD_V": manifest["ORD_V"],
        "ORD_YUV": manifest["ORD_YUV"],
    }
    for key in OFFICIAL_METRIC_KEYS:
        row[key] = manifest.get(key, manifest.get("official_metrics", {}).get(key))
    return row


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def validate_bd_curve_points(rows: list[dict[str, Any]], qps: list[int], metric_key: str) -> dict[str, list[float]]:
    if len(qps) != 4:
        raise ValueError(f"BDBR requires exactly four QPs, got {qps}")
    if metric_key not in OFFICIAL_METRIC_KEYS:
        raise ValueError(f"unknown official metric key: {metric_key}")

    requested_qps = sorted(int(qp) for qp in qps)
    if len(set(requested_qps)) != len(requested_qps):
        raise ValueError(f"BDBR QPs must be unique, got {qps}")
    indexed: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        try:
            repeat = int(row.get("repeat", 1))
            qp = int(row["QP"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(row.get("kind", ""))
        if repeat != 1 or qp not in requested_qps or kind not in {"anchor", "proposed"}:
            continue
        index_key = (qp, kind)
        if index_key in indexed:
            raise ValueError(f"duplicate first-repeat row for QP {qp} kind {kind}")
        indexed[index_key] = row

    missing = [(qp, kind) for kind in ("anchor", "proposed") for qp in requested_qps if (qp, kind) not in indexed]
    if missing:
        details = ", ".join(f"QP{qp}/{kind}" for qp, kind in missing)
        raise ValueError(f"missing BDBR curve point(s) for {metric_key}: {details}")

    curves: dict[str, list[float]] = {}
    for kind in ("anchor", "proposed"):
        rates: list[float] = []
        qualities: list[float] = []
        for qp in requested_qps:
            row = indexed[(qp, kind)]
            rate = _finite_float(row.get("Kbps"), f"{kind} QP{qp} Kbps")
            if rate <= 0.0:
                raise ValueError(f"{kind} QP{qp} Kbps must be positive")
            rates.append(rate)
            qualities.append(_finite_float(row.get(metric_key), f"{kind} QP{qp} {metric_key}"))
        if any(left <= right for left, right in zip(rates, rates[1:])):
            raise ValueError(f"{kind} rates must be strictly decreasing after QP sorting for {metric_key}")
        if len(set(qualities)) != len(qualities):
            raise ValueError(f"{kind} {metric_key} quality values must be unique")
        curves[f"{kind}_rates"] = rates
        curves[f"{kind}_qualities"] = qualities

    overlap_lo = max(min(curves["anchor_qualities"]), min(curves["proposed_qualities"]))
    overlap_hi = min(max(curves["anchor_qualities"]), max(curves["proposed_qualities"]))
    if overlap_hi <= overlap_lo:
        raise ValueError(f"anchor/proposed quality intervals do not overlap for {metric_key}")
    return curves


def compute_official_bdbr(rows: list[dict[str, Any]], qps: list[int]) -> dict[str, float]:
    result: dict[str, float] = {}
    for metric_key in ("360Lib13_6_WS_Y", "360Lib13_6_S_Y", "360Lib13_6_CPP_Y"):
        curves = validate_bd_curve_points(rows, qps, metric_key)
        value = bdrate(
            curves["anchor_rates"],
            curves["anchor_qualities"],
            curves["proposed_rates"],
            curves["proposed_qualities"],
        )
        if not math.isfinite(value):
            raise ValueError(f"non-finite BDBR result for {metric_key}")
        result[f"{metric_key}_BDBR_pct"] = float(value)
    return result


def aggregate_acceptance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 14:
        raise ValueError(f"aggregate acceptance requires exactly 14 sequence rows, got {len(rows)}")
    sequences = [str(row.get("sequence", "")) for row in rows]
    if len(set(sequences)) != 14:
        raise ValueError("aggregate acceptance requires exactly 14 distinct sequence values")

    metrics: dict[str, Any] = {}
    pass_flags: dict[str, bool] = {}
    for key in REQUIRED_ACCEPTANCE_BDBR_KEYS:
        values: list[tuple[str, float]] = []
        for row in rows:
            sequence = str(row.get("sequence", ""))
            if not sequence:
                raise ValueError(f"missing sequence for {key}")
            if key not in row:
                raise ValueError(f"missing {key} for sequence {sequence}")
            values.append((sequence, _finite_float(row[key], f"{sequence} {key}")))

        numeric = [value for _, value in values]
        worst_sequence, worst_value = max(values, key=lambda item: item[1])
        mean_value = statistics.fmean(numeric)
        passed = mean_value < 0.5
        metrics[key] = {
            "mean": mean_value,
            "median": statistics.median(numeric),
            "min": min(numeric),
            "max": max(numeric),
            "worst_sequence": worst_sequence,
            "sequence_count": len(values),
            "passed": passed,
        }
        pass_flags[key] = passed

    return {
        "sequence_count": len(rows),
        "metrics": metrics,
        "pass_flags": pass_flags,
        "accepted": all(pass_flags.values()),
    }


def _git_revision() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except (OSError, RuntimeError):
        return None
    revision = proc.stdout.strip()
    return revision if proc.returncode == 0 and revision else None


def _flatten_sequence_summary(summary: dict[str, Any]) -> dict[str, Any]:
    timing_overall = summary.get("timing", {}).get("overall", {})
    row = {
        "profile": summary.get("profile"),
        "sequence": summary.get("sequence"),
        "frames": summary.get("frames"),
        "TS_best": timing_overall.get("max_TS_pct"),
        "TS_median": timing_overall.get("median_TS_pct"),
        "median_TS_pct": timing_overall.get("median_TS_pct"),
        "positive_repeats": timing_overall.get("positive_repeats"),
        "repeats": timing_overall.get("repeats", summary.get("repeats")),
    }
    metrics = summary.get("metrics")
    if isinstance(metrics, dict):
        row.update(metrics)
    else:
        for key in REQUIRED_ACCEPTANCE_BDBR_KEYS:
            if key in summary:
                row[key] = summary[key]
    return row


def _formal_flat_rows(sequence_summaries_or_flat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sequence_summaries_or_flat_rows:
        return []
    if any("metrics" in row or "timing" in row for row in sequence_summaries_or_flat_rows):
        return [_flatten_sequence_summary(row) for row in sequence_summaries_or_flat_rows]
    return [dict(row) for row in sequence_summaries_or_flat_rows]


def _average_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if _is_finite_number(value):
            values.append(float(value))
    return statistics.fmean(values) if values else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    absolute = abs(float(denominator))
    if absolute <= 1e-12:
        return None
    return float(numerator) / absolute


def _sequence_summary_rows(flat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in flat_rows:
        rows.append(
            {
                "profile": row.get("profile"),
                "sequence": row.get("sequence"),
                "frames": row.get("frames"),
                "TS_best": row.get("TS_best", row.get("max_TS_pct")),
                "TS_median": row.get("TS_median", row.get("median_TS_pct")),
                "WS_Y": row.get("360Lib13_6_WS_Y_BDBR_pct"),
                "S_Y": row.get("360Lib13_6_S_Y_BDBR_pct"),
                "CPP_Y": row.get("360Lib13_6_CPP_Y_BDBR_pct"),
            }
        )
    return rows


def _profile_summary_rows(flat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    profiles = sorted({str(row.get("profile", "")) for row in flat_rows if row.get("profile")})
    for profile in profiles:
        group_rows = [row for row in flat_rows if str(row.get("profile")) == profile]
        avg_ts_best = _average_numeric(group_rows, "TS_best")
        avg_ts_median = _average_numeric(group_rows, "TS_median")
        avg_ws_y = _average_numeric(group_rows, "360Lib13_6_WS_Y_BDBR_pct")
        avg_s_y = _average_numeric(group_rows, "360Lib13_6_S_Y_BDBR_pct")
        avg_cpp_y = _average_numeric(group_rows, "360Lib13_6_CPP_Y_BDBR_pct")
        rows.append(
            {
                "profile": profile,
                "sequence_count": len(group_rows),
                "avg_TS_best": avg_ts_best,
                "avg_TS_median": avg_ts_median,
                "avg_WS_Y": avg_ws_y,
                "avg_S_Y": avg_s_y,
                "avg_CPP_Y": avg_cpp_y,
                "TSbest_per_BDBR": _ratio(avg_ts_best, avg_ws_y),
                "TSmedian_per_BDBR": _ratio(avg_ts_median, avg_ws_y),
                "formal_complete": len(group_rows) == 14,
                "accepted_tsbest": (
                    _ratio(avg_ts_best, avg_ws_y) is not None
                    and _ratio(avg_ts_best, avg_ws_y) > 10.0
                    and avg_ws_y is not None
                    and avg_ws_y < 1.0
                ),
            }
        )
    return rows


def write_formal_summaries(
    out_root: Path,
    run_config: dict[str, Any],
    sequence_summaries_or_flat_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    flat_rows = _formal_flat_rows(sequence_summaries_or_flat_rows)
    write_csv(out_root / "flat_summary.csv", flat_rows)
    write_csv(out_root / "sequence_summary.csv", _sequence_summary_rows(flat_rows))
    write_csv(out_root / "profile_summary.csv", _profile_summary_rows(flat_rows))

    finished = time.strftime("%Y-%m-%d %H:%M:%S")
    groups: dict[str, Any] = {}
    profiles = sorted({str(row.get("profile", "")) for row in flat_rows if row.get("profile")})
    for profile in profiles:
        group_rows = [row for row in flat_rows if str(row.get("profile")) == profile]
        if len(group_rows) == 14:
            groups[profile] = aggregate_acceptance(group_rows)
        else:
            groups[profile] = {
                "accepted": False,
                "formal_complete": False,
                "sequence_count": len(group_rows),
                "reason": f"formal acceptance requires exactly 14 sequence rows, got {len(group_rows)}",
            }

    aggregate_payload = {
        "finished": finished,
        "groups": groups,
    }
    atomic_write_json(out_root / "aggregate_summary.json", aggregate_payload)

    manifest = {
        **run_config,
        "anchor_additional": run_config.get("anchor_additional", ANCHOR_ADDITIONAL),
        "profile_commands": run_config.get(
            "profile_commands",
            {
                profile: {
                    "anchor": ANCHOR_ADDITIONAL,
                    "proposed": proposed,
                }
                for profile, proposed in run_config.get("profile_additional", {}).items()
            },
        ),
        "finished": finished,
        "git_revision": _git_revision(),
    }
    atomic_write_json(out_root / "run_manifest.json", manifest)
    return {"flat_rows": flat_rows, "aggregate": aggregate_payload, "manifest": manifest}


def write_lfnst21_audit_summary_if_requested(out_root: Path, args: argparse.Namespace) -> None:
    if not bool(getattr(args, "lfnst21_audit", False)):
        return
    from tools.lard_lfnst.summarize_stage3ab_audit import summarize_formal_run_root

    rows = summarize_formal_run_root(out_root)
    path = out_root / "audit_summary.csv"
    if rows:
        write_csv(path, rows)
    else:
        path.write_text(
            "profile,sequence,qp,stage1Skip,stage2Skip,stage3ZdSkip,candidateDrop,dropRate,estSkippedMs,propActualCandMs\n",
            encoding="utf-8",
        )


def _run_config_payload(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "encoder": str(config["encoder"]),
        "convert360": str(config["convert360"]),
        "sphere_file": str(config["sphere_file"]),
        "hashes": {
            "encoder_sha256": sha256_file(config["encoder"]),
            "convert360_sha256": sha256_file(config["convert360"]),
            "sphere_sha256": sha256_file(config["sphere_file"]),
        },
        "qps": config["qps"],
        "profiles": config["profiles"],
        "encode_config": config["encode_config"],
        "profile_additional": {
            name: profile_additional_manifest(name, config["qps"], [str(seq["name"]) for seq in config["sequences"]])
            for name in config["profiles"]
        },
        "anchor_additional": ANCHOR_ADDITIONAL,
        "profile_commands": {
            name: {
                "anchor": ANCHOR_ADDITIONAL,
                "proposed": profile_additional_manifest(name, config["qps"], [str(seq["name"]) for seq in config["sequences"]]),
            }
            for name in config["profiles"]
        },
        "frames": config["frames"],
        "ra_gop": args.ra_gop,
        "ld_gop": args.ld_gop,
        "ai_frames": args.ai_frames,
        "threads": args.threads,
        "preset": args.preset,
        "repeats": args.repeats,
        "lfnst21_audit": bool(getattr(args, "lfnst21_audit", False)),
        "sequences": [str(seq["name"]) for seq in config["sequences"]],
        "sequence_metadata": [
            {
                "name": str(seq["name"]),
                "path": str(seq["path"]),
                "width": int(seq["width"]),
                "height": int(seq["height"]),
                "fps": int(seq["fps"]),
                "bitdepth": int(seq["bitdepth"]),
                "available_frames": int(seq["available_frames"]),
            }
            for seq in config["sequences"]
        ],
    }


def run_all(args: argparse.Namespace, config: dict[str, Any]) -> list[dict[str, Any]]:
    all_summaries: list[dict[str, Any]] = []
    total = len(config["profiles"]) * len(config["sequences"])
    index = 0
    for profile_name in config["profiles"]:
        args.profile_name = profile_name
        for seq in config["sequences"]:
            index += 1
            print(f"[{index}/{total}] config={config['encode_config']} profile={profile_name} sequence={seq['name']}", flush=True)
            rows: list[dict[str, Any]] = []
            for repeat, kind in paired_schedule(args.repeats):
                for qp in config["qps"]:
                    run_dir = config["out_root"] / str(config["encode_config"]) / profile_name / str(seq["name"]) / f"QP{qp}" / f"repeat{repeat}"
                    base_additional = ANCHOR_ADDITIONAL if kind == "anchor" else proposed_additional_for_qp(profile_name, qp, str(seq["name"]))
                    manifest = run_encode_case(
                        encoder=config["encoder"],
                        convert360=config["convert360"],
                        seq=seq,
                        run_dir=run_dir,
                        qp=qp,
                        repeat=repeat,
                        kind=kind,
                        additional=case_additional_with_optional_audit(
                            base_additional,
                            kind=kind,
                            qp=qp,
                            run_dir=run_dir,
                            args=args,
                        ),
                        args=args,
                    )
                    rows.append(_row_from_manifest(manifest))

            out_dir = config["out_root"] / str(config["encode_config"]) / profile_name / str(seq["name"])
            rows.sort(key=lambda row: (int(row["repeat"]), int(row["QP"]), str(row["kind"])))
            write_csv(out_dir / "encode_rows.csv", rows)
            summary = {
                "sequence": str(seq["name"]),
                "profile": profile_name,
                "width": int(seq["width"]),
                "height": int(seq["height"]),
                "fps": int(seq["fps"]),
                "bitdepth": int(seq["bitdepth"]),
                "encode_config": config["encode_config"],
                "frames": config["frames"],
                "gop": args.ra_gop,
                "ld_gop": args.ld_gop,
                "ai_frames": args.ai_frames,
                "qps": config["qps"],
                "repeats": args.repeats,
                "timing": summarize_timing(rows),
                "metrics": compute_official_bdbr(rows, config["qps"]),
            }
            atomic_write_json(out_dir / "summary.json", summary)
            all_summaries.append(summary)
    return all_summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--360convert", dest="convert360", type=Path, required=True)
    parser.add_argument("--seq-root", type=Path, required=True)
    parser.add_argument("--sphere-file", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--qps", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--profile-json", type=Path, default=None, help="register calibrated/dynamic formal profiles from {\"profiles\": {name: additional}} JSON")
    parser.add_argument("--threads", type=int, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--encode-config", choices=("RA", "LD", "AI"), default="RA")
    parser.add_argument("--ra-gop", type=int, required=True)
    parser.add_argument("--ld-gop", type=int, default=8)
    parser.add_argument("--ai-frames", type=int, default=1)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--expect-count", type=int, required=True)
    parser.add_argument("--sequence-filter", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-bitstreams", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rec-bitdepth", type=int, default=10)
    parser.add_argument("--lfnst21-audit", action="store_true", help="append per-case LardLfnst21AuditFile aggregate audit paths")
    args = parser.parse_args(argv)
    loaded_profiles = load_external_profiles(args.profile_json)

    config = preflight(args)
    if loaded_profiles:
        config["external_profiles"] = loaded_profiles
    config["out_root"].mkdir(parents=True, exist_ok=True)
    run_config = _run_config_payload(args, config)
    atomic_write_json(config["out_root"] / "run_config.json", run_config)
    print(json.dumps(run_config, ensure_ascii=False), flush=True)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "out_root": str(config["out_root"])}, ensure_ascii=False), flush=True)
        return 0

    summaries = run_all(args, config)
    atomic_write_json(config["out_root"] / "summaries.json", {"sequences": summaries})
    write_formal_summaries(config["out_root"], run_config, summaries)
    write_lfnst21_audit_summary_if_requested(config["out_root"], args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
