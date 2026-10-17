from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Skip21ProfileContractTests(unittest.TestCase):
    def test_cpp_exposes_e12_and_e15_stage1_profiles(self) -> None:
        intra_search = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(
            encoding="utf-8"
        )
        cfg = (ROOT / "source/Lib/vvenc/vvencCfg.cpp").read_text(encoding="utf-8")

        self.assertIn("static constexpr LardSkip21ProfileParams params[7]", intra_search)
        self.assertIn("{ 563, 704, 192, 4 }", intra_search)
        self.assertIn("{ 666, 768, 256, 4 }", intra_search)
        self.assertIn("{ 563, 704, 192, 0 }", intra_search)
        self.assertIn("{ 666, 768, 256, 0 }", intra_search)
        self.assertIn("d.latBin >= params.minLatBin", intra_search)
        self.assertIn(
            "m_LardLfnst21Profile < 0 || c->m_LardLfnst21Profile > 6", cfg
        )


if __name__ == "__main__":
    unittest.main()
