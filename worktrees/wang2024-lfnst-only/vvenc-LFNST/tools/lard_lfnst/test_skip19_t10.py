from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Skip19PolicyTest(unittest.TestCase):
    def policy(self):
        return importlib.import_module("tools.lard_lfnst.skip19_policy").decide_mask

    def test_support_degeneracy_skips_both_candidates(self) -> None:
        self.assertEqual(self.policy()(0, 1, 0.0, 0.0, 0.0, 0.0, 0.0), 0x1)

    def test_support_profile_falls_back_to_full_candidates(self) -> None:
        self.assertEqual(self.policy()(0, 2, 0.0, 0.0, 0.0, 0.0, 0.0), 0x7)

    def test_single_candidate_keeps_candidate_one(self) -> None:
        mask = self.policy()(1, 2, 1.5, 0.0, 2.0, 1.0, 2.0, single_margin=1.0)
        self.assertEqual(mask, 0x3)

    def test_single_candidate_keeps_candidate_two(self) -> None:
        mask = self.policy()(2, 2, -0.2, 0.7, 2.0, 2.0, 1.0, single_margin=0.5)
        self.assertEqual(mask, 0x5)

    def test_single_candidate_requires_nonzero_count_tie_break(self) -> None:
        mask = self.policy()(2, 2, 2.0, 0.0, 2.0, 3.0, 1.0, single_margin=0.5)
        self.assertEqual(mask, 0x7)

    def test_profile_three_can_skip_both_weak_candidates(self) -> None:
        mask = self.policy()(3, 2, -0.4, -0.2, 2.0, 2.1, 2.0, zero_margin=0.1)
        self.assertEqual(mask, 0x1)

    def test_negative_zero_margin_spends_rd_budget(self) -> None:
        mask = self.policy()(3, 2, 0.4, 0.3, 2.0, 2.1, 2.0, zero_margin=-0.5)
        self.assertEqual(mask, 0x1)

    def test_actual_cu_qp_bypasses_only_the_table_stage(self) -> None:
        module = importlib.import_module("tools.lard_lfnst.skip19_policy")
        self.assertTrue(module.table_stage_enabled(24, 24))
        self.assertFalse(module.table_stage_enabled(29, 24))

    def test_hybrid_profile_only_applies_single_pruning_after_full_mask(self) -> None:
        module = importlib.import_module("tools.lard_lfnst.skip19_policy")
        self.assertEqual(
            module.apply_single_candidate_to_full_mask(
                0x1, 2, 3.0, 0.0, 2.0, 1.0, 2.0, single_margin=1.0
            ),
            0x1,
        )
        self.assertEqual(
            module.apply_single_candidate_to_full_mask(
                0x7, 2, 3.0, 0.0, 2.0, 1.0, 2.0, single_margin=1.0
            ),
            0x3,
        )


class Skip19SourceContractTest(unittest.TestCase):
    def test_configuration_and_cli_are_independent(self) -> None:
        cfg_h = (ROOT / "include/vvenc/vvencCfg.h").read_text(encoding="utf-8")
        cfg_cpp = (ROOT / "source/Lib/vvenc/vvencCfg.cpp").read_text(encoding="utf-8")
        app = (ROOT / "source/Lib/apputils/VVEncAppCfg.h").read_text(encoding="utf-8")
        self.assertIn("m_LardLfnst19Profile", cfg_h)
        self.assertIn("m_LardLfnst19SingleMargin", cfg_h)
        self.assertIn("m_LardLfnst19ZeroMargin", cfg_h)
        self.assertIn("m_LardLfnst19MaxCuQp", cfg_h)
        self.assertIn("LardLfnstSkip out of range [0..21]", cfg_cpp)
        self.assertIn('"LardLfnst19Profile"', app)
        self.assertIn('"LardLfnst19SingleMargin"', app)
        self.assertIn('"LardLfnst19ZeroMargin"', app)
        self.assertIn('"LardLfnst19MaxCuQp"', app)
        self.assertIn("LardLfnst19ZeroMargin out of range [-1e9..64]", cfg_cpp)
        self.assertIn("LardLfnst19MaxCuQp out of range [0..63]", cfg_cpp)
        self.assertIn("LardLfnst19Profile out of range [0..4]", cfg_cpp)

    def test_skip19_uses_second_response_mask_path(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("const bool t10SpaceSkip", source)
        self.assertIn("m_LardLfnstSkip == 19", source)
        self.assertIn("lardLfnstSkip19", source)
        self.assertIn("xLard19DecisionMask", source)

    def test_skip19_single_candidate_path_uses_o1_theory_table(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("const bool t10TableFastPath", source)
        self.assertIn("xLard2ndTheoryABin( sigmaBase, qStep )", source)
        self.assertIn("xLard2ndFindTheoryStatsEntry", source)

    def test_skip19_support_gate_runs_before_candidate_rdo(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("const bool lardLfnst19EarlySupportSkip", source)
        self.assertIn("&& !lardLfnst19EarlySupportSkip", source)
        self.assertIn("if( lardLfnst19EarlySupportSkip )", source)

    def test_skip19_table_stage_has_actual_cu_qp_bypass(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("cu.qp > m_pcEncCfg->m_LardLfnst19MaxCuQp", source)

    def test_skip19_profile_four_chains_qp_schedule_and_single_pruning(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(encoding="utf-8")
        self.assertIn("const bool t10HybridProfile = t10SpaceSkip && t10Profile == 4", source)
        self.assertIn("xLard19QpScheduleMode", source)
        self.assertIn("if( t10HybridProfile && d.mask == 0x7 )", source)


class T10MetricTest(unittest.TestCase):
    def test_bdrate_summary_includes_ordinary_yuv(self) -> None:
        module = importlib.import_module("tools.lard_run_eval_360_cleanup")
        build = getattr(module, "build_bdrate_metrics")
        rows = []
        for qp, rate, psnr in (
            (22, 1000.0, 40.0),
            (27, 700.0, 37.0),
            (32, 450.0, 34.0),
            (37, 280.0, 31.0),
        ):
            row = {"QP": qp, "AnchorKbps": rate, "ProposedKbps": rate * 1.01}
            for metric in ("ORD", "WS", "S", "CPP"):
                for comp in ("Y", "U", "V", "YUV"):
                    row[f"Anchor_{metric}_{comp}"] = psnr
                    row[f"Proposed_{metric}_{comp}"] = psnr
            rows.append(row)
        metrics = build(rows)
        self.assertIn("ORD_YUV_BDBR_pct", metrics)
        self.assertIn("WS_YUV_BDBR_pct", metrics)
        self.assertIn("S_YUV_BDBR_pct", metrics)
        self.assertIn("CPP_YUV_BDBR_pct", metrics)

    def test_t10_runner_defines_four_profiles_and_constraint(self) -> None:
        module = importlib.import_module("tools.lard_lfnst.run_skip19_t10_sweep")
        profiles = module.profile_additional_args()
        self.assertEqual(set(profiles), {"T10-0", "T10-1", "T10-2", "T10-3"})
        sample = {
            "T10-0": {"TS_pct": 6.0, "ORD_YUV_BDBR_pct": 0.1, "WS_YUV_BDBR_pct": 0.1, "S_YUV_BDBR_pct": 0.1, "CPP_YUV_BDBR_pct": 0.1},
            "T10-2": {"TS_pct": 10.0, "ORD_YUV_BDBR_pct": 0.4, "WS_YUV_BDBR_pct": 0.3, "S_YUV_BDBR_pct": 0.2, "CPP_YUV_BDBR_pct": 0.4},
            "T10-3": {"TS_pct": 13.0, "ORD_YUV_BDBR_pct": 0.6, "WS_YUV_BDBR_pct": 0.4, "S_YUV_BDBR_pct": 0.4, "CPP_YUV_BDBR_pct": 0.4},
        }
        self.assertEqual(module.select_best_feasible(sample, 0.5), "T10-2")


if __name__ == "__main__":
    unittest.main()
