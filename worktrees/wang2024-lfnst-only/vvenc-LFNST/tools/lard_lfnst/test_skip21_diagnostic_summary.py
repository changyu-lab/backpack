from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.lard_lfnst import run_skip21_stage1_diagnostic_summary as diag
from tools.lard_lfnst.run_skip21_stage1_diagnostic_summary import (
    _diagnostic_command,
    _parse_profiles,
    additional_file_value,
    anchor_cleanup_outputs,
    summarize_profiles,
)


STAGE1_HEADER = (
    "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,"
    "supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
)

FINAL_HEADER = "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"


class Skip21DiagnosticSummaryTests(unittest.TestCase):
    def test_parse_profiles_accepts_subset_in_requested_order(self) -> None:
        self.assertEqual(
            _parse_profiles("E15_noLat,E10"),
            [("E15_noLat", 6), ("E10", 2)],
        )

    def test_diagnostic_command_uses_configured_geometry(self) -> None:
        cmd = _diagnostic_command(
            Path("vvencFFapp"),
            Path("Gaslamp_8192x4096.yuv"),
            Path("out"),
            22,
            8192,
            4096,
            20,
            "medium",
            1,
            "LFNST=1",
        )

        self.assertIn("8192x4096", cmd)
        self.assertNotIn("3840x1920", cmd)

    def test_anchor_cleanup_removes_large_main_trace(self) -> None:
        out_dir = Path("runs") / "ANCHOR" / "QP22"
        trace_base = out_dir / "trace.csv"

        cleanup = anchor_cleanup_outputs(out_dir, 22, trace_base)

        self.assertIn(trace_base, cleanup)
        self.assertIn(out_dir / "QP22.vvc", cleanup)
        self.assertIn(out_dir / "QP22_rec.yuv", cleanup)

    def test_additional_file_value_prefers_relative_paths_without_drive_colon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "runs" / "diag" / "trace.csv"
            value = additional_file_value(path, root)

            self.assertEqual(value, "runs/diag/trace.csv")
            self.assertNotIn(":", value)

    def test_summarizes_required_groups_and_e10_extra_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e5 = root / "e5.csv"
            e10 = root / "e10.csv"
            final = root / "anchor_final.csv"
            e5.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,3,4,1,0,0,200,1,1,2,0\n"
                + "22,64,0,32,32,1,4,1,0,0,500,0,0,2,2\n",
                encoding="utf-8",
            )
            e10.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,3,4,1,0,0,200,1,1,2,0\n"
                + "22,64,0,32,32,1,4,1,0,0,340,1,1,2,0\n"
                + "27,0,64,16,16,4,2,2,1,1,430,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                FINAL_HEADER
                + "0,0,0,32,32,22,0,0,0,0,0,1\n"
                + "0,64,0,32,32,22,0,0,1,0,0,1\n"
                + "0,0,64,16,16,27,0,0,2,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_profiles({"E5": e5, "E10": e10}, final)

            self.assertEqual(summary["profiles"]["E5"]["total_lfnst_eligible"], 2)
            self.assertEqual(summary["profiles"]["E5"]["stage1_checked"], 2)
            self.assertIn("by_mode_group", summary["profiles"]["E10"])
            self.assertIn("by_setIdx", summary["profiles"]["E10"])
            self.assertIn("by_transpose", summary["profiles"]["E10"])
            self.assertEqual(
                summary["profiles"]["E10"]["by_support_ratio_bin"]["<=0.25"][
                    "early_zero_count"
                ],
                1,
            )
            self.assertEqual(
                summary["profiles"]["E10"]["by_support_ratio_bin"]["0.35-0.45"][
                    "early_zero_count"
                ],
                1,
            )
            self.assertEqual(
                summary["profiles"]["E10"][
                    "anchor_final_idx_distribution_early_zero"
                ],
                {"0": 1, "1": 1, "2": 1},
            )
            extra = summary["e10_extra_vs_e5"]
            self.assertEqual(extra["early_zero_count"], 2)
            self.assertEqual(
                extra["delta_early_zero_by_support_ratio_bin"]["0.25-0.35"][
                    "early_zero_count"
                ],
                1,
            )
            self.assertEqual(
                extra["delta_early_zero_by_support_ratio_bin"]["0.35-0.45"][
                    "early_zero_count"
                ],
                1,
            )
            self.assertEqual(
                extra["anchor_final_idx_distribution_E10_extra"],
                {"1": 1, "2": 1},
            )

    def test_summarizes_profiles_without_full_stage1_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e5 = root / "e5.csv"
            e10 = root / "e10.csv"
            final = root / "anchor_final.csv"
            e5.write_text(
                STAGE1_HEADER + "22,0,0,32,32,3,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )
            e10.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,3,4,1,0,0,200,1,1,2,0\n"
                + "22,64,0,32,32,2,4,1,0,0,340,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                FINAL_HEADER
                + "0,0,0,32,32,22,0,0,0,0,0,1\n"
                + "0,64,0,32,32,22,0,0,1,0,0,1\n",
                encoding="utf-8",
            )

            with patch.object(
                diag, "_read_stage1_rows", side_effect=AssertionError("full read")
            ):
                summary = summarize_profiles({"E5": e5, "E10": e10}, final)

            self.assertEqual(summary["profiles"]["E10"]["early_zero_count"], 2)
            self.assertEqual(summary["e10_extra_vs_e5"]["early_zero_count"], 1)

    def test_summarizes_e12_and_e15_extra_against_e10(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e10 = root / "e10.csv"
            e12 = root / "e12.csv"
            e15 = root / "e15.csv"
            final = root / "anchor_final.csv"
            e10.write_text(
                STAGE1_HEADER + "22,0,0,32,32,4,4,1,0,0,430,1,1,2,0\n",
                encoding="utf-8",
            )
            e12.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,4,4,1,0,0,430,1,1,2,0\n"
                + "22,64,0,32,32,4,4,1,0,0,520,1,1,2,0\n",
                encoding="utf-8",
            )
            e15.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,4,4,1,0,0,430,1,1,2,0\n"
                + "22,64,0,32,32,4,4,1,0,0,520,1,1,2,0\n"
                + "22,96,0,32,32,4,4,1,0,0,640,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                FINAL_HEADER
                + "0,0,0,32,32,22,0,0,0,0,0,1\n"
                + "0,64,0,32,32,22,0,0,1,0,0,1\n"
                + "0,96,0,32,32,22,0,0,2,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_profiles({"E10": e10, "E12": e12, "E15": e15}, final)

            self.assertEqual(summary["e12_extra_vs_e10"]["early_zero_count"], 1)
            self.assertEqual(
                summary["e12_extra_vs_e10"][
                    "anchor_final_idx_distribution_E12_extra"
                ],
                {"1": 1},
            )
            self.assertEqual(summary["e15_extra_vs_e10"]["early_zero_count"], 2)
            self.assertEqual(
                summary["e15_extra_vs_e10"][
                    "delta_early_zero_by_support_ratio_bin"
                ]["0.60-0.65"]["early_zero_count"],
                1,
            )

    def test_summarizes_nolat_extra_against_lat_constrained_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            e12 = root / "e12.csv"
            e12_nolat = root / "e12_nolat.csv"
            final = root / "anchor_final.csv"
            e12.write_text(
                STAGE1_HEADER + "22,0,0,32,32,4,4,1,0,0,520,1,1,2,0\n",
                encoding="utf-8",
            )
            e12_nolat.write_text(
                STAGE1_HEADER
                + "22,0,0,32,32,4,4,1,0,0,520,1,1,2,0\n"
                + "22,64,0,32,32,3,4,1,0,0,520,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                FINAL_HEADER
                + "0,0,0,32,32,22,0,0,0,0,0,1\n"
                + "0,64,0,32,32,22,0,0,1,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_profiles({"E12": e12, "E12_noLat": e12_nolat}, final)

            extra = summary["e12_nolat_extra_vs_e12"]
            self.assertEqual(extra["early_zero_count"], 1)
            self.assertEqual(
                extra["delta_early_zero_by_lat_bin"]["3"]["early_zero_count"],
                1,
            )
            self.assertEqual(
                extra["anchor_final_idx_distribution_E12_noLat_extra"],
                {"1": 1},
            )

    def test_run_diagnostics_supports_selected_profiles_and_dynamic_merged_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_root = root / "diag"
            encoder = root / "vvencFFapp"
            orig = root / "Gaslamp_8192x4096_30fps_8bit_420_erp.yuv"
            encoder.write_text("", encoding="utf-8")
            orig.write_text("", encoding="utf-8")

            def fake_run_encode(
                cmd: list[str],
                required_outputs: list[Path],
                cleanup_outputs: list[Path],
            ) -> None:
                self.assertIn("8192x4096", cmd)
                for path in required_outputs:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.name.endswith(".final.csv"):
                        path.write_text(
                            FINAL_HEADER + "0,0,0,32,32,22,0,0,0,0,0,1\n",
                            encoding="utf-8",
                        )
                    else:
                        path.write_text(
                            STAGE1_HEADER
                            + "22,0,0,32,32,3,4,1,0,0,640,1,1,2,0\n",
                            encoding="utf-8",
                        )
                for path in cleanup_outputs:
                    path.unlink(missing_ok=True)

            args = diag.argparse.Namespace(
                encoder=encoder,
                orig=orig,
                out_root=out_root,
                profiles=[("E15_noLat", 6)],
                width=8192,
                height=4096,
                frames=1,
                threads=20,
                preset="medium",
            )

            with patch.object(diag, "_run_encode_and_cleanup", side_effect=fake_run_encode):
                summary = diag.run_diagnostics(args, [22])

            self.assertEqual(list(summary["profiles"].keys()), ["E15_noLat"])
            self.assertEqual(summary["configuration"]["profiles"], "E15_noLat")
            self.assertEqual(summary["configuration"]["width"], 8192)
            self.assertIn("E15_noLat_stage1_csv", summary["merged_files"])
            self.assertNotIn("E5_stage1_csv", summary["merged_files"])


if __name__ == "__main__":
    unittest.main()
