from __future__ import annotations

import unittest
from pathlib import Path

from tools.lard_lfnst import run_skip21_stage2_validation as runner


ROOT = Path(__file__).resolve().parents[2]


class Skip21Stage2ValidationTests(unittest.TestCase):
    def test_profiles_define_stage2_only_and_joint_modes(self) -> None:
        self.assertIn("S2_D1_only", runner.PROFILES)
        self.assertIn("S2_D2_only", runner.PROFILES)
        self.assertIn("S2_D3_only", runner.PROFILES)
        self.assertIn("S12_E15_noLat_D1", runner.PROFILES)
        self.assertIn("S12_E15_noLat_D2", runner.PROFILES)
        self.assertIn("LardLfnst21Stages=2", runner.PROFILES["S2_D1_only"])
        self.assertIn("LardLfnst21Stages=3", runner.PROFILES["S12_E15_noLat_D1"])
        self.assertIn("LardLfnst21Profile=6", runner.PROFILES["S12_E15_noLat_D1"])
        self.assertIn("LardLfnst21Stage2Profile=2", runner.PROFILES["S2_D3_only"])
        self.assertEqual(runner.DEFAULT_PROFILES, "S2_D1_only,S2_D2_only,S2_D3_only")

    def test_timing_command_uses_named_profile_additional(self) -> None:
        cmd = runner.timing_command(
            encoder="vvencFFapp",
            orig="input.yuv",
            sphere_file="sphere.tsv",
            out_root="out",
            qps=[22, 27],
            threads=20,
            preset="medium",
            profile_name="S2_D2_only",
            frames=8,
            repeats=5,
        )

        self.assertIn("--proposed-additional", cmd)
        additional = cmd[cmd.index("--proposed-additional") + 1]
        self.assertIn("LardLfnst21Stages=2", additional)
        self.assertIn("LardLfnst21Stage2Profile=1", additional)
        target_profile = cmd[cmd.index("--target-profile") + 1]
        self.assertEqual(target_profile, "0")

    def test_server_script_runs_stage2_runner_and_cleans_large_outputs(self) -> None:
        script = (ROOT / "tools/server_run_skip21_stage2_validation.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("tools.lard_lfnst.run_skip21_stage2_validation", script)
        self.assertIn("skip21_stage2_validation", script)
        self.assertIn("-name '*_rec.yuv' -o -name '*.vvc'", script)


if __name__ == "__main__":
    unittest.main()
