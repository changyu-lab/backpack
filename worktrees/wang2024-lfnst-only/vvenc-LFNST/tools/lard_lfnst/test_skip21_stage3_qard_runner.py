import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.lard_lfnst import run_skip21_stage3_qard_shadow as shadow


class Skip21Stage3QardShadowRunnerTests(unittest.TestCase):
    def test_dry_run_uses_portable_stat_path_and_ra_no_reordering(self) -> None:
        tmp_root = Path.cwd() / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_root) as tmp_dir:
            out = io.StringIO()
            args = [
                "run_skip21_stage3_qard_shadow",
                "--encoder", "bin/release-static/vvencFFapp.exe",
                "--orig", "I:/Sequences360/AerialCity_3840x1920_30fps_8bit_420_erp.yuv",
                "--size", "3840x1920",
                "--bitdepth", "8",
                "--qps", "22",
                "--frames", "1",
                "--config", "RA",
                "--gop", "8",
                "--out-dir", str(Path(tmp_dir) / "shadow"),
                "--dry-run",
            ]
            with patch("sys.argv", args), redirect_stdout(out):
                shadow.main()

        command = out.getvalue()
        self.assertIn("--GOPSize 8", command)
        self.assertIn("--DecodingRefreshType 0", command)
        self.assertIn("--PicReordering 0", command)
        self.assertIn("--POC0IDR 1", command)
        self.assertIn("LardLfnst21Stage3RdeStatFile=", command)
        stat_arg = command.split("LardLfnst21Stage3RdeStatFile=", 1)[1].split(" ", 1)[0]
        self.assertNotIn(":", stat_arg)
        self.assertNotIn("\\", stat_arg)


if __name__ == "__main__":
    unittest.main()
