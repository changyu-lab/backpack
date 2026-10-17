#include "LatFbTempComp.h"
#include "Rc360IbrcModel.h"
#include "Rc360Ieff.h"

#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <sstream>
#include <numeric>

namespace
{
constexpr int RC360_FB_TC_MAX_LOG_CTUS = 50;

bool shouldLogCtu(int ctuRsAddr)
{
  return ctuRsAddr >= 0 && ctuRsAddr < RC360_FB_TC_MAX_LOG_CTUS;
}

[[maybe_unused]] double rc360Percentile(std::vector<double> values, double p, double fallback)
{
  values.erase(std::remove_if(values.begin(), values.end(), [](double v) { return !std::isfinite(v); }), values.end());
  if (values.empty())
  {
    return fallback;
  }
  std::sort(values.begin(), values.end());
  const double pos = std::max(0.0, std::min(1.0, p)) * double(values.size() - 1);
  const int lo = int(std::floor(pos));
  const int hi = std::min(int(values.size()) - 1, lo + 1);
  const double frac = pos - double(lo);
  return values[lo] * (1.0 - frac) + values[hi] * frac;
}

[[maybe_unused]] double rc360MeanFinite(const std::vector<double>& values, double fallback)
{
  double sum = 0.0;
  int count = 0;
  for (double v : values)
  {
    if (std::isfinite(v))
    {
      sum += v;
      count++;
    }
  }
  return count > 0 ? sum / double(count) : fallback;
}

[[maybe_unused]] double rc360StdFinite(const std::vector<double>& values, double mean)
{
  double sum2 = 0.0;
  int count = 0;
  for (double v : values)
  {
    if (std::isfinite(v))
    {
      const double d = v - mean;
      sum2 += d * d;
      count++;
    }
  }
  return count > 0 ? std::sqrt(std::max(0.0, sum2 / double(count))) : 0.0;
}

[[maybe_unused]] int rc360EnvInt(const char* name, int fallback)
{
  const char* v = std::getenv(name);
  if (v == nullptr || *v == '\0')
  {
    return fallback;
  }
  try
  {
    return std::stoi(v);
  }
  catch (...)
  {
    return fallback;
  }
}

[[maybe_unused]] double rc360EnvDouble(const char* name, double fallback)
{
  const char* v = std::getenv(name);
  if (v == nullptr || *v == '\0')
  {
    return fallback;
  }
  try
  {
    const double parsed = std::stod(v);
    return std::isfinite(parsed) ? parsed : fallback;
  }
  catch (...)
  {
    return fallback;
  }
}

#if RC360_FB_TC_IEFF
double computeIeffBlock16FromOrgAndPredLogged(
  const Pel* org,
  ptrdiff_t orgStride,
  const Pel* ref,
  ptrdiff_t refStride,
  double cosPhi,
  const rc360_ieff::IeffCfg& cfg,
  int poc,
  int ctuRsAddr,
  int refPoc,
  int listId,
  int refIdx,
  int blockIdx,
  int bx,
  int by)
{
  (void)poc;
  (void)ctuRsAddr;
  (void)refPoc;
  (void)listId;
  (void)refIdx;
  (void)blockIdx;
  (void)bx;
  (void)by;

  return rc360_ieff::computeIeffBlock16FromOrgAndPred(
    org, orgStride, ref, refStride, cosPhi, cfg);
}

double computeIeffBlock16OldFromOrgAndPred(
  const Pel* org,
  ptrdiff_t orgStride,
  const Pel* ref,
  ptrdiff_t refStride,
  double cosPhi,
  const rc360_ieff::IeffCfg& cfg)
{
  const double varResiRaw =
    rc360_ieff::calcResidualVariance16x16(org, orgStride, ref, refStride, cfg.sampleNorm);
#if IBRC360IeffVersion == 2
  const double varResi = varResiRaw;
#else
  const double varResi = varResiRaw / 256.0;
#endif

  if (varResi <= 0.0)
  {
    return 0.0;
  }

  cosPhi = rc360_ieff::clampd(std::fabs(cosPhi), cfg.minCos, 1.0);

  const double stretch = 1.0 / cosPhi;
  const double betaSafe = rc360_ieff::clampd(cfg.tau, 1e-9, 0.999999);
  const int uMax = std::max(0, std::min(15, int(std::floor(15.0 * cosPhi + 1e-9))));

  double blockIeff = 0.0;
  for (int v = 0; v < 16; ++v)
  {
    for (int u = 0; u < 16; ++u)
    {
      if (u > uMax)
      {
        continue;
      }
      const double rho2 = rc360_ieff::getRhoSquareN16(u, v, stretch);
      if (rho2 <= betaSafe)
      {
        continue;
      }

      const double coeffWeight = rc360_coeff::DCT2_RURV_N16_RHO060[v][u];
      const double coeffEnergy = varResi * coeffWeight;
      const double targetEnergy = cosPhi * coeffEnergy;
      const double denom = betaSafe * std::max(1.0 - rho2, cfg.eps);
      const double gammaStar = std::max(0.0, (rho2 - betaSafe) / denom);
      const double iHat = 0.5 * std::log2(1.0 + gammaStar);
      blockIeff += targetEnergy * iHat;
    }
  }

  return blockIeff;
}
#endif
} // namespace

LatFbTempComp::LatFbTempComp()
{
}

void LatFbTempComp::init(const Config& cfg)
{
  m_cfg = cfg;
}

void LatFbTempComp::clear()
{
  m_refDistPics.clear();
  m_ctuWeights.clear();
  m_ctuIeff.clear();
  m_ctuModelIeff.clear();
  m_ctuNewIeffFormulaRaw.clear();
  m_ctuOldIeffFormulaRaw.clear();
  m_ctuOldIeffModelRaw.clear();
  m_ctuOldIeffNorm.clear();
  m_ctuDref.clear();
  m_ctuDtar.clear();
  m_ctuRefDrecList.clear();
  m_currentMeanWref = 1.0;
  m_currentCtuFrameDemand = 1.0;
  m_currentMeanDref = 0.0;
  m_currentP75Dref = 0.0;
  m_currentFrameRisk = 0.0;
  m_currentFrameIeffRawMean = 1.0;
  m_currentFrameIeffHistoryEligible = false;
  m_currentWrefStatsValid = false;
  m_currentWrefPoc = -1;
  m_lastCommittedWrefPoc = -1;
  m_wrefHistSum = 0.0;
  m_ctuFrameDemandHistSum = 0.0;
  m_frameDrecHistSum = 0.0;
  m_frameDrecHistCount = 0;
  m_frameIeffHistSum = 0.0;
  m_frameIeffHistCount = 0;
  m_wrefHistCount = 0;
}

double LatFbTempComp::getCtuWeight(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWeights.size())
  {
    return 1.0;
  }
  return m_ctuWeights[ctuRsAddr];
}

double LatFbTempComp::getCtuIeff(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuIeff.size())
  {
    return 0.0;
  }
  return m_ctuIeff[ctuRsAddr];
}

double LatFbTempComp::getCtuModelIeff(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuModelIeff.size())
  {
    return getCtuIeff(ctuRsAddr);
  }
  return m_ctuModelIeff[ctuRsAddr];
}

double LatFbTempComp::getCtuNewIeffFormulaRaw(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuNewIeffFormulaRaw.size())
  {
    return 0.0;
  }
  return m_ctuNewIeffFormulaRaw[ctuRsAddr];
}

double LatFbTempComp::getCtuOldIeffFormulaRaw(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuOldIeffFormulaRaw.size())
  {
    return 0.0;
  }
  return m_ctuOldIeffFormulaRaw[ctuRsAddr];
}

double LatFbTempComp::getCtuOldIeffModelRaw(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuOldIeffModelRaw.size())
  {
    return 0.0;
  }
  return m_ctuOldIeffModelRaw[ctuRsAddr];
}

double LatFbTempComp::getCtuOldIeffNorm(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuOldIeffNorm.size())
  {
    return 0.0;
  }
  return m_ctuOldIeffNorm[ctuRsAddr];
}

double LatFbTempComp::getCtuDref(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuDref.size())
  {
    return 0.0;
  }
  return m_ctuDref[ctuRsAddr];
}

double LatFbTempComp::getCtuDtar(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuDtar.size())
  {
    return 1.0;
  }
  return m_ctuDtar[ctuRsAddr];
}

double LatFbTempComp::getCtuDrec(Picture* pic, int ctuRsAddr) const
{
  if (pic == nullptr || pic->cs == nullptr || pic->cs->pcv == nullptr || ctuRsAddr < 0)
  {
    return 0.0;
  }

  const PreCalcValues& pcv = *pic->cs->pcv;
  if (ctuRsAddr >= pcv.sizeInCtus)
  {
    return 0.0;
  }

  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const int x = ctuX * pcv.maxCUWidth;
  const int y = ctuY * pcv.maxCUHeight;
  const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
  const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);

  if (w <= 0 || h <= 0)
  {
    return 0.0;
  }

  const CompArea area(COMPONENT_Y, pcv.chrFormat, Position(x, y), Size(w, h));
  const double mse = calcCtuMse8bitNorm(pic, area);
  if (m_cfg.useWsDrec)
  {
    const double phi = calcLatitudeRad(y + h / 2, pcv.lumaHeight);
    const double cosPhi = clipDouble(std::cos(std::fabs(phi)), 1e-6, 1.0);
    return mse * cosPhi;
  }
  return mse;
}

std::string LatFbTempComp::getCtuRefDrecList(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuRefDrecList.size())
  {
    return std::string();
  }
  return m_ctuRefDrecList[ctuRsAddr];
}

double LatFbTempComp::getHistoricalMeanWref() const
{
  return m_wrefHistCount > 0 ? m_wrefHistSum / double(m_wrefHistCount) : 1.0;
}

double LatFbTempComp::getHistoricalCtuFrameDemand() const
{
  return m_wrefHistCount > 0 ? m_ctuFrameDemandHistSum / double(m_wrefHistCount) : 1.0;
}

double LatFbTempComp::getHistoricalFrameDrec() const
{
  return m_frameDrecHistCount > 0 ? m_frameDrecHistSum / double(m_frameDrecHistCount) : 0.0;
}

double LatFbTempComp::getHistoricalFrameIeffRawMean() const
{
  return m_frameIeffHistCount > 0 ? m_frameIeffHistSum / double(m_frameIeffHistCount) : 0.0;
}

void LatFbTempComp::recordPictureDistortion(Picture* pic)
{
  if (!m_cfg.enabled || pic == nullptr || pic->cs == nullptr || pic->cs->pcv == nullptr)
  {
    return;
  }

  const PreCalcValues& pcv = *pic->cs->pcv;

  RefDistPic rec;
  rec.poc          = pic->getPOC();
  rec.widthInCtus  = pcv.widthInCtus;
  rec.heightInCtus = pcv.heightInCtus;
  rec.ctuW         = pcv.maxCUWidth;
  rec.ctuH         = pcv.maxCUHeight;
  rec.picW         = pcv.lumaWidth;
  rec.picH         = pcv.lumaHeight;
  rec.ctuMse.assign(pcv.sizeInCtus, 0.0);

  double meanMse = 0.0;
  int validCtus = 0;

  for (int ctuY = 0; ctuY < rec.heightInCtus; ctuY++)
  {
    for (int ctuX = 0; ctuX < rec.widthInCtus; ctuX++)
    {
      const int ctuRsAddr = ctuY * rec.widthInCtus + ctuX;

      const int x = ctuX * rec.ctuW;
      const int y = ctuY * rec.ctuH;
      const int w = std::min(rec.ctuW, rec.picW - x);
      const int h = std::min(rec.ctuH, rec.picH - y);

      if (w <= 0 || h <= 0)
      {
        continue;
      }

      const CompArea area(COMPONENT_Y, pcv.chrFormat, Position(x, y), Size(w, h));
      const double mse = calcCtuMse8bitNorm(pic, area);
      if (m_cfg.useWsDrec)
      {
        const double phi = calcLatitudeRad(y + h / 2, pcv.lumaHeight);
        const double cosPhi = clipDouble(std::cos(std::fabs(phi)), 1e-6, 1.0);
        rec.ctuMse[ctuRsAddr] = mse * cosPhi;
      }
      else
      {
        rec.ctuMse[ctuRsAddr] = mse;
      }
      meanMse += rec.ctuMse[ctuRsAddr];
      validCtus++;
    }
  }

  m_refDistPics[rec.poc] = rec;

  while ((int)m_refDistPics.size() > m_cfg.maxStoredRefPics)
  {
    m_refDistPics.erase(m_refDistPics.begin());
  }

  if (validCtus > 0)
  {
    meanMse /= double(validCtus);
  }
  if (m_cfg.verbose)
  {
    std::printf("[RC360FbTc] recordPictureDistortion POC=%d storedCtus=%d meanDrec=%.6f storedRefs=%d\n",
                rec.poc, validCtus, meanMse, int(m_refDistPics.size()));
    std::fflush(stdout);
  }

  if (m_currentWrefStatsValid && m_currentWrefPoc == rec.poc && m_lastCommittedWrefPoc != rec.poc)
  {
    m_wrefHistSum += m_currentMeanWref;
    m_ctuFrameDemandHistSum += m_currentCtuFrameDemand;
#if IBRC360FrameHistoryDrec
    if (validCtus > 0)
    {
      m_frameDrecHistSum += meanMse;
      m_frameDrecHistCount++;
    }
#endif
    m_wrefHistCount++;
    if (m_currentFrameIeffHistoryEligible && m_currentFrameIeffRawMean > 0.0)
    {
      m_frameIeffHistSum += m_currentFrameIeffRawMean;
      m_frameIeffHistCount++;
    }
    m_lastCommittedWrefPoc = rec.poc;
    if (m_cfg.verbose)
    {
      std::printf("[RC360FbTc] WrefHistoryCommit POC=%d meanWref=%.9f ctuFrameDemand=%.9f actualMeanDrec=%.9f histCount=%d histMeanWref=%.9f histCtuFrameDemand=%.9f histFrameDrec=%.9f histFrameDrecCount=%d historyDrecEnabled=%d\n",
                  rec.poc, m_currentMeanWref, m_currentCtuFrameDemand, meanMse, m_wrefHistCount,
                  getHistoricalMeanWref(), getHistoricalCtuFrameDemand(),
                  getHistoricalFrameDrec(), m_frameDrecHistCount,
                  IBRC360FrameHistoryDrec ? 1 : 0);
      std::fflush(stdout);
    }
  }
}

double LatFbTempComp::calcCtuMse8bitNorm(Picture* pic, const CompArea& area) const
{
  const CPelBuf org = pic->getOrigBuf(area);
  const CPelBuf rec = pic->getRecoBuf(area);

  const int bitDepth = pic->cs->sps->getBitDepth(ChannelType::LUMA);
  const double norm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;

  uint64_t sse = 0;

  for (int y = 0; y < org.height; y++)
  {
    const Pel* pOrg = org.bufAt(0, y);
    const Pel* pRec = rec.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      const int d = int(pOrg[x]) - int(pRec[x]);
      sse += uint64_t(d * d);
    }
  }

  const int numSamples = std::max(1, int(org.width) * int(org.height));
  const double mse = double(sse) / double(numSamples);
  return mse / (norm * norm);
}

void LatFbTempComp::preAnalyzePicture(Picture* pic, Slice* slice, double frameLambda, int frameQP)
{
  m_ctuWeights.clear();
  m_ctuIeff.clear();
  m_ctuModelIeff.clear();
  m_ctuNewIeffFormulaRaw.clear();
  m_ctuOldIeffFormulaRaw.clear();
  m_ctuOldIeffModelRaw.clear();
  m_ctuOldIeffNorm.clear();
  m_ctuDref.clear();
  m_ctuDtar.clear();
  m_ctuRefDrecList.clear();

  if (!m_cfg.enabled || pic == nullptr || slice == nullptr || pic->cs == nullptr || pic->cs->pcv == nullptr)
  {
    return;
  }

  const PreCalcValues& pcv = *pic->cs->pcv;
  const int numCtus = pcv.sizeInCtus;

  m_ctuWeights.assign(numCtus, 1.0);
  m_ctuIeff.assign(numCtus, 0.0);
  m_ctuModelIeff.assign(numCtus, 1.0);
  m_ctuNewIeffFormulaRaw.assign(numCtus, 0.0);
  m_ctuOldIeffFormulaRaw.assign(numCtus, 0.0);
  m_ctuOldIeffModelRaw.assign(numCtus, 1.0);
  m_ctuOldIeffNorm.assign(numCtus, 1.0);
  m_ctuDref.assign(numCtus, 0.0);
  m_ctuDtar.assign(numCtus, 1.0);
  m_ctuRefDrecList.assign(numCtus, std::string());
  m_currentMeanWref = 1.0;
  m_currentCtuFrameDemand = 1.0;
  m_currentMeanDref = 0.0;
  m_currentP75Dref = 0.0;
  m_currentFrameRisk = 0.0;
  m_currentFrameIeffRawMean = 1.0;
  m_currentFrameIeffHistoryEligible = false;
  m_currentWrefStatsValid = false;
  m_currentWrefPoc = pic->getPOC();

  if (slice->isIntra())
  {
    std::printf("[RC360FbTc] preAnalyzePicture POC=%d intra=1 refsWithDrec={} frameLambda=%.6f frameQP=%d\n",
                pic->getPOC(), frameLambda, frameQP);
    std::fflush(stdout);
    return;
  }

  std::vector<int> refPocsWithDrec;
  const int numListsForLog = slice->isInterB() ? 2 : 1;
  for (int listId = 0; listId < numListsForLog; listId++)
  {
    const RefPicList eList = listId == 0 ? REF_PIC_LIST_0 : REF_PIC_LIST_1;
    const int numRef = slice->getNumRefIdx(eList);
    for (int refIdx = 0; refIdx < numRef; refIdx++)
    {
      Picture* refPic = slice->getRefPic(eList, refIdx);
      if (refPic != nullptr
          && m_refDistPics.find(refPic->getPOC()) != m_refDistPics.end()
          && std::find(refPocsWithDrec.begin(), refPocsWithDrec.end(), refPic->getPOC()) == refPocsWithDrec.end())
      {
        refPocsWithDrec.push_back(refPic->getPOC());
      }
    }
  }

  std::printf("[RC360FbTc] preAnalyzePicture POC=%d intra=0 refsWithDrec={", pic->getPOC());
  for (size_t i = 0; i < refPocsWithDrec.size(); i++)
  {
    std::printf("%s%d", i == 0 ? "" : ",", refPocsWithDrec[i]);
  }
  std::printf("} frameLambda=%.6f frameQP=%d\n", frameLambda, frameQP);
  std::fflush(stdout);

#if IBRC360DrefPartsLog
  double drefPartRefDistSum = 0.0;
  double drefPartAlpha2Sum = 0.0;
  double drefPartDepSum = 0.0;
  double drefPartContributionSum = 0.0;
  double drefPartRefDistSum2 = 0.0;
  double drefPartAlpha2Sum2 = 0.0;
  double drefPartDepSum2 = 0.0;
  int drefPartCount = 0;
#endif

  for (int ctuRsAddr = 0; ctuRsAddr < numCtus; ctuRsAddr++)
  {
    const int ctuX = ctuRsAddr % pcv.widthInCtus;
    const int ctuY = ctuRsAddr / pcv.widthInCtus;

    const int x = ctuX * pcv.maxCUWidth;
    const int y = ctuY * pcv.maxCUHeight;
    const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
    const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);

    if (w <= 0 || h <= 0)
    {
      continue;
    }

    const CompArea curArea(COMPONENT_Y, pcv.chrFormat, Position(x, y), Size(w, h));
    const CPelBuf curOrg = pic->getOrigBuf(curArea);

    const double phi = calcLatitudeRad(y + h / 2, pcv.lumaHeight);
    const double intraCost = double(simpleIntraCost(curOrg)) + 1.0;

    std::vector<Candidate> candList;
    double invCostSum = 0.0;

    const int numLists = slice->isInterB() ? 2 : 1;

    for (int listId = 0; listId < numLists; listId++)
    {
      const RefPicList eList = listId == 0 ? REF_PIC_LIST_0 : REF_PIC_LIST_1;
      const int numRef = slice->getNumRefIdx(eList);

      for (int refIdx = 0; refIdx < numRef; refIdx++)
      {
        Picture* refPic = slice->getRefPic(eList, refIdx);

        if (refPic == nullptr)
        {
          continue;
        }

        if (m_refDistPics.find(refPic->getPOC()) == m_refDistPics.end())
        {
          continue;
        }

        Candidate cand = searchOneReference(pic, refPic, listId, refIdx, curArea, intraCost, phi);
        candList.push_back(cand);

        invCostSum += 1.0 / (cand.interCost + 1.0);
        if (shouldLogCtu(ctuRsAddr))
        {
          std::printf("[RC360FbTc][Cand] POC=%d ctu=%d refPoc=%d list=%d refIdx=%d intraCost=%.9f interCost=%.9f q=%.9f rx=%d ry=%d mvx=%d mvy=%d refDist=%.9f delta=%.9f eta=%.9f dep=%.9f invCostTerm=%.9f invCostSum=%.9f\n",
                      pic->getPOC(), ctuRsAddr, cand.refPoc, cand.listId, cand.refIdx,
                      intraCost, cand.interCost, cand.interCost / (intraCost + 1e-9),
                      cand.rx, cand.ry, cand.mvx, cand.mvy, cand.refDist,
                      cand.delta, cand.eta, cand.dep, 1.0 / (cand.interCost + 1.0), invCostSum);
          std::fflush(stdout);
        }
      }
    }

    if (!m_ctuRefDrecList.empty())
    {
      std::ostringstream oss;
      oss.setf(std::ios::fixed);
      oss << std::setprecision(9);
      for (size_t n = 0; n < candList.size(); n++)
      {
        if (n > 0)
        {
          oss << ";";
        }
        oss << candList[n].refPoc << ":" << candList[n].listId << ":" << candList[n].refIdx << ":" << candList[n].refDist;
      }
      m_ctuRefDrecList[ctuRsAddr] = oss.str();
    }

    double dref = 0.0;

    if (!candList.empty() && invCostSum > 0.0)
    {
      for (size_t n = 0; n < candList.size(); n++)
      {
        const double a = (1.0 / (candList[n].interCost + 1.0)) / invCostSum;
        const double drefContribution = a * a * candList[n].dep * candList[n].refDist;
        dref += drefContribution;
#if IBRC360DrefPartsLog
        const double alpha2 = a * a;
        drefPartRefDistSum += candList[n].refDist;
        drefPartAlpha2Sum += alpha2;
        drefPartDepSum += candList[n].dep;
        drefPartContributionSum += drefContribution;
        drefPartRefDistSum2 += candList[n].refDist * candList[n].refDist;
        drefPartAlpha2Sum2 += alpha2 * alpha2;
        drefPartDepSum2 += candList[n].dep * candList[n].dep;
        drefPartCount++;
#endif
        if (shouldLogCtu(ctuRsAddr))
        {
          std::printf("[RC360FbTc][DrefStep] POC=%d ctu=%d cand=%zu refPoc=%d list=%d refIdx=%d interCost=%.9f invCostSum=%.9f alpha=%.9f alpha2=%.9f dep=%.9f refDist=%.9f drefPartial=%.9f\n",
                      pic->getPOC(), ctuRsAddr, n, candList[n].refPoc, candList[n].listId, candList[n].refIdx,
                      candList[n].interCost, invCostSum, a, a * a, candList[n].dep,
                      candList[n].refDist, dref);
          std::fflush(stdout);
        }
      }
    }

    double fallbackIeff = 0.0;
#if RC360_FB_TC_IEFF
    double oldIeffFormula = 0.0;
    const double newIeffFormula = calcCtuIeffFromBestRefBlocks(pic, slice, curArea, ctuRsAddr, candList, &oldIeffFormula);
#if IBRC360IeffVersion == 2
    double ieff = oldIeffFormula;
#else
    double ieff = newIeffFormula;
#endif
    if (ieff <= 0.0 || oldIeffFormula <= 0.0)
    {
      fallbackIeff = calcSimpleIeffProxy(curOrg, phi);
    }
    if (ieff <= 0.0)
    {
      ieff = fallbackIeff;
      if (shouldLogCtu(ctuRsAddr))
      {
        std::printf("[RC360FbTc][IeffFallback] POC=%d ctu=%d phi=%.9f ieffProxy=%.9f\n",
                    pic->getPOC(), ctuRsAddr, phi, ieff);
        std::fflush(stdout);
      }
    }
#else
    const double newIeffFormula = calcSimpleIeffProxy(curOrg, phi);
    const double oldIeffFormula = newIeffFormula;
    const double ieff = calcSimpleIeffProxy(curOrg, phi);
    fallbackIeff = ieff;
#endif
    m_ctuIeff[ctuRsAddr] = ieff;
    m_ctuNewIeffFormulaRaw[ctuRsAddr] = newIeffFormula;
    m_ctuOldIeffFormulaRaw[ctuRsAddr] = oldIeffFormula;
    m_ctuOldIeffModelRaw[ctuRsAddr] = oldIeffFormula > 0.0 ? oldIeffFormula : fallbackIeff;
    m_ctuDref[ctuRsAddr] = dref;
  }

  std::vector<double> rawIeff = m_ctuIeff;
  std::vector<double> oldModelRawIeff = m_ctuOldIeffModelRaw;
  double sumPositiveIeff = 0.0;
  double sumPositiveOldIeff = 0.0;
  std::vector<double> positiveIeffValues;
  positiveIeffValues.reserve(numCtus);
  std::vector<double> positiveOldIeffValues;
  positiveOldIeffValues.reserve(numCtus);
  int validIeffCtus = 0;
  int validOldIeffCtus = 0;
  constexpr double minPositiveIeff = 1e-9;
  constexpr double ieffNormMin = 1e-6;
  constexpr double ieffNormMax = 50.0;

  for (int k = 0; k < numCtus; k++)
  {
    if (rawIeff[k] > 0.0)
    {
      sumPositiveIeff += rawIeff[k];
      positiveIeffValues.push_back(rawIeff[k]);
      validIeffCtus++;
    }
    if (oldModelRawIeff[k] > 0.0)
    {
      sumPositiveOldIeff += oldModelRawIeff[k];
      positiveOldIeffValues.push_back(oldModelRawIeff[k]);
      validOldIeffCtus++;
    }
  }

  const double meanPositiveIeff =
    validIeffCtus > 0 ? sumPositiveIeff / double(validIeffCtus) : 1.0;
  m_currentFrameIeffRawMean = meanPositiveIeff;
  m_currentFrameIeffHistoryEligible = !slice->isIntra() && validIeffCtus > 0;
  const double meanPositiveOldIeff =
    validOldIeffCtus > 0 ? sumPositiveOldIeff / double(validOldIeffCtus) : 1.0;
  double medianPositiveIeff = 1.0;
  if (!positiveIeffValues.empty())
  {
    std::sort(positiveIeffValues.begin(), positiveIeffValues.end());
    const size_t n = positiveIeffValues.size();
    medianPositiveIeff = (n & 1) != 0
      ? positiveIeffValues[n / 2]
      : 0.5 * (positiveIeffValues[n / 2 - 1] + positiveIeffValues[n / 2]);
  }
  double medianPositiveOldIeff = 1.0;
  if (!positiveOldIeffValues.empty())
  {
    std::sort(positiveOldIeffValues.begin(), positiveOldIeffValues.end());
    const size_t n = positiveOldIeffValues.size();
    medianPositiveOldIeff = (n & 1) != 0
      ? positiveOldIeffValues[n / 2]
      : 0.5 * (positiveOldIeffValues[n / 2 - 1] + positiveOldIeffValues[n / 2]);
  }
  const double ieffNormDenom = meanPositiveIeff > minPositiveIeff ? meanPositiveIeff : 1.0;
  const double oldIeffNormDenom = meanPositiveOldIeff > minPositiveIeff ? meanPositiveOldIeff : 1.0;
  const double modelIeffDenom = medianPositiveIeff > minPositiveIeff ? medianPositiveIeff : 1.0;
  (void)modelIeffDenom;
  double modelIeffFrameMin = std::numeric_limits<double>::max();
  double modelIeffFrameMax = 0.0;
  const char* mapIeffEnv = std::getenv("RC360_IBRC_MAP_IEFF_TO_GUARD");
  const bool mapIeffToGuardRange = mapIeffEnv != nullptr && std::atoi(mapIeffEnv) != 0;
  double modelIeffFrameP5 = 1.0;
  double modelIeffFrameP95 = 1.0;
  int modelIeffPercentileMapApplied = 0;
  double modelIeffFrameLogP5 = 0.0;
  double modelIeffFrameLogP95 = 0.0;
  int modelIeffLogQuantileApplied = 0;

  double modelIeffMin = std::numeric_limits<double>::max();
  double modelIeffMax = 0.0;
  double modelIeffSum = 0.0;
  double modelIeffRdMin = std::numeric_limits<double>::max();
  double modelIeffRdMax = 0.0;
  double modelIeffRdSum = 0.0;
  double modelZMin = std::numeric_limits<double>::max();
  double modelZMax = -std::numeric_limits<double>::max();
  double modelZSum = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double positiveIeff = rawIeff[k] > 0.0 ? rawIeff[k] : minPositiveIeff;
#if IBRC360FrameMedianIeffModel
    m_ctuModelIeff[k] = positiveIeff / modelIeffDenom;
#else
    m_ctuModelIeff[k] = positiveIeff;
#endif
    modelIeffFrameMin = std::min(modelIeffFrameMin, m_ctuModelIeff[k]);
    modelIeffFrameMax = std::max(modelIeffFrameMax, m_ctuModelIeff[k]);
  }

#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyLogQuantileNorm
  if (numCtus > 0)
  {
    std::vector<double> modelLogIeffValues;
    modelLogIeffValues.reserve(numCtus);
    for (int k = 0; k < numCtus; k++)
    {
      modelLogIeffValues.push_back(std::log(clipDouble(m_ctuModelIeff[k], 1e-12, 1e12)));
    }
    std::sort(modelLogIeffValues.begin(), modelLogIeffValues.end());
    const auto percentileLogValue = [&](double p)
    {
      if (modelLogIeffValues.empty())
      {
        return 0.0;
      }
      const double clippedP = clipDouble(p, 0.0, 1.0);
      const double pos = clippedP * double(modelLogIeffValues.size() - 1);
      const size_t loIdx = size_t(std::floor(pos));
      const size_t hiIdx = std::min(modelLogIeffValues.size() - 1, loIdx + 1);
      const double frac = pos - double(loIdx);
      return (1.0 - frac) * modelLogIeffValues[loIdx] + frac * modelLogIeffValues[hiIdx];
    };

    modelIeffFrameLogP5 = percentileLogValue(double(IBRC360IeffOnlyPercentileLo));
    modelIeffFrameLogP95 = percentileLogValue(double(IBRC360IeffOnlyPercentileHi));
    const double logLo = std::min(modelIeffFrameLogP5, modelIeffFrameLogP95);
    const double logHi = std::max(modelIeffFrameLogP5, modelIeffFrameLogP95);

    for (int k = 0; k < numCtus; k++)
    {
      const double u = std::log(clipDouble(m_ctuModelIeff[k], 1e-12, 1e12));
      const double clippedU = clipDouble(u, logLo, logHi);
      m_ctuModelIeff[k] = clipDouble(std::exp(clippedU), 1e-12, 1e12);
    }
    modelIeffLogQuantileApplied = 1;
    modelIeffFrameP5 = std::exp(logLo);
    modelIeffFrameP95 = std::exp(logHi);
  }
#elif IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyPercentileMap
  if (numCtus > 0)
  {
    std::vector<double> modelIeffValues = m_ctuModelIeff;
    std::sort(modelIeffValues.begin(), modelIeffValues.end());
    const auto percentileValue = [&](double p)
    {
      if (modelIeffValues.empty())
      {
        return 1.0;
      }
      const double clippedP = clipDouble(p, 0.0, 1.0);
      const double pos = clippedP * double(modelIeffValues.size() - 1);
      const size_t loIdx = size_t(std::floor(pos));
      const size_t hiIdx = std::min(modelIeffValues.size() - 1, loIdx + 1);
      const double frac = pos - double(loIdx);
      return (1.0 - frac) * modelIeffValues[loIdx] + frac * modelIeffValues[hiIdx];
    };

    modelIeffFrameP5 = percentileValue(double(IBRC360IeffOnlyPercentileLo));
    modelIeffFrameP95 = percentileValue(double(IBRC360IeffOnlyPercentileHi));
    const double srcRange = modelIeffFrameP95 - modelIeffFrameP5;
    const double dstMin = double(IBRC360IeffOnlyMapMin);
    const double dstMax = double(IBRC360IeffOnlyMapMax);
    const double dstRange = std::max(1e-12, dstMax - dstMin);
    const double dstCenter = 0.5 * (dstMin + dstMax);

    for (int k = 0; k < numCtus; k++)
    {
      if (srcRange > 1e-12)
      {
        const double t = clipDouble((m_ctuModelIeff[k] - modelIeffFrameP5) / srcRange, 0.0, 1.0);
        m_ctuModelIeff[k] = dstMin + t * dstRange;
      }
      else
      {
        m_ctuModelIeff[k] = dstCenter;
      }
    }
    modelIeffPercentileMapApplied = 1;
  }
#endif

  if (mapIeffToGuardRange && numCtus > 0)
  {
    const double mapSrcRange = modelIeffFrameMax - modelIeffFrameMin;
    const double mapDstMin = double(IBRC360RdGuardIeffMin);
    const double mapDstMax = double(IBRC360RdGuardIeffMax);
    const double mapDstRange = std::max(1e-12, mapDstMax - mapDstMin);
    const double mapDstCenter = 0.5 * (mapDstMin + mapDstMax);
    for (int k = 0; k < numCtus; k++)
    {
      if (mapSrcRange > 1e-12)
      {
        const double t = clipDouble((m_ctuModelIeff[k] - modelIeffFrameMin) / mapSrcRange, 0.0, 1.0);
        m_ctuModelIeff[k] = mapDstMin + t * mapDstRange;
      }
      else
      {
        m_ctuModelIeff[k] = mapDstCenter;
      }
    }
  }

  for (int k = 0; k < numCtus; k++)
  {
    const double positiveIeff = rawIeff[k] > 0.0 ? rawIeff[k] : minPositiveIeff;
    const double positiveOldIeff = oldModelRawIeff[k] > 0.0 ? oldModelRawIeff[k] : minPositiveIeff;
    const double normIeff = positiveIeff / ieffNormDenom;
    const double oldNormIeff = positiveOldIeff / oldIeffNormDenom;
    m_ctuIeff[k] = clipDouble(normIeff, ieffNormMin, ieffNormMax);
    m_ctuOldIeffNorm[k] = clipDouble(oldNormIeff, ieffNormMin, ieffNormMax);
    const double modelIeffRd = rc360IbrcCtuIeffCalibrated(m_ctuModelIeff[k]);
    const double modelZ = rc360IbrcModelZFromIeff(m_ctuModelIeff[k]);
    modelIeffMin = std::min(modelIeffMin, m_ctuModelIeff[k]);
    modelIeffMax = std::max(modelIeffMax, m_ctuModelIeff[k]);
    modelIeffSum += m_ctuModelIeff[k];
    modelIeffRdMin = std::min(modelIeffRdMin, modelIeffRd);
    modelIeffRdMax = std::max(modelIeffRdMax, modelIeffRd);
    modelIeffRdSum += modelIeffRd;
    modelZMin = std::min(modelZMin, modelZ);
    modelZMax = std::max(modelZMax, modelZ);
    modelZSum += modelZ;

    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][IeffNorm] POC=%d ctu=%d newFormulaRaw=%.9f newModelInput=%.9f newModelInputRd=%.9f newMean=%.9f newMedian=%.9f newNorm=%.9f newClipped=%.9f oldFormulaRaw=%.9f oldModelRaw=%.9f oldMean=%.9f oldMedian=%.9f oldNorm=%.9f oldClipped=%.9f clipMin=%.9f clipMax=%.9f modelZ=%.9f frameMedianModel=%d ctuIeffCalib=%d percentileMap=%d logQuantileNorm=%d mapPlo=%.9f mapPhi=%.9f logPlo=%.9f logPhi=%.9f mapMin=%.9f mapMax=%.9f logQuantileGamma=%.9f\n",
                  pic->getPOC(), k,
                  m_ctuNewIeffFormulaRaw[k], m_ctuModelIeff[k], modelIeffRd, meanPositiveIeff, medianPositiveIeff,
                  normIeff, m_ctuIeff[k],
                  m_ctuOldIeffFormulaRaw[k], oldModelRawIeff[k], meanPositiveOldIeff, medianPositiveOldIeff,
                  oldNormIeff, m_ctuOldIeffNorm[k],
                  ieffNormMin, ieffNormMax, modelZ, IBRC360FrameMedianIeffModel, IBRC360CtuIeffCalib,
                  modelIeffPercentileMapApplied, modelIeffLogQuantileApplied,
                  modelIeffFrameP5, modelIeffFrameP95,
                  modelIeffFrameLogP5, modelIeffFrameLogP95,
                  double(IBRC360IeffOnlyMapMin), double(IBRC360IeffOnlyMapMax),
                  double(IBRC360IeffOnlyLogQuantileGamma));
      std::fflush(stdout);
    }
  }
  std::printf("[RC360IBRC][IeffScale] POC=%d ctus=%d rawMean=%.9f rawMedian=%.9f oldRawMean=%.9f oldRawMedian=%.9f modelInputMean=%.9f modelInputMin=%.9f modelInputMax=%.9f modelInputRdMean=%.9f modelInputRdMin=%.9f modelInputRdMax=%.9f modelZMean=%.9f modelZMin=%.9f modelZMax=%.9f trainMedian=%.9f frameMedianModel=%d ctuIeffCalib=%d mapIeffToGuard=%d mapSrcMin=%.9f mapSrcMax=%.9f mapDstMin=%.9f mapDstMax=%.9f percentileMap=%d logQuantileNorm=%d percentileLo=%.9f percentileHi=%.9f percentileSrcLo=%.9f percentileSrcHi=%.9f percentileLogSrcLo=%.9f percentileLogSrcHi=%.9f percentileDstMin=%.9f percentileDstMax=%.9f logQuantileGamma=%.9f\n",
              pic->getPOC(), numCtus,
              meanPositiveIeff, medianPositiveIeff, meanPositiveOldIeff, medianPositiveOldIeff,
              numCtus > 0 ? modelIeffSum / double(numCtus) : 1.0,
              numCtus > 0 ? modelIeffMin : 1.0,
              numCtus > 0 ? modelIeffMax : 1.0,
              numCtus > 0 ? modelIeffRdSum / double(numCtus) : 1.0,
              numCtus > 0 ? modelIeffRdMin : 1.0,
              numCtus > 0 ? modelIeffRdMax : 1.0,
              numCtus > 0 ? modelZSum / double(numCtus) : 0.0,
              numCtus > 0 ? modelZMin : 0.0,
              numCtus > 0 ? modelZMax : 0.0,
              RC360_IBRC_MODEL_IEFF_MEDIAN,
              IBRC360FrameMedianIeffModel, IBRC360CtuIeffCalib,
              mapIeffToGuardRange ? 1 : 0,
              numCtus > 0 ? modelIeffFrameMin : 1.0,
              numCtus > 0 ? modelIeffFrameMax : 1.0,
              double(IBRC360RdGuardIeffMin),
              double(IBRC360RdGuardIeffMax),
              modelIeffPercentileMapApplied, modelIeffLogQuantileApplied,
              double(IBRC360IeffOnlyPercentileLo), double(IBRC360IeffOnlyPercentileHi),
              modelIeffFrameP5, modelIeffFrameP95,
              modelIeffFrameLogP5, modelIeffFrameLogP95,
              double(IBRC360IeffOnlyMapMin), double(IBRC360IeffOnlyMapMax),
              double(IBRC360IeffOnlyLogQuantileGamma));
  std::fflush(stdout);

  std::vector<double> feedbackWForFrameStats(numCtus, 1.0);
  std::vector<double> rawWForFrameStats(numCtus, 1.0);
  std::vector<double> sphericalWeights(numCtus, 1.0);
  double sumCosPhi = 0.0;
  int validCosCtus = 0;

  for (int ctuRsAddr = 0; ctuRsAddr < numCtus; ctuRsAddr++)
  {
    const int ctuX = ctuRsAddr % pcv.widthInCtus;
    const int ctuY = ctuRsAddr / pcv.widthInCtus;

    const int x = ctuX * pcv.maxCUWidth;
    const int y = ctuY * pcv.maxCUHeight;
    const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
    const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);

    if (w <= 0 || h <= 0)
    {
      continue;
    }

    const double phi = calcLatitudeRad(y + h / 2, pcv.lumaHeight);
    const double cosPhi = clipDouble(std::cos(std::fabs(phi)), 1e-6, 1.0);
    sphericalWeights[ctuRsAddr] = cosPhi;
    sumCosPhi += cosPhi;
    validCosCtus++;
  }

#if IBRC360RealDtarWref || IBRC360OldWref
  const double meanCosPhi = validCosCtus > 0 ? sumCosPhi / double(validCosCtus) : 1.0;
  constexpr double sphericalGamma = 0.50;
#endif

#if IBRC360DecoupleWref
  std::vector<double> unNormWref(numCtus, 1.0);
  double sumUnNormWref = 0.0;
  double sumLogUnNormWref = 0.0;
  int validWrefCount = 0;

  const double epsD = 1e-9;
  const double alpha = m_cfg.wrefAlpha;
  const double gamma = m_cfg.wrefGamma;
#if IBRC360WrefIeffOverDrefQuarter
  (void)gamma;
#endif
#endif
#if IBRC360RealDtarWref
  rc360IbrcInitModelFromEnv();
  std::vector<double> legacyFeedbackWForCompare(numCtus, 1.0);
  std::vector<double> legacyRawWForCompare(numCtus, 1.0);
  std::vector<double> legacyClippedRawWForCompare(numCtus, 1.0);
  std::vector<double> unNormWref(numCtus, 1.0);
  double sumUnNormWref = 0.0;
  int validWrefCount = 0;
#endif

  for (int ctuRsAddr = 0; ctuRsAddr < numCtus; ctuRsAddr++)
  {
    const int ctuX = ctuRsAddr % pcv.widthInCtus;
    const int ctuY = ctuRsAddr / pcv.widthInCtus;

    const int x = ctuX * pcv.maxCUWidth;
    const int y = ctuY * pcv.maxCUHeight;
    const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
    const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);

    if (w <= 0 || h <= 0)
    {
      continue;
    }

    const double ieff = m_ctuIeff[ctuRsAddr];
    const double dref = m_ctuDref[ctuRsAddr];
   
#if IBRC360DecoupleWref
#if IBRC360WrefDrefOnly
    (void)ieff;
#endif
#if IBRC360WrefIeffOverDrefQuarter
    const double score =
      std::max(epsD, ieff) / std::pow(std::max(epsD, dref), 0.25);
    const double wRaw = std::max(epsD, score);
#elif IBRC360WrefDrefOnly
    const double demand = std::max(epsD, dref);
    const double wRaw = std::pow(std::max(epsD, demand), gamma);
#elif IBRC360WrefDrefTimesSqrtIeff
    const double demand = std::max(epsD, dref) * std::sqrt(std::max(epsD, ieff));
    const double score = std::pow(std::max(epsD, demand), gamma);
#if IBRC360WrefDrefTimesSqrtIeffInvert
    const double wRaw = 1.0 / std::max(epsD, score);
#else
    const double wRaw = score;
#endif
#else
    const double ieffFactor = std::pow(std::max(epsD, ieff), alpha);
#if IBRC360WrefDivideIeff
    const double demand = std::max(epsD, dref) / std::max(epsD, ieffFactor);
#else
    const double demand = std::max(epsD, dref) * ieffFactor;
#endif
    const double wRaw = std::pow(std::max(epsD, demand), gamma);
#endif

    unNormWref[ctuRsAddr] = wRaw;
    sumUnNormWref += wRaw;
    sumLogUnNormWref += std::log(std::max(epsD, wRaw));
    validWrefCount++;

    // Do not infer Dtar from RD/QS in this path.
    m_ctuDtar[ctuRsAddr] = 1.0;
#endif

#if IBRC360RealDtarWref
    const double qStep = std::pow(2.0, (double(frameQP) - 4.0) / 6.0);
    const double qStepMse8bit = (qStep * qStep) / 256.0;
#if RC360_FB_TC_IEFF
    const double ieffForDtar = std::log2(1.0 + std::max(0.0, ieff));
#else
    const double ieffForDtar = ieff;
#endif
    const double dtarUnclipped =
      m_cfg.dtarScale * qStepMse8bit * (1.0 + m_cfg.dtarIeffScale * ieffForDtar);
    const double dtar = std::max(1e-6, dtarUnclipped);

    const double legacyDtar = dtar;
    const double legacyRatioDenom = legacyDtar + 1e-9;
    const double legacyRatio = dref / legacyRatioDenom;
    const double legacyExcessRatio = std::max(0.0, legacyRatio - 1.0);
    const double legacyBetaTerm = m_cfg.beta * legacyExcessRatio;
    const double legacyFeedbackW = 1.0 + legacyBetaTerm;
    const double sphericalW = m_cfg.useSphericalW
      ? std::pow(clipDouble(sphericalWeights[ctuRsAddr] / std::max(1e-9, meanCosPhi),
                            0.25, 4.0),
                 sphericalGamma)
      : 1.0;
    const double legacyRawW = legacyFeedbackW * sphericalW;
    const double legacyClippedRawW = clipDouble(legacyRawW, m_cfg.wMin, m_cfg.wMax);

    const double ieffNorm = rc360ClipPositive(m_ctuModelIeff[ctuRsAddr], 1e-9, 1e9);
    const double lambdaBase = rc360ClipPositive(frameLambda, 1e-12, 1e12);
#if IBRC360SplitSkipModel
    const Rc360IbrcModelState& frameModel = rc360IbrcFrameModel();
    const double qsTar = rc360IbrcQsFromLambda(frameModel, lambdaBase, ieffNorm);
    const double dtarModel = rc360IbrcDistMse(frameModel, qsTar, ieffNorm);
#else
    const double qsTar = rc360IbrcQsFromLambda(lambdaBase, ieffNorm);
    const double dtarModel = rc360IbrcDistMse(qsTar, ieffNorm);
#endif
    const double rdDtar = std::max(1e-12, m_cfg.dtarScale * dtarModel);

    const double ratio = dref / std::max(rdDtar, 1e-12);
    const double unNormW = std::max(1.0, ratio);

    m_ctuDtar[ctuRsAddr] = rdDtar;
    unNormWref[ctuRsAddr] = unNormW;
    sumUnNormWref += unNormW;
    validWrefCount++;
    legacyFeedbackWForCompare[ctuRsAddr] = legacyFeedbackW;
    legacyRawWForCompare[ctuRsAddr] = legacyRawW;
    legacyClippedRawWForCompare[ctuRsAddr] = legacyClippedRawW;
    feedbackWForFrameStats[ctuRsAddr] = unNormW;
    rawWForFrameStats[ctuRsAddr] = unNormW;

    if (shouldLogCtu(ctuRsAddr))
    {
      std::printf("[RC360FbTc][IBRC360RealDtarWrefCompareRaw] POC=%d ctu=%d ctuX=%d ctuY=%d x=%d y=%d w=%d h=%d frameQP=%d frameLambda=%.9f ieff=%.9f rawIeff=%.9f ieffForDtar=%.9f qStep=%.9f qStepMse8bit=%.9f dtarScale=%.9f dtarIeffScale=%.9f beforeDtarUnclipped=%.9f beforeDtar=%.9f afterIeffNorm=%.9f afterLambdaBase=%.9f afterQsTar=%.9f afterDtarModel=%.9f afterDtar=%.9f dref=%.9f beforeRatioDenom=%.9f beforeRatio=%.9f beforeExcessRatio=%.9f beforeBeta=%.9f beforeBetaTerm=%.9f beforeFeedbackW=%.9f beforeSphericalW=%.9f beforeMeanCosPhi=%.9f beforeRawW=%.9f beforeClippedRawW=%.9f afterRatio=%.9f afterUnNormWref=%.9f afterRawW=%.9f wMin=%.9f wMax=%.9f\n",
                  pic->getPOC(), ctuRsAddr, ctuX, ctuY, x, y, w, h,
                  frameQP, frameLambda, ieff, rawIeff[ctuRsAddr], ieffForDtar, qStep, qStepMse8bit,
                  m_cfg.dtarScale, m_cfg.dtarIeffScale, dtarUnclipped, legacyDtar,
                  ieffNorm, lambdaBase, qsTar, dtarModel, rdDtar, dref,
                  legacyRatioDenom, legacyRatio, legacyExcessRatio, m_cfg.beta, legacyBetaTerm,
                  legacyFeedbackW, sphericalW, meanCosPhi, legacyRawW, legacyClippedRawW,
                  ratio, unNormW, unNormW, m_cfg.wMin, m_cfg.wMax);
      std::fflush(stdout);
    }
#endif
#if IBRC360OldWref
    const double qStep = std::pow(2.0, (double(frameQP) - 4.0) / 6.0);
    const double qStepMse8bit = (qStep * qStep) / 256.0;
#if RC360_FB_TC_IEFF
    const double ieffForDtar = std::log2(1.0 + std::max(0.0, ieff));
#else
    const double ieffForDtar = ieff;
#endif
    const double dtarUnclipped =
      m_cfg.dtarScale * qStepMse8bit * (1.0 + m_cfg.dtarIeffScale * ieffForDtar);
    const double dtar = std::max(1e-6, dtarUnclipped);

    m_ctuDtar[ctuRsAddr] = dtar;

    const double ratioDenom = dtar + 1e-9;
    const double ratio = dref / ratioDenom;
    const double excessRatio = std::max(0.0, ratio - 1.0);
    const double betaTerm = m_cfg.beta * excessRatio;
    const double feedbackW = 1.0 + betaTerm;
    const double sphericalW = m_cfg.useSphericalW
      ? std::pow(clipDouble(sphericalWeights[ctuRsAddr] / std::max(1e-9, meanCosPhi),
                            0.25, 4.0),
                 sphericalGamma)
      : 1.0;
    const double rawW = feedbackW * sphericalW;

    feedbackWForFrameStats[ctuRsAddr] = feedbackW;
    rawWForFrameStats[ctuRsAddr] = rawW;
    m_ctuWeights[ctuRsAddr] = clipDouble(rawW, m_cfg.wMin, m_cfg.wMax);

    if (shouldLogCtu(ctuRsAddr))
    {
      std::printf("[RC360FbTc][WrefRaw] POC=%d ctu=%d ctuX=%d ctuY=%d x=%d y=%d w=%d h=%d frameQP=%d ieff=%.9f rawIeff=%.9f ieffForDtar=%.9f qStep=%.9f qStepMse8bit=%.9f dtarScale=%.9f dtarIeffScale=%.9f dtarUnclipped=%.9f dtar=%.9f dref=%.9f ratioDenom=%.9f ratio=%.9f excessRatio=%.9f beta=%.9f betaTerm=%.9f feedbackW=%.9f sphericalW=%.9f meanCosPhi=%.9f rawW=%.9f wMin=%.9f wMax=%.9f clippedRawW=%.9f\n",
                  pic->getPOC(), ctuRsAddr, ctuX, ctuY, x, y, w, h,
                  frameQP, ieff, rawIeff[ctuRsAddr], ieffForDtar, qStep, qStepMse8bit,
                  m_cfg.dtarScale, m_cfg.dtarIeffScale, dtarUnclipped, dtar, dref,
                  ratioDenom, ratio, excessRatio, m_cfg.beta, betaTerm, feedbackW, sphericalW, meanCosPhi, rawW,
                  m_cfg.wMin, m_cfg.wMax, m_ctuWeights[ctuRsAddr]);
      std::fflush(stdout);
    }
#endif

  }//ctu loop end

#if IBRC360DrefPartsLog
  const double meanDrefPartRefDist =
    drefPartCount > 0 ? drefPartRefDistSum / double(drefPartCount) : 0.0;
  const double meanDrefPartAlpha2 =
    drefPartCount > 0 ? drefPartAlpha2Sum / double(drefPartCount) : 0.0;
  const double meanDrefPartDep =
    drefPartCount > 0 ? drefPartDepSum / double(drefPartCount) : 0.0;
  const double meanDrefPartContribution =
    drefPartCount > 0 ? drefPartContributionSum / double(drefPartCount) : 0.0;
  const double varDrefPartRefDist =
    drefPartCount > 0 ? std::max(0.0, drefPartRefDistSum2 / double(drefPartCount) - meanDrefPartRefDist * meanDrefPartRefDist) : 0.0;
  const double varDrefPartAlpha2 =
    drefPartCount > 0 ? std::max(0.0, drefPartAlpha2Sum2 / double(drefPartCount) - meanDrefPartAlpha2 * meanDrefPartAlpha2) : 0.0;
  const double varDrefPartDep =
    drefPartCount > 0 ? std::max(0.0, drefPartDepSum2 / double(drefPartCount) - meanDrefPartDep * meanDrefPartDep) : 0.0;
  const double cvDrefPartRefDist =
    meanDrefPartRefDist > 1e-12 ? std::sqrt(varDrefPartRefDist) / meanDrefPartRefDist : 0.0;
  const double cvDrefPartAlpha2 =
    meanDrefPartAlpha2 > 1e-12 ? std::sqrt(varDrefPartAlpha2) / meanDrefPartAlpha2 : 0.0;
  const double cvDrefPartDep =
    meanDrefPartDep > 1e-12 ? std::sqrt(varDrefPartDep) / meanDrefPartDep : 0.0;
  std::printf("[RC360FbTc][DrefParts] POC=%d samples=%d meanRefDist=%.9f meanAlpha2=%.9f meanDep=%.9f meanContribution=%.9f cvRefDist=%.9f cvAlpha2=%.9f cvDep=%.9f\n",
              pic->getPOC(), drefPartCount, meanDrefPartRefDist, meanDrefPartAlpha2,
              meanDrefPartDep, meanDrefPartContribution,
              cvDrefPartRefDist, cvDrefPartAlpha2, cvDrefPartDep);
  std::fflush(stdout);
#endif

  // Normalize Wref and store it in m_ctuWeights.
#if IBRC360RealDtarWref
  const double meanUnNormWref =
    validWrefCount > 0 ? sumUnNormWref / double(validWrefCount) : 1.0;
  double legacyMeanW = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    legacyMeanW += legacyClippedRawWForCompare[k];
  }
  legacyMeanW = numCtus > 0 ? legacyMeanW / double(numCtus) : 1.0;
  if (legacyMeanW <= 1e-9)
  {
    legacyMeanW = 1.0;
  }

  for (int k = 0; k < numCtus; k++)
  {
    const double legacyPreNormW = legacyClippedRawWForCompare[k];
    const double legacyNormW = legacyPreNormW / legacyMeanW;
    const double legacyFinalW = clipDouble(legacyNormW, m_cfg.wMin, m_cfg.wMax);
    const double normW = unNormWref[k] / std::max(meanUnNormWref, 1e-12);
    const double clippedW = clipDouble(normW, m_cfg.wMin, m_cfg.wMax);
    m_ctuWeights[k] = clippedW;

    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][IBRC360RealDtarWrefCompareNorm] POC=%d ctu=%d beforePreNormW=%.9f beforeMeanW=%.9f beforeNormW=%.9f beforeFinalWRef=%.9f afterUnNormWref=%.9f afterMeanUnNormWref=%.9f afterNormWref=%.9f wMin=%.9f wMax=%.9f afterFinalWRef=%.9f\n",
                  pic->getPOC(), k, legacyPreNormW, legacyMeanW, legacyNormW, legacyFinalW,
                  unNormWref[k], meanUnNormWref, normW, m_cfg.wMin, m_cfg.wMax, clippedW);
      std::fflush(stdout);
    }
  }
#endif
#if IBRC360OldWref
  double meanW = 0.0;

  for (int k = 0; k < numCtus; k++)
  {
    meanW += m_ctuWeights[k];
  }

  meanW = numCtus > 0 ? meanW / double(numCtus) : 1.0;

  if (meanW <= 1e-9)
  {
    meanW = 1.0;
  }

  for (int k = 0; k < numCtus; k++)
  {
    const double preNormW = m_ctuWeights[k];
    const double normW = preNormW / meanW;
    m_ctuWeights[k] = clipDouble(normW, m_cfg.wMin, m_cfg.wMax);
    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][WrefNorm] POC=%d ctu=%d preNormW=%.9f meanW=%.9f normW=%.9f wMin=%.9f wMax=%.9f finalWRef=%.9f\n",
                  pic->getPOC(), k, preNormW, meanW, normW, m_cfg.wMin, m_cfg.wMax, m_ctuWeights[k]);
      std::fflush(stdout);
    }
  }
#endif
#if IBRC360DecoupleWref
  const double frameWref =
  validWrefCount > 0 ? sumUnNormWref / double(validWrefCount) : 1.0;
#if IBRC360WrefIeffOverDrefQuarter
  (void)frameWref;
  const double frameGeoScore =
    validWrefCount > 0 ? std::exp(sumLogUnNormWref / double(validWrefCount)) : 1.0;
  const double rankMapWMin = std::max(m_cfg.wMin, double(IBRC360WrefIeffOverDrefQuarterMin));
  const double rankMapWMax = std::max(rankMapWMin, std::min(m_cfg.wMax, double(IBRC360WrefIeffOverDrefQuarterMax)));
#if IBRC360WrefRankMap
  std::vector<int> wrefRankOrder;
  wrefRankOrder.reserve(numCtus);
  for (int k = 0; k < numCtus; k++)
  {
    wrefRankOrder.push_back(k);
  }
  std::stable_sort(wrefRankOrder.begin(), wrefRankOrder.end(),
                   [&](int a, int b) { return unNormWref[a] < unNormWref[b]; });
  std::vector<double> rankMappedWref(numCtus, 1.0);
  if (numCtus == 1)
  {
    rankMappedWref[wrefRankOrder[0]] = 1.0;
  }
  else if (numCtus > 1)
  {
    for (int rank = 0; rank < numCtus; rank++)
    {
      const double t = double(rank) / double(numCtus - 1);
      rankMappedWref[wrefRankOrder[rank]] = rankMapWMin + t * (rankMapWMax - rankMapWMin);
    }
  }
#endif
#endif

  for (int k = 0; k < numCtus; k++)
  {
#if IBRC360WrefIeffOverDrefQuarter
#if IBRC360WrefRankMap
    const double normW = rankMappedWref[k];
    m_ctuWeights[k] = normW;
#else
    const double scoreNorm = unNormWref[k] / std::max(frameGeoScore, 1e-12);
    const double normW = std::pow(std::max(epsD, scoreNorm),
                                  double(IBRC360WrefIeffOverDrefQuarterGamma));
    m_ctuWeights[k] = clipDouble(normW, rankMapWMin, rankMapWMax);
#endif
#else
    const double normW = unNormWref[k] / std::max(frameWref, 1e-12);
#if IBRC360WrefDrefTimesSqrtIeff && IBRC360WrefDrefTimesSqrtIeffNarrow
    const double wMin = std::max(m_cfg.wMin, double(IBRC360WrefDrefTimesSqrtIeffMin));
    const double wMax = std::min(m_cfg.wMax, double(IBRC360WrefDrefTimesSqrtIeffMax));
    m_ctuWeights[k] = clipDouble(normW, wMin, std::max(wMin, wMax));
#elif IBRC360WrefDrefOnly
    const double wMin = double(IBRC360WrefDrefOnlyMin);
    const double wMax = double(IBRC360WrefDrefOnlyMax);
    m_ctuWeights[k] = clipDouble(normW, wMin, std::max(wMin, wMax));
#else
    m_ctuWeights[k] = clipDouble(normW, m_cfg.wMin, m_cfg.wMax);
#endif
#endif
    feedbackWForFrameStats[k] = m_ctuWeights[k];
    rawWForFrameStats[k] = unNormWref[k];

    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][WrefNew] POC=%d ctu=%d dref=%.9f ieff=%.9f alpha=%.6f gamma=%.6f demand=%.9f ctuRawWref=%.9f frameWref=%.9f normWref=%.9f finalWref=%.9f wMin=%.9f wMax=%.9f formula=%s frameGeoScore=%.9f\n",
                  pic->getPOC(), k,
                  m_ctuDref[k], m_ctuIeff[k],
                  alpha,
#if IBRC360WrefIeffOverDrefQuarter
                  double(IBRC360WrefIeffOverDrefQuarterGamma),
                  std::max(epsD, m_ctuIeff[k]) / std::pow(std::max(epsD, m_ctuDref[k]), 0.25),
#elif IBRC360WrefDrefTimesSqrtIeff
                  gamma,
                  std::max(epsD, m_ctuDref[k]) * std::sqrt(std::max(epsD, m_ctuIeff[k])),
#elif IBRC360WrefDrefOnly
                  gamma,
                  std::max(epsD, m_ctuDref[k]),
#else
                  gamma,
                  std::max(epsD, m_ctuDref[k])
#if IBRC360WrefDivideIeff
                    / std::max(epsD, std::pow(std::max(epsD, m_ctuIeff[k]), alpha)),
#else
                    * std::pow(std::max(epsD, m_ctuIeff[k]), alpha),
#endif
#endif
                  unNormWref[k],
#if IBRC360WrefIeffOverDrefQuarter
                  frameGeoScore,
#else
                  frameWref,
#endif
                  normW, m_ctuWeights[k], m_cfg.wMin, m_cfg.wMax,
#if IBRC360WrefIeffOverDrefQuarter
                  "IeffOverDrefQuarter", frameGeoScore
#elif IBRC360WrefDrefOnly
                  "DrefOnly", 0.0
#else
                  "legacy", 0.0
#endif
      );
      std::fflush(stdout);
    }
  }
#if IBRC360WrefIeffOverDrefQuarter || IBRC360WrefDrefOnly || (IBRC360WrefDrefTimesSqrtIeff && IBRC360WrefDrefTimesSqrtIeffNarrow)
  double clippedMeanWref = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    clippedMeanWref += m_ctuWeights[k];
  }
  clippedMeanWref = numCtus > 0 ? clippedMeanWref / double(numCtus) : 1.0;
  clippedMeanWref = std::max(clippedMeanWref, 1e-12);

#if IBRC360WrefIeffOverDrefQuarter
  const double narrowWMin = rankMapWMin;
  const double narrowWMax = rankMapWMax;
#elif IBRC360WrefDrefOnly
  const double narrowWMin = double(IBRC360WrefDrefOnlyMin);
  const double narrowWMax = std::max(narrowWMin, double(IBRC360WrefDrefOnlyMax));
#else
  const double narrowWMin = std::max(m_cfg.wMin, double(IBRC360WrefDrefTimesSqrtIeffMin));
  const double narrowWMax = std::max(narrowWMin, std::min(m_cfg.wMax, double(IBRC360WrefDrefTimesSqrtIeffMax)));
#endif
  double renormScaleLo = 0.0;
  double renormScaleHi = 1.0;
  for (int iter = 0; iter < 32; iter++)
  {
    double meanAtHi = 0.0;
    for (int k = 0; k < numCtus; k++)
    {
      meanAtHi += clipDouble(m_ctuWeights[k] * renormScaleHi, narrowWMin, narrowWMax);
    }
    meanAtHi = numCtus > 0 ? meanAtHi / double(numCtus) : 1.0;
    if (meanAtHi >= 1.0 || renormScaleHi > 1024.0)
    {
      break;
    }
    renormScaleHi *= 2.0;
  }
  for (int iter = 0; iter < 40; iter++)
  {
    const double mid = 0.5 * (renormScaleLo + renormScaleHi);
    double meanAtMid = 0.0;
    for (int k = 0; k < numCtus; k++)
    {
      meanAtMid += clipDouble(m_ctuWeights[k] * mid, narrowWMin, narrowWMax);
    }
    meanAtMid = numCtus > 0 ? meanAtMid / double(numCtus) : 1.0;
    if (meanAtMid < 1.0)
    {
      renormScaleLo = mid;
    }
    else
    {
      renormScaleHi = mid;
    }
  }
  const double renormScale = 0.5 * (renormScaleLo + renormScaleHi);
  double renormMeanWref = 0.0;
  double renormMinWref = std::numeric_limits<double>::max();
  double renormMaxWref = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double finalW = clipDouble(m_ctuWeights[k] * renormScale, narrowWMin, narrowWMax);
    m_ctuWeights[k] = finalW;
    feedbackWForFrameStats[k] = finalW;
    renormMeanWref += finalW;
    renormMinWref = std::min(renormMinWref, finalW);
    renormMaxWref = std::max(renormMaxWref, finalW);
  }
  renormMeanWref = numCtus > 0 ? renormMeanWref / double(numCtus) : 1.0;
  std::printf("[RC360FbTc][WrefRenorm] POC=%d clippedMeanWref=%.9f renormScale=%.9f renormMeanWref=%.9f renormMinWref=%.9f renormMaxWref=%.9f narrowMin=%.9f narrowMax=%.9f formula=%s\n",
              pic->getPOC(), clippedMeanWref, renormScale, renormMeanWref,
              numCtus > 0 ? renormMinWref : 1.0, numCtus > 0 ? renormMaxWref : 1.0,
              narrowWMin, narrowWMax,
#if IBRC360WrefIeffOverDrefQuarter
              "IeffOverDrefQuarter"
#elif IBRC360WrefDrefOnly
              "DrefOnly"
#else
              "DrefTimesSqrtIeff"
#endif
  );
  std::fflush(stdout);
#endif
#endif
#if IBRC360DecoupleWref && IBRC360WrefFloorLift
  const double floorLiftMin = clipDouble(double(IBRC360WrefFloorLiftMin), m_cfg.wMin, 1.0);
  const double floorLiftMax = std::max(floorLiftMin, std::min(double(IBRC360WrefFloorLiftMax), m_cfg.wMax));
  double floorLiftMean = 0.0;
  std::vector<double> floorLiftW(numCtus, 1.0);
  for (int k = 0; k < numCtus; k++)
  {
    const double liftedW = clipDouble(m_ctuWeights[k], floorLiftMin, floorLiftMax);
    floorLiftW[k] = liftedW;
    floorLiftMean += liftedW;
  }
  floorLiftMean = numCtus > 0 ? floorLiftMean / double(numCtus) : 1.0;
  floorLiftMean = std::max(floorLiftMean, 1e-12);

  double floorLiftSum = 0.0;
  double floorLiftSum2 = 0.0;
  double floorLiftMinFinal = std::numeric_limits<double>::max();
  double floorLiftMaxFinal = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double beforeW = m_ctuWeights[k];
    const double finalW = clipDouble(floorLiftW[k] / floorLiftMean, m_cfg.wMin, m_cfg.wMax);
    m_ctuWeights[k] = finalW;
    feedbackWForFrameStats[k] = finalW;
    floorLiftSum += finalW;
    floorLiftSum2 += finalW * finalW;
    floorLiftMinFinal = std::min(floorLiftMinFinal, finalW);
    floorLiftMaxFinal = std::max(floorLiftMaxFinal, finalW);
    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][WrefFloorLift] POC=%d ctu=%d beforeW=%.9f liftMin=%.9f liftMax=%.9f liftedW=%.9f liftedMean=%.9f finalW=%.9f\n",
                  pic->getPOC(), k, beforeW, floorLiftMin, floorLiftMax, floorLiftW[k], floorLiftMean, finalW);
      std::fflush(stdout);
    }
  }
  const double floorLiftMeanFinal = numCtus > 0 ? floorLiftSum / double(numCtus) : 1.0;
  const double floorLiftVarFinal = numCtus > 0
    ? std::max(0.0, floorLiftSum2 / double(numCtus) - floorLiftMeanFinal * floorLiftMeanFinal)
    : 0.0;
  std::printf("[RC360FbTc][WrefFloorLiftSummary] POC=%d meanW=%.9f stdW=%.9f minW=%.9f maxW=%.9f liftMin=%.9f liftMax=%.9f liftedMean=%.9f\n",
              pic->getPOC(), floorLiftMeanFinal, std::sqrt(floorLiftVarFinal),
              numCtus > 0 ? floorLiftMinFinal : 1.0,
              numCtus > 0 ? floorLiftMaxFinal : 1.0,
              floorLiftMin, floorLiftMax, floorLiftMean);
  std::fflush(stdout);
#endif
#if IBRC360DecoupleWref && IBRC360WrefNarrowGuard
  double narrowSumW = 0.0;
  double narrowSumW2 = 0.0;
  double narrowMinW = std::numeric_limits<double>::max();
  double narrowMaxW = 0.0;
  std::vector<double> narrowBeforeW(numCtus, 1.0);
  std::vector<double> narrowCompressedW(numCtus, 1.0);
  const double narrowPower = clipDouble(double(IBRC360WrefNarrowPower), 0.0, 1.0);
  const double narrowMin = std::max(1e-6, double(IBRC360WrefNarrowMin));
  const double narrowMax = std::max(narrowMin, double(IBRC360WrefNarrowMax));
  for (int k = 0; k < numCtus; k++)
  {
    const double beforeW = rc360ClipPositive(m_ctuWeights[k], 1e-6, 1e6);
    double compressedW = std::pow(beforeW, narrowPower);
    compressedW = clipDouble(compressedW, narrowMin, narrowMax);
    narrowBeforeW[k] = beforeW;
    narrowCompressedW[k] = compressedW;
    m_ctuWeights[k] = compressedW;
    feedbackWForFrameStats[k] = compressedW;
    narrowSumW += compressedW;
  }
  const double narrowMeanW = numCtus > 0 ? narrowSumW / double(numCtus) : 1.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double beforeNormW = m_ctuWeights[k];
    double finalW = beforeNormW / std::max(narrowMeanW, 1e-12);
    finalW = clipDouble(finalW, narrowMin, narrowMax);
    m_ctuWeights[k] = finalW;
    feedbackWForFrameStats[k] = finalW;
    narrowSumW2 += finalW * finalW;
    narrowMinW = std::min(narrowMinW, finalW);
    narrowMaxW = std::max(narrowMaxW, finalW);
    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][WrefNarrowGuard] POC=%d ctu=%d beforeW=%.9f power=%.9f compressedW=%.9f meanCompressedW=%.9f finalW=%.9f guardMin=%.9f guardMax=%.9f\n",
                  pic->getPOC(), k, narrowBeforeW[k], narrowPower, narrowCompressedW[k], narrowMeanW,
                  finalW, narrowMin, narrowMax);
      std::fflush(stdout);
    }
  }
  double finalMeanW = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    finalMeanW += m_ctuWeights[k];
  }
  finalMeanW = numCtus > 0 ? finalMeanW / double(numCtus) : 1.0;
  const double finalVarW =
    numCtus > 0 ? std::max(0.0, narrowSumW2 / double(numCtus) - finalMeanW * finalMeanW) : 0.0;
  std::printf("[RC360FbTc][WrefNarrowGuardSummary] POC=%d meanW=%.9f stdW=%.9f minW=%.9f maxW=%.9f power=%.9f guardMin=%.9f guardMax=%.9f\n",
              pic->getPOC(), finalMeanW, std::sqrt(finalVarW), narrowMinW, narrowMaxW,
              narrowPower, narrowMin, narrowMax);
  std::fflush(stdout);
#endif
#if IBRC360DecoupleWref && IBRC360WrefStrengthGate
  double gateSumDref = 0.0;
  double gateSumDref2 = 0.0;
  int gateDrefCount = 0;
  for (int k = 0; k < numCtus; k++)
  {
    const double dref = m_ctuDref[k];
    if (std::isfinite(dref))
    {
      gateSumDref += dref;
      gateSumDref2 += dref * dref;
      gateDrefCount++;
    }
  }
  const double gateMeanDref =
    gateDrefCount > 0 ? gateSumDref / double(gateDrefCount) : 0.0;
  const double gateVarDref =
    gateDrefCount > 0 ? std::max(0.0, gateSumDref2 / double(gateDrefCount) - gateMeanDref * gateMeanDref) : 0.0;
  const double gateStdDref = std::sqrt(gateVarDref);
  const double gateCvDref = gateMeanDref > 1e-9 ? gateStdDref / gateMeanDref : 0.0;
  const double gateMin = clipDouble(IBRC360WrefGateMin, 0.0, 1.0);
  const double gateTau = std::max(1e-9, double(IBRC360WrefGateTau));
  const double gateCvRef = std::max(1e-9, double(IBRC360WrefGateCvRef));
  const double gateLowDref = std::max(0.0, double(IBRC360WrefGateLowDref));
  double wrefGate =
    gateMin + (1.0 - gateMin) * gateMeanDref / (gateMeanDref + gateTau + 1e-9);
  if (gateMeanDref < gateLowDref)
  {
    const double cvGate = clipDouble(gateCvDref / gateCvRef, 0.70, 1.0);
    wrefGate *= cvGate;
  }
  wrefGate = clipDouble(wrefGate, gateMin, 1.0);
  const double dynWMin = 1.0 - wrefGate * (1.0 - m_cfg.wMin);
  const double dynWMax = 1.0 + wrefGate * (m_cfg.wMax - 1.0);

  for (int k = 0; k < numCtus; k++)
  {
    const double gatedW = 1.0 + wrefGate * (m_ctuWeights[k] - 1.0);
    m_ctuWeights[k] = clipDouble(gatedW, dynWMin, dynWMax);
    feedbackWForFrameStats[k] = m_ctuWeights[k];
  }
  std::printf("[RC360FbTc][WrefStrengthGate] POC=%d meanDref=%.9f stdDref=%.9f cvDref=%.9f gate=%.9f dynWMin=%.9f dynWMax=%.9f gateMin=%.9f gateTau=%.9f cvRef=%.9f lowDref=%.9f samples=%d\n",
              pic->getPOC(), gateMeanDref, gateStdDref, gateCvDref, wrefGate,
              dynWMin, dynWMax, gateMin, gateTau, gateCvRef, gateLowDref, gateDrefCount);
  std::fflush(stdout);
#endif
#if IBRC360DecoupleWref && IBRC360WrefTemporalReliabilityGate
  double temporalSumDref = 0.0;
  double temporalSumDref2 = 0.0;
  double beforeSumW = 0.0;
  double beforeSumW2 = 0.0;
  double beforeMinW = std::numeric_limits<double>::max();
  double beforeMaxW = 0.0;
  int temporalDrefCount = 0;
  for (int k = 0; k < numCtus; k++)
  {
    const double dref = m_ctuDref[k];
    if (std::isfinite(dref))
    {
      temporalSumDref += dref;
      temporalSumDref2 += dref * dref;
      temporalDrefCount++;
    }
    const double w = m_ctuWeights[k];
    beforeSumW += w;
    beforeSumW2 += w * w;
    beforeMinW = std::min(beforeMinW, w);
    beforeMaxW = std::max(beforeMaxW, w);
  }

  const double temporalMeanDref =
    temporalDrefCount > 0 ? temporalSumDref / double(temporalDrefCount) : 0.0;
  const double temporalVarDref =
    temporalDrefCount > 0
      ? std::max(0.0, temporalSumDref2 / double(temporalDrefCount) - temporalMeanDref * temporalMeanDref)
      : 0.0;
  const double temporalStdDref = std::sqrt(temporalVarDref);
  const double temporalCvDref = temporalMeanDref > 1e-9 ? temporalStdDref / temporalMeanDref : 0.0;

  const int temporalStartPoc = std::max(0, int(IBRC360WrefTemporalGateStartPoc));
  const int temporalRamp = std::max(1, int(IBRC360WrefTemporalGateRamp));
  const double temporalProgress =
    pic->getPOC() >= temporalStartPoc
      ? clipDouble((double(pic->getPOC() - temporalStartPoc + 1)) / double(temporalRamp), 0.0, 1.0)
      : 0.0;
  const double temporalMinGate = clipDouble(double(IBRC360WrefTemporalGateMin), 0.0, 1.0);
  const double temporalDrefTau = std::max(1e-9, double(IBRC360WrefTemporalGateDrefTau));
  const double temporalCvRef = std::max(1e-9, double(IBRC360WrefTemporalGateCvRef));
  const double strengthWeight = clipDouble(double(IBRC360WrefTemporalGateStrengthWeight), 0.0, 1.0);

  const double cvReliability = clipDouble(temporalCvDref / temporalCvRef, temporalMinGate, 1.0);
  const double strengthReliability =
    clipDouble(temporalMeanDref / (temporalMeanDref + temporalDrefTau), temporalMinGate, 1.0);
  const double frameReliability =
    clipDouble((1.0 - strengthWeight) * cvReliability + strengthWeight * strengthReliability,
               temporalMinGate, 1.0);
  const double temporalGate =
    clipDouble(1.0 - temporalProgress * (1.0 - frameReliability), temporalMinGate, 1.0);

  double gatedMeanW = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double gatedW = 1.0 + temporalGate * (m_ctuWeights[k] - 1.0);
    m_ctuWeights[k] = clipDouble(gatedW, m_cfg.wMin, m_cfg.wMax);
    gatedMeanW += m_ctuWeights[k];
  }
  gatedMeanW = numCtus > 0 ? gatedMeanW / double(numCtus) : 1.0;

#if IBRC360WrefTemporalGateRenorm
  if (gatedMeanW > 1e-12)
  {
    for (int k = 0; k < numCtus; k++)
    {
      m_ctuWeights[k] = clipDouble(m_ctuWeights[k] / gatedMeanW, m_cfg.wMin, m_cfg.wMax);
    }
  }
#endif

  double afterSumW = 0.0;
  double afterSumW2 = 0.0;
  double afterMinW = std::numeric_limits<double>::max();
  double afterMaxW = 0.0;
  for (int k = 0; k < numCtus; k++)
  {
    const double w = m_ctuWeights[k];
    feedbackWForFrameStats[k] = w;
    afterSumW += w;
    afterSumW2 += w * w;
    afterMinW = std::min(afterMinW, w);
    afterMaxW = std::max(afterMaxW, w);
  }
  const double beforeMeanW = numCtus > 0 ? beforeSumW / double(numCtus) : 1.0;
  const double beforeStdW = numCtus > 0
    ? std::sqrt(std::max(0.0, beforeSumW2 / double(numCtus) - beforeMeanW * beforeMeanW))
    : 0.0;
  const double afterMeanW = numCtus > 0 ? afterSumW / double(numCtus) : 1.0;
  const double afterStdW = numCtus > 0
    ? std::sqrt(std::max(0.0, afterSumW2 / double(numCtus) - afterMeanW * afterMeanW))
    : 0.0;

  std::printf("[RC360FbTc][WrefTemporalGate] POC=%d startPoc=%d ramp=%d progress=%.9f meanDref=%.9f stdDref=%.9f cvDref=%.9f cvReliability=%.9f strengthReliability=%.9f frameReliability=%.9f gate=%.9f beforeMeanW=%.9f beforeStdW=%.9f beforeMinW=%.9f beforeMaxW=%.9f gatedMeanW=%.9f afterMeanW=%.9f afterStdW=%.9f afterMinW=%.9f afterMaxW=%.9f minGate=%.9f tau=%.9f cvRef=%.9f strengthWeight=%.9f renorm=%d samples=%d\n",
              pic->getPOC(), temporalStartPoc, temporalRamp, temporalProgress,
              temporalMeanDref, temporalStdDref, temporalCvDref,
              cvReliability, strengthReliability, frameReliability, temporalGate,
              beforeMeanW, beforeStdW, numCtus > 0 ? beforeMinW : 1.0, numCtus > 0 ? beforeMaxW : 1.0,
              gatedMeanW, afterMeanW, afterStdW,
              numCtus > 0 ? afterMinW : 1.0, numCtus > 0 ? afterMaxW : 1.0,
              temporalMinGate, temporalDrefTau, temporalCvRef, strengthWeight,
              int(IBRC360WrefTemporalGateRenorm), temporalDrefCount);
  std::fflush(stdout);
#endif
#if IBRC360AblationMode == 1
  for (int k = 0; k < numCtus; k++)
  {
    feedbackWForFrameStats[k] = 1.0;
    rawWForFrameStats[k] = 1.0;
    m_ctuWeights[k] = 1.0;
  }
#elif IBRC360AblationMode == 7
  {
    const int group = rc360EnvInt("RC360_GAIN_ORACLE_GROUP", int(IBRC360GainOracleGroup));
    const double oracleW = clipDouble(rc360EnvDouble("RC360_GAIN_ORACLE_WREF", double(IBRC360GainOracleWref)),
                                      double(IBRC360GainWrefMin),
                                      double(IBRC360GainWrefMax));
    const double wTopThr = rc360Percentile(m_ctuWeights, 0.90, 1.0);
    const double wBotThr = rc360Percentile(m_ctuWeights, 0.10, 1.0);
    const double ieffTopThr = rc360Percentile(m_ctuIeff, 0.90, 0.0);
    const double ieffBotThr = rc360Percentile(m_ctuIeff, 0.10, 0.0);
    const double residualTopThr = rc360Percentile(m_ctuOldIeffFormulaRaw, 0.90, 0.0);
    const double drefTopThr = rc360Percentile(m_ctuDref, 0.90, 0.0);
    int selectedCtus = 0;
    for (int k = 0; k < numCtus; k++)
    {
      const int ctuY = pcv.widthInCtus > 0 ? k / pcv.widthInCtus : 0;
      const int y = ctuY * pcv.maxCUHeight;
      const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);
      const double phi = calcLatitudeRad(y + std::max(1, h) / 2, pcv.lumaHeight);
      const double absLatDeg = std::abs(phi) * 180.0 / 3.14159265358979323846;
      bool selected = false;
      switch (group)
      {
      case 1:  selected = m_ctuWeights[k] >= wTopThr; break;
      case 2:  selected = m_ctuWeights[k] <= wBotThr; break;
      case 3:  selected = m_ctuIeff[k] >= ieffTopThr; break;
      case 4:  selected = m_ctuIeff[k] <= ieffBotThr; break;
      case 5:  selected = m_ctuOldIeffFormulaRaw[k] >= residualTopThr; break;
      case 8:  selected = absLatDeg < 30.0; break;
      case 9:  selected = absLatDeg >= 30.0 && absLatDeg < 60.0; break;
      case 10: selected = absLatDeg >= 60.0; break;
      case 11: selected = m_ctuDref[k] >= drefTopThr; break;
      default: selected = false; break;
      }
      m_ctuWeights[k] = selected ? oracleW : 1.0;
      feedbackWForFrameStats[k] = m_ctuWeights[k];
      rawWForFrameStats[k] = m_ctuWeights[k];
      selectedCtus += selected ? 1 : 0;
    }
    std::printf("[RC360FbTc][GainOracle] POC=%d group=%d oracleW=%.9f selectedCtus=%d numCtus=%d wTopThr=%.9f wBotThr=%.9f ieffTopThr=%.9f ieffBotThr=%.9f residualTopThr=%.9f drefTopThr=%.9f skipGroupsAppliedInEnc=%d\n",
                pic->getPOC(), group, oracleW, selectedCtus, numCtus,
                wTopThr, wBotThr, ieffTopThr, ieffBotThr, residualTopThr, drefTopThr,
                (group == 6 || group == 7) ? 1 : 0);
    std::fflush(stdout);
  }
#elif IBRC360AblationMode == 8 || IBRC360AblationMode == 9
  {
    std::vector<double> logScore(numCtus, 0.0);
    for (int k = 0; k < numCtus; k++)
    {
      const int ctuY = pcv.widthInCtus > 0 ? k / pcv.widthInCtus : 0;
      const int y = ctuY * pcv.maxCUHeight;
      const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);
      const double phi = calcLatitudeRad(y + std::max(1, h) / 2, pcv.lumaHeight);
      const double cosPhi = clipDouble(std::cos(std::abs(phi)), 0.05, 1.0);
      const double ieffTerm = std::sqrt(std::max(1e-9, m_ctuIeff[k]));
      const double residualTerm = std::sqrt(std::max(1e-9, m_ctuOldIeffFormulaRaw[k]));
      const double drefTerm = 1.0 + 0.15 * std::log1p(std::max(0.0, m_ctuDref[k]));
      const double score = std::max(1e-12, cosPhi * ieffTerm * residualTerm * drefTerm);
      logScore[k] = std::log(score);
    }
    const double meanLogScore = rc360MeanFinite(logScore, 0.0);
    const double stdLogScore = std::max(1e-6, rc360StdFinite(logScore, meanLogScore));
    const double kGain = double(IBRC360GainWrefK);
    const double gainMin = double(IBRC360GainWrefMin);
    const double gainMax = double(IBRC360GainWrefMax);
    double meanGainW = 0.0;
    for (int k = 0; k < numCtus; k++)
    {
      const double z = (logScore[k] - meanLogScore) / stdLogScore;
      const double w = clipDouble(std::exp(kGain * z), gainMin, gainMax);
      m_ctuWeights[k] = w;
      meanGainW += w;
    }
    meanGainW = numCtus > 0 ? meanGainW / double(numCtus) : 1.0;
    meanGainW = std::max(1e-12, meanGainW);
    double sumGainW = 0.0;
    double sumGainW2 = 0.0;
    double minGainW = std::numeric_limits<double>::max();
    double maxGainW = 0.0;
    for (int k = 0; k < numCtus; k++)
    {
      const double w = clipDouble(m_ctuWeights[k] / meanGainW, gainMin, gainMax);
      m_ctuWeights[k] = w;
      feedbackWForFrameStats[k] = w;
      rawWForFrameStats[k] = w;
      sumGainW += w;
      sumGainW2 += w * w;
      minGainW = std::min(minGainW, w);
      maxGainW = std::max(maxGainW, w);
    }
    const double finalMeanGainW = numCtus > 0 ? sumGainW / double(numCtus) : 1.0;
    const double finalStdGainW =
      numCtus > 0 ? std::sqrt(std::max(0.0, sumGainW2 / double(numCtus) - finalMeanGainW * finalMeanGainW)) : 0.0;
    std::printf("[RC360FbTc][GainWref] POC=%d mode=%d k=%.9f min=%.9f max=%.9f meanLogScore=%.9f stdLogScore=%.9f meanW=%.9f stdW=%.9f minW=%.9f maxW=%.9f\n",
                pic->getPOC(), IBRC360AblationMode, kGain, gainMin, gainMax,
                meanLogScore, stdLogScore, finalMeanGainW, finalStdGainW,
                numCtus > 0 ? minGainW : 1.0, numCtus > 0 ? maxGainW : 1.0);
    std::fflush(stdout);
  }
#elif IBRC360AblationMode == 3
  for (int k = 0; k < numCtus; k++)
  {
    m_ctuWeights[k] = clipDouble(m_ctuWeights[k], double(IBRC360AblationWrefMin), double(IBRC360AblationWrefMax));
  }
#endif
#if IBRC360GopFirstNoWref && (IBRC360AblationMode == 2 || IBRC360GopFirstNoWrefAllModes)
  const int gopFirstNoWrefSize = std::max(1, IBRC360GopFirstNoWrefGopSize);
  const bool gopFirstNoWrefFrame = (pic->getPOC() % gopFirstNoWrefSize) == 0;
  if (gopFirstNoWrefFrame)
  {
    for (int k = 0; k < numCtus; k++)
    {
      feedbackWForFrameStats[k] = 1.0;
      rawWForFrameStats[k] = 1.0;
      m_ctuWeights[k] = 1.0;
    }
    std::printf("[RC360FbTc][GopFirstNoWref] POC=%d gopSize=%d effectiveWref=1.000000 ablationMode=%d\n",
                pic->getPOC(), gopFirstNoWrefSize, IBRC360AblationMode);
    std::fflush(stdout);
  }
#endif
  double minRawW = std::numeric_limits<double>::max();
  double maxRawW = 0.0;
  double sumFeedbackW = 0.0;
  double sumRawW = 0.0;
  double sumFinalW = 0.0;
  double sumIeff = 0.0;
  double sumDref = 0.0;
  double sumDtar = 0.0;
  int rawModulatedCtus = 0;
  for (int k = 0; k < numCtus; k++)
  {
    minRawW = std::min(minRawW, rawWForFrameStats[k]);
    maxRawW = std::max(maxRawW, rawWForFrameStats[k]);
    sumFeedbackW += feedbackWForFrameStats[k];
    sumRawW += rawWForFrameStats[k];
    sumFinalW += m_ctuWeights[k];
    sumIeff += m_ctuIeff[k];
    sumDref += m_ctuDref[k];
    sumDtar += m_ctuDtar[k];
    if (std::abs(rawWForFrameStats[k] - 1.0) > 1e-6)
    {
      rawModulatedCtus++;
    }
  }
  const double meanRawW = numCtus > 0 ? sumRawW / double(numCtus) : 1.0;
  const double meanFinalW = numCtus > 0 ? sumFinalW / double(numCtus) : 1.0;
  const double meanDref = numCtus > 0 ? sumDref / double(numCtus) : 0.0;
  const double p75Dref = rc360Percentile(m_ctuDref, 0.75, meanDref);
  const double frameRisk = 0.65 * meanDref + 0.35 * p75Dref;
#if IBRC360RealDtarWref
  const double meanFeedbackW = meanFinalW;
#else
  const double meanFeedbackW = numCtus > 0 ? sumFeedbackW / double(numCtus) : 1.0;
#endif
  double topQuartileFeedbackW = meanFeedbackW;
  if (numCtus > 0)
  {
#if IBRC360RealDtarWref
    std::vector<double> sortedFeedbackW = m_ctuWeights;
#else
    std::vector<double> sortedFeedbackW = feedbackWForFrameStats;
#endif
    std::sort(sortedFeedbackW.begin(), sortedFeedbackW.end());
    const int firstTop = std::max(0, int(sortedFeedbackW.size()) - std::max(1, int(sortedFeedbackW.size() + 3) / 4));
    double sumTop = 0.0;
    int countTop = 0;
    for (int k = firstTop; k < int(sortedFeedbackW.size()); k++)
    {
      sumTop += sortedFeedbackW[k];
      countTop++;
    }
    topQuartileFeedbackW = countTop > 0 ? sumTop / double(countTop) : meanFeedbackW;
  }
  constexpr double ctuFrameDemandTailAlpha = 0.35;
  const double ctuFrameDemand =
    (1.0 - ctuFrameDemandTailAlpha) * meanFeedbackW + ctuFrameDemandTailAlpha * topQuartileFeedbackW;

  std::printf("[RC360FbTc] WrefStats POC=%d ctus=%d rawModulated=%d rawMin=%.6f temporalMeanWref=%.6f rawMean=%.6f rawMax=%.6f meanWref=%.6f finalMeanWref=%.6f topQuartileFeedbackW=%.6f ctuFrameDemand=%.6f ctuFrameDemandTailAlpha=%.6f meanIeff=%.6f meanDref=%.6f p75Dref=%.6f frameRisk=%.6f meanDtar=%.6f\n",
              pic->getPOC(), numCtus, rawModulatedCtus,
              numCtus > 0 ? minRawW : 1.0,
              meanFeedbackW,
              meanRawW,
              numCtus > 0 ? maxRawW : 1.0,
              meanFeedbackW,
              meanFinalW,
              topQuartileFeedbackW,
              ctuFrameDemand,
              ctuFrameDemandTailAlpha,
              numCtus > 0 ? sumIeff / double(numCtus) : 0.0,
              meanDref,
              p75Dref,
              frameRisk,
              numCtus > 0 ? sumDtar / double(numCtus) : 1.0);
  std::fflush(stdout);

  m_currentMeanWref = meanFeedbackW;
  m_currentCtuFrameDemand = ctuFrameDemand;
  m_currentMeanDref = meanDref;
  m_currentP75Dref = p75Dref;
  m_currentFrameRisk = frameRisk;
  m_currentWrefStatsValid = true;
  m_currentWrefPoc = pic->getPOC();
}

LatFbTempComp::Candidate LatFbTempComp::searchOneReference(
  Picture* curPic,
  Picture* refPic,
  int      listId,
  int      refIdx,
  const CompArea& curArea,
  double   intraCost,
  double   phi
) const
{
  Candidate best;
  best.refPoc = refPic->getPOC();
  best.refIdx = refIdx;
  best.listId = listId;
  best.interCost = std::numeric_limits<double>::max();

  const CPelBuf curOrg = curPic->getOrigBuf(curArea);

  const PreCalcValues& refPcv = *refPic->cs->pcv;
  const int picW = refPcv.lumaWidth;
  const int picH = refPcv.lumaHeight;

  const int x0 = curArea.x;
  const int y0 = curArea.y;
  const int w  = curArea.width;
  const int h  = curArea.height;

  const int minRx = std::max(0, x0 - m_cfg.searchRange);
  const int maxRx = std::min(picW - w, x0 + m_cfg.searchRange);
  const int minRy = std::max(0, y0 - m_cfg.searchRange);
  const int maxRy = std::min(picH - h, y0 + m_cfg.searchRange);

  const int step = std::max(1, m_cfg.searchStep);

  for (int ry = minRy; ry <= maxRy; ry += step)
  {
    for (int rx = minRx; rx <= maxRx; rx += step)
    {
      const CompArea refArea(
        COMPONENT_Y,
        refPcv.chrFormat,
        Position(rx, ry),
        Size(w, h)
      );

      const CPelBuf refRec = refPic->getRecoBuf(refArea);
      const double cost = double(satdDiff(curOrg, refRec));

      if (cost < best.interCost)
      {
        best.interCost = cost;
        best.rx = rx;
        best.ry = ry;
        best.mvx = rx - x0;
        best.mvy = ry - y0;
      }
    }
  }

  best.refDist = calcWeightedRefDist(best.refPoc, best.rx, best.ry, w, h);

  const double q = best.interCost / (intraCost + 1e-9);

  best.delta =
    clipDouble(
      (m_cfg.tauHigh - q) / (m_cfg.tauHigh - m_cfg.tauLow + 1e-9),
      0.0,
      1.0
    );

  const double pi = 3.14159265358979323846;
  const double absPhi = std::min(std::abs(phi), 89.0 * pi / 180.0);
  const double tanPhi = std::tan(absPhi);
  const double mvxNorm = double(best.mvx) / double(std::max(1, w));

  best.eta = std::exp(-m_cfg.kappa * mvxNorm * mvxNorm * tanPhi * tanPhi);
  best.dep = best.delta * best.eta;

  return best;
}

double LatFbTempComp::calcWeightedRefDist(int refPoc, int x, int y, int w, int h) const
{
  auto it = m_refDistPics.find(refPoc);

  if (it == m_refDistPics.end())
  {
    return 0.0;
  }

  const RefDistPic& ref = it->second;

  const int x1 = x;
  const int y1 = y;
  const int x2 = std::min(ref.picW, x + w);
  const int y2 = std::min(ref.picH, y + h);

  if (x2 <= x1 || y2 <= y1)
  {
    return 0.0;
  }

  const int ctuX0 = x1 / ref.ctuW;
  const int ctuY0 = y1 / ref.ctuH;
  const int ctuX1 = (x2 - 1) / ref.ctuW;
  const int ctuY1 = (y2 - 1) / ref.ctuH;

  double weighted = 0.0;
  double areaSum  = 0.0;

  for (int cy = ctuY0; cy <= ctuY1; cy++)
  {
    for (int cx = ctuX0; cx <= ctuX1; cx++)
    {
      if (cx < 0 || cy < 0 || cx >= ref.widthInCtus || cy >= ref.heightInCtus)
      {
        continue;
      }

      const int bx1 = cx * ref.ctuW;
      const int by1 = cy * ref.ctuH;
      const int bx2 = std::min(ref.picW, bx1 + ref.ctuW);
      const int by2 = std::min(ref.picH, by1 + ref.ctuH);

      const int ox1 = std::max(x1, bx1);
      const int oy1 = std::max(y1, by1);
      const int ox2 = std::min(x2, bx2);
      const int oy2 = std::min(y2, by2);

      if (ox2 <= ox1 || oy2 <= oy1)
      {
        continue;
      }

      const double overlapArea = double((ox2 - ox1) * (oy2 - oy1));
      const int ctuAddr = cy * ref.widthInCtus + cx;

      weighted += overlapArea * ref.ctuMse[ctuAddr];
      areaSum  += overlapArea;
    }
  }

  return areaSum > 0.0 ? weighted / areaSum : 0.0;
}

uint64_t LatFbTempComp::satdDiff(const CPelBuf& org, const CPelBuf& ref) const
{
  uint64_t sum = 0;

  const int w = std::min(org.width, ref.width);
  const int h = std::min(org.height, ref.height);

  for (int y = 0; y < h; y += 4)
  {
    for (int x = 0; x < w; x += 4)
    {
      const int bw = std::min(4, w - x);
      const int bh = std::min(4, h - y);

      if (bw != 4 || bh != 4)
      {
        const CPelBuf a(org.bufAt(x, y), org.stride, bw, bh);
        const CPelBuf b(ref.bufAt(x, y), ref.stride, bw, bh);
        sum += sadPartial(a, b, bw, bh);
        continue;
      }

      int d[4][4];
      int m[4][4];

      for (int yy = 0; yy < 4; yy++)
      {
        const Pel* pOrg = org.bufAt(x, y + yy);
        const Pel* pRef = ref.bufAt(x, y + yy);

        for (int xx = 0; xx < 4; xx++)
        {
          d[yy][xx] = int(pOrg[xx]) - int(pRef[xx]);
        }

        const int s0 = d[yy][0] + d[yy][3];
        const int s1 = d[yy][1] + d[yy][2];
        const int s2 = d[yy][1] - d[yy][2];
        const int s3 = d[yy][0] - d[yy][3];

        m[yy][0] = s0 + s1;
        m[yy][1] = s3 + s2;
        m[yy][2] = s0 - s1;
        m[yy][3] = s3 - s2;
      }

      for (int xx = 0; xx < 4; xx++)
      {
        const int s0 = m[0][xx] + m[3][xx];
        const int s1 = m[1][xx] + m[2][xx];
        const int s2 = m[1][xx] - m[2][xx];
        const int s3 = m[0][xx] - m[3][xx];

        sum += std::abs(s0 + s1);
        sum += std::abs(s3 + s2);
        sum += std::abs(s0 - s1);
        sum += std::abs(s3 - s2);
      }
    }
  }

  return (sum + 1) >> 1;
}

uint64_t LatFbTempComp::sadPartial(const CPelBuf& a, const CPelBuf& b, int w, int h) const
{
  uint64_t sum = 0;

  for (int y = 0; y < h; y++)
  {
    const Pel* pa = a.bufAt(0, y);
    const Pel* pb = b.bufAt(0, y);

    for (int x = 0; x < w; x++)
    {
      sum += uint64_t(std::abs(int(pa[x]) - int(pb[x])));
    }
  }

  return sum;
}

uint64_t LatFbTempComp::simpleIntraCost(const CPelBuf& org) const
{
  uint64_t sumPix = 0;
  const int n = std::max(1, int(org.width) * int(org.height));

  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      sumPix += uint64_t(p[x]);
    }
  }

  const int mean = int((sumPix + n / 2) / n);

  uint64_t sum = 0;

  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      sum += uint64_t(std::abs(int(p[x]) - mean));
    }
  }

  return sum;
}

double LatFbTempComp::calcLatitudeRad(int yCenter, int picH) const
{
  const double pi = 3.14159265358979323846;
  const double v = (double(yCenter) + 0.5) / double(std::max(1, picH));

  return (0.5 - v) * pi;
}

#if RC360_FB_TC_IEFF
double LatFbTempComp::calcCtuIeffFromBestRefBlocks(Picture* curPic, Slice* slice, const CompArea& curArea, int ctuRsAddr, const std::vector<Candidate>& candList, double* oldIeffOut) const
{
  if (curPic == nullptr || slice == nullptr || curPic->cs == nullptr || curPic->cs->pcv == nullptr)
  {
    return 0.0;
  }

  const CPelBuf curOrg = curPic->getOrigBuf(curArea);
  const PreCalcValues& curPcv = *curPic->cs->pcv;

  rc360_ieff::IeffCfg cfg;
  cfg.tau        = m_cfg.ieffTau;
  cfg.eta        = m_cfg.ieffEta;
  cfg.minCos     = m_cfg.ieffMinCos;
  cfg.useLog2    = m_cfg.ieffUseLog2;

  const int bitDepth = slice->getSPS()->getBitDepth(ChannelType::LUMA);
  cfg.sampleNorm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;

  double sumIeff = 0.0;
  double sumOldIeff = 0.0;
  double sumRefMeanVarResiRaw = 0.0;
  double sumRefMeanVarResi = 0.0;
  int numRefs = 0;

  for (size_t candIdx = 0; candIdx < candList.size(); candIdx++)
  {
    const Candidate& cand = candList[candIdx];
    const int listId = cand.listId;

    if (listId < 0 || listId > 1)
    {
      continue;
    }

    const RefPicList eList = listId == 0 ? REF_PIC_LIST_0 : REF_PIC_LIST_1;
    const int numRef = slice->getNumRefIdx(eList);

    if (cand.refIdx < 0 || cand.refIdx >= numRef)
    {
      continue;
    }

    Picture* refPic = slice->getRefPic(eList, cand.refIdx);

    if (refPic == nullptr || refPic->cs == nullptr || refPic->cs->pcv == nullptr)
    {
      continue;
    }

    if (m_refDistPics.find(refPic->getPOC()) == m_refDistPics.end())
    {
      continue;
    }

    const PreCalcValues& refPcv = *refPic->cs->pcv;
    if (cand.rx < 0 || cand.ry < 0
        || cand.rx + curArea.width > refPcv.lumaWidth
        || cand.ry + curArea.height > refPcv.lumaHeight)
    {
      continue;
    }

    const CompArea refArea(COMPONENT_Y, refPcv.chrFormat, Position(cand.rx, cand.ry), Size(curArea.width, curArea.height));
    const CPelBuf refReco = refPic->getRecoBuf(refArea);

    double refIeff = 0.0;
    double refOldIeff = 0.0;
    double refVarResiRaw = 0.0;
    double refVarResi = 0.0;
    int blockCount = 0;

    for (int by = 0; by + 16 <= curArea.height; by += 16)
    {
      for (int bx = 0; bx + 16 <= curArea.width; bx += 16)
      {
        const Pel* orgPtr = curOrg.bufAt(bx, by);
        const Pel* refPtr = refReco.bufAt(bx, by);
        const double rowCenter = double(curArea.y + by) + 8.0;
        const double cosPhi = rc360_ieff::cosPhiFromRowCenter(rowCenter, curPcv.lumaHeight);
        const double varResiRaw = rc360_ieff::calcResidualVariance16x16(orgPtr, curOrg.stride, refPtr, refReco.stride, cfg.sampleNorm);
        const double varResi = varResiRaw;
        const double blockIeff = computeIeffBlock16FromOrgAndPredLogged(
          orgPtr,
          curOrg.stride,
          refPtr,
          refReco.stride,
          cosPhi,
          cfg,
          curPic->getPOC(),
          ctuRsAddr,
          refPic->getPOC(),
          listId,
          cand.refIdx,
          blockCount,
          bx,
          by);
        const double oldBlockIeff = computeIeffBlock16OldFromOrgAndPred(
          orgPtr,
          curOrg.stride,
          refPtr,
          refReco.stride,
          cosPhi,
          cfg);

        refIeff += blockIeff;
        refOldIeff += oldBlockIeff;
        refVarResiRaw += varResiRaw;
        refVarResi += varResi;
        blockCount++;
      }
    }

    const double ieff = blockCount > 0 ? refIeff / double(blockCount) : 0.0;
    const double oldIeff = blockCount > 0 ? refOldIeff / double(blockCount) : 0.0;
    const double meanVarResiRaw = blockCount > 0 ? refVarResiRaw / double(blockCount) : 0.0;
    const double meanVarResi = blockCount > 0 ? refVarResi / double(blockCount) : 0.0;
    if (shouldLogCtu(ctuRsAddr))
    {
      std::printf("[RC360FbTc][IeffRef] POC=%d ctu=%d cand=%zu refPoc=%d list=%d refIdx=%d refX=%d refY=%d mvx=%d mvy=%d blockCount=%d meanBlockVarRaw=%.9f meanBlockVar=%.9f sumNewBlockIeff=%.9f refNewMeanIeff=%.9f sumOldBlockIeff=%.9f refOldMeanIeff=%.9f\n",
                  curPic->getPOC(), ctuRsAddr, candIdx, refPic->getPOC(), listId, cand.refIdx,
                  cand.rx, cand.ry, cand.mvx, cand.mvy, blockCount,
                  meanVarResiRaw, meanVarResi, refIeff, ieff, refOldIeff, oldIeff);
      std::fflush(stdout);
    }

    sumIeff += ieff;
    sumOldIeff += oldIeff;
    sumRefMeanVarResiRaw += meanVarResiRaw;
    sumRefMeanVarResi += meanVarResi;
    numRefs++;
  }

  const double ctuIeff = numRefs > 0 ? sumIeff / double(numRefs) : 0.0;
  const double ctuOldIeff = numRefs > 0 ? sumOldIeff / double(numRefs) : 0.0;
  const double ctuMeanVarResiRaw = numRefs > 0 ? sumRefMeanVarResiRaw / double(numRefs) : 0.0;
  const double ctuMeanVarResi = numRefs > 0 ? sumRefMeanVarResi / double(numRefs) : 0.0;
  if (shouldLogCtu(ctuRsAddr))
  {
    std::printf("[RC360FbTc][IeffCTU] POC=%d ctu=%d numRefs=%d meanBlockVarRaw=%.9f meanBlockVar=%.9f sumNewRefIeff=%.9f ctuNewIeff=%.9f sumOldRefIeff=%.9f ctuOldIeff=%.9f\n",
                curPic->getPOC(), ctuRsAddr, numRefs, ctuMeanVarResiRaw, ctuMeanVarResi,
                sumIeff, ctuIeff, sumOldIeff, ctuOldIeff);
    std::fflush(stdout);
  }

  if (oldIeffOut != nullptr)
  {
    *oldIeffOut = ctuOldIeff;
  }

  return ctuIeff;
}
#endif

double LatFbTempComp::calcSimpleIeffProxy(const CPelBuf& org, double phi) const
{
  double mean = 0.0;
  const int n = std::max(1, int(org.width) * int(org.height));

  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      mean += double(p[x]);
    }
  }

  mean /= double(n);

  double var = 0.0;

  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      const double d = double(p[x]) - mean;
      var += d * d;
    }
  }

  var /= double(n);

  const double sphWeight = std::max(0.05, std::cos(std::abs(phi)));

  // Runnable proxy term. Replace with online GC-GIB Ieff when it is available.
  return std::log2(1.0 + var) * sphWeight;
}

double LatFbTempComp::calcTargetDistortion(int qp, double ieff) const
{
  const double qStep = std::pow(2.0, (double(qp) - 4.0) / 6.0);
  const double qStepMse8bit = (qStep * qStep) / 256.0;
#if RC360_FB_TC_IEFF
  const double ieffForDtar = std::log2(1.0 + std::max(0.0, ieff));
#else
  const double ieffForDtar = ieff;
#endif

  return std::max(
    1e-6,
    m_cfg.dtarScale * qStepMse8bit * (1.0 + m_cfg.dtarIeffScale * ieffForDtar)
  );
}
