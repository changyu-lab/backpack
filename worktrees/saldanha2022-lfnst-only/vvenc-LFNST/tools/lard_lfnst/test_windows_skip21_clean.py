from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.lard_lfnst import run_windows_skip21_clean


def fake_job_summary() -> dict[str, object]:
    return {
        "paired_timing": {
            "overall": {
                "median_TS_pct": 1.0,
                "mean_TS_pct": 1.0,
                "std_TS_pct": 0.0,
                "min_TS_pct": 1.0,
                "max_TS_pct": 1.0,
                "positive_repeats": 1,
                "repeats": 1,
            }
        },
        "metrics": {
            "CPP_Y_BDBR_pct": 0.1,
            "WS_Y_BDBR_pct": 0.2,
            "S_Y_BDBR_pct": 0.3,
            "ORD_Y_BDBR_pct": 0.4,
            "CPP_YUV_BDBR_pct": 0.5,
            "ByteDelta_pct": 0.6,
        },
    }


class WindowsSkip21CleanTests(unittest.TestCase):
    def test_main_runs_lfnst_off_8f5_and_records_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            encoder = root / "vvencFFapp.exe"
            sphere = root / "sphere.txt"
            orig = root / "AerialCity_3840x1920_30fps_8bit_420_erp.yuv"
            out_root = root / "out"
            encoder.write_text("encoder", encoding="utf-8")
            sphere.write_text("sphere", encoding="utf-8")
            orig.write_text("orig", encoding="utf-8")
            argv = [
                "prog",
                "--encoder",
                str(encoder),
                "--orig",
                str(orig),
                "--sphere-file",
                str(sphere),
                "--out-root",
                str(out_root),
                "--qps",
                "22",
            ]

            calls: list[tuple[str, int, int, str]] = []

            def fake_run_job(
                name: str,
                args: object,
                orig_path: Path,
                frames: int,
                repeats: int,
                target_profile: int,
                proposed_additional: str,
            ) -> dict[str, object]:
                calls.append((name, frames, repeats, proposed_additional))
                return fake_job_summary()

            with patch("sys.argv", argv), patch.object(
                run_windows_skip21_clean, "run_job", side_effect=fake_run_job
            ):
                with redirect_stdout(io.StringIO()):
                    run_windows_skip21_clean.main()

            self.assertIn(("LFNST_OFF_8f5", 8, 5, "LFNST=0"), calls)
            summary = json.loads(
                (out_root / "clean_windows_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["configuration"]["lfnst_off_additional"], "LFNST=0")
            self.assertIn("LFNST_OFF_8f5", summary["jobs"])


if __name__ == "__main__":
    unittest.main()
