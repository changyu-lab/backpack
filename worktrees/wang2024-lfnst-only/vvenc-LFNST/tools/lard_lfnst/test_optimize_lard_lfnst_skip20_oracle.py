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


class Skip20OracleTests(unittest.TestCase):
    def test_oracle_uses_real_candidate_time_and_true_mask_loss(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "trace.csv"
            with log.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "J0", "J1", "J2", "rdoValid0", "rdoValid1", "rdoValid2",
                        "candidateRdoTimeNs1", "candidateRdoTimeNs2",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "J0": 100, "J1": 90, "J2": 110,
                            "rdoValid0": 1, "rdoValid1": 1, "rdoValid2": 1,
                            "candidateRdoTimeNs1": 20, "candidateRdoTimeNs2": 30,
                        },
                        {
                            "J0": 80, "J1": 100, "J2": 90,
                            "rdoValid0": 1, "rdoValid1": 1, "rdoValid2": 1,
                            "candidateRdoTimeNs1": 40, "candidateRdoTimeNs2": 10,
                        },
                    ]
                )

            out_json = root / "oracle.json"
            subprocess.run(
                [
                    sys.executable,
                    str(HERE / "optimize_lard_lfnst_skip20_oracle.py"),
                    str(log),
                    "--mu",
                    "0,10",
                    "--out-json",
                    str(out_json),
                ],
                check=True,
            )
            result = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(result["rows"], 2)

            aggressive = result["sweep"][0]
            self.assertEqual(aggressive["mu"], 0.0)
            self.assertEqual(aggressive["total_time_saved_ns"], 100)
            self.assertEqual(aggressive["total_rd_loss"], 10.0)
            self.assertEqual(aggressive["mask_counts"]["0"], 2)

            conservative = result["sweep"][1]
            self.assertEqual(conservative["mu"], 10.0)
            self.assertEqual(conservative["total_time_saved_ns"], 80)
            self.assertEqual(conservative["total_rd_loss"], 0.0)
            self.assertEqual(conservative["mask_counts"]["0,1"], 1)
            self.assertEqual(conservative["mask_counts"]["0"], 1)

    def test_oracle_rejects_logs_without_per_candidate_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "trace.csv"
            log.write_text("J0,J1,J2\n1,2,3\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "optimize_lard_lfnst_skip20_oracle.py"),
                    str(log),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("candidateRdoTimeNs1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
