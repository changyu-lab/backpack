from __future__ import annotations

import unittest
from pathlib import Path

from tools.lard_lfnst.run_skip18_paired_repeats import (
    build_interleaved_schedule,
    proposed_additional,
    resolve_additional,
    summarize_paired_times,
)


class Skip18PairedRepeatTests(unittest.TestCase):
    def test_target_profile_is_forwarded_to_encoder(self) -> None:
        self.assertIn("LardLfnst18TargetProfile=1", proposed_additional(1))
        self.assertIn("LardLfnst18TargetProfile=2", proposed_additional(2))

    def test_explicit_additional_arguments_override_skip18_defaults(self) -> None:
        class Args:
            anchor_additional = "anchor custom"
            proposed_additional = "proposed custom"
            target_profile = 0

        self.assertEqual(resolve_additional("anchor", Args()), "anchor custom")
        self.assertEqual(resolve_additional("proposed", Args()), "proposed custom")

    def test_cpp_target_profiles_are_early_dispatch_gates(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (
            root / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp"
        ).read_text(encoding="utf-8")
        cfg = (root / "source" / "Lib" / "vvenc" / "vvencCfg.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("m_LardLfnst18TargetProfile == 1", source)
        self.assertIn("m_LardLfnst18TargetProfile == 2", source)
        self.assertIn("actualQp == 24", source)
        self.assertIn("width == 32 && height == 32", source)
        self.assertIn("LardLfnst18TargetProfile out of range [0..2]", cfg)

    def test_server_script_falls_back_to_existing_sphere_file(self) -> None:
        root = Path(__file__).resolve().parents[2]
        script = (root / "tools" / "server_run_skip18_v4_repeats.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("find /root -name sphere_655362.txt", script)

    def test_schedule_alternates_pair_order_per_repeat(self) -> None:
        self.assertEqual(
            build_interleaved_schedule(5),
            [
                (1, "anchor"),
                (1, "proposed"),
                (2, "proposed"),
                (2, "anchor"),
                (3, "anchor"),
                (3, "proposed"),
                (4, "proposed"),
                (4, "anchor"),
                (5, "anchor"),
                (5, "proposed"),
            ],
        )

    def test_summary_uses_matched_repeat_and_qp_pairs(self) -> None:
        rows = [
            {"repeat": 1, "QP": 22, "kind": "anchor", "Seconds": 10.0},
            {"repeat": 1, "QP": 22, "kind": "proposed", "Seconds": 9.0},
            {"repeat": 1, "QP": 27, "kind": "anchor", "Seconds": 20.0},
            {"repeat": 1, "QP": 27, "kind": "proposed", "Seconds": 18.0},
            {"repeat": 2, "QP": 22, "kind": "proposed", "Seconds": 11.0},
            {"repeat": 2, "QP": 22, "kind": "anchor", "Seconds": 10.0},
            {"repeat": 2, "QP": 27, "kind": "proposed", "Seconds": 19.0},
            {"repeat": 2, "QP": 27, "kind": "anchor", "Seconds": 20.0},
        ]

        summary = summarize_paired_times(rows)

        self.assertAlmostEqual(summary["repeats"][0]["TS_pct"], 10.0)
        self.assertAlmostEqual(summary["repeats"][1]["TS_pct"], 0.0)
        self.assertAlmostEqual(summary["overall"]["mean_TS_pct"], 5.0)
        self.assertAlmostEqual(summary["overall"]["median_TS_pct"], 5.0)
        self.assertAlmostEqual(summary["overall"]["min_TS_pct"], 0.0)
        self.assertAlmostEqual(summary["overall"]["max_TS_pct"], 10.0)
        self.assertEqual(summary["overall"]["positive_repeats"], 1)
        self.assertAlmostEqual(summary["by_qp"]["22"]["median_TS_pct"], 0.0)
        self.assertAlmostEqual(summary["by_qp"]["27"]["median_TS_pct"], 7.5)

    def test_skip21_stat_file_option_is_plumbed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        cfg_h = (root / "include" / "vvenc" / "vvencCfg.h").read_text(
            encoding="utf-8"
        )
        cfg_cpp = (root / "source" / "Lib" / "vvenc" / "vvencCfg.cpp").read_text(
            encoding="utf-8"
        )
        app_cfg = (root / "source" / "Lib" / "apputils" / "VVEncAppCfg.h").read_text(
            encoding="utf-8"
        )

        self.assertIn("m_LardLfnst21StatFile", cfg_h)
        self.assertIn("memset( c->m_LardLfnst21StatFile", cfg_cpp)
        self.assertIn("vvenc_checkCharArrayStr( c->m_LardLfnst21StatFile", cfg_cpp)
        self.assertIn('"lardlfnst21statfile"', app_cfg)
        self.assertIn('"LardLfnst21StatFile"', app_cfg)

    def test_skip21_diagnostic_rows_are_separate_from_timing_stats(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (
            root / "source" / "Lib" / "EncoderLib" / "IntraSearch.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn("struct LardSkip21EarlyDecision", source)
        self.assertIn("xLardSkip21EarlyDecision", source)
        self.assertIn("xLardSkip21AppendStage1Stat", source)
        self.assertIn("stage1EarlyZero", source)
        self.assertIn(
            "d.stage1EarlyZero = stage1Enabled && d.latBin >= params.minLatBin && d.supportRatioQ <= params.supportQ",
            source,
        )
        self.assertIn("d.earlyZero = d.stage1EarlyZero", source)
        self.assertIn("m_LardLfnst21StatFile", source)
        self.assertIn("d.earlyZero ? 1 : 0, d.stage1EarlyZero ? 1 : 0", source)
        self.assertNotIn("m_LardLfnst18StatFile, cu.qp, cu.lwidth(), cu.lheight(), lardSkip21", source)


if __name__ == "__main__":
    unittest.main()
