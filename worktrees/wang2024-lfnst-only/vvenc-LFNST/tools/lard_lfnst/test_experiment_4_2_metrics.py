from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from tools.lard_lfnst import experiment_4_2_metrics as m


class Experiment42MetricsTests(unittest.TestCase):
    def test_canonical_vector_row_accepts_legacy_names(self) -> None:
        row = {
            "poc": 3,
            "x": 4,
            "y": 8,
            "w": 8,
            "h": 8,
            "qp": 32,
            "latBucket": 2,
            "lfnstSetIdx": 1,
            "transposeFlag": 1,
            "trSize": 48,
            "zeroOutSize": 8,
            "x00": 1.0,
            "x01": -2.0,
        }
        vec = m.canonical_vector_row(row, theta_values=[0.0, 30.0, 60.0, 75.0])
        self.assertEqual(vec.group_key, m.GroupKey(qp=32, w=8, h=8, lat_bin=2, set_idx=1, transpose=1, k=48))
        self.assertEqual(vec.kz, 8)
        self.assertEqual(vec.values.shape, (48,))
        self.assertEqual(vec.values[0], 1.0)
        self.assertEqual(vec.values[1], -2.0)

    def test_canonical_rdo_row_accepts_cov_log_names(self) -> None:
        row = {
            "POC": 3,
            "x": 4,
            "y": 8,
            "W": 16,
            "H": 16,
            "QP": 32,
            "latBin": 3,
            "setIdx": 2,
            "transpose": 0,
            "kIn": 48,
            "J0": 100.0,
            "J1": 90.0,
            "J2": 130.0,
            "bestIdx": 1,
            "sigma2_res": 7.5,
        }
        rdo = m.canonical_rdo_row(row)
        self.assertIsNotNone(rdo)
        assert rdo is not None
        self.assertEqual(rdo.group_key, m.GroupKey(qp=32, w=16, h=16, lat_bin=3, set_idx=2, transpose=0, k=48))
        self.assertEqual(rdo.delta_j1, 10.0)
        self.assertEqual(rdo.delta_j2, -30.0)
        self.assertEqual(rdo.delta_jmax, 10.0)

    def test_cov_accumulator_uses_mean_centered_unbiased_covariance(self) -> None:
        acc = m.CovAccumulator(dim=2)
        acc.add(np.array([1.0, 2.0]))
        acc.add(np.array([3.0, 4.0]))
        cov = acc.covariance()
        expected = np.array([[2.0, 2.0], [2.0, 2.0]])
        self.assertTrue(np.allclose(cov, expected))

    def test_corr_and_nce_mask_zero_variance_dimensions(self) -> None:
        sigma_emp = np.array([[4.0, 2.0, 0.0], [2.0, 9.0, 0.0], [0.0, 0.0, 0.0]])
        sigma_th = np.array([[4.0, 1.0, 0.0], [1.0, 9.0, 0.0], [0.0, 0.0, 0.0]])
        r_emp, active = m.correlation_matrix(sigma_emp)
        r_th, _ = m.correlation_matrix(sigma_th)
        self.assertEqual(active.tolist(), [True, True, False])
        full = m.normalized_covariance_error(r_emp, r_th, active, offdiag_only=False)
        off = m.normalized_covariance_error(r_emp, r_th, active, offdiag_only=True)
        self.assertGreater(full, 0.0)
        self.assertGreater(off, 0.0)
        self.assertLess(off, 1.0)

    def test_spearman_handles_order_and_constant_vectors(self) -> None:
        self.assertAlmostEqual(m.spearman([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]), 1.0)
        self.assertAlmostEqual(m.spearman([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]), -1.0)
        self.assertTrue(math.isnan(m.spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])))

    def test_covariance_rank_correlation_uses_upper_offdiag(self) -> None:
        r_emp = np.array([[1.0, 0.9, 0.2], [0.9, 1.0, 0.4], [0.2, 0.4, 1.0]])
        r_th = np.array([[1.0, 0.8, 0.1], [0.8, 1.0, 0.3], [0.1, 0.3, 1.0]])
        rho, valid = m.covariance_rank_correlation(r_emp, r_th, np.array([True, True, True]))
        self.assertEqual(valid, 1)
        self.assertAlmostEqual(rho, 1.0)

    def test_response_metrics_and_top1_match(self) -> None:
        sigma = np.eye(4)
        lfnst = np.array(
            [
                [[2.0, 0.0, 0.0, 0.0], [0.0, 0.5, 0.0, 0.0]],
                [[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.5, 0.0]],
            ],
            dtype=np.float64,
        )
        metrics = m.response_metrics(sigma, lfnst)
        self.assertGreater(metrics["G1_resp"], metrics["G2_resp"])
        self.assertEqual(m.theory_top1_candidate(metrics), 1)
        rdo = m.rdo_group_metrics(
            [
                m.RdoSample(m.GroupKey(32, 4, 4, 0, 0, 0, 4), 100.0, 80.0, 110.0, 1, None),
                m.RdoSample(m.GroupKey(32, 4, 4, 0, 0, 0, 4), 120.0, 100.0, 130.0, 1, None),
            ]
        )
        self.assertEqual(rdo["rdo_top1"], 1)
        self.assertEqual(rdo["top1_rdo_valid"], 1)
        self.assertAlmostEqual(rdo["P_positive_gain"], 1.0)

    def test_analyze_groups_writes_formal_metric_tables(self) -> None:
        key = m.GroupKey(qp=32, w=4, h=4, lat_bin=0, set_idx=0, transpose=0, k=4)
        acc = m.CovAccumulator(dim=4)
        for vec in (
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.array([2.0, 0.0, 0.0, 0.0]),
            np.array([3.0, 0.0, 0.0, 0.0]),
        ):
            acc.add(vec)
        rdos = {
            key: [
                m.RdoSample(key, 100.0, 80.0, 120.0, 1, 1.0),
                m.RdoSample(key, 120.0, 100.0, 140.0, 1, 1.0),
            ]
        }
        lfnst_by_key = {
            key: np.array(
                [
                    [[2.0, 0.0, 0.0, 0.0], [0.0, 0.5, 0.0, 0.0]],
                    [[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 0.5, 0.0]],
                ],
                dtype=np.float64,
            )
        }
        theory_by_key = {key: acc.covariance()}
        with tempfile.TemporaryDirectory() as tmp:
            result = m.write_formal_analysis_outputs(
                out_dir=Path(tmp),
                empirical_accs={key: acc},
                theory_cov_by_key=theory_by_key,
                lfnst_by_key=lfnst_by_key,
                rdo_by_key=rdos,
                min_samples=2,
            )
            self.assertEqual(result["groups"], 1)
            cov = pd.read_csv(Path(tmp) / "covariance_group_metrics.csv")
            top = pd.read_csv(Path(tmp) / "top1_candidate_match.csv")
            rel = pd.read_csv(Path(tmp) / "low_gain_reliability_curve.csv")
            self.assertIn("NCE_full", cov.columns)
            self.assertIn("NCE_off", cov.columns)
            self.assertEqual(int(top["match"].iloc[0]), 1)
            self.assertIn("P_no_gain", rel.columns)

    def test_plot_formal_outputs_creates_required_figures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cov = pd.DataFrame(
                [
                    {"QP": 32, "W": 4, "H": 4, "latBin": 0, "setIdx": 0, "transpose": 0, "K": 4, "Kz": 8, "NCE_full": 0.1, "NCE_off": 0.2, "samples": 10},
                    {"QP": 32, "W": 8, "H": 8, "latBin": 2, "setIdx": 0, "transpose": 0, "K": 48, "Kz": 8, "NCE_full": 0.3, "NCE_off": 0.4, "samples": 20},
                ]
            )
            merged = pd.DataFrame(
                [
                    {"G_max_resp_th": 1.0, "P_positive_gain": 0.2, "U_max_offplus_th": 0.5, "O_x_th": 0.1, "chi_diag_th": 0.9},
                    {"G_max_resp_th": 2.0, "P_positive_gain": 0.8, "U_max_offplus_th": 0.8, "O_x_th": 0.3, "chi_diag_th": 0.4},
                ]
            )
            rel = pd.DataFrame([{"bin": "Q1", "P_no_gain": 0.8}, {"bin": "Q2", "P_no_gain": 0.2}])
            m.plot_formal_outputs(out, cov, merged, rel)
            self.assertTrue((out / "fig_4_2_nce_by_size_lat.png").exists())
            self.assertTrue((out / "fig_4_2_response_vs_gain.png").exists())
            self.assertTrue((out / "fig_4_2_low_gain_reliability.png").exists())


if __name__ == "__main__":
    unittest.main()
