#include "source/Lib/EncoderLib/Rc360Uprop.h"

#include <cassert>
#include <cmath>
#include <vector>

int main()
{
  Rc360Uprop::Config cfg;
  cfg.enabled = true;
  cfg.normMin = 0.7;
  cfg.normMax = 1.5;

  std::vector<Rc360Uprop::CoreFrameInput> frames(2);
  frames[0].poc = 0;
  frames[0].u0 = { 1.0, 2.0 };
  frames[1].poc = 1;
  frames[1].u0 = { 4.0, 8.0 };
  frames[1].legalRefPocs = { 0 };

  std::vector<Rc360Uprop::CoreEdge> edges;
  edges.push_back({ 0, 0, 1, 1, 0.5 });
  edges.push_back({ 1, 0, 0, 0, 100.0 });

  const auto result = Rc360Uprop::solveCoreForTest(frames, edges, cfg);

  assert(result.frames.size() == 2);
  assert(result.frames[0].ctus.size() == 2);
  assert(std::fabs(result.frames[0].ctus[0].raw - 5.0) < 1e-9);
  assert(std::fabs(result.frames[0].ctus[1].raw - 2.0) < 1e-9);
  assert(std::fabs(result.frames[1].ctus[1].raw - 8.0) < 1e-9);

  assert(std::fabs(result.frames[0].medianRaw - 3.5) < 1e-9);
  assert(std::fabs(result.frames[0].ctus[0].norm - (5.0 / 3.5)) < 1e-9);
  assert(std::fabs(result.frames[0].ctus[1].norm - 0.7) < 1e-9);

  Rc360Uprop::Config u0OnlyCfg = cfg;
  u0OnlyCfg.ctuSignalMode = 1;
  const auto u0Only = Rc360Uprop::solveCoreForTest(frames, edges, u0OnlyCfg);
  assert(std::fabs(u0Only.frames[0].ctus[0].raw - 1.0) < 1e-9);
  assert(std::fabs(u0Only.frames[0].ctus[1].raw - 2.0) < 1e-9);
  assert(std::fabs(u0Only.frames[1].ctus[0].raw - 4.0) < 1e-9);

  Rc360Uprop::Config excessOnlyCfg = cfg;
  excessOnlyCfg.ctuSignalMode = 2;
  const auto excessOnly = Rc360Uprop::solveCoreForTest(frames, edges, excessOnlyCfg);
  assert(std::fabs(excessOnly.frames[0].ctus[0].raw - 4.0) < 1e-9);
  assert(std::fabs(excessOnly.frames[0].ctus[1].raw - 1e-9) < 1e-12);
  assert(std::fabs(excessOnly.frames[1].ctus[0].norm - 1.0) < 1e-9);
  assert(std::fabs(excessOnly.frames[1].ctus[1].norm - 1.0) < 1e-9);

  assert(std::fabs(Rc360Uprop::dependencyDelta(0.25, 1.0, 0.35, 1.20) - 1.0) < 1e-9);
  assert(std::fabs(Rc360Uprop::dependencyDelta(1.20, 1.0, 0.35, 1.20)) < 1e-9);
  assert(std::fabs(Rc360Uprop::sphericalU0(240, 480) - 1.0) < 1e-4);

  assert(Rc360Uprop::windowStartForPoc(0, 8) == 0);
  assert(Rc360Uprop::windowStartForPoc(7, 8) == 0);
  assert(Rc360Uprop::windowStartForPoc(8, 8) == 8);
  assert(Rc360Uprop::windowStartForPoc(15, 8) == 8);

  // A non-overlapping propagation window must be immutable after its first analysis.
  Rc360Uprop cache;
  cache.init(cfg);
  assert(cache.beginWindow(0, 7));
  assert(!cache.beginWindow(0, 7));
  assert(cache.beginWindow(8, 15));

  const auto legal = Rc360Uprop::selectLegalReferenceFramesForTest(
    { 0, 1, 2, 3 }, 3, { 0, 2, 99 }
  );
  assert(legal.size() == 2);
  assert(legal[0] == 0);
  assert(legal[1] == 2);

  return 0;
}
