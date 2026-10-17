#ifndef __LAT_FB_TEMP_COMP__
#define __LAT_FB_TEMP_COMP__

#include "CommonLib/CommonDef.h"
#include "CommonLib/Picture.h"
#include "CommonLib/Slice.h"
#include "CommonLib/Unit.h"

#include <vector>
#include <map>
#include <cmath>
#include <cstdint>
#include <algorithm>
#include <limits>
#include <string>

#ifndef RC360_FB_TC_IEFF
#define RC360_FB_TC_IEFF 1
#endif

class LatFbTempComp
{
public:
  struct Config
  {
    bool   enabled        = false;
    bool   verbose        = true;

    int    searchRange    = 16;
    int    searchStep     = 4;

    double tauLow         = 0.35;
    double tauHigh        = 1.20;
    double kappa          = 0.50;
    double beta           = 0.20;   // Wref feedback strength, not the Ieff gate.

    double ieffTau        = 0.20;
    double ieffEta        = 0.85;
    double ieffMinCos     = 1e-6;
    bool   ieffUseLog2    = true;

    double wMin           = 0.25;
    double wMax           = 4.00;

    double dtarScale      = 1.00;
    double dtarIeffScale  = 0.10;

    // New Wref parameters.
    double wrefAlpha      = 0.50;
    double wrefGamma      = 0.50;

    // Recommended default for WS-BDBR-oriented RC:
    bool   useWsDrec      = true;
    bool   useSphericalW  = false;
    double sphericalGamma = 0.50;

    int    maxStoredRefPics = 16;
  };

  LatFbTempComp();

  void init(const Config& cfg);
  void clear();

  bool isEnabled() const { return m_cfg.enabled; }

  void recordPictureDistortion(Picture* pic);

  void preAnalyzePicture(Picture* pic, Slice* slice, double frameLambda, int frameQP);

  bool   hasCurrentPictureWeights() const { return !m_ctuWeights.empty(); }
  bool   hasCurrentWrefStats() const { return m_currentWrefStatsValid; }
  double getCtuWeight(int ctuRsAddr) const;
  double getCtuIeff  (int ctuRsAddr) const;
  double getCtuModelIeff(int ctuRsAddr) const;
  double getCtuNewIeffFormulaRaw(int ctuRsAddr) const;
  double getCtuOldIeffFormulaRaw(int ctuRsAddr) const;
  double getCtuOldIeffModelRaw(int ctuRsAddr) const;
  double getCtuOldIeffNorm(int ctuRsAddr) const;
  double getCtuDref  (int ctuRsAddr) const;
  double getCtuDtar  (int ctuRsAddr) const;
  double getCtuDrec  (Picture* pic, int ctuRsAddr) const;
  std::string getCtuRefDrecList(int ctuRsAddr) const;
  double getCurrentMeanWref() const { return m_currentMeanWref; }
  double getCurrentCtuFrameDemand() const { return m_currentCtuFrameDemand; }
  double getCurrentMeanDref() const { return m_currentMeanDref; }
  double getCurrentP75Dref() const { return m_currentP75Dref; }
  double getCurrentFrameRisk() const { return m_currentFrameRisk; }
  double getCurrentFrameIeffRawMean() const { return m_currentFrameIeffRawMean; }
  double getHistoricalFrameIeffRawMean() const;
  int    getHistoricalFrameIeffCount() const { return m_frameIeffHistCount; }
  double getHistoricalMeanWref() const;
  double getHistoricalCtuFrameDemand() const;
  double getHistoricalFrameDrec() const;
  int    getHistoricalWrefCount() const { return m_wrefHistCount; }

private:
  struct RefDistPic
  {
    int poc          = -1;
    int widthInCtus  = 0;
    int heightInCtus = 0;
    int ctuW         = 0;
    int ctuH         = 0;
    int picW         = 0;
    int picH         = 0;

    std::vector<double> ctuMse;
  };

  struct Candidate
  {
    int refPoc = -1;
    int refIdx = -1;
    int listId = 0;

    int rx = 0;
    int ry = 0;
    int mvx = 0;
    int mvy = 0;

    double interCost = 0.0;
    double refDist   = 0.0;
    double delta     = 0.0;
    double eta       = 0.0;
    double dep       = 0.0;
  };

private:
  double calcCtuMse8bitNorm(Picture* pic, const CompArea& area) const;

  Candidate searchOneReference(
    Picture* curPic,
    Picture* refPic,
    int      listId,
    int      refIdx,
    const CompArea& curArea,
    double   intraCost,
    double   phi
  ) const;

  uint64_t satdDiff(const CPelBuf& org, const CPelBuf& ref) const;
  uint64_t sadPartial(const CPelBuf& a, const CPelBuf& b, int w, int h) const;
  uint64_t simpleIntraCost(const CPelBuf& org) const;

  double calcWeightedRefDist(int refPoc, int x, int y, int w, int h) const;
  double calcLatitudeRad(int yCenter, int picH) const;

#if RC360_FB_TC_IEFF
  double calcCtuIeffFromBestRefBlocks(Picture* curPic, Slice* slice, const CompArea& curArea, int ctuRsAddr, const std::vector<Candidate>& candList, double* oldIeffOut = nullptr) const;
#endif
  double calcSimpleIeffProxy(const CPelBuf& org, double phi) const;
  double calcTargetDistortion(int qp, double ieff) const;

  static double clipDouble(double v, double lo, double hi)
  {
    return v < lo ? lo : (v > hi ? hi : v);
  }

private:
  Config m_cfg;

  std::map<int, RefDistPic> m_refDistPics;

  std::vector<double> m_ctuWeights;
  std::vector<double> m_ctuIeff;
  std::vector<double> m_ctuModelIeff;
  std::vector<double> m_ctuNewIeffFormulaRaw;
  std::vector<double> m_ctuOldIeffFormulaRaw;
  std::vector<double> m_ctuOldIeffModelRaw;
  std::vector<double> m_ctuOldIeffNorm;
  std::vector<double> m_ctuDref;
  std::vector<double> m_ctuDtar;
  std::vector<std::string> m_ctuRefDrecList;

  double m_currentMeanWref = 1.0;
  double m_currentCtuFrameDemand = 1.0;
  double m_currentMeanDref = 0.0;
  double m_currentP75Dref = 0.0;
  double m_currentFrameRisk = 0.0;
  double m_currentFrameIeffRawMean = 1.0;
  bool   m_currentFrameIeffHistoryEligible = false;
  bool   m_currentWrefStatsValid = false;
  int    m_currentWrefPoc = -1;
  int    m_lastCommittedWrefPoc = -1;
  double m_wrefHistSum = 0.0;
  double m_ctuFrameDemandHistSum = 0.0;
  double m_frameDrecHistSum = 0.0;
  int    m_frameDrecHistCount = 0;
  double m_frameIeffHistSum = 0.0;
  int    m_frameIeffHistCount = 0;
  int    m_wrefHistCount = 0;
};

#endif
