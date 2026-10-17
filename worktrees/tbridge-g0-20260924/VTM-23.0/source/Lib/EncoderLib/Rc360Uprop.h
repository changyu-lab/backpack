/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 */

#ifndef __RC360_UPROP__
#define __RC360_UPROP__

#include "CommonLib/Picture.h"
#include "CommonLib/Unit.h"

#include <map>
#include <set>
#include <utility>
#include <vector>

class Rc360Uprop
{
public:
  struct Config
  {
    bool   enabled = false;
    bool   frameEnabled = false;
    bool   ctuEnabled = false;
    bool   verbose = true;
    int    ctuSignalMode = 0;
    int    searchRange = 16;
    int    searchStep = 4;
    double tauLow = 0.35;
    double tauHigh = 1.20;
    double alpha = 0.30;
    double beta = 0.20;
    double normMin = 0.70;
    double normMax = 1.50;
    double frameMin = 0.95;
    double frameMax = 1.05;
  };

  struct CoreCtuResult
  {
    double u0 = 1.0;
    double raw = 1.0;
    double norm = 1.0;
  };

  struct CoreFrameInput
  {
    int poc = -1;
    std::vector<double> u0;
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
    double meanRaw = 1.0;
    double medianRaw = 1.0;
    double minNorm = 1.0;
    double maxNorm = 1.0;
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
  void commitPicture(int poc);

  bool hasPicture(int poc) const;
  double getCtuNorm(int poc, int ctuRsAddr) const;
  double getCtuScale(int poc, int ctuRsAddr) const;
  double getFrameMeanRaw(int poc) const;
  double getFramePi(int poc) const;
  double getHistoricalFrameMeanRaw() const;
  int getHistoricalFrameCount() const { return m_histCount; }

  static CoreResult solveCoreForTest(const std::vector<CoreFrameInput>& frames,
                                     const std::vector<CoreEdge>& edges,
                                     const Config& cfg);
  static int windowStartForPoc(int poc, int gopSize);
  static std::vector<int> selectLegalReferenceFramesForTest(const std::vector<int>& framePocs,
                                                            int futureFrameIdx,
                                                            const std::vector<int>& legalRefPocs);
  static double dependencyDelta(double interCost, double intraCost, double tauLow, double tauHigh);
  static double sphericalU0(int yCenter, int picH);

private:
  struct SearchResult
  {
    int frameIdx = -1;
    int rx = 0;
    int ry = 0;
    double interCost = 0.0;
    double delta = 0.0;
  };

  static double clipDouble(double v, double lo, double hi);
  static double median(std::vector<double> values, double fallback);
  static uint64_t sadPartial(const CPelBuf& a, const CPelBuf& b, int w, int h);
  static uint64_t sadDiff(const CPelBuf& org, const CPelBuf& ref);
  static uint64_t simpleIntraCost(const CPelBuf& org);

  SearchResult searchPreviousFrames(const std::vector<AnalysisFrame>& frames,
                                      int futureFrameIdx,
                                      int x,
                                      int y,
                                      int width,
                                      int height,
                                      double intraCost) const;
  void addOverlapEdgesForReferenceArea(const AnalysisFrame& refFrame,
                                       int refFrameIdx,
                                       int toFrameIdx,
                                       int toCtu,
                                       int rx,
                                       int ry,
                                       int w,
                                       int h,
                                       double delta,
                                       std::vector<CoreEdge>& edges) const;

private:
  Config m_cfg;
  std::map<int, CoreFrameResult> m_framesByPoc;
  std::set<std::pair<int, int>> m_analyzedWindows;
  double m_histSum = 0.0;
  int m_histCount = 0;
};

#endif
