from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HEADER = [
    "covQard", "QP", "w", "h", "outN", "sizeGroup",
    "predMinNormQard", "J0", "J1", "J2", "R0",
    "rdoTime0", "rdoTime1", "rdoTime2", "rdeEvalTime",
    "baseAbsSum",
]


def _sample(**overrides):
    from tools.lard_lfnst.calibrate_skip21_stage3_qard import Sample

    values = {
        "sequence": "seq",
        "qp": 22,
        "pred": 2.0,
        "truth": 1.0,
        "error": 1.0,
        "rdo0": 5.0,
        "rdo12": 100.0,
        "eval_time": 10.0,
        "out_n": 16,
        "size_group": 2,
        "width": 16,
        "height": 16,
        "base_abs_sum": 256.0,
        "r0": 256.0 * 30000.0,
    }
    values.update(overrides)
    return Sample(**values)


class CalibrateSkip21Stage3QardTests(unittest.TestCase):
    def test_selective_activation_limits_pruning_and_eval_overhead_to_activated_blocks(self) -> None:
        from tools.lard_lfnst.calibrate_skip21_stage3_qard import evaluate

        activated_pruned = _sample(sequence="on", pred=2.0, rdo12=100.0, eval_time=10.0)
        inactive_would_prune = _sample(
            sequence="off",
            pred=2.0,
            rdo12=1000.0,
            eval_time=100.0,
            base_abs_sum=255.0,
        )

        result = evaluate([activated_pruned, inactive_would_prune], margin=1.0, profile=2, activation_profile=1)

        self.assertEqual(result["n_eligible"], 2)
        self.assertEqual(result["activated_n"], 1)
        self.assertAlmostEqual(result["activation_rate"], 0.5)
        self.assertEqual(result["skip_n"], 1)
        self.assertAlmostEqual(result["conditional_prune_rate"], 1.0)
        self.assertAlmostEqual(result["prune_rate_over_eligible"], 0.5)
        self.assertAlmostEqual(result["stage3_eval_time_total_ns"], 10.0)
        self.assertAlmostEqual(result["estimated_nonzero_rdo_time_saved_fraction_net_after_stage3"], 90.0 / 1100.0)
        self.assertEqual(result["by_sequence"]["off"]["activated_n"], 0)

    def test_default_cli_matches_frozen_selective_qard_profile(self) -> None:
        from tools.lard_lfnst import calibrate_skip21_stage3_qard as mod

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            csv_path = tmp / "shadow.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADER)
                writer.writeheader()
                writer.writerow({
                    "covQard": 1,
                    "QP": 22,
                    "w": 16,
                    "h": 16,
                    "outN": 16,
                    "sizeGroup": 2,
                    "predMinNormQard": 1.0,
                    "J0": 100.0,
                    "J1": 110.0,
                    "J2": 120.0,
                    "R0": 256.0 * 30000.0,
                    "rdoTime0": 1,
                    "rdoTime1": 10,
                    "rdoTime2": 20,
                    "rdeEvalTime": 3,
                    "baseAbsSum": 256,
                })

            out_dir = tmp / "out"
            argv = [
                "calibrate_skip21_stage3_qard.py",
                "--calibration", f"seq={csv_path}",
                "--out-dir", str(out_dir),
            ]
            with mock.patch.object(sys, "argv", argv):
                mod.main()

            result = json.loads((out_dir / "stage3_qard_calibration.json").read_text(encoding="utf-8"))
            real = (out_dir / "stage3_qard_real.additional.txt").read_text(encoding="utf-8")

        self.assertEqual(result["alpha"], 0.005)
        self.assertEqual(result["parameters"]["profile"], 2)
        self.assertEqual(result["parameters"]["activation_profile"], 1)
        self.assertIn("LardLfnst21Stage3RdeProfile=2", real)
        self.assertIn("LardLfnst21Stage3RdeActivationProfile=1", real)


if __name__ == "__main__":
    unittest.main()
