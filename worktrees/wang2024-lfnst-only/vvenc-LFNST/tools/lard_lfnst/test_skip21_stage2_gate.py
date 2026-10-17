from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.lard_lfnst.run_skip21_stage1_diagnostic_summary import summarize_profiles


ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2GateTests(unittest.TestCase):
    def test_diagnostic_parser_accepts_stage2_only_profiles(self) -> None:
        from tools.lard_lfnst import run_skip21_stage1_diagnostic_summary as diag

        parsed = diag._parse_profiles("E15_noLat,S2_D1_only,S2_D2_only,S2_D3_only")

        self.assertEqual(parsed[0][0], "E15_noLat")
        self.assertIn("LardLfnst21Stages=2", diag.skip21_additional(parsed[1][1]))
        self.assertIn("LardLfnst21Stage2Profile=0", diag.skip21_additional(parsed[1][1]))
        self.assertIn("LardLfnst21Stage2Profile=2", diag.skip21_additional(parsed[3][1]))

    def test_cpp_exposes_independent_stage2_mode(self) -> None:
        cfg_h = (ROOT / "include/vvenc/vvencCfg.h").read_text(encoding="utf-8")
        app_cfg = (ROOT / "source/Lib/apputils/VVEncAppCfg.h").read_text(
            encoding="utf-8"
        )
        vvenc_cfg = (ROOT / "source/Lib/vvenc/vvencCfg.cpp").read_text(
            encoding="utf-8"
        )
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(
            encoding="utf-8"
        )

        self.assertIn("m_LardLfnst21Stage2Profile", cfg_h)
        self.assertIn("LardLfnst21Stage2Profile", app_cfg)
        self.assertIn("LardLfnst21Stage2Profile out of range [0..2]", vvenc_cfg)
        self.assertIn("1 Stage1-only, 2 Stage2-only, 3 Stage1+Stage2", app_cfg)
        self.assertIn(
            "const bool stage1Enabled = cfg->m_LardLfnst21Stages == 1 || cfg->m_LardLfnst21Stages == 3",
            source,
        )
        self.assertIn(
            "const bool stage2Enabled = cfg->m_LardLfnst21Stages == 2 || cfg->m_LardLfnst21Stages == 3",
            source,
        )
        self.assertIn("d.stage2EarlyZero", source)
        self.assertIn("xLardSkip21Stage2WeakCoupling", source)

    def test_summary_reports_stage2_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage2.csv"
            final = root / "anchor_final.csv"
            stage.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,"
                "supportRatioQ,oxQ,diagDominanceQ,gmaxCovQ,diffCovQ,earlyZero,stage1Decision,"
                "stage2Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,3,4,1,0,0,700,180,840,120,20,1,0,1,2,0\n"
                "22,64,0,32,32,4,4,1,0,0,430,420,700,300,80,1,1,0,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
                "0,0,0,32,32,22,0,0,0,0,0,1\n"
                "0,64,0,32,32,22,0,0,1,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_profiles({"S2_D1_only": stage}, final)
            profile = summary["profiles"]["S2_D1_only"]

            self.assertEqual(profile["stage2_checked"], 2)
            self.assertEqual(profile["stage1_early_zero_count"], 1)
            self.assertEqual(profile["stage2_early_zero_count"], 1)
            self.assertEqual(profile["stage2_early_zero_ratio"], 0.5)
            self.assertEqual(profile["overlap"]["s1_only"], 1)
            self.assertEqual(profile["overlap"]["s2_only"], 1)
            self.assertEqual(profile["both_count"], 0)
            self.assertEqual(profile["stage1_only_count"], 1)
            self.assertEqual(profile["stage2_only_count"], 1)
            self.assertEqual(profile["neither_count"], 0)
            self.assertIn("by_gmax_cov_bin", profile)
            self.assertIn("<=0.125", profile["by_gmax_cov_bin"])
            self.assertIn("by_ox_bin", profile)
            self.assertIn("by_diag_dominance_bin", profile)
            self.assertIn("<=0.25", profile["by_ox_bin"])
            self.assertIn("0.75-0.875", profile["by_diag_dominance_bin"])

    def test_summary_reports_overlap_with_stage1_e15_nolat_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e15 = root / "e15.csv"
            s2 = root / "s2.csv"
            final = root / "anchor_final.csv"
            header = (
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,"
                "supportRatioQ,oxQ,diagDominanceQ,gmaxCovQ,diffCovQ,earlyZero,"
                "stage1Decision,stage2Decision,candidateBefore,candidateAfter\n"
            )
            e15.write_text(
                header
                + "22,0,0,32,32,3,4,1,0,0,620,180,840,120,20,1,1,0,2,0\n"
                + "22,64,0,32,32,4,4,1,0,0,430,420,700,300,80,0,0,0,2,2\n",
                encoding="utf-8",
            )
            s2.write_text(
                header
                + "22,0,0,32,32,3,4,1,0,0,620,180,840,120,20,1,0,1,2,0\n"
                + "22,64,0,32,32,4,4,1,0,0,430,200,820,120,80,1,0,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
                "0,0,0,32,32,22,0,0,0,0,0,1\n"
                "0,64,0,32,32,22,0,0,1,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_profiles({"E15_noLat": e15, "S2_D1_only": s2}, final)
            overlap = summary["profiles"]["S2_D1_only"]["overlap_with_stage1_e15_nolat"]

            self.assertEqual(overlap["stage1_e15_nolat_count"], 1)
            self.assertEqual(overlap["stage2_count"], 2)
            self.assertEqual(overlap["both_count"], 1)
            self.assertEqual(overlap["stage2_only_count"], 1)
            self.assertEqual(overlap["stage1_only_count"], 0)
            self.assertEqual(overlap["neither_count"], 0)


if __name__ == "__main__":
    unittest.main()
