#include "LatFbTempComp.h"
#include "Rc360Ieff.h"

#include <cstdio>

#if RC360_FB_TC_IEFF
namespace
{
constexpr int RC360_FB_TC_MAX_LOG_CTUS = 50;

bool shouldLogCtu(int ctuRsAddr)
{
  return ctuRsAddr >= 0 && ctuRsAddr < RC360_FB_TC_MAX_LOG_CTUS;
}

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
  const double varResiRaw = rc360_ieff::calcResidualVariance16x16(org, orgStride, ref, refStride);
  const double varResi = varResiRaw / 256.0;

  if (varResi <= 0.0)
  {
    return 0.0;
  }

  cosPhi = rc360_ieff::clampd(std::fabs(cosPhi), cfg.minCos, 1.0);

  const double stretch  = 1.0 / cosPhi;
  const double betaSafe = rc360_ieff::clampd(cfg.beta, 1e-9, 0.999999);
  const int uMax = std::max(0, std::min(15, int(std::floor(15.0 * cosPhi + 1e-9))));

  double blockIeff = 0.0;

  for (int v = 0; v < 16; ++v)
  {
    for (int u = 0; u < 16; ++u)
    {
      const bool supportSkip = (u > uMax);
      const double rho2 = rc360_ieff::getRhoSquareN16(u, v, stretch);
      const bool gateSkip = (!supportSkip && rho2 <= betaSafe);

      double coeffWeight = 0.0;
      double coeffEnergy = 0.0;
      double targetEnergy = 0.0;
      double denom = 0.0;
      double gammaStar = 0.0;
      double iHat = 0.0;
      double contribution = 0.0;

      if (!supportSkip && !gateSkip)
      {
        coeffWeight  = rc360_coeff::DCT2_RURV_N16_RHO060[v][u];
        coeffEnergy  = varResi * coeffWeight;
        targetEnergy = cosPhi * coeffEnergy;
        denom        = betaSafe * std::max(1.0 - rho2, cfg.eps);
        gammaStar    = std::max(0.0, (rho2 - betaSafe) / denom);
        iHat         = 0.5 * std::log2(1.0 + gammaStar);
        contribution = targetEnergy * iHat;
        blockIeff += contribution;
      }

    }
  }

  return blockIeff;
}
} // namespace
#endif

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
  m_ctuWrefRawUnclipped.clear();
  m_ctuWrefRawClipped.clear();
  m_ctuWrefNormUnclipped.clear();
  m_ctuWrefNormClipped.clear();
  m_ctuIeff.clear();
  m_ctuDref.clear();
  m_ctuDtar.clear();
  m_frameWrefRawUnclipped = 1.0;
  m_frameWrefRawClipped = 1.0;
  m_frameWrefNormUnclippedMean = 1.0;
  m_frameWrefNormClippedMean = 1.0;
  m_frameWrefFinalMean = 1.0;
}

double LatFbTempComp::getCtuWeight(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWeights.size())
  {
    return 1.0;
  }
  return m_ctuWeights[ctuRsAddr];
}

double LatFbTempComp::getCtuWrefRawUnclipped(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWrefRawUnclipped.size())
  {
    return 1.0;
  }
  return m_ctuWrefRawUnclipped[ctuRsAddr];
}

double LatFbTempComp::getCtuWrefRawClipped(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWrefRawClipped.size())
  {
    return 1.0;
  }
  return m_ctuWrefRawClipped[ctuRsAddr];
}

double LatFbTempComp::getCtuWrefNormUnclipped(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWrefNormUnclipped.size())
  {
    return 1.0;
  }
  return m_ctuWrefNormUnclipped[ctuRsAddr];
}

double LatFbTempComp::getCtuWrefNormClipped(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuWrefNormClipped.size())
  {
    return 1.0;
  }
  return m_ctuWrefNormClipped[ctuRsAddr];
}

double LatFbTempComp::getCtuIeff(int ctuRsAddr) const
{
  if (ctuRsAddr < 0 || ctuRsAddr >= (int)m_ctuIeff.size())
  {
    return 0.0;
  }
  return m_ctuIeff[ctuRsAddr];
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
      rec.ctuMse[ctuRsAddr] = calcCtuMse8bitNorm(pic, area);
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
  m_ctuWrefRawUnclipped.clear();
  m_ctuWrefRawClipped.clear();
  m_ctuWrefNormUnclipped.clear();
  m_ctuWrefNormClipped.clear();
  m_ctuIeff.clear();
  m_ctuDref.clear();
  m_ctuDtar.clear();
  m_frameWrefRawUnclipped = 1.0;
  m_frameWrefRawClipped = 1.0;
  m_frameWrefNormUnclippedMean = 1.0;
  m_frameWrefNormClippedMean = 1.0;
  m_frameWrefFinalMean = 1.0;

  if (!m_cfg.enabled || pic == nullptr || slice == nullptr || pic->cs == nullptr || pic->cs->pcv == nullptr)
  {
    return;
  }

  const PreCalcValues& pcv = *pic->cs->pcv;
  const int numCtus = pcv.sizeInCtus;

  m_ctuWeights.assign(numCtus, 1.0);
  m_ctuWrefRawUnclipped.assign(numCtus, 1.0);
  m_ctuWrefRawClipped.assign(numCtus, 1.0);
  m_ctuWrefNormUnclipped.assign(numCtus, 1.0);
  m_ctuWrefNormClipped.assign(numCtus, 1.0);
  m_ctuIeff.assign(numCtus, 0.0);
  m_ctuDref.assign(numCtus, 0.0);
  m_ctuDtar.assign(numCtus, 1.0);

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

    double dref = 0.0;

    if (!candList.empty() && invCostSum > 0.0)
    {
      for (size_t n = 0; n < candList.size(); n++)
      {
        const double a = (1.0 / (candList[n].interCost + 1.0)) / invCostSum;
        const double drefContribution = a * a * candList[n].dep * candList[n].refDist;
        dref += drefContribution;
        if (shouldLogCtu(ctuRsAddr))
        {
          std::printf("[RC360FbTc][DrefStep] POC=%d ctu=%d cand=%zu refPoc=%d list=%d refIdx=%d interCost=%.9f invCostSum=%.9f alpha=%.9f alpha2=%.9f dep=%.9f refDist=%.9f contribution=%.9f drefPartial=%.9f\n",
                      pic->getPOC(), ctuRsAddr, n, candList[n].refPoc, candList[n].listId, candList[n].refIdx,
                      candList[n].interCost, invCostSum, a, a * a, candList[n].dep,
                      candList[n].refDist, drefContribution, dref);
          std::fflush(stdout);
        }
      }
    }

#if RC360_FB_TC_IEFF
    double ieff = calcCtuIeffFromSamePosRefs(pic, slice, curArea, ctuRsAddr);
    if (ieff <= 0.0)
    {
      ieff = calcSimpleIeffProxy(curOrg, phi);
      if (shouldLogCtu(ctuRsAddr))
      {
        std::printf("[RC360FbTc][IeffFallback] POC=%d ctu=%d phi=%.9f ieffProxy=%.9f\n",
                    pic->getPOC(), ctuRsAddr, phi, ieff);
        std::fflush(stdout);
      }
    }
#else
    const double ieff = calcSimpleIeffProxy(curOrg, phi);
#endif
    m_ctuIeff[ctuRsAddr] = ieff;
    m_ctuDref[ctuRsAddr] = dref;
  }

  std::vector<double> rawIeff = m_ctuIeff;
  double sumPositiveIeff = 0.0;
  int validIeffCtus = 0;
  constexpr double minPositiveIeff = 1e-9;

  for (int k = 0; k < numCtus; k++)
  {
    if (rawIeff[k] > 0.0)
    {
      sumPositiveIeff += rawIeff[k];
      validIeffCtus++;
    }
  }

  const double meanPositiveIeff =
    validIeffCtus > 0 ? sumPositiveIeff / double(validIeffCtus) : 1.0;
  const double ieffNormDenom = meanPositiveIeff > minPositiveIeff ? meanPositiveIeff : 1.0;

  for (int k = 0; k < numCtus; k++)
  {
    const double positiveIeff = rawIeff[k] > 0.0 ? rawIeff[k] : minPositiveIeff;
    m_ctuIeff[k] = positiveIeff / ieffNormDenom;

    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][IeffNorm] POC=%d ctu=%d rawIeff=%.9f meanPositiveIeff=%.9f normIeff=%.9f\n",
                  pic->getPOC(), k, rawIeff[k], meanPositiveIeff, m_ctuIeff[k]);
      std::fflush(stdout);
    }
  }

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
    const double dtar = calcTargetDistortion(frameQP, ieff);
    m_ctuDtar[ctuRsAddr] = dtar;

    const double rawW =
      1.0 + m_cfg.beta * std::max(0.0, dref / (dtar + 1e-9) - 1.0);
    const double clippedRawW = clipDouble(rawW, m_cfg.wMin, m_cfg.wMax);

    m_ctuWrefRawUnclipped[ctuRsAddr] = rawW;
    m_ctuWrefRawClipped[ctuRsAddr] = clippedRawW;
    m_ctuWeights[ctuRsAddr] = clippedRawW;
    if (shouldLogCtu(ctuRsAddr))
    {
      const double ratio = dref / (dtar + 1e-9);
      const double wRef1 = ratio;
      std::printf("[RC360FbTc][WrefRaw] POC=%d ctu=%d ctuX=%d ctuY=%d x=%d y=%d w=%d h=%d ieff=%.9f rawIeff=%.9f dref=%.9f dtar=%.9f ratio=%.9f wRef1=%.9f beta=%.9f wrefRawUnclipped=%.9f wrefRawClipped=%.9f\n",
                  pic->getPOC(), ctuRsAddr, ctuX, ctuY, x, y, w, h,
                  ieff, rawIeff[ctuRsAddr], dref, dtar, ratio, wRef1, m_cfg.beta, rawW, clippedRawW);
      std::fflush(stdout);
    }
  }

  double meanWRawUnclipped = 0.0;
  double meanWRawClipped = 0.0;

  for (int k = 0; k < numCtus; k++)
  {
    meanWRawUnclipped += m_ctuWrefRawUnclipped[k];
    meanWRawClipped += m_ctuWrefRawClipped[k];
  }

  meanWRawUnclipped = numCtus > 0 ? meanWRawUnclipped / double(numCtus) : 1.0;
  meanWRawClipped = numCtus > 0 ? meanWRawClipped / double(numCtus) : 1.0;

  if (meanWRawUnclipped <= 1e-9)
  {
    meanWRawUnclipped = 1.0;
  }
  if (meanWRawClipped <= 1e-9)
  {
    meanWRawClipped = 1.0;
  }

  m_frameWrefRawUnclipped = meanWRawUnclipped;
  m_frameWrefRawClipped = meanWRawClipped;

  for (int k = 0; k < numCtus; k++)
  {
    const double rawUnclipped = m_ctuWrefRawUnclipped[k];
    const double rawClipped = m_ctuWrefRawClipped[k];
    const double normUnclipped = rawUnclipped / meanWRawUnclipped;
    const double normFromClipped = rawClipped / meanWRawClipped;
    const double finalClippedNorm = clipDouble(normFromClipped, m_cfg.wMin, m_cfg.wMax);

    m_ctuWrefNormUnclipped[k] = normUnclipped;
    m_ctuWrefNormClipped[k] = normFromClipped;
    m_ctuWeights[k] = finalClippedNorm;
    if (shouldLogCtu(k))
    {
      std::printf("[RC360FbTc][WrefNorm] POC=%d ctu=%d rawUnclipped=%.9f frameWrefRawUnclipped=%.9f normUnclipped=%.9f rawClipped=%.9f frameWrefRawClipped=%.9f normFromClipped=%.9f finalClippedNorm=%.9f\n",
                  pic->getPOC(), k, rawUnclipped, meanWRawUnclipped, normUnclipped,
                  rawClipped, meanWRawClipped, normFromClipped, m_ctuWeights[k]);
      std::fflush(stdout);
    }
  }

  double minW = std::numeric_limits<double>::max();
  double maxW = 0.0;
  double sumW = 0.0;
  double minRawUnclipped = std::numeric_limits<double>::max();
  double maxRawUnclipped = 0.0;
  double minRawClipped = std::numeric_limits<double>::max();
  double maxRawClipped = 0.0;
  double sumNormUnclipped = 0.0;
  double sumNormClipped = 0.0;
  double sumIeff = 0.0;
  double sumDref = 0.0;
  double sumDtar = 0.0;
  int modulatedCtus = 0;
  for (int k = 0; k < numCtus; k++)
  {
    minW = std::min(minW, m_ctuWeights[k]);
    maxW = std::max(maxW, m_ctuWeights[k]);
    sumW += m_ctuWeights[k];
    minRawUnclipped = std::min(minRawUnclipped, m_ctuWrefRawUnclipped[k]);
    maxRawUnclipped = std::max(maxRawUnclipped, m_ctuWrefRawUnclipped[k]);
    minRawClipped = std::min(minRawClipped, m_ctuWrefRawClipped[k]);
    maxRawClipped = std::max(maxRawClipped, m_ctuWrefRawClipped[k]);
    sumNormUnclipped += m_ctuWrefNormUnclipped[k];
    sumNormClipped += m_ctuWrefNormClipped[k];
    sumIeff += m_ctuIeff[k];
    sumDref += m_ctuDref[k];
    sumDtar += m_ctuDtar[k];
    if (std::abs(m_ctuWeights[k] - 1.0) > 1e-6)
    {
      modulatedCtus++;
    }
  }
  m_frameWrefNormUnclippedMean = numCtus > 0 ? sumNormUnclipped / double(numCtus) : 1.0;
  m_frameWrefNormClippedMean = numCtus > 0 ? sumNormClipped / double(numCtus) : 1.0;
  m_frameWrefFinalMean = numCtus > 0 ? sumW / double(numCtus) : 1.0;
  std::printf("[RC360FbTc] WrefStats POC=%d ctus=%d modulated=%d rawUnclippedMin=%.6f rawUnclippedMean=%.6f rawUnclippedMax=%.6f rawClippedMin=%.6f rawClippedMean=%.6f rawClippedMax=%.6f normUnclippedMean=%.6f normFromClippedMean=%.6f finalMin=%.6f finalMean=%.6f finalMax=%.6f meanIeff=%.6f meanDref=%.6f meanDtar=%.6f\n",
              pic->getPOC(), numCtus, modulatedCtus,
              minRawUnclipped, m_frameWrefRawUnclipped, maxRawUnclipped,
              minRawClipped, m_frameWrefRawClipped, maxRawClipped,
              m_frameWrefNormUnclippedMean, m_frameWrefNormClippedMean,
              minW, m_frameWrefFinalMean, maxW,
              numCtus > 0 ? sumIeff / double(numCtus) : 0.0,
              numCtus > 0 ? sumDref / double(numCtus) : 0.0,
              numCtus > 0 ? sumDtar / double(numCtus) : 1.0);
  std::fflush(stdout);
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
double LatFbTempComp::calcCtuIeffFromSamePosRefs(Picture* curPic, Slice* slice, const CompArea& curArea, int ctuRsAddr) const
{
  if (curPic == nullptr || slice == nullptr || curPic->cs == nullptr || curPic->cs->pcv == nullptr)
  {
    return 0.0;
  }

  const CPelBuf curOrg = curPic->getOrigBuf(curArea);
  const PreCalcValues& curPcv = *curPic->cs->pcv;

  rc360_ieff::IeffCfg cfg;
  cfg.beta = 0.2;

  const int numLists = slice->isInterB() ? 2 : 1;
  double sumIeff = 0.0;
  double sumRefMeanVarResiRaw = 0.0;
  double sumRefMeanVarResi = 0.0;
  int numRefs = 0;

  for (int listId = 0; listId < numLists; listId++)
  {
    const RefPicList eList = listId == 0 ? REF_PIC_LIST_0 : REF_PIC_LIST_1;
    const int numRef = slice->getNumRefIdx(eList);

    for (int refIdx = 0; refIdx < numRef; refIdx++)
    {
      Picture* refPic = slice->getRefPic(eList, refIdx);

      if (refPic == nullptr || refPic->cs == nullptr || refPic->cs->pcv == nullptr)
      {
        continue;
      }

      if (m_refDistPics.find(refPic->getPOC()) == m_refDistPics.end())
      {
        continue;
      }

      const PreCalcValues& refPcv = *refPic->cs->pcv;
      if (curArea.x < 0 || curArea.y < 0
          || curArea.x + curArea.width > refPcv.lumaWidth
          || curArea.y + curArea.height > refPcv.lumaHeight)
      {
        continue;
      }

      const CompArea refArea(COMPONENT_Y, refPcv.chrFormat, Position(curArea.x, curArea.y), Size(curArea.width, curArea.height));
      const CPelBuf refReco = refPic->getRecoBuf(refArea);

      double refIeff = 0.0;
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
          const double varResiRaw = rc360_ieff::calcResidualVariance16x16(orgPtr, curOrg.stride, refPtr, refReco.stride);
          const double varResi = varResiRaw / 256.0;
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
            refIdx,
            blockCount,
            bx,
            by);

          refIeff += blockIeff;
          refVarResiRaw += varResiRaw;
          refVarResi += varResi;
          blockCount++;
        }
      }

      const double ieff = blockCount > 0 ? refIeff / double(blockCount) : 0.0;
      const double meanVarResiRaw = blockCount > 0 ? refVarResiRaw / double(blockCount) : 0.0;
      const double meanVarResi = blockCount > 0 ? refVarResi / double(blockCount) : 0.0;
      if (shouldLogCtu(ctuRsAddr))
      {
        std::printf("[RC360FbTc][IeffRef] POC=%d ctu=%d refPoc=%d list=%d refIdx=%d blockCount=%d meanBlockVarRaw=%.9f meanBlockVar=%.9f sumBlockIeff=%.9f refMeanIeff=%.9f\n",
                    curPic->getPOC(), ctuRsAddr, refPic->getPOC(), listId, refIdx, blockCount,
                    meanVarResiRaw, meanVarResi, refIeff, ieff);
        std::fflush(stdout);
      }

      sumIeff += ieff;
      sumRefMeanVarResiRaw += meanVarResiRaw;
      sumRefMeanVarResi += meanVarResi;
      numRefs++;
    }
  }

  const double ctuIeff = numRefs > 0 ? sumIeff / double(numRefs) : 0.0;
  const double ctuMeanVarResiRaw = numRefs > 0 ? sumRefMeanVarResiRaw / double(numRefs) : 0.0;
  const double ctuMeanVarResi = numRefs > 0 ? sumRefMeanVarResi / double(numRefs) : 0.0;
  if (shouldLogCtu(ctuRsAddr))
  {
    std::printf("[RC360FbTc][IeffCTU] POC=%d ctu=%d numRefs=%d meanBlockVarRaw=%.9f meanBlockVar=%.9f sumRefIeff=%.9f ctuIeff=%.9f\n",
                curPic->getPOC(), ctuRsAddr, numRefs, ctuMeanVarResiRaw, ctuMeanVarResi, sumIeff, ctuIeff);
    std::fflush(stdout);
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
