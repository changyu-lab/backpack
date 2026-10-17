from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.lard_lfnst import summarize_skip21_theory_table as summary_tool


ROOT = Path(__file__).resolve().parents[2]


class Skip21TheorySanityTests(unittest.TestCase):
    def test_summary_reports_metric_ranges_and_group_means(self) -> None:
        table = ROOT / "source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.json"
            summary = summary_tool.summarize_table(table, out)

            self.assertEqual(summary["num_entries"], 13440)
            for metric in ("oxQ", "diagDominanceQ", "gmaxCovQ", "diffCovQ"):
                self.assertIn(metric, summary["metrics"])
                stats = summary["metrics"][metric]
                self.assertLess(stats["min"], stats["max"])
                self.assertIn("p10", stats)
                self.assertIn("p50", stats)
                self.assertIn("p90", stats)
            self.assertIn("latBin", summary["group_means"])
            self.assertIn("sizeId", summary["group_means"])
            self.assertIn("setIdx", summary["group_means"])
            self.assertIn("transpose", summary["group_means"])
            self.assertGreater(summary["mode_group_qp_repetition"]["base_keys"], 0)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
