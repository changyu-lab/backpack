/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 */

#ifndef __RC360_PAPER_TI__
#define __RC360_PAPER_TI__

#include "CommonLib/Picture.h"
#include "CommonLib/Unit.h"

#include <map>
#include <set>
#include <utility>
#include <vector>

class Rc360PaperTI
{
public:
  struct Config
  {
    bool enabled = false;
    bool frameEnabled = true;
    bool ctuEnabled = true;
    bool verbose = true;
    int  blockSize = 32;
    int  searchRange = 16;
    int  searchStep = 4;
    int  frameSignalMode = 0; // 0=raw TI, 1=linear de-depth residual
    bool frameLogNeutral = true;
    bool ctuRateNeutral = true;
    int  ctuDqpDeltaMax = 1;
    double frameNormMin = 0.70;
    double frameNormMax = 1.30;
    double frameLambdaMin = 0.95;
    double frameLambdaMax = 1.05;
    double ctuNormMin = 0.50;
    double ctuNormMax = 2.00;
  };

  struct CoreCtuResult
  {
    double complexity = 1.0;
    double tau = 1.0;
    double importance = 1.0;
    double dqpFloat = 0.0;
    double neutralDqpFloat = 0.0;
    int dqp = 0;
  };

  struct CoreFrameInput
  {
    int poc = -1;
    std::vector<double> ctuComplexity;
    std::vector<int> legalRefPocs;
  };

  struct AnalysisFrame
  {
    int poc = -1;
    CPelBuf luma;
    int ctuWidth = 0;
    int ctuHeight = 0;
    std::vector<int> legalRefPocs;
  };

  struct CoreFrameResult
  {
    int poc = -1;
    double rawFrameImportance = 1.0;
    double frameImportance = 1.0;
    double frameLambdaRatio = 1.0;
    double medianCtuImportance = 1.0;
    double minCtuImportance = 1.0;
    double maxCtuImportance = 1.0;
    double ctuTP10 = 1.0;
    double ctuTP50 = 1.0;
    double ctuTP90 = 1.0;
    double ctuDqpFloatP10 = 0.0;
    double ctuDqpFloatP50 = 0.0;
    double ctuDqpFloatP90 = 0.0;
    double meanCtuLambdaRatio = 1.0;
    double predBitsDeltaSum = 0.0;
    int dqpClipCount = 0;
    int dqpHist[5] = { 0, 0, 0, 0, 0 };
    int edgeCount = 0;
    std::vector<CoreCtuResult> ctus;
  };

  struct CoreEdge
  {
    int fromFrame = -1;
    int fromCtu = -1;
    int toFrame = -1;
    int toCtu = -1;
    double weight = 0.0;
  };

  struct CoreResult
  {
    std::vector<CoreFrameResult> frames;
  };

  void init(const Config& cfg);
  void clear();

  bool isEnabled() const { return m_cfg.enabled; }
  bool frameEnabled() const { return m_cfg.enabled && m_cfg.frameEnabled; }
  bool ctuEnabled() const { return m_cfg.enabled && m_cfg.ctuEnabled; }

  bool beginWindow(int startPoc, int endPoc);
  void analyzeWindow(int startPoc, int endPoc, const std::vector<AnalysisFrame>& frames);
  void storeCoreResult(int startPoc, int endPoc, const CoreResult& result);

  bool hasPicture(int poc) const;
  double getFrameImportance(int poc) const;
  double getFrameLambdaRatio(int poc) const;
  double getCtuImportance(int poc, int ctuRsAddr) const;
  int getCtuDqp(int poc, int ctuRsAddr) const;

  static CoreResult solveCoreForTest(const std::vector<CoreFrameInput>& frames,
                                     const std::vector<CoreEdge>& edges,
                                     const Config& cfg);
  static double dependencyDelta(double predComplexity, double intraComplexity);
  static int windowStartForPoc(int poc, int gopSize);

private:
  struct SearchResult
  {
    int frameIdx = -1;
    int rx = 0;
    int ry = 0;
    double predComplexity = 0.0;
  };

  static double clipDouble(double v, double lo, double hi);
  static double median(std::vector<double> values, double fallback);
  static uint64_t satdDiffArea(const CPelBuf& org, int ox, int oy,
                               const CPelBuf& pred, int px, int py,
                               int w, int h);
  static uint64_t satdIntraArea(const CPelBuf& org, int x, int y, int w, int h);

  SearchResult searchPreviousFrames(const std::vector<AnalysisFrame>& frames,
                                    int futureFrameIdx,
                                    int x,
                                    int y,
                                    int width,
                                    int height,
                                    double intraComplexity) const;

private:
  Config m_cfg;
  std::map<int, CoreFrameResult> m_framesByPoc;
  std::set<std::pair<int, int>> m_analyzedWindows;
};

#endif
