#include "source/Lib/EncoderLib/Rc360PaperTI.h"

#include <cstdlib>
#include <cmath>
#include <iostream>
#include <vector>

int main()
{
  auto require = [](bool condition, const char* message)
  {
    if (!condition)
    {
      std::cerr << message << "\n";
      std::exit(1);
    }
  };

  Rc360PaperTI::Config cfg;
  cfg.enabled = true;
  cfg.ctuNormMin = 0.50;
  cfg.ctuNormMax = 2.00;
  cfg.frameNormMin = 0.50;
  cfg.frameNormMax = 2.00;
  cfg.frameLambdaMin = 0.95;
  cfg.frameLambdaMax = 1.05;
  cfg.frameLogNeutral = true;
  cfg.ctuRateNeutral = true;
  cfg.ctuDqpDeltaMax = 1;

  require(std::fabs(Rc360PaperTI::dependencyDelta(25.0, 100.0) - 0.75) < 1e-9, "delta basic");
  require(std::fabs(Rc360PaperTI::dependencyDelta(120.0, 100.0)) < 1e-12, "delta clamp high");
  require(std::fabs(Rc360PaperTI::dependencyDelta(10.0, 0.0)) < 1e-12, "delta zero intra");

  std::vector<Rc360PaperTI::CoreFrameInput> frames(3);
  frames[0].poc = 0;
  frames[0].ctuComplexity = { 20.0, 10.0 };
  frames[1].poc = 1;
  frames[1].ctuComplexity = { 30.0, 40.0 };
  frames[1].legalRefPocs = { 0 };
  frames[2].poc = 2;
  frames[2].ctuComplexity = { 50.0, 60.0 };
  frames[2].legalRefPocs = { 1 };

  std::vector<Rc360PaperTI::CoreEdge> edges;
  edges.push_back({ 0, 0, 1, 1, 0.50 });
  edges.push_back({ 1, 1, 2, 0, 0.25 });
  edges.push_back({ 0, 1, 2, 0, 10.0 }); // ignored: POC0 is not legal for POC2

  const auto result = Rc360PaperTI::solveCoreForTest(frames, edges, cfg);
  require(result.frames.size() == 3, "frame count");
  require(std::fabs(result.frames[2].ctus[0].tau - 1.0) < 1e-12, "tau frame2");
  require(std::fabs(result.frames[1].ctus[1].tau - 1.25) < 1e-12, "tau frame1");
  require(std::fabs(result.frames[0].ctus[0].tau - 1.625) < 1e-12, "tau frame0");
  require(std::fabs(result.frames[0].ctus[1].tau - 1.0) < 1e-12, "illegal edge ignored");

  // T_i,M is C-aware: the same tau gives stronger CTU weight when complexity is higher.
  require(result.frames[0].ctus[0].importance > 1.0, "ctu importance high");
  require(result.frames[1].ctus[1].importance > result.frames[1].ctus[0].importance, "complexity aware");
  require(result.frames[0].frameImportance > result.frames[2].frameImportance, "frame importance order");

  double logFrameLambdaSum = 0.0;
  double maxAbsFrameLambdaLog = 0.0;
  int frameLambdaCount = 0;
  for (const auto& frame: result.frames)
  {
    if (frame.poc > 0)
    {
      require(frame.frameLambdaRatio >= cfg.frameLambdaMin - 1e-12, "frame lambda lower bound");
      require(frame.frameLambdaRatio <= cfg.frameLambdaMax + 1e-12, "frame lambda upper bound");
      logFrameLambdaSum += std::log(frame.frameLambdaRatio);
      maxAbsFrameLambdaLog = std::max(maxAbsFrameLambdaLog, std::fabs(std::log(frame.frameLambdaRatio)));
      frameLambdaCount++;
    }
  }
  require(frameLambdaCount > 0, "frame lambda active count");
  require(std::fabs(logFrameLambdaSum / double(frameLambdaCount)) < 1e-12, "frame lambda log neutral");
  require(maxAbsFrameLambdaLog > 1e-6, "frame lambda should change");

  bool sawNonZeroDqp = false;
  for (const auto& frame: result.frames)
  {
    int dqpSum = 0;
    for (const auto& ctu: frame.ctus)
    {
      require(ctu.dqp >= -cfg.ctuDqpDeltaMax, "ctu dqp lower bound");
      require(ctu.dqp <= cfg.ctuDqpDeltaMax, "ctu dqp upper bound");
      sawNonZeroDqp = sawNonZeroDqp || ctu.dqp != 0;
      dqpSum += ctu.dqp;
    }
    require(std::abs(dqpSum) <= int(frame.ctus.size()), "ctu dqp approximately neutral");
  }
  require(sawNonZeroDqp, "ctu dqp should change");

  Rc360PaperTI ti;
  ti.init(cfg);
  require(ti.beginWindow(0, 7), "begin window first");
  require(!ti.beginWindow(0, 7), "begin window cache hit");
  ti.storeCoreResult(0, 7, result);
  require(ti.hasPicture(1), "stored picture");
  require(ti.getCtuImportance(1, 1) > 1.0, "stored ctu importance");
  require(ti.getCtuDqp(1, 1) >= -cfg.ctuDqpDeltaMax, "stored ctu dqp lower");
  require(ti.getCtuDqp(1, 1) <= cfg.ctuDqpDeltaMax, "stored ctu dqp upper");
  require(ti.getFrameLambdaRatio(1) >= cfg.frameLambdaMin - 1e-12, "stored frame lambda lower");
  require(ti.getFrameLambdaRatio(1) <= cfg.frameLambdaMax + 1e-12, "stored frame lambda upper");
  require(ti.getFrameImportance(100) == 1.0, "missing frame importance default");
  ti.clear();
  require(!ti.hasPicture(1), "clear picture");

  Rc360PaperTI::Config disabled = cfg;
  disabled.enabled = false;
  ti.init(disabled);
  require(ti.getCtuImportance(1, 1) == 1.0, "disabled ctu default");
  require(ti.getFrameImportance(1) == 1.0, "disabled frame default");

  return 0;
}
