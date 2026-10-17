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
    double beta           = 0.20;

    double wMin           = 0.70;
    double wMax           = 1.35;

    double dtarScale      = 1.00;
    double dtarIeffScale  = 0.10;

    int    maxStoredRefPics = 16;
  };

  LatFbTempComp();

  void init(const Config& cfg);
  void clear();

  bool isEnabled() const { return m_cfg.enabled; }

  void recordPictureDistortion(Picture* pic);

  void preAnalyzePicture(Picture* pic, Slice* slice, double frameLambda, int frameQP);

  bool   hasCurrentPictureWeights() const { return !m_ctuWeights.empty(); }
  double getCtuWeight(int ctuRsAddr) const;
  double getCtuWrefRawUnclipped(int ctuRsAddr) const;
  double getCtuWrefRawClipped(int ctuRsAddr) const;
  double getCtuWrefNormUnclipped(int ctuRsAddr) const;
  double getCtuWrefNormClipped(int ctuRsAddr) const;
  double getFrameWrefRawUnclipped() const { return m_frameWrefRawUnclipped; }
  double getFrameWrefRawClipped() const { return m_frameWrefRawClipped; }
  double getFrameWrefNormUnclippedMean() const { return m_frameWrefNormUnclippedMean; }
  double getFrameWrefNormClippedMean() const { return m_frameWrefNormClippedMean; }
  double getFrameWrefFinalMean() const { return m_frameWrefFinalMean; }
  double getCtuIeff  (int ctuRsAddr) const;
  double getCtuDref  (int ctuRsAddr) const;
  double getCtuDtar  (int ctuRsAddr) const;

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
  double calcCtuIeffFromSamePosRefs(Picture* curPic, Slice* slice, const CompArea& curArea, int ctuRsAddr) const;
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
  std::vector<double> m_ctuWrefRawUnclipped;
  std::vector<double> m_ctuWrefRawClipped;
  std::vector<double> m_ctuWrefNormUnclipped;
  std::vector<double> m_ctuWrefNormClipped;
  std::vector<double> m_ctuIeff;
  std::vector<double> m_ctuDref;
  std::vector<double> m_ctuDtar;

  double m_frameWrefRawUnclipped = 1.0;
  double m_frameWrefRawClipped = 1.0;
  double m_frameWrefNormUnclippedMean = 1.0;
  double m_frameWrefNormClippedMean = 1.0;
  double m_frameWrefFinalMean = 1.0;
};

#endif
