#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


class Skip20DirectTableTests(unittest.TestCase):
    @staticmethod
    def _write_trace(path: Path, rows: list[dict[str, object]]) -> None:
        fields = [
            "J0", "J1", "J2", "rdoValid0", "rdoValid1", "rdoValid2",
            "candidateRdoTimeNs1", "candidateRdoTimeNs2",
            "actualCuQp", "W", "H", "setIdx", "transpose", "latBin", "modeGroup",
            "baseRoiEnergy", "baseNnz", "baseLast", "qStep", "tableFound",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _row(idx: int, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "J0": 100,
            "J1": 90 if idx % 2 == 0 else 120,
            "J2": 130 if idx % 2 == 0 else 95,
            "rdoValid0": 1,
            "rdoValid1": 1,
            "rdoValid2": 1,
            "candidateRdoTimeNs1": 100,
            "candidateRdoTimeNs2": 200,
            "actualCuQp": 24,
            "W": 16,
            "H": 16,
            "setIdx": 1,
            "transpose": 0,
            "latBin": 2,
            "modeGroup": 3,
            "baseRoiEnergy": (idx + 1) * 16,
            "baseNnz": 1 + idx % 8,
            "baseLast": idx % 16,
            "qStep": 2,
            "tableFound": 1,
        }
        row.update(overrides)
        return row

    def test_cpp_has_independent_skip20_lookup_path(self) -> None:
        cfg = (HERE.parents[1] / "include/vvenc/vvencCfg.h").read_text(encoding="utf-8")
        source = (HERE.parents[1] / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        app_cfg = (HERE.parents[1] / "source/Lib/apputils/VVEncAppCfg.h").read_text(encoding="utf-8")
        vvenc_cfg = (HERE.parents[1] / "source/Lib/vvenc/vvencCfg.cpp").read_text(encoding="utf-8")
        self.assertIn("m_LardLfnst20Profile", cfg)
        self.assertIn("m_Skip20ForceMask0", cfg)
        self.assertIn("m_EarlyForceNoNonzeroLfnst", cfg)
        self.assertIn("Skip20ForceMask0", app_cfg)
        self.assertIn("EarlyForceNoNonzeroLfnst", app_cfg)
        self.assertIn("Skip20ForceMask0 out of range [0..1]", vvenc_cfg)
        self.assertIn("EarlyForceNoNonzeroLfnst out of range [0..1]", vvenc_cfg)
        self.assertIn('#include "LardLfnstSkip20DirectMaskTable.inc"', source)
        self.assertIn("xLardSkip20DirectMask", source)
        self.assertIn("lardLfnstSkip20", source)
        self.assertIn("lardSkip20Mask", source)
        self.assertIn("m_Skip20ForceMask0 ? 0x1 : xLardSkip20DirectMask", source)
        self.assertIn("m_EarlyForceNoNonzeroLfnst", source)
        self.assertIn("endLfnstIdx = 0;", source)

    def test_cpp_has_skip21_early_theory_gate_path(self) -> None:
        cfg = (HERE.parents[1] / "include/vvenc/vvencCfg.h").read_text(encoding="utf-8")
        source = (HERE.parents[1] / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        app_cfg = (HERE.parents[1] / "source/Lib/apputils/VVEncAppCfg.h").read_text(encoding="utf-8")
        vvenc_cfg = (HERE.parents[1] / "source/Lib/vvenc/vvencCfg.cpp").read_text(encoding="utf-8")
        self.assertIn("m_LardLfnst21Profile", cfg)
        self.assertIn("m_LardLfnst21Stages", cfg)
        self.assertIn("LardLfnst21Profile", app_cfg)
        self.assertIn("LardLfnst21Stages", app_cfg)
        self.assertIn("LardLfnstSkip out of range [0..21]", vvenc_cfg)
        self.assertIn("LardLfnst21Profile out of range [0..6]", vvenc_cfg)
        self.assertIn("LardLfnst21Stages out of range [1..3]", vvenc_cfg)
        self.assertIn('#include "LardLfnstSkip21TheoryTable.inc"', source)
        self.assertIn("xLardSkip21EarlyNoNonzero", source)
        self.assertIn("xLardSkip21SupportRatioQ", source)
        self.assertIn("m_LardLfnstSkip == 21", source)
        self.assertIn("lardLfnst21EarlySkip", source)
        self.assertIn("endLfnstIdx = 0;", source)

    def test_cpp_v2_scans_quant_structure_once_and_probes_fallbacks(self) -> None:
        source = (HERE.parents[1] / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("baseNnz", source)
        self.assertIn("baseLast", source)
        self.assertIn("LARD_LFNST_SKIP20_LEVEL_FULL", source)
        self.assertIn("LARD_LFNST_SKIP20_LEVEL_CORE", source)
        self.assertIn("xLardSkip20FindMask", source)
        self.assertIn("std::floor( std::abs( input[idx] ) / qStep + 0.5 )", source)

    def test_fit_emits_energy_bins_profiles_and_mask_replay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.csv"
            fields = [
                "J0", "J1", "J2", "rdoValid0", "rdoValid1", "rdoValid2",
                "candidateRdoTimeNs1", "candidateRdoTimeNs2",
                "actualCuQp", "W", "H", "setIdx", "transpose", "latBin", "modeGroup",
                "baseRoiEnergy", "baseNnz", "baseLast", "qStep", "tableFound",
            ]
            rows = []
            for idx in range(16):
                rows.append(
                    {
                        "J0": 100,
                        "J1": 90 if idx < 8 else 120,
                        "J2": 130 if idx < 8 else 95,
                        "rdoValid0": 1,
                        "rdoValid1": 1,
                        "rdoValid2": 1,
                        "candidateRdoTimeNs1": 100,
                        "candidateRdoTimeNs2": 200,
                        "actualCuQp": 24,
                        "W": 16,
                        "H": 16,
                        "setIdx": 1,
                        "transpose": 0,
                        "latBin": 2,
                        "modeGroup": 3,
                        "baseRoiEnergy": (idx + 1) * 16,
                        "baseNnz": 1 + idx % 8,
                        "baseLast": idx % 16,
                        "qStep": 2,
                        "tableFound": 1,
                    }
                )
            with trace.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "fit.json"
            out_inc = root / "table.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                    str(trace),
                    "--profiles",
                    "0,1000",
                    "--energy-bins",
                    "4",
                    "--min-samples",
                    "2",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["rows"], 16)
            self.assertEqual(len(result["energy_thresholds"]), 1)
            self.assertEqual(len(result["profiles"]), 2)
            self.assertGreater(result["profiles"][0]["candidate_reduction"], 0)
            inc = out_inc.read_text(encoding="utf-8")
            self.assertIn("LARD_LFNST_SKIP20_ENERGY_THRESHOLDS", inc)
            self.assertIn("LARD_LFNST_SKIP20_DIRECT_MASKS", inc)
            self.assertIn("{ 24, 16, 16", inc)

    def test_fit_requires_online_reproducible_key_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "trace.csv"
            trace.write_text(
                "J0,J1,J2,candidateRdoTimeNs1,candidateRdoTimeNs2\n1,2,3,4,5\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(HERE / "fit_lard_lfnst_skip20_direct.py"), str(trace)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("baseRoiEnergy", proc.stderr)

    def test_v2_uses_training_only_cuts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            train = root / "train.csv"
            valid_a = root / "valid_a.csv"
            valid_b = root / "valid_b.csv"
            self._write_trace(train, [self._row(idx) for idx in range(24)])
            self._write_trace(
                valid_a,
                [self._row(idx, baseRoiEnergy=4 + idx, baseNnz=1, baseLast=1) for idx in range(12)],
            )
            self._write_trace(
                valid_b,
                [self._row(idx, baseRoiEnergy=1_000_000 + idx, baseNnz=48, baseLast=47) for idx in range(12)],
            )

            outputs = []
            for suffix, valid in (("a", valid_a), ("b", valid_b)):
                out_json = root / f"fit_{suffix}.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                        "--train", str(train),
                        "--validation", str(valid),
                        "--energy-bins", "4",
                        "--nnz-bins", "3",
                        "--last-bins", "3",
                        "--target-ts", "3,5,6,7",
                        "--min-samples", "2",
                        "--out-json", str(out_json),
                    ],
                    check=True,
                )
                outputs.append(json.loads(out_json.read_text(encoding="utf-8")))

            self.assertEqual(outputs[0]["bin_thresholds"], outputs[1]["bin_thresholds"])
            self.assertEqual(outputs[0]["split"]["train_rows"], 24)
            self.assertEqual(outputs[0]["split"]["validation_rows"], 12)

    def test_v2_hierarchy_falls_back_from_last_then_nnz(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            train = root / "train.csv"
            valid = root / "valid.csv"
            rows = []
            for idx in range(24):
                rows.append(
                    self._row(
                        idx,
                        baseNnz=1 + idx % 3,
                        baseLast=idx % 8,
                        candidateRdoTimeNs1=400,
                        candidateRdoTimeNs2=500,
                        J0=100,
                        J1=120,
                        J2=130,
                    )
                )
            self._write_trace(train, rows)
            self._write_trace(valid, rows[:12])
            out_json = root / "fit.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                    "--train", str(train),
                    "--validation", str(valid),
                    "--energy-bins", "4",
                    "--nnz-bins", "3",
                    "--last-bins", "3",
                    "--target-ts", "3,5,6,7",
                    "--profiles", "0",
                    "--min-samples", "6",
                    "--out-json", str(out_json),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            profile = result["profiles"][0]
            self.assertIn("fallback_counts", profile)
            self.assertTrue(
                profile["fallback_counts"].get("no_last", 0)
                or profile["fallback_counts"].get("no_nnz", 0)
            )
            self.assertIn("mask_counts", profile)
            self.assertIn("by_qp", profile)
            self.assertIn("by_size", profile)

    def test_v2_include_contains_three_cut_tables_and_fallback_levels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.csv"
            self._write_trace(trace, [self._row(idx) for idx in range(32)])
            out_inc = root / "table.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                    "--train", str(trace),
                    "--validation", str(trace),
                    "--profiles", "0",
                    "--min-samples", "2",
                    "--out-inc", str(out_inc),
                ],
                check=True,
            )
            inc = out_inc.read_text(encoding="utf-8")
            self.assertIn("LARD_LFNST_SKIP20_ENERGY_THRESHOLDS", inc)
            self.assertIn("LARD_LFNST_SKIP20_NNZ_THRESHOLDS", inc)
            self.assertIn("LARD_LFNST_SKIP20_LAST_THRESHOLDS", inc)
            self.assertIn("LARD_LFNST_SKIP20_LEVEL_FULL", inc)
            self.assertIn("LARD_LFNST_SKIP20_LEVEL_CORE", inc)

    def test_v2_selects_target_profiles_from_validation_pareto(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            train = root / "train.csv"
            valid = root / "valid.csv"
            rows = [
                self._row(
                    idx,
                    J0=100,
                    J1=101 if idx % 3 else 90,
                    J2=102 if idx % 4 else 92,
                    candidateRdoTimeNs1=1000,
                    candidateRdoTimeNs2=1200,
                )
                for idx in range(48)
            ]
            self._write_trace(train, rows)
            self._write_trace(valid, rows)
            out_json = root / "fit.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                    "--train", str(train),
                    "--validation", str(valid),
                    "--mu-grid", "0,10,100,1000,10000",
                    "--target-ts", "3,5,6,110",
                    "--anchor-time-ns", "100000",
                    "--min-efficiency", "0",
                    "--min-samples", "2",
                    "--out-json", str(out_json),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual([item["target_ts"] for item in result["profiles"]], [3.0, 5.0, 6.0, 110.0])
            self.assertEqual(len(result["pareto_candidates"]), 5)
            self.assertTrue(all("estimated_efficiency_proxy" in item for item in result["profiles"]))
            self.assertFalse(result["profiles"][-1]["available"])
            self.assertEqual(result["profiles"][-1]["fallback_counts"]["full_rdo"], len(rows))

    def test_v2_calibrates_ts_from_full_candidate_and_intra_times(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "trace.csv"
            self._write_trace(trace, [self._row(idx, J0=100, J1=120, J2=130) for idx in range(32)])
            out_json = root / "fit.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip20_direct.py"),
                    "--train", str(trace),
                    "--validation", str(trace),
                    "--profiles", "0",
                    "--candidate-time-total-ns", "400000",
                    "--intra-time-total-ns", "1000000",
                    "--min-samples", "2",
                    "--out-json", str(out_json),
                ],
                check=True,
            )
            profile = json.loads(out_json.read_text(encoding="utf-8"))["profiles"][0]
            self.assertAlmostEqual(
                profile["estimated_local_ts_proxy"],
                40.0 * profile["time_saving_ratio"],
                places=9,
            )


if __name__ == "__main__":
    unittest.main()
