from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Skip21TheoryTableTests(unittest.TestCase):
    def test_theory_table_is_nonempty_and_carries_weak_coupling_metrics(self) -> None:
        table = (ROOT / "source/Lib/EncoderLib/LardLfnstSkip21TheoryTable.inc").read_text(
            encoding="utf-8"
        )

        self.assertIn("oxQ", table)
        self.assertIn("diagDominanceQ", table)
        match = re.search(r"#define LARD_LFNST_SKIP21_THEORY_TABLE_SIZE\s+(\d+)", table)
        self.assertIsNotNone(match)
        self.assertGreater(int(match.group(1)), 1000)
        self.assertNotIn("{ -1, -1, -1, -1, -1, -1", table)

    def test_cpp_stage2_gate_uses_ox_and_diag_dominance(self) -> None:
        source = (ROOT / "source/Lib/EncoderLib/IntraSearch.cpp").read_text(
            encoding="utf-8"
        )

        self.assertIn("int oxQ = -1;", source)
        self.assertIn("int diagDominanceQ = -1;", source)
        self.assertIn("entry.oxQ <= params.oxQ", source)
        self.assertIn("entry.diagDominanceQ >= params.diagDominanceQ", source)
        self.assertIn("return oxWeak && diagDominant && gmaxGuard;", source)
        self.assertNotIn("useDiagOr", source)
        self.assertIn("d.oxQ = entry->oxQ;", source)
        self.assertIn("d.diagDominanceQ = entry->diagDominanceQ;", source)


if __name__ == "__main__":
    unittest.main()
