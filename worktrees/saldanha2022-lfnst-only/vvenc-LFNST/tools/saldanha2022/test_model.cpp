#include "SaldanhaLfnst.h"
#include <cassert>
#include <fstream>
#include <limits>
#include <iostream>

int main()
{
  { std::ofstream o("tiny.model"); o << "LFNST_REPTREE_V1 13 3\n0 0 8 1 2 0.5 0.5 0.5\n1 -1 0 -1 -1 0 1 0\n2 -1 0 -1 -1 0 0 1\n"; }
  saldanha::Model m("tiny.model");
  saldanha::Features f{};
  f[0] = 7.999999999999;
  assert(m.skip(f));
  f[0] = 8;
  assert(!m.skip(f));
  f[0] = std::numeric_limits<double>::quiet_NaN();
  assert(!m.skip(f));
  f[0] = 1; f[7] = std::numeric_limits<double>::infinity();
  assert(!m.skip(f));
  { std::ofstream o("bad.model"); o << "LFNST_REPTREE_V1 13 1\n0 0 8 0 0 0.5 0.5 0.5\n"; }
  bool threw = false;
  try { saldanha::Model bad("bad.model"); } catch (const std::exception&) { threw = true; }
  assert(threw);
  { std::ofstream o("tie.model"); o << "LFNST_REPTREE_V1 13 1\n0 -1 0 -1 -1 0 0.5 0.5\n"; }
  saldanha::Model tie("tie.model");
  f.fill(0); assert(tie.skip(f));
  std::cout << "PASS: numeric boundaries, class tie, nonfinite fail-open, malformed tree\n";
}
