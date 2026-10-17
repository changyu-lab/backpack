from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tools.lard_lfnst import run_lfnst_covariance_model_validation as cov42


ROOT = Path(__file__).resolve().parents[2]


def _write_vec_log(path: Path) -> None:
    fieldnames = [
        "poc", "x", "y", "w", "h", "qp", "intraMode", "lfnstSet", "sbSize",
        "zeroOutSize", "trSize", "transposeFlag", "absLatDeg", "thetaMaxDeg",
        "modeGroup", "sizeGroup", "latBucket", "sbClass", "inputEnergy",
        *[f"x{i:02d}" for i in range(48)],
    ]
    rows = []
    templates = [
        (0, 0.0, [1.0, 0.0, 0.0, 0.0]),
        (0, 0.0, [2.0, 0.0, 0.0, 0.0]),
        (0, 0.0, [3.0, 0.0, 0.0, 0.0]),
        (2, 60.0, [1.0, 1.0, 0.0, 0.0]),
        (2, 60.0, [2.0, 2.0, 0.0, 0.0]),
        (2, 60.0, [3.0, 3.0, 0.0, 0.0]),
    ]
    for idx, (bucket, theta, vals) in enumerate(templates):
        row = {
            "poc": 0,
            "x": idx * 4,
            "y": 0,
            "w": 4,
            "h": 4,
            "qp": 32,
            "intraMode": 0,
            "lfnstSet": 0,
            "sbSize": 4,
            "zeroOutSize": 8,
            "trSize": 16,
            "transposeFlag": 0,
            "absLatDeg": theta,
            "thetaMaxDeg": theta,
            "modeGroup": 0,
            "sizeGroup": 0,
            "latBucket": bucket,
            "sbClass": 0,
            "inputEnergy": sum(v * v for v in vals),
        }
        for i in range(48):
            row[f"x{i:02d}"] = vals[i] if i < len(vals) else 0.0
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class CovarianceModelValidationTests(unittest.TestCase):
    def test_theory_propagation_exposes_all_required_matrices(self) -> None:
        mats = cov42.theory_matrices_for(8, 8, 60.0)

        self.assertEqual(mats.R_hor.shape, (8, 8))
        self.assertEqual(mats.Sigma_E.shape, (64, 64))
        self.assertEqual(mats.Sigma_F.shape, (64, 64))
        self.assertEqual(mats.Sigma_x.shape, (48, 48))
        self.assertGreater(mats.R_hor[0, 7], mats.R_hor[0, 7] * 0.0)
        self.assertTrue((mats.Sigma_x.diagonal() >= -1e-9).all())

    def test_empirical_validation_outputs_correct_and_shuffled_similarity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            vec = out / "vec.csv"
            _write_vec_log(vec)

            result = cov42.run_empirical_validation(
                vec_logs=[vec],
                out_dir=out,
                sizes=[(4, 4)],
                theta_values=[0.0, 60.0],
                min_samples=2,
                write_figures=True,
            )

            self.assertEqual(result["groups"], 2)
            table = pd.read_csv(out / "covariance_similarity_by_group.csv")
            self.assertIn("simF_correct", table.columns)
            self.assertIn("simF_shuffled", table.columns)
            self.assertTrue((table["simF_correct"] != table["simF_shuffled"]).any())
            summary = pd.read_csv(out / "covariance_similarity_summary.csv")
            self.assertIn("mean_simF_correct", summary.columns)
            self.assertTrue((out / "fig_4_2_B_similarity_heatmap.png").exists())
            self.assertTrue((out / "fig_4_2_B_real_vs_theory_matrices.png").exists())

    def test_formal_mode_writes_experiment_4_2_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            vec = out / "vec.csv"
            cov = out / "cov.csv"
            _write_vec_log(vec)
            cov.write_text(
                "POC,x,y,W,H,QP,latBin,setIdx,transpose,kIn,J0,J1,J2,bestIdx,sigma2_res\n"
                "0,0,0,4,4,32,0,0,0,16,100,80,120,1,1.0\n"
                "0,4,0,4,4,32,0,0,0,16,120,100,140,1,1.0\n",
                encoding="utf-8",
            )
            result = cov42.run_formal_experiment_4_2(
                vec_logs=[vec],
                cov_logs=[cov],
                out_dir=out / "formal",
                sizes=[(4, 4)],
                theta_values=[0.0, 60.0],
                min_samples=2,
                write_figures=False,
            )
            self.assertGreaterEqual(result["groups"], 1)
            self.assertTrue((out / "formal" / "covariance_group_metrics.csv").exists())
            self.assertTrue((out / "formal" / "metric_rank_correlations.csv").exists())
            self.assertTrue((out / "formal" / "top1_candidate_match.csv").exists())
            self.assertTrue((out / "formal" / "low_gain_reliability_curve.csv").exists())

    def test_script_entrypoint_runs_from_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            script = ROOT / "tools/lard_lfnst/run_lfnst_covariance_model_validation.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--out-dir",
                    str(out),
                    "--sizes",
                    "4",
                    "--theta-values",
                    "0,60",
                    "--skip-empirical",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            self.assertTrue((out / "fig_4_2_A_theory_covariance_propagation_4x4.png").exists())


if __name__ == "__main__":
    unittest.main()
