from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from tools.lard_lfnst.run_skip21_stage1_validation import (
    diagnostic_command,
    diagnostic_final_trace_csv,
    e10_needs_8f_fallback,
    main as validation_main,
    merge_diagnostic_profile_csvs,
    _run_diagnostics,
    _run_timing_job,
    skip21_additional,
    timing_command,
)
from tools.lard_lfnst.summarize_skip21_stage1_stats import main, summarize_stage1_stats


REQUIRED_GROUP_FIELDS = {
    "eligible_count",
    "early_zero_count",
    "early_zero_ratio",
    "candidate_before",
    "candidate_after",
    "candidate_reduction",
}


class Skip21Stage1StatsTests(unittest.TestCase):
    def test_skip21_additional_has_expected_profile_without_stat_file(self) -> None:
        self.assertEqual(
            skip21_additional(0),
            "LFNST=1 LardLfnstSkip=21 LardLfnst21Stages=1 LardLfnst21Profile=0",
        )
        self.assertIn("LardLfnst21Profile=2", skip21_additional(2))
        self.assertNotIn("LardLfnst21StatFile", skip21_additional(2))

    def test_e10_fallback_rule_uses_dispersion_and_positive_repeats(self) -> None:
        self.assertFalse(e10_needs_8f_fallback(9.0, 10.0, 7))
        self.assertTrue(e10_needs_8f_fallback(5.0, 10.0, 7))
        self.assertTrue(e10_needs_8f_fallback(9.0, 10.0, 6))

    def test_timing_and_diagnostic_commands_keep_stat_file_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            timing = timing_command(
                encoder=root / "vvencapp",
                orig=root / "input.yuv",
                sphere_file=root / "sphere.txt",
                out_root=root / "timing",
                qps=[22, 27],
                threads=8,
                preset="medium",
                profile=2,
                frames=4,
                repeats=10,
            )
            diagnostic = diagnostic_command(
                encoder=root / "vvencapp",
                orig=root / "input.yuv",
                out_dir=root / "diagnostic",
                qp=22,
                threads=8,
                preset="medium",
                profile=2,
                stage1_csv=root / "stage1.csv",
                trace_base=root / "trace.csv",
                frames=4,
            )

        timing_text = " ".join(timing)
        diagnostic_text = " ".join(diagnostic)
        self.assertNotIn("LardLfnst21StatFile", timing_text)
        self.assertIn("LardLfnst21StatFile=", diagnostic_text)
        self.assertIn("LardLfnstTraceFile=", diagnostic_text)
        self.assertEqual(
            diagnostic_final_trace_csv(root / "trace.csv"),
            root / "trace.csv.final.csv",
        )

    def test_diagnostic_merge_includes_final_lfnst_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage1_a = root / "qp22_stage1.csv"
            stage1_b = root / "qp27_stage1.csv"
            final_a = root / "qp22_trace.csv.final.csv"
            final_b = root / "qp27_trace.csv.final.csv"
            stage1_header = (
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,"
                "supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
            )
            final_header = (
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
            )
            stage1_a.write_text(
                stage1_header + "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )
            stage1_b.write_text(
                stage1_header + "27,64,0,16,16,1,2,1,0,0,500,0,0,2,2\n",
                encoding="utf-8",
            )
            final_a.write_text(
                final_header + "0,0,0,32,32,22,0,0,0,0,0,1\n",
                encoding="utf-8",
            )
            final_b.write_text(
                final_header
                + "0,64,0,16,16,27,0,0,2,0,0,1\n"
                + "0,80,0,16,16,27,0,0,2,0,0,1\n",
                encoding="utf-8",
            )

            stats = merge_diagnostic_profile_csvs(
                {"E10": [stage1_a, stage1_b]},
                {"E10": [final_a, final_b]},
                root / "diagnostics",
            )

            self.assertEqual(
                stats["E10"]["final_lfnst_idx_distribution"], {"0": 1, "2": 2}
            )
            summary = (root / "diagnostics" / "E10" / "diagnostic_summary.json")
            self.assertEqual(
                summarize_stage1_stats(
                    root / "diagnostics" / "E10" / "diagnostic_stage1.csv",
                    root / "diagnostics" / "E10" / "diagnostic_final_trace.csv",
                )["final_lfnst_idx_distribution"],
                {"0": 1, "2": 2},
            )
            self.assertIn('"final_lfnst_idx_distribution"', summary.read_text(encoding="utf-8"))
            merged_final = (root / "diagnostics" / "E10" / "diagnostic_final_trace.csv").read_text(
                encoding="utf-8"
            )
            self.assertEqual(merged_final.count(final_header), 1)

    def test_validation_main_runs_diagnostics_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = {
                "paired_timing": {
                    "overall": {
                        "mean_TS_pct": 9.0,
                        "median_TS_pct": 10.0,
                        "positive_repeats": 7,
                    }
                }
            }
            diagnostics = {
                "E10": {"final_lfnst_idx_distribution": {"0": 1, "2": 2}}
            }
            argv = [
                "prog",
                "--encoder",
                str(root / "vvencapp"),
                "--orig",
                str(root / "input.yuv"),
                "--sphere-file",
                str(root / "sphere.txt"),
                "--out-root",
                str(root / "out"),
            ]

            with patch("sys.argv", argv), patch(
                "tools.lard_lfnst.run_skip21_stage1_validation._run_timing_job",
                return_value=summary,
            ), patch(
                "tools.lard_lfnst.run_skip21_stage1_validation._run_diagnostics",
                return_value=diagnostics,
            ) as run_diagnostics:
                with redirect_stdout(io.StringIO()):
                    validation_main()

            validation_summary = json.loads(
                (root / "out" / "validation_summary.json").read_text(encoding="utf-8")
            )
            run_diagnostics.assert_called_once()
            self.assertEqual(validation_summary["diagnostic_stats"], diagnostics)

    def test_validation_main_can_skip_diagnostics_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = {
                "paired_timing": {
                    "overall": {
                        "mean_TS_pct": 9.0,
                        "median_TS_pct": 10.0,
                        "positive_repeats": 7,
                    }
                }
            }
            argv = [
                "prog",
                "--encoder",
                str(root / "vvencapp"),
                "--orig",
                str(root / "input.yuv"),
                "--sphere-file",
                str(root / "sphere.txt"),
                "--out-root",
                str(root / "out"),
                "--skip-diagnostics",
            ]

            with patch("sys.argv", argv), patch(
                "tools.lard_lfnst.run_skip21_stage1_validation._run_timing_job",
                return_value=summary,
            ), patch(
                "tools.lard_lfnst.run_skip21_stage1_validation._run_diagnostics"
            ) as run_diagnostics:
                with redirect_stdout(io.StringIO()):
                    validation_main()

            validation_summary = json.loads(
                (root / "out" / "validation_summary.json").read_text(encoding="utf-8")
            )
            run_diagnostics.assert_not_called()
            self.assertEqual(validation_summary["diagnostic_stats"], {})

    def test_timing_job_rejects_stale_summary_after_child_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_summary = root / "E5_8f5" / "timing" / "summary.json"
            stale_summary.parent.mkdir(parents=True)
            stale_summary.write_text(
                json.dumps({"paired_timing": {"overall": {}}}),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                encoder=root / "vvencapp",
                orig=root / "input.yuv",
                sphere_file=root / "sphere.txt",
                out_root=root,
                threads=8,
                preset="medium",
            )

            with patch("tools.lard_lfnst.run_skip21_stage1_validation.subprocess.run"):
                with self.assertRaises(RuntimeError):
                    _run_timing_job("E5_8f5", 0, 8, 5, args, [22])

    def test_diagnostics_reject_stale_csvs_after_child_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage1_header = (
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,"
                "supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
            )
            final_header = (
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
            )
            for profile_name in ("E5", "E10"):
                out_dir = root / profile_name / "diagnostic" / "QP22"
                out_dir.mkdir(parents=True)
                (out_dir / "stage1.csv").write_text(
                    stage1_header + "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                    encoding="utf-8",
                )
                (out_dir / "trace.csv.final.csv").write_text(
                    final_header + "0,0,0,32,32,22,0,0,0,0,0,1\n",
                    encoding="utf-8",
                )
                (out_dir / "QP22.vvc").write_text("stale bitstream", encoding="utf-8")
                (out_dir / "QP22_rec.yuv").write_text("stale rec", encoding="utf-8")

            args = argparse.Namespace(
                encoder=root / "vvencapp",
                orig=root / "input.yuv",
                out_root=root,
                threads=8,
                preset="medium",
            )

            with patch("tools.lard_lfnst.run_skip21_stage1_validation.subprocess.run"):
                with self.assertRaises(RuntimeError):
                    _run_diagnostics(args, [22])

    def test_aggregates_candidate_reduction_and_ratios(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n"
                "22,64,0,32,32,0,4,1,0,0,800,0,0,2,2\n"
                "27,0,512,16,16,3,2,2,1,1,240,1,1,2,0\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat)

            self.assertEqual(summary["eligible_count"], 3)
            self.assertEqual(summary["early_zero_count"], 2)
            self.assertAlmostEqual(summary["early_zero_ratio"], 2 / 3)
            self.assertEqual(summary["candidate_before_total"], 6)
            self.assertEqual(summary["candidate_after_total"], 2)
            self.assertAlmostEqual(summary["nonzero_candidate_reduction"], 4 / 6)
            self.assertEqual(summary["by_qp"]["22"]["eligible_count"], 2)
            self.assertAlmostEqual(summary["by_qp"]["22"]["candidate_reduction"], 2 / 4)
            self.assertEqual(summary["by_size"]["32x32"]["eligible_count"], 2)
            self.assertEqual(summary["by_size"]["16x16"]["early_zero_count"], 1)
            self.assertEqual(summary["by_lat_bin"]["3"]["early_zero_count"], 1)
            self.assertEqual(summary["early_zero_by_support_ratio_bin"]["[0,0.25)"]["early_zero_count"], 2)
            self.assertEqual(summary["early_zero_by_support_ratio_bin"]["[0.75,1.0]"]["early_zero_count"], 0)

    def test_grouped_diagnostics_include_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat)

            for section_name, key in (
                ("by_qp", "22"),
                ("by_size", "32x32"),
                ("by_lat_bin", "0"),
                ("early_zero_by_support_ratio_bin", "[0,0.25)"),
            ):
                self.assertEqual(
                    set(summary[section_name][key]),
                    REQUIRED_GROUP_FIELDS,
                    section_name,
                )

    def test_skips_rows_with_nonpositive_candidate_before(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n"
                "37,64,64,64,64,3,4,1,0,0,200,1,1,0,0\n"
                "37,128,64,64,64,3,4,1,0,0,200,1,1,-1,0\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat)

            self.assertEqual(summary["eligible_count"], 1)
            self.assertNotIn("37", summary["by_qp"])
            self.assertNotIn("64x64", summary["by_size"])

    def test_reads_stage1_csv_with_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8-sig",
            )

            summary = summarize_stage1_stats(stat)

            self.assertEqual(summary["by_qp"]["22"]["eligible_count"], 1)

    def test_cli_requires_out_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )

            with patch("sys.argv", ["prog", "--stage1-csv", str(stat)]):
                with self.assertRaises(SystemExit) as err:
                    main()

            self.assertEqual(err.exception.code, 2)

    def test_reads_final_lfnst_distribution_without_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stat = Path(tmp) / "stage1.csv"
            final = Path(tmp) / "trace.final.csv"
            stat.write_text(
                "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,earlyZero,stage1Decision,candidateBefore,candidateAfter\n"
                "22,0,0,32,32,0,4,1,0,0,200,1,1,2,0\n",
                encoding="utf-8",
            )
            final.write_text(
                "poc,x,y,w,h,qp,predMode,intraMode,lfnstIdx,ispMode,mipFlag,rootCbf\n"
                "0,0,0,32,32,22,0,0,0,0,0,1\n"
                "0,64,0,32,32,22,0,0,1,0,0,1\n"
                "0,96,0,32,32,22,0,0,2,0,0,1\n",
                encoding="utf-8",
            )

            summary = summarize_stage1_stats(stat, final)

            self.assertEqual(summary["final_lfnst_idx_distribution"], {"0": 1, "1": 1, "2": 1})


if __name__ == "__main__":
    unittest.main()
