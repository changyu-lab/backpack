#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from generate_lard_lfnst_cov_table import LAT_BINS, SIZES, generate_entries, lfnst_positions
from verify_lard_lfnst_trace import extract_input_from_raw, integer_response


class LardLfnstCovTests(unittest.TestCase):
    def test_lfnst_positions_match_vvenc_order(self) -> None:
        self.assertEqual(
            lfnst_positions(4, 4, 4, False),
            [(x, y) for y in range(4) for x in range(4)],
        )
        self.assertEqual(
            lfnst_positions(4, 4, 4, True),
            [(x, y) for x in range(4) for y in range(4)],
        )
        normal8 = lfnst_positions(8, 8, 8, False)
        trans8 = lfnst_positions(8, 8, 8, True)
        self.assertEqual(len(normal8), 48)
        self.assertEqual(len(trans8), 48)
        self.assertEqual(normal8[:8], [(x, 0) for x in range(8)])
        self.assertEqual(normal8[-4:], [(x, 7) for x in range(4)])
        self.assertEqual(trans8[:8], [(0, y) for y in range(8)])
        self.assertEqual(trans8[-4:], [(7, y) for y in range(4)])

    def test_generator_emits_complete_deterministic_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            cmd = [
                sys.executable,
                str(HERE / "generate_lard_lfnst_cov_table.py"),
                "--rom-lfnst",
                str(ROOT / "source/Lib/CommonLib/Rom.cpp"),
                "--out-dir",
                str(out),
            ]
            subprocess.run(cmd, check=True)
            first = (out / "LardLfnstCovTable.cpp").read_bytes()
            subprocess.run(cmd, check=True)
            second = (out / "LardLfnstCovTable.cpp").read_bytes()
            self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
            self.assertNotIn(b" 0f", first)

            with (out / "lard_lfnst_cov_summary.csv").open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), len(LAT_BINS) * len(SIZES) * 2 * 4)
            keys = {(r["latBin"], r["W"], r["H"], r["transpose"], r["setIdx"]) for r in rows}
            self.assertEqual(len(keys), len(rows))
            self.assertTrue(all(float(r["minVarX"]) >= -1e-10 for r in rows))
            self.assertTrue(all(float(r["minVarY"]) >= -1e-10 for r in rows))
            self.assertTrue(
                all(
                    1e-3 <= float(r[key]) / max(float(r["traceX"]), 1e-12) <= 1e3
                    for r in rows
                    for key in ("traceY1", "traceY2")
                )
            )
            four_by_four = next(r for r in rows if r["W"] == "4" and r["H"] == "4")
            sixteen = next(r for r in rows if r["W"] == "16" and r["H"] == "16")
            self.assertGreater(float(four_by_four["expZeroY1"]), 0.0)
            self.assertGreater(float(four_by_four["expRetainedY1"]), 0.0)
            self.assertEqual(float(sixteen["expZeroY1"]), 0.0)

    def test_analyzer_reports_prediction_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv"
            with log.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx", "maskPred",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {"G1_cov": 2, "G2_cov": -1, "J0": 10, "J1": 8, "J2": 11, "bestIdx": 1, "maskPred": 3},
                        {"G1_cov": -2, "G2_cov": -1, "J0": 10, "J1": 12, "J2": 11, "bestIdx": 0, "maskPred": 1},
                    ]
                )
            out = root / "summary.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "analyze_lard_lfnst_cov_logs.py"),
                    str(log),
                    "--out-json",
                    str(out),
                ],
                check=True,
            )
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["rank_correct"], 1)
            self.assertEqual(result["false_skip_count"], 0)
            self.assertIn("corr_g1_dj1", result)

    def test_integer_response_uses_vvenc_rounding_shift(self) -> None:
        matrix = np.zeros((2, 2), dtype=np.float64)
        matrix[0] = [64 / 128, 64 / 128]
        matrix[1] = [-64 / 128, 64 / 128]
        self.assertEqual(integer_response(matrix, [3, 1], 2, 2), [2, -1])

    def test_raw_roi_transpose_extraction(self) -> None:
        raw4 = list(range(16))
        self.assertEqual(extract_input_from_raw(raw4, 16, False), raw4)
        self.assertEqual(extract_input_from_raw(raw4, 16, True), [0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15])

    def test_diagnosis_reports_exact_rd_decomposition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = [
                "QP", "W", "H", "tableFound", "actualValid1", "actualValid2",
                "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx", "latBin", "setIdx", "transpose",
                "dist0", "dist1", "dist2", "fracBits0", "fracBits1", "fracBits2",
                "distCost0", "distCost1", "distCost2", "rateCost0", "rateCost1", "rateCost2",
                "inputEnergy1", "inputEnergy2", "outputEnergy1", "outputEnergy2",
                "zeroOutEnergy1", "zeroOutEnergy2",
            ]
            for candidate in (1, 2):
                fields.extend(f"actualY{candidate}Sq_{index:02d}" for index in range(16))
                fields.extend(f"predVarY{candidate}_{index:02d}" for index in range(16))
            row = {field: 0 for field in fields}
            row.update(
                {
                    "QP": 22, "W": 16, "H": 16, "tableFound": 1,
                    "actualValid1": 1, "actualValid2": 1, "G1_cov": 4, "G2_cov": -2,
                    "J0": 130, "J1": 110, "J2": 150, "bestIdx": 1,
                    "latBin": 3, "setIdx": 0, "transpose": 0,
                    "dist0": 10, "dist1": 8, "dist2": 12,
                    "fracBits0": 30, "fracBits1": 30, "fracBits2": 30,
                    "distCost0": 100, "distCost1": 80, "distCost2": 120,
                    "rateCost0": 30, "rateCost1": 30, "rateCost2": 30,
                    "inputEnergy1": 100, "inputEnergy2": 100,
                    "outputEnergy1": 70, "outputEnergy2": 60,
                    "zeroOutEnergy1": 30, "zeroOutEnergy2": 40,
                }
            )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)
            out = root / "diagnosis.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "diagnose_lard_lfnst_cov.py"),
                    str(log),
                    "--out-json",
                    str(out),
                ],
                check=True,
            )
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["rd_decomposition"]["max_abs_residual"], 0.0)
            self.assertEqual(result["rd_decomposition"]["candidate1"]["delta_dist_cost_mean"], 20.0)
            self.assertEqual(result["rd_decomposition"]["candidate1"]["delta_rate_cost_mean"], 0.0)

    def test_skip16_fit_reports_cost_domain_rd_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = [
                "QP", "W", "H", "tableFound", "actualValid1", "actualValid2", "outN",
                "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx",
                "distCost0", "distCost1", "distCost2", "rateCost0", "rateCost1", "rateCost2",
                "zeroOutEnergy1", "zeroOutEnergy2", "outputEnergy1", "outputEnergy2",
            ]
            rows = []
            for index, g1 in enumerate([10.0, 20.0, 30.0, 40.0, 15.0, 35.0]):
                zero1 = [2.0, 30.0, 3.0, 60.0, 4.0, 50.0][index]
                zero2 = zero1 + 10.0
                rate_gain1 = 100.0 * g1 + 5.0
                rate_gain2 = 80.0 * (g1 - 5.0) + 3.0
                dist_loss1 = 50.0 * zero1
                dist_loss2 = 45.0 * zero2
                j0 = 10000.0
                j1 = j0 - (rate_gain1 - dist_loss1)
                j2 = j0 - (rate_gain2 - dist_loss2)
                rows.append(
                    {
                        "QP": 22 + (index % 2) * 5, "W": 16, "H": 16, "tableFound": 1,
                        "actualValid1": 1, "actualValid2": 1, "outN": 16,
                        "G1_cov": g1, "G2_cov": g1 - 5.0, "J0": j0, "J1": j1, "J2": j2,
                        "bestIdx": 1 if j1 < min(j0, j2) else (2 if j2 < min(j0, j1) else 0),
                        "distCost0": 1000.0, "distCost1": 1000.0 + dist_loss1,
                        "distCost2": 1000.0 + dist_loss2,
                        "rateCost0": 9000.0, "rateCost1": 9000.0 - rate_gain1,
                        "rateCost2": 9000.0 - rate_gain2,
                        "zeroOutEnergy1": zero1, "zeroOutEnergy2": zero2,
                        "outputEnergy1": 100.0 - zero1, "outputEnergy2": 100.0 - zero2,
                    }
                )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "skip16_fit.json"
            out_inc = root / "LardLfnstSkip16FitTable.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip16.py"),
                    str(log),
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                    "--ridge",
                    "1e-9",
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertGreater(result["validation"]["overall"]["corr_pred_rd_true_rd"], 0.9)
            self.assertIn("missed_positive_gain_ratio", result["skip_only_sweep"][0])
            self.assertIn("LARD_LFNST_SKIP16_RATE_FEATURES", out_inc.read_text(encoding="utf-8"))

    def test_skip17_fit_can_use_table_expected_energy(self) -> None:
        entries = generate_entries(ROOT / "source/Lib/CommonLib/Rom.cpp")
        entry = next(
            e for e in entries
            if e["latBin"] == 0 and e["W"] == 4 and e["H"] == 4 and e["setIdx"] == 0 and e["transpose"] == 0
        )
        zero1 = float(np.asarray(entry["expZeroEnergy"])[0])
        retained1 = float(np.asarray(entry["expRetainedEnergy"])[0])
        self.assertGreater(zero1, 0.0)
        self.assertGreater(retained1, 0.0)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = [
                "QP", "W", "H", "tableFound", "actualValid1", "actualValid2", "outN",
                "latBin", "setIdx", "transpose", "sigma2", "qStep",
                "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx",
                "distCost0", "distCost1", "distCost2", "rateCost0", "rateCost1", "rateCost2",
            ]
            rows = []
            for index, sigma2 in enumerate([10.0, 20.0, 40.0, 80.0, 120.0, 160.0]):
                g1 = 5.0 * sigma2
                g2 = 3.0 * sigma2
                rate_gain1 = 20.0 * g1
                rate_gain2 = 20.0 * g2
                dist_loss1 = 150.0 * sigma2 * zero1
                dist_loss2 = 120.0 * sigma2 * zero1
                j0 = 100000.0
                j1 = j0 - (rate_gain1 - dist_loss1)
                j2 = j0 - (rate_gain2 - dist_loss2)
                rows.append(
                    {
                        "QP": 22 + (index % 2) * 5, "W": 4, "H": 4, "tableFound": 1,
                        "actualValid1": 1, "actualValid2": 1, "outN": 8,
                        "latBin": 0, "setIdx": 0, "transpose": 0,
                        "sigma2": sigma2, "qStep": 4.0,
                        "G1_cov": g1, "G2_cov": g2,
                        "J0": j0, "J1": j1, "J2": j2,
                        "bestIdx": 1 if j1 < min(j0, j2) else (2 if j2 < min(j0, j1) else 0),
                        "distCost0": 1000.0, "distCost1": 1000.0 + dist_loss1,
                        "distCost2": 1000.0 + dist_loss2,
                        "rateCost0": 9000.0, "rateCost1": 9000.0 - rate_gain1,
                        "rateCost2": 9000.0 - rate_gain2,
                    }
                )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "skip17_fit.json"
            out_inc = root / "LardLfnstSkip17FitTable.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip16.py"),
                    str(log),
                    "--energy-source",
                    "table",
                    "--rom-lfnst",
                    str(ROOT / "source/Lib/CommonLib/Rom.cpp"),
                    "--cpp-prefix",
                    "LARD_LFNST_SKIP17",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                    "--ridge",
                    "1e-9",
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertGreater(result["validation"]["overall"]["corr_pred_rd_true_rd"], 0.9)
            self.assertEqual(result["energy_source"], "table")
            rates = [row["target_skip_rate"] for row in result["skip_only_sweep"]]
            self.assertIn(0.01, rates)
            self.assertIn(0.05, rates)
            by_qp = result["skip_only_sweep_by_qp"]
            self.assertTrue(by_qp)
            self.assertIn("QP", by_qp[0])
            self.assertIn("target_skip_rate", by_qp[0])
            self.assertIn("missed_gain_ratio", by_qp[0])
            self.assertIn("LARD_LFNST_SKIP17_RATE_FEATURES", out_inc.read_text(encoding="utf-8"))

    def test_skip18_fit_can_use_response_energy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = [
                "QP", "W", "H", "tableFound", "actualValid1", "actualValid2", "outN",
                "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx",
                "distCost0", "distCost1", "distCost2", "rateCost0", "rateCost1", "rateCost2",
                "responseZeroOutEnergy1", "responseZeroOutEnergy2",
                "responseRetainedEnergy1", "responseRetainedEnergy2",
            ]
            rows = []
            for index, g1 in enumerate([10.0, 20.0, 30.0, 40.0, 15.0, 35.0]):
                zero1 = [1.0, 25.0, 2.0, 55.0, 3.0, 45.0][index]
                zero2 = zero1 + 8.0
                rate_gain1 = 90.0 * g1 + 7.0
                rate_gain2 = 70.0 * (g1 - 5.0) + 5.0
                dist_loss1 = 60.0 * zero1
                dist_loss2 = 55.0 * zero2
                j0 = 10000.0
                j1 = j0 - (rate_gain1 - dist_loss1)
                j2 = j0 - (rate_gain2 - dist_loss2)
                rows.append(
                    {
                        "QP": 22 + (index % 2) * 5, "W": 16, "H": 16, "tableFound": 1,
                        "actualValid1": 1, "actualValid2": 1, "outN": 16,
                        "G1_cov": g1, "G2_cov": g1 - 5.0, "J0": j0, "J1": j1, "J2": j2,
                        "bestIdx": 1 if j1 < min(j0, j2) else (2 if j2 < min(j0, j1) else 0),
                        "distCost0": 1000.0, "distCost1": 1000.0 + dist_loss1,
                        "distCost2": 1000.0 + dist_loss2,
                        "rateCost0": 9000.0, "rateCost1": 9000.0 - rate_gain1,
                        "rateCost2": 9000.0 - rate_gain2,
                        "responseZeroOutEnergy1": zero1,
                        "responseZeroOutEnergy2": zero2,
                        "responseRetainedEnergy1": 100.0 - zero1,
                        "responseRetainedEnergy2": 100.0 - zero2,
                    }
                )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "skip18_fit.json"
            out_inc = root / "LardLfnstSkip18FitTable.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip16.py"),
                    str(log),
                    "--energy-source",
                    "response",
                    "--cpp-prefix",
                    "LARD_LFNST_SKIP18",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                    "--ridge",
                    "1e-9",
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["energy_source"], "response")
            self.assertGreater(result["validation"]["overall"]["corr_pred_rd_true_rd"], 0.9)
            self.assertIn("LARD_LFNST_SKIP18_RATE_FEATURES", out_inc.read_text(encoding="utf-8"))

    def test_skip18_quant_struct_actual_qp_calibration_outputs_threshold_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            threshold_csv = root / "thresholds.csv"
            fields = [
                "QP", "actualCuQp", "W", "H", "tableFound", "actualValid1", "actualValid2",
                "outN", "kIn", "qStep", "G1_cov", "G2_cov", "J0", "J1", "J2", "bestIdx",
                "distCost0", "distCost1", "distCost2", "rateCost0", "rateCost1", "rateCost2",
                "responseZeroOutEnergy1", "responseZeroOutEnergy2",
                "responseRetainedEnergy1", "responseRetainedEnergy2",
                "responseNnz1", "responseNnz2", "responseZeroNnz1", "responseZeroNnz2",
                "responseRetainedNnz1", "responseRetainedNnz2", "responseLast1", "responseLast2",
                "responseSigDensity1", "responseSigDensity2", "responseHoleCount1", "responseHoleCount2",
                "responseLevelSum1", "responseLevelSum2", "responseLogLevelSum1", "responseLogLevelSum2",
                "responseMaxLevel1", "responseMaxLevel2",
                "baseNnz", "baseLast", "baseSigDensity", "baseLogLevelSum",
            ]
            rows = []
            row_index = 0
            for actual_qp in (19, 24, 29, 34):
                for rep in range(10):
                    for cand_bias in (0, 1):
                        g1 = 100.0 + actual_qp * 2.0 + rep * 5.0 + cand_bias
                        g2 = g1 - 12.0
                        nnz1 = 2.0 + rep + cand_bias
                        nnz2 = nnz1 + 2.0
                        last1 = 3.0 + rep
                        last2 = last1 + 2.0
                        zero1 = 10.0 + nnz1 * 4.0
                        zero2 = 15.0 + nnz2 * 5.0
                        retained1 = 80.0 + rep * 3.0
                        retained2 = 70.0 + rep * 2.0
                        rate_gain1 = 7.0 * g1 - 30.0 * nnz1 - actual_qp * 3.0
                        rate_gain2 = 7.0 * g2 - 30.0 * nnz2 - actual_qp * 3.0
                        dist_loss1 = 25.0 * zero1 + 40.0 * last1
                        dist_loss2 = 25.0 * zero2 + 40.0 * last2
                        j0 = 100000.0 + row_index
                        j1 = j0 - (rate_gain1 - dist_loss1)
                        j2 = j0 - (rate_gain2 - dist_loss2)
                        rows.append(
                            {
                                "QP": actual_qp + 3,
                                "actualCuQp": actual_qp,
                                "W": 16,
                                "H": 16,
                                "tableFound": 1,
                                "actualValid1": 1,
                                "actualValid2": 1,
                                "outN": 16,
                                "kIn": 48,
                                "qStep": 2.0 ** ((actual_qp - 4.0) / 6.0),
                                "G1_cov": g1,
                                "G2_cov": g2,
                                "J0": j0,
                                "J1": j1,
                                "J2": j2,
                                "bestIdx": 1 if j1 < min(j0, j2) else (2 if j2 < min(j0, j1) else 0),
                                "distCost0": 10000.0,
                                "distCost1": 10000.0 + dist_loss1,
                                "distCost2": 10000.0 + dist_loss2,
                                "rateCost0": 90000.0,
                                "rateCost1": 90000.0 - rate_gain1,
                                "rateCost2": 90000.0 - rate_gain2,
                                "responseZeroOutEnergy1": zero1,
                                "responseZeroOutEnergy2": zero2,
                                "responseRetainedEnergy1": retained1,
                                "responseRetainedEnergy2": retained2,
                                "responseNnz1": nnz1,
                                "responseNnz2": nnz2,
                                "responseZeroNnz1": 0.0,
                                "responseZeroNnz2": 0.0,
                                "responseRetainedNnz1": nnz1,
                                "responseRetainedNnz2": nnz2,
                                "responseLast1": last1,
                                "responseLast2": last2,
                                "responseSigDensity1": nnz1 / (last1 + 1.0),
                                "responseSigDensity2": nnz2 / (last2 + 1.0),
                                "responseHoleCount1": last1 + 1.0 - nnz1,
                                "responseHoleCount2": last2 + 1.0 - nnz2,
                                "responseLevelSum1": nnz1 * 3.0,
                                "responseLevelSum2": nnz2 * 3.0,
                                "responseLogLevelSum1": nnz1 * 2.0,
                                "responseLogLevelSum2": nnz2 * 2.0,
                                "responseMaxLevel1": 4.0 + rep,
                                "responseMaxLevel2": 5.0 + rep,
                                "baseNnz": nnz1 + 4.0,
                                "baseLast": last1 + 3.0,
                                "baseSigDensity": (nnz1 + 4.0) / (last1 + 4.0),
                                "baseLogLevelSum": nnz1 * 2.5,
                            }
                        )
                        row_index += 1
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "skip18_quant_struct_fit.json"
            out_inc = root / "LardLfnstSkip18FitTable.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip16.py"),
                    str(log),
                    "--energy-source",
                    "response",
                    "--feature-set",
                    "quant-struct",
                    "--calibration",
                    "actual-qp",
                    "--cpp-prefix",
                    "LARD_LFNST_SKIP18",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                    "--out-threshold-csv",
                    str(threshold_csv),
                    "--ridge",
                    "1e-9",
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["feature_set"], "quant-struct")
            self.assertEqual(result["calibration"], "actual-qp")
            self.assertIn("actual_qp_models", result)
            self.assertEqual(sorted(int(qp) for qp in result["actual_qp_models"]), [19, 24, 29, 34])
            self.assertIn("responseNnz", result["dist_features"])
            self.assertIn("deltaLast", result["dist_features"])
            with threshold_csv.open(encoding="utf-8") as handle:
                threshold_rows = list(csv.DictReader(handle))
            self.assertTrue(threshold_rows)
            self.assertEqual(
                ["QP", "target_skip_rate", "threshold", "false_skip_rate", "missed_gain_ratio"],
                threshold_rows[0].keys().__iter__().__class__(threshold_rows[0].keys()) if False else list(threshold_rows[0].keys()),
            )
            self.assertIn("LARD_LFNST_SKIP18_QP_BUCKETS", out_inc.read_text(encoding="utf-8"))

    def test_skip18_real_skip_has_fast_table_gate(self) -> None:
        source = (HERE.parent.parent / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("xLardSkip18FastRealEnabled", source)
        self.assertIn("xLardSkip18TablePreGateThreshold", source)
        self.assertIn("xLardSkip18MetaGatePass", source)
        self.assertIn("tablePreGatePass", source)
        self.assertIn("m_LardLfnst18RealSkip == 1", source)
        self.assertIn("m_LardLfnstSkip == 18", source)

    def test_skip18_complexity_summary_contains_required_counters(self) -> None:
        source = (HERE.parent.parent / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp").read_text(encoding="utf-8")
        for field in (
            "numLfnstEligible",
            "numTableFound",
            "numMetadataGateReject",
            "numMetadataGatePass",
            "numCheapGateReject",
            "numCheapGatePass",
            "numResponsePredictorEntered",
            "numPredSkip0",
            "numCandidate1Skipped",
            "numCandidate2Skipped",
            "numCandidateRdoSaved",
            "timeMetaGateNs",
            "timeCheapGateNs",
            "timeResponseFeatureNs",
            "timePredictScoreNs",
            "timeCandidateRdoActualNs",
        ):
            self.assertIn(field, source)
        cfg = (HERE.parent.parent / "include" / "vvenc" / "vvencCfg.h").read_text(encoding="utf-8")
        self.assertIn("m_LardLfnst18StatFile", cfg)
        self.assertIn("m_LardLfnst18HighCostOnly", cfg)

    def test_skip18_optimization_profiles_are_configurable(self) -> None:
        root = HERE.parent.parent
        cfg = (root / "include" / "vvenc" / "vvencCfg.h").read_text(encoding="utf-8")
        cfg_cpp = (root / "source" / "Lib" / "vvenc" / "vvencCfg.cpp").read_text(encoding="utf-8")
        app_cfg = (root / "source" / "Lib" / "apputils" / "VVEncAppCfg.h").read_text(encoding="utf-8")
        self.assertIn("m_LardLfnst18OptLevel", cfg)
        self.assertIn("LardLfnst18OptLevel out of range [0..4]", cfg_cpp)
        self.assertIn('"LardLfnst18OptLevel"', app_cfg)
        self.assertIn('"lardlfnst18optlevel"', app_cfg)

    def test_skip18_integer_dispatch_precedes_latitude_lookup(self) -> None:
        source = (HERE.parent.parent / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp").read_text(encoding="utf-8")
        decision = source[source.index("LardLfnstCovDecision IntraSearch::xLardLfnstCovDecision"):]
        dispatch_pos = decision.index("xLardSkip18EarlyDispatchPass")
        latitude_pos = decision.index("xLardSkip18LatBinCached")
        self.assertLess(dispatch_pos, latitude_pos)
        self.assertIn("skip18QpEnabled", source)
        self.assertIn("actualQp == 29", source)
        self.assertIn("width < 16 || height < 16", source)
        self.assertIn("xLardSkip18MetaGatePassFast", source)

    def test_skip18_roi_energy_and_fused_response_paths_exist(self) -> None:
        source = (HERE.parent.parent / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("xLardSkip18RoiEnergy", source)
        self.assertIn("xLardCovComputeResponseStatsFused", source)
        self.assertIn("xLardSkip18LevelLogLut", source)
        self.assertIn("numQpEarlyBypass", source)
        self.assertIn("numSizeEarlyBypass", source)
        self.assertIn("numRoiEnergyGate", source)
        self.assertIn("numOptimizedResponse", source)

    def test_skip18_shadow_measure_records_direct_predicted_mask_time(self) -> None:
        root = HERE.parent.parent
        source = (root / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp").read_text(encoding="utf-8")
        cfg_cpp = (root / "source" / "Lib" / "vvenc" / "vvencCfg.cpp").read_text(encoding="utf-8")
        app_cfg = (root / "source" / "Lib" / "apputils" / "VVEncAppCfg.h").read_text(encoding="utf-8")
        self.assertIn("LardLfnst18RealSkip out of range [0..2]", cfg_cpp)
        self.assertIn("2: shadow measure", app_cfg)
        for field in (
            "numPredMaskCandidate1Rdo",
            "numPredMaskCandidate2Rdo",
            "timePredMaskCandidate1RdoNs",
            "timePredMaskCandidate2RdoNs",
            "timeSavedByPredictedMaskNs",
        ):
            self.assertIn(field, source)
        self.assertIn('"actual_qp_size"', source)
        self.assertIn("m_LardLfnst18RealSkip == 2", source)

    def test_skip18_cheap_gate_fit_outputs_qp_threshold_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = ["actualCuQp", "tableFound", "G1_cov", "G2_cov", "predRDGain1", "predRDGain2"]
            rows = []
            for qp, final_thr in ((19, -100.0), (24, -200.0)):
                for idx in range(10):
                    trigger = idx < 4
                    score = -20.0 + idx * 10.0 if trigger else 100.0 + idx
                    pred = final_thr - 10.0 if trigger else final_thr + 10.0
                    rows.append(
                        {
                            "actualCuQp": qp,
                            "tableFound": 1,
                            "G1_cov": score,
                            "G2_cov": score - 1.0,
                            "predRDGain1": pred,
                            "predRDGain2": pred + 1.0,
                        }
                    )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "cheap_gate.json"
            out_inc = root / "LardLfnstSkip18CheapGate.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip18_cheap_gate.py"),
                    str(log),
                    "--final-threshold",
                    "19:-100,24:-200",
                    "--retain",
                    "0.75",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["score"], "max_g_cov")
            self.assertEqual(result["retain_target"], 0.75)
            self.assertIn("19", result["by_qp"])
            self.assertGreaterEqual(result["by_qp"]["19"]["trigger_retain_rate"], 0.75)
            inc = out_inc.read_text(encoding="utf-8")
            self.assertIn("LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS", inc)
            self.assertIn("LARD_LFNST_SKIP18_CHEAP_GATE_THRESHOLD", inc)

    def test_skip18_cheap_gate_linear_trigger_outputs_model_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "cov.csv.gz"
            fields = [
                "actualCuQp", "QP", "tableFound", "W", "H", "latBin", "setIdx", "transpose",
                "sigma2", "qStep", "kIn", "outN",
                "G1_cov", "G2_cov", "predRateGainBits1", "predRateGainBits2",
                "tableZeroOutEnergy1", "tableZeroOutEnergy2", "tableRetainedEnergy1", "tableRetainedEnergy2",
                "predRDGain1", "predRDGain2",
            ]
            rows = []
            for qp, final_thr in ((19, -100.0), (24, -200.0)):
                for idx in range(20):
                    trigger = idx < 6
                    z = -10.0 if trigger else 10.0
                    pred = final_thr - 10.0 if trigger else final_thr + 10.0
                    rows.append(
                        {
                            "actualCuQp": qp,
                            "QP": qp + 3,
                            "tableFound": 1,
                            "W": 16,
                            "H": 16,
                            "latBin": idx % 4,
                            "setIdx": idx % 2,
                            "transpose": idx % 2,
                            "sigma2": 100.0 + idx,
                            "qStep": 2.0,
                            "kIn": 48,
                            "outN": 16,
                            "G1_cov": z,
                            "G2_cov": z - 1.0,
                            "predRateGainBits1": z * 0.1,
                            "predRateGainBits2": z * 0.2,
                            "tableZeroOutEnergy1": 100.0 if trigger else 10.0,
                            "tableZeroOutEnergy2": 90.0 if trigger else 9.0,
                            "tableRetainedEnergy1": 5.0 if trigger else 80.0,
                            "tableRetainedEnergy2": 6.0 if trigger else 70.0,
                            "predRDGain1": pred,
                            "predRDGain2": pred + 1.0,
                        }
                    )
            with gzip.open(log, "wt", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            out_json = root / "cheap_gate_linear.json"
            out_inc = root / "LardLfnstSkip18CheapGate.inc"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fit_lard_lfnst_skip18_cheap_gate.py"),
                    str(log),
                    "--score",
                    "linear_trigger",
                    "--final-threshold",
                    "19:-100,24:-200",
                    "--retain",
                    "0.90",
                    "--out-json",
                    str(out_json),
                    "--out-inc",
                    str(out_inc),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["score"], "linear_trigger")
            self.assertIn("feature_names", result)
            self.assertLess(result["by_qp"]["19"]["non_trigger_pass_rate"], 0.5)
            self.assertIn("meta_gate", result)
            inc = out_inc.read_text(encoding="utf-8")
            self.assertIn("LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES", inc)
            self.assertIn("LARD_LFNST_SKIP18_CHEAP_GATE_COEFF", inc)
            self.assertIn("LARD_LFNST_SKIP18_META_GATE_KEYS", inc)

    def test_cov_measure_log_records_per_candidate_rdo_time(self) -> None:
        header = (ROOT / "source/Lib/EncoderLib/IntraSearch.h").read_text(encoding="utf-8")
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")

        self.assertIn("uint64_t actualRdoTimeNs[3]", header)
        self.assertIn("candidateRdoTimeNs1,candidateRdoTimeNs2", source)
        self.assertIn("actualCuQp,modeGroup,tableFound", source)
        self.assertIn("baseLogLevelSum,baseRoiEnergy", source)
        self.assertIn("lardCovTimeCandidateRdo", source)
        self.assertIn("lardCovDecision.actualRdoTimeNs[lfnstIdx] += ns", source)


if __name__ == "__main__":
    unittest.main()
