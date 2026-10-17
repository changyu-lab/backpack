/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 *
 * Copyright (c) 2010-2023, ITU/ISO/IEC
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *  * Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *  * Neither the name of the ITU/ISO/IEC nor the names of its contributors may
 *    be used to endorse or promote products derived from this software without
 *    specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
 * BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
 * THE POSSIBILITY OF SUCH DAMAGE.
 */

/** \file     EncSlice.cpp
    \brief    slice encoder class
*/

#include "EncSlice.h"
#include "LatFbTempComp.h"
#include "Rc360IbrcModel.h"
#include "Rc360Ieff.h"

#include "EncLib.h"
#include "CommonLib/UnitTools.h"
#include "CommonLib/Picture.h"
#if K0149_BLOCK_STATISTICS
#include "CommonLib/dtrace_blockstatistics.h"
#endif


#include <math.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <string>

//! \ingroup EncoderLib
//! \{

namespace
{
double rc360QStepFromQp(int qp)
{
  return std::pow(2.0, (double(qp) - 4.0) / 6.0);
}

double rc360LatitudeRad(double rowCenter, int picH)
{
  const double pi = 3.14159265358979323846;
  return (0.5 - rowCenter / double(std::max(1, picH))) * pi;
}

uint64_t rc360SadPartial(const CPelBuf& a, const CPelBuf& b, int w, int h)
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

uint64_t rc360SatdDiff(const CPelBuf& org, const CPelBuf& pred)
{
  uint64_t sum = 0;
  const int w = std::min(org.width, pred.width);
  const int h = std::min(org.height, pred.height);

  for (int y = 0; y < h; y += 4)
  {
    for (int x = 0; x < w; x += 4)
    {
      const int bw = std::min(4, w - x);
      const int bh = std::min(4, h - y);

      if (bw != 4 || bh != 4)
      {
        const CPelBuf a(org.bufAt(x, y), org.stride, bw, bh);
        const CPelBuf b(pred.bufAt(x, y), pred.stride, bw, bh);
        sum += rc360SadPartial(a, b, bw, bh);
        continue;
      }

      int d[4][4];
      int m[4][4];

      for (int yy = 0; yy < 4; yy++)
      {
        const Pel* pOrg  = org.bufAt(x, y + yy);
        const Pel* pPred = pred.bufAt(x, y + yy);

        for (int xx = 0; xx < 4; xx++)
        {
          d[yy][xx] = int(pOrg[xx]) - int(pPred[xx]);
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

bool rc360NeedsCsvHeader(const std::string& fileName)
{
  std::ifstream in(fileName.c_str(), std::ios::binary | std::ios::ate);
  return !in.good() || in.tellg() == std::ifstream::pos_type(0);
}

std::string rc360CsvQuote(const std::string& value)
{
  std::string out;
  out.reserve(value.size() + 2);
  out.push_back('"');
  for (char c: value)
  {
    if (c == '"')
    {
      out.push_back('"');
    }
    out.push_back(c);
  }
  out.push_back('"');
  return out;
}

std::ofstream& rc360CtuHeatmapCsv()
{
  static bool initialized = false;
  static std::ofstream out;

  if (!initialized)
  {
    initialized = true;
    const char* fileName = std::getenv("RC360_CTU_HEATMAP_CSV");
    if (fileName != nullptr && fileName[0] != '\0')
    {
      const bool needsHeader = rc360NeedsCsvHeader(fileName);
      out.open(fileName, std::ios::out | std::ios::app);
      if (out.good() && needsHeader)
      {
        out << "poc,sliceType,ctu,ctuX,ctuY,x,y,w,h,Drec,Ieff,Wref,Dref,Dtar,"
               "ctuTargetBits,picTargetBits,actualBits,lambda,QP,refDrecList\n";
      }
    }
  }

  return out;
}

void rc360WriteCtuHeatmapSample(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, EncLib* pEncLib,
                                RateCtrl* pRateCtrl, int ctuRsAddr, int actualBits, double ctuLambda)
{
  std::ofstream& out = rc360CtuHeatmapCsv();
  if (!out.is_open() || !out.good()
      || pcPic == nullptr || pcSlice == nullptr || pEncLib == nullptr || pRateCtrl == nullptr
      || !pEncLib->getUseRateCtrl()
      || !pEncLib->getLatFbTempComp()->isEnabled())
  {
    return;
  }

  const PreCalcValues& pcv = *cs.pcv;
  if (ctuRsAddr < 0 || ctuRsAddr >= pcv.sizeInCtus)
  {
    return;
  }

  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const int x = ctuX * pcv.maxCUWidth;
  const int y = ctuY * pcv.maxCUHeight;
  const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
  const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);
  if (w <= 0 || h <= 0)
  {
    return;
  }

  const TRCLCU& rcCtu = pRateCtrl->getRCPic()->getLCU(ctuRsAddr);
  CodingUnit* cu = cs.getCU(Position(x, y), ChannelType::LUMA);
  const int qp = cu != nullptr ? cu->qp : g_RCInvalidQPValue;
  const char* sliceType = pcSlice->isIntra() ? "I" : (pcSlice->isInterB() ? "B" : "P");
  LatFbTempComp* fb = pEncLib->getLatFbTempComp();

  out.setf(std::ios::fixed);
  out << std::setprecision(9)
      << pcPic->getPOC() << ','
      << sliceType << ','
      << ctuRsAddr << ','
      << ctuX << ','
      << ctuY << ','
      << x << ','
      << y << ','
      << w << ','
      << h << ','
      << fb->getCtuDrec(pcPic, ctuRsAddr) << ','
      << fb->getCtuIeff(ctuRsAddr) << ','
      << fb->getCtuWeight(ctuRsAddr) << ','
      << fb->getCtuDref(ctuRsAddr) << ','
      << fb->getCtuDtar(ctuRsAddr) << ','
      << rcCtu.m_targetBits << ','
      << pRateCtrl->getRCPic()->getTargetBits() << ','
      << actualBits << ','
      << ctuLambda << ','
      << qp << ','
      << rc360CsvQuote(fb->getCtuRefDrecList(ctuRsAddr))
      << '\n';
}

std::ofstream& rc360OracleDumpCsv(const std::string& fileName)
{
  static std::string openedFileName;
  static std::ofstream out;

  if (fileName.empty())
  {
    return out;
  }
  if (!out.is_open() || openedFileName != fileName)
  {
    if (out.is_open())
    {
      out.close();
    }
    const bool needsHeader = rc360NeedsCsvHeader(fileName);
    out.open(fileName.c_str(), std::ios::out | std::ios::app);
    openedFileName = fileName;
    if (out.good() && needsHeader)
    {
      out << "poc,ctu,baseQpLuma,baseLambda,baseQpChroma,actualBits,localYWsMse,localYMse,"
             "frameTargetBits,frameActualBits,ctuX,ctuY,x,y,w,h\n";
    }
  }
  return out;
}

void rc360CalcOracleLocalDist(Picture* pcPic, CodingStructure& cs, const UnitArea& ctuArea,
                              double& yWsSse8bit, double& ySse8bit)
{
  yWsSse8bit = 0.0;
  ySse8bit = 0.0;
  if (pcPic == nullptr || pcPic->cs == nullptr || pcPic->cs->pcv == nullptr)
  {
    return;
  }

  const PreCalcValues& pcv = *pcPic->cs->pcv;
  const CompArea lumaArea = clipArea(ctuArea.Y(), cs.area.Y());
  if (!lumaArea.valid() || lumaArea.width <= 0 || lumaArea.height <= 0)
  {
    return;
  }

  const CPelBuf org = pcPic->getOrigBuf(lumaArea);
  const CPelBuf reco = pcPic->getRecoBuf(lumaArea);
  uint64_t sse = 0;
  for (int y = 0; y < org.height; y++)
  {
    const Pel* pOrg = org.bufAt(0, y);
    const Pel* pReco = reco.bufAt(0, y);
    for (int x = 0; x < org.width; x++)
    {
      const int d = int(pOrg[x]) - int(pReco[x]);
      sse += uint64_t(d * d);
    }
  }

  const int bitDepth = cs.sps->getBitDepth(ChannelType::LUMA);
  const double norm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;
  const double norm2 = norm * norm;
  ySse8bit = double(sse) / norm2;

  const double rowCenter = double(lumaArea.y) + 0.5 * double(lumaArea.height);
  const double phi = rc360LatitudeRad(rowCenter, pcv.lumaHeight);
  const double cosPhi = std::max(std::cos(std::abs(phi)), 1e-6);
  yWsSse8bit = ySse8bit * cosPhi;
}

void rc360WriteOracleBaselineSample(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, EncLib* pEncLib,
                                    RateCtrl* pRateCtrl, const UnitArea& ctuArea, int ctuRsAddr,
                                    int actualBits, double ctuLambda, int qpLuma, int qpChroma)
{
  if (pEncLib == nullptr || !pEncLib->getRc360OracleReplay()->dumpEnabled())
  {
    return;
  }

  std::ofstream& out = rc360OracleDumpCsv(pEncLib->getRc360OracleReplay()->config().dumpFile);
  if (!out.is_open() || !out.good() || pcPic == nullptr || pcSlice == nullptr || pRateCtrl == nullptr)
  {
    return;
  }

  const PreCalcValues& pcv = *cs.pcv;
  if (ctuRsAddr < 0 || ctuRsAddr >= pcv.sizeInCtus)
  {
    return;
  }

  const CompArea lumaArea = clipArea(ctuArea.Y(), cs.area.Y());
  double yWsSse8bit = 0.0;
  double ySse8bit = 0.0;
  rc360CalcOracleLocalDist(pcPic, cs, ctuArea, yWsSse8bit, ySse8bit);

  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const int frameTargetBits = pEncLib->getUseRateCtrl() && pRateCtrl->getRCPic() != nullptr
                            ? pRateCtrl->getRCPic()->getTargetBits() : 0;

  out.setf(std::ios::fixed);
  out << std::setprecision(12)
      << pcPic->getPOC() << ','
      << ctuRsAddr << ','
      << qpLuma << ','
      << ctuLambda << ','
      << qpChroma << ','
      << actualBits << ','
      << yWsSse8bit << ','
      << ySse8bit << ','
      << frameTargetBits << ','
      << 0 << ','
      << ctuX << ','
      << ctuY << ','
      << lumaArea.x << ','
      << lumaArea.y << ','
      << lumaArea.width << ','
      << lumaArea.height
      << '\n';
}

std::ofstream& rc360CtuClosedLoopCsv()
{
  static bool initialized = false;
  static std::ofstream out;

  if (!initialized)
  {
    initialized = true;
    const char* fileName = std::getenv("RC360_CTU_CLOSED_LOOP_CSV");
    if (fileName != nullptr && fileName[0] != '\0')
    {
      const bool needsHeader = rc360NeedsCsvHeader(fileName);
      out.open(fileName, std::ios::out | std::ios::app);
      if (out.good() && needsHeader)
      {
        out << "sequence,mode,targetBitrate,poc,tid,sliceType,ctu,ctuX,ctuY,x,y,w,h,ctuPixels,"
               "Ieff_model,Ieff_rd,Dref,Wref_effective,lambdaPic,lambdaCtu,QS_final,"
               "QP_model,QP_final,QP_clip_before,QP_clip_after,predBits_old,predBits_raw,"
               "rateBias,rateBiasTargetClass,rateBiasSkipClass,rateBiasCtuClass,"
               "actualBits,actualBitsPerPixel,skipRatio,isIntra,picTargetBits,ctuTargetBits,modelUsed,ablationMode\n";
      }
    }
  }

  return out;
}

void rc360WriteCtuClosedLoopSample(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, EncLib* pEncLib,
                                   RateCtrl* pRateCtrl, const UnitArea& ctuArea, int ctuRsAddr,
                                   int actualBits, double ieffModel, double ieffRd, double dref,
                                   double wrefEffective, double lambdaPic, double lambdaCtu,
                                   double qsFinal, int qpModel, int qpFinal, int qpClipBefore,
                                   int qpClipAfter, double predBitsOld, double predBitsRaw,
                                   double rateBias, int rateBiasTargetClass, int rateBiasSkipClass,
                                   int rateBiasCtuClass, int modelUsed)
{
  std::ofstream& out = rc360CtuClosedLoopCsv();
  if (!out.is_open() || !out.good()
      || pcPic == nullptr || pcSlice == nullptr || pEncLib == nullptr || pRateCtrl == nullptr
      || !pEncLib->getUseRateCtrl())
  {
    return;
  }

  const PreCalcValues& pcv = *cs.pcv;
  if (ctuRsAddr < 0 || ctuRsAddr >= pcv.sizeInCtus)
  {
    return;
  }

  const CompArea lumaArea = clipArea(ctuArea.Y(), cs.area.Y());
  if (!lumaArea.valid() || lumaArea.width <= 0 || lumaArea.height <= 0)
  {
    return;
  }

  double skipArea = 0.0;
  double cuAreaSum = 0.0;
  for (const CodingUnit& cu: cs.traverseCUs(ctuArea, ChannelType::LUMA))
  {
    const double area = double(cu.lumaSize().area());
    cuAreaSum += area;
    if (cu.skip)
    {
      skipArea += area;
    }
  }

  const int ctuPixels = std::max(1, int(lumaArea.width * lumaArea.height));
  const double denomArea = cuAreaSum > 0.0 ? cuAreaSum : double(ctuPixels);
  const double skipRatio = skipArea / denomArea;
  const int actualBitsClipped = std::max(0, actualBits);
  const double actualBpp = double(actualBitsClipped) / double(ctuPixels);
  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const char* sliceType = pcSlice->isIntra() ? "I" : (pcSlice->isInterB() ? "B" : "P");
  const char* mode =
#if IBRC360AblationMode == 1
    "A_wref1";
#else
    "Proposed";
#endif

  int picTargetBits = 0;
  int ctuTargetBits = 0;
  if (pEncLib->getUseRateCtrl())
  {
    picTargetBits = pRateCtrl->getRCPic()->getTargetBits();
    ctuTargetBits = pRateCtrl->getRCPic()->getLCU(ctuRsAddr).m_targetBits;
  }

  out.setf(std::ios::fixed);
  out << std::setprecision(12)
      << pEncLib->getRc360CtuExpSequence() << ','
      << mode << ','
      << pEncLib->getTargetBitrate() << ','
      << pcPic->getPOC() << ','
      << pcSlice->getTLayer() << ','
      << sliceType << ','
      << ctuRsAddr << ','
      << ctuX << ','
      << ctuY << ','
      << lumaArea.x << ','
      << lumaArea.y << ','
      << lumaArea.width << ','
      << lumaArea.height << ','
      << ctuPixels << ','
      << ieffModel << ','
      << ieffRd << ','
      << dref << ','
      << wrefEffective << ','
      << lambdaPic << ','
      << lambdaCtu << ','
      << qsFinal << ','
      << qpModel << ','
      << qpFinal << ','
      << qpClipBefore << ','
      << qpClipAfter << ','
      << predBitsOld << ','
      << predBitsRaw << ','
      << rateBias << ','
      << rateBiasTargetClass << ','
      << rateBiasSkipClass << ','
      << rateBiasCtuClass << ','
      << actualBits << ','
      << actualBpp << ','
      << skipRatio << ','
      << (pcSlice->isIntra() ? 1 : 0) << ','
      << picTargetBits << ','
      << ctuTargetBits << ','
      << modelUsed << ','
      << IBRC360AblationMode
      << '\n';
}

std::ofstream& rc360IeffCompareCsv()
{
  static bool initialized = false;
  static std::ofstream out;

  if (!initialized)
  {
    initialized = true;
    const char* fileName = std::getenv("RC360_IEFF_COMPARE_CSV");
    if (fileName != nullptr && fileName[0] != '\0')
    {
      const bool needsHeader = rc360NeedsCsvHeader(fileName);
      out.open(fileName, std::ios::out | std::ios::app);
      if (out.good() && needsHeader)
      {
        out << "poc,sliceType,ctu,ctuX,ctuY,x,y,w,h,"
               "newIeffFormulaRaw,newIeffModelRaw,newIeffMeanNormClip10,"
               "oldIeffFormulaRaw,oldIeffModelRaw,oldIeffMeanNormClip10,"
               "Dref,Wref,ctuTargetBits,picTargetBits,actualBits,lambda,QP\n";
      }
    }
  }

  return out;
}

void rc360WriteIeffCompareSample(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, EncLib* pEncLib,
                                 RateCtrl* pRateCtrl, int ctuRsAddr, int actualBits, double ctuLambda)
{
  std::ofstream& out = rc360IeffCompareCsv();
  if (!out.is_open() || !out.good()
      || pcPic == nullptr || pcSlice == nullptr || pEncLib == nullptr || pRateCtrl == nullptr
      || !pEncLib->getUseRateCtrl()
      || !pEncLib->getLatFbTempComp()->isEnabled())
  {
    return;
  }

  const PreCalcValues& pcv = *cs.pcv;
  if (ctuRsAddr < 0 || ctuRsAddr >= pcv.sizeInCtus)
  {
    return;
  }

  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const int x = ctuX * pcv.maxCUWidth;
  const int y = ctuY * pcv.maxCUHeight;
  const int w = std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x);
  const int h = std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y);
  if (w <= 0 || h <= 0)
  {
    return;
  }

  const TRCLCU& rcCtu = pRateCtrl->getRCPic()->getLCU(ctuRsAddr);
  CodingUnit* cu = cs.getCU(Position(x, y), ChannelType::LUMA);
  const int qp = cu != nullptr ? cu->qp : g_RCInvalidQPValue;
  const char* sliceType = pcSlice->isIntra() ? "I" : (pcSlice->isInterB() ? "B" : "P");
  LatFbTempComp* fb = pEncLib->getLatFbTempComp();

  out.setf(std::ios::fixed);
  out << std::setprecision(9)
      << pcPic->getPOC() << ','
      << sliceType << ','
      << ctuRsAddr << ','
      << ctuX << ','
      << ctuY << ','
      << x << ','
      << y << ','
      << w << ','
      << h << ','
      << fb->getCtuNewIeffFormulaRaw(ctuRsAddr) << ','
      << fb->getCtuModelIeff(ctuRsAddr) << ','
      << fb->getCtuIeff(ctuRsAddr) << ','
      << fb->getCtuOldIeffFormulaRaw(ctuRsAddr) << ','
      << fb->getCtuOldIeffModelRaw(ctuRsAddr) << ','
      << fb->getCtuOldIeffNorm(ctuRsAddr) << ','
      << fb->getCtuDref(ctuRsAddr) << ','
      << fb->getCtuWeight(ctuRsAddr) << ','
      << rcCtu.m_targetBits << ','
      << pRateCtrl->getRCPic()->getTargetBits() << ','
      << actualBits << ','
      << ctuLambda << ','
      << qp
      << '\n';
}

void rc360WriteCtuExpSample(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, EncLib* pEncLib,
                             const UnitArea& ctuArea, int ctuRsAddr, int actualBits, double ctuLambda)
{
  if (!pEncLib->getRc360CtuExp() || actualBits < 0)
  {
    return;
  }

  const std::string& fileName = pEncLib->getRc360CtuExpFile();
  if (fileName.empty())
  {
    return;
  }

  const PreCalcValues& pcv = *cs.pcv;
  const CompArea lumaArea = clipArea(ctuArea.Y(), cs.area.Y());
  if (!lumaArea.valid() || lumaArea.width <= 0 || lumaArea.height <= 0)
  {
    return;
  }

  const double rowCenter = double(lumaArea.y) + 0.5 * double(lumaArea.height);
  const double phi = rc360LatitudeRad(rowCenter, pcv.lumaHeight);
  const double cosPhi = std::max(std::cos(std::abs(phi)), 1e-6);
  const double stretch = 1.0 / cosPhi;

  if (stretch > pEncLib->getRc360CtuExpMaxStretch())
  {
    return;
  }

  const CPelBuf org  = pcPic->getOrigBuf(lumaArea);
  const CPelBuf pred = pcPic->getPredBuf(lumaArea);
  const CPelBuf reco = pcPic->getRecoBuf(lumaArea);

  const int bitDepth = pcSlice->getSPS()->getBitDepth(ChannelType::LUMA);
  const double norm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;
  const double norm2 = norm * norm;
  const int numPixels = std::max(1, int(lumaArea.width * lumaArea.height));

  uint64_t residualSse = 0;
  uint64_t reconSse = 0;
  for (int y = 0; y < org.height; y++)
  {
    const Pel* pOrg  = org.bufAt(0, y);
    const Pel* pPred = pred.bufAt(0, y);
    const Pel* pReco = reco.bufAt(0, y);

    for (int x = 0; x < org.width; x++)
    {
      const int rPred = int(pOrg[x]) - int(pPred[x]);
      const int rReco = int(pOrg[x]) - int(pReco[x]);
      residualSse += uint64_t(rPred * rPred);
      reconSse += uint64_t(rReco * rReco);
    }
  }

  const double residualEnergy = double(residualSse) / double(numPixels) / norm2;
  const double ordinaryMse = double(reconSse) / double(numPixels) / norm2;
  const double weightedMse = ordinaryMse * cosPhi;
  const double satd = double(rc360SatdDiff(org, pred)) / norm;

  double intraArea = 0.0;
  double interArea = 0.0;
  double skipArea = 0.0;
  double cuAreaSum = 0.0;
  int actualQP = pcSlice->getSliceQp();

  for (const auto &cu: cs.traverseCUs(ctuArea, ChannelType::LUMA))
  {
    const double area = double(cu.lumaSize().area());
    cuAreaSum += area;
    if (cu.predMode == MODE_INTRA)
    {
      intraArea += area;
    }
    else if (cu.predMode == MODE_INTER || cu.predMode == MODE_IBC)
    {
      interArea += area;
    }
    if (cu.skip)
    {
      skipArea += area;
    }
    actualQP = cu.qp;
  }

  double nonzeroCoeff = 0.0;
  double coeffCount = 0.0;
  for (const auto &tu: cs.traverseTUs(ctuArea, ChannelType::LUMA))
  {
    const CompArea& tuY = tu.Y();
    if (!tuY.valid())
    {
      continue;
    }
    coeffCount += double(tuY.width * tuY.height);
    if (tu.cbf[COMPONENT_Y] == 0)
    {
      continue;
    }

    const CCoeffBuf coeff = tu.getCoeffs(COMPONENT_Y);
    for (int y = 0; y < coeff.height; y++)
    {
      const TCoeff* row = coeff.bufAt(0, y);
      for (int x = 0; x < coeff.width; x++)
      {
        if (row[x] != 0)
        {
          nonzeroCoeff += 1.0;
        }
      }
    }
  }

  double ieffCtuExpPredRaw = 0.0;
#if RC360_FB_TC_IEFF
  rc360_ieff::IeffCfg ieffCfg;
  ieffCfg.tau        = 0.20;
  ieffCfg.eta        = 0.85;
  ieffCfg.useLog2    = true;
  ieffCfg.sampleNorm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;
  ieffCtuExpPredRaw = rc360_ieff::computeCtuIeffFromOrgAndPred(org.buf, org.stride, pred.buf, pred.stride,
                                                               lumaArea.x, lumaArea.y, lumaArea.width, lumaArea.height,
                                                               pcv.lumaHeight, ieffCfg);
#endif

  const bool writeHeader = rc360NeedsCsvHeader(fileName);
  std::ofstream out(fileName.c_str(), std::ios::out | std::ios::app);
  if (!out.good())
  {
    std::fprintf(stderr, "[RC360CtuExp] failed to open CSV: %s\n", fileName.c_str());
    return;
  }

  if (writeHeader)
  {
    out << "sequence,slice_type,frame_qp,qp,poc,ctu,ctu_x,ctu_y,x,y,w,h,"
        << "latitude_deg,cos_phi,stretch,qs,ctu_lambda,ieff_raw,ieff_raw_source,ieff_ctuexp_pred_raw,"
        << "ieff_model_online,ieff_wref_norm_online,ieff_old_formula_online,ieff_old_model_online,ieff_old_wref_norm_online,"
        << "wref_online,dref_online,dtar_online,"
        << "satd,residual_energy,actual_bits,"
        << "ordinary_mse,latitude_weighted_mse,intra_ratio,inter_ratio,skip_ratio,nonzero_coeff_ratio\n";
  }

  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const double denomArea = cuAreaSum > 0.0 ? cuAreaSum : double(numPixels);
  const double nonzeroRatio = coeffCount > 0.0 ? nonzeroCoeff / coeffCount : 0.0;
  const char sliceType = pcSlice->isIntra() ? 'I' : (pcSlice->isInterP() ? 'P' : 'B');
  const bool hasOnlineIeff = !pcSlice->isIntra() && pEncLib->getLatFbTempComp()->hasCurrentPictureWeights();
  const double ieffModelOnline = hasOnlineIeff
                               ? pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr) : 0.0;
  const double ieffWrefNormOnline = hasOnlineIeff
                                  ? pEncLib->getLatFbTempComp()->getCtuIeff(ctuRsAddr) : 0.0;
  const double ieffOldFormulaOnline = hasOnlineIeff
                                    ? pEncLib->getLatFbTempComp()->getCtuOldIeffFormulaRaw(ctuRsAddr) : 0.0;
  const double ieffOldModelOnline = hasOnlineIeff
                                  ? pEncLib->getLatFbTempComp()->getCtuOldIeffModelRaw(ctuRsAddr) : 0.0;
  const double ieffOldWrefNormOnline = hasOnlineIeff
                                     ? pEncLib->getLatFbTempComp()->getCtuOldIeffNorm(ctuRsAddr) : 0.0;
  const double ieffRaw = hasOnlineIeff ? ieffModelOnline : ieffCtuExpPredRaw;
  const char* ieffRawSource = hasOnlineIeff ? "online_model" : "ctuexp_pred";
  const double wrefOnline = hasOnlineIeff
                          ? pEncLib->getLatFbTempComp()->getCtuWeight(ctuRsAddr) : 1.0;
  const double drefOnline = hasOnlineIeff
                          ? pEncLib->getLatFbTempComp()->getCtuDref(ctuRsAddr) : 0.0;
  const double dtarOnline = hasOnlineIeff
                          ? pEncLib->getLatFbTempComp()->getCtuDtar(ctuRsAddr) : 0.0;

  if (ctuRsAddr < 4)
  {
    std::printf("[RC360CtuExp][IeffRawSelect] POC=%d ctu=%d source=%s before_ctuexp_pred_raw=%.9f after_ieff_raw=%.9f online_model=%.9f online_wref_norm=%.9f old_formula=%.9f old_model=%.9f\n",
                pcPic->getPOC(), ctuRsAddr, ieffRawSource,
                ieffCtuExpPredRaw, ieffRaw, ieffModelOnline, ieffWrefNormOnline,
                ieffOldFormulaOnline, ieffOldModelOnline);
    std::fflush(stdout);
  }

  out << std::setprecision(12)
      << pEncLib->getRc360CtuExpSequence() << ','
      << sliceType << ','
      << pcSlice->getSliceQp() << ','
      << actualQP << ','
      << pcPic->getPOC() << ','
      << ctuRsAddr << ','
      << ctuX << ','
      << ctuY << ','
      << lumaArea.x << ','
      << lumaArea.y << ','
      << lumaArea.width << ','
      << lumaArea.height << ','
      << (phi * 180.0 / 3.14159265358979323846) << ','
      << cosPhi << ','
      << stretch << ','
      << rc360QStepFromQp(actualQP) << ','
      << ctuLambda << ','
      << ieffRaw << ','
      << ieffRawSource << ','
      << ieffCtuExpPredRaw << ','
      << ieffModelOnline << ','
      << ieffWrefNormOnline << ','
      << ieffOldFormulaOnline << ','
      << ieffOldModelOnline << ','
      << ieffOldWrefNormOnline << ','
      << wrefOnline << ','
      << drefOnline << ','
      << dtarOnline << ','
      << satd << ','
      << residualEnergy << ','
      << actualBits << ','
      << ordinaryMse << ','
      << weightedMse << ','
      << (intraArea / denomArea) << ','
      << (interArea / denomArea) << ','
      << (skipArea / denomArea) << ','
      << nonzeroRatio << '\n';
}

struct Rc360IbrcDecision
{
  double lambdaPic = 0.0;
  double lambdaCtu = 0.0;
  double qs = 1.0;
  double predBitsRaw = 0.0;
  double predBits = 0.0;
  double predBpp = 0.0;
  double predD = 0.0;
  double rateBias = 1.0;
  int    rateBiasTargetClass = 0;
  int    rateBiasSkipClass = 0;
  int    rateBiasCtuClass = 0;
  double sumRemBits = 0.0;
  int    qp = 0;
  int    iterations = 0;
};

struct Rc360RateBiasBucket
{
  double logBias = 0.0;
  int count = 0;
};

#if IBRC360RateBias
static Rc360RateBiasBucket g_rc360RateBias[4][4][4];
#endif

int rc360RateBiasTargetClass(RateCtrl* rateCtrl, const PreCalcValues& pcv)
{
  if (rateCtrl == nullptr || rateCtrl->getRCPic() == nullptr)
  {
    return 0;
  }
  const double targetBits = double(std::max(1, rateCtrl->getRCPic()->getTargetBits()));
  const double pixels = double(std::max<int64_t>(1, int64_t(pcv.lumaWidth) * int64_t(pcv.lumaHeight)));
  const double bpp = targetBits / pixels;
  if (bpp < 0.005) return 0;
  if (bpp < 0.012) return 1;
  if (bpp < 0.025) return 2;
  return 3;
}

double rc360RateBiasPredSkipRatio(RateCtrl* rateCtrl, int ctuRsAddr)
{
  if (!rateCtrl || !rateCtrl->getRCPic() || !rateCtrl->getRCSeq())
  {
    return 0.0;
  }
  const int frameLevel = rateCtrl->getRCPic()->getFrameLevel();
  return rc360ClipPositive(rateCtrl->getRCSeq()->getLCUPara(frameLevel, ctuRsAddr).m_skipRatio, 0.0, 1.0);
}

int rc360RateBiasSkipClass(double skipRatio)
{
  const double r = rc360ClipPositive(skipRatio, 0.0, 1.0);
  if (r < 0.25) return 0;
  if (r < 0.50) return 1;
  if (r < 0.75) return 2;
  return 3;
}

int rc360RateBiasCtuClass(const LatFbTempComp* fb, int ctuRsAddr)
{
  if (fb == nullptr)
  {
    return 0;
  }
  const double z = rc360IbrcModelZFromIeff(fb->getCtuModelIeff(ctuRsAddr));
  if (z < -1.0) return 0;
  if (z <  0.0) return 1;
  if (z <  1.0) return 2;
  return 3;
}

double rc360RateBiasValue(int targetClass, int skipClass, int ctuClass)
{
#if IBRC360RateBias
  const int t = Clip3(0, 3, targetClass);
  const int s = Clip3(0, 3, skipClass);
  const int c = Clip3(0, 3, ctuClass);
  return rc360ClipPositive(std::exp(g_rc360RateBias[t][s][c].logBias),
                           double(IBRC360RateBiasMin),
                           double(IBRC360RateBiasMax));
#else
  return 1.0;
#endif
}

#if IBRC360IeffOnlySpendabilityGate
static Rc360RateBiasBucket g_rc360IeffOnlySpendability[4][4][4];
#endif

double rc360IeffOnlySkipSpendGate(double skipRatio)
{
#if IBRC360IeffOnlySpendabilityGate
  const double start = rc360ClipPositive(double(IBRC360IeffOnlySpendSkipStart), 0.0, 1.0);
  const double full = rc360ClipPositive(double(IBRC360IeffOnlySpendSkipFull), start + 1e-6, 1.0);
  const double minGate = rc360ClipPositive(double(IBRC360IeffOnlySpendGateMin), 0.0, 1.0);
  const double skip = rc360ClipPositive(skipRatio, 0.0, 1.0);
  if (skip <= start)
  {
    return 1.0;
  }
  if (skip >= full)
  {
    return minGate;
  }
  const double t = (skip - start) / std::max(1e-12, full - start);
  return minGate + (1.0 - minGate) * (1.0 - t);
#else
  (void)skipRatio;
  return 1.0;
#endif
}

double rc360IeffOnlyHistSpendRatio(int targetClass, int skipClass, int ctuClass, int* outCount = nullptr)
{
#if IBRC360IeffOnlySpendabilityGate
  const int t = Clip3(0, 3, targetClass);
  const int s = Clip3(0, 3, skipClass);
  const int c = Clip3(0, 3, ctuClass);
  const Rc360RateBiasBucket& bucket = g_rc360IeffOnlySpendability[t][s][c];
  if (outCount != nullptr)
  {
    *outCount = bucket.count;
  }
  return rc360ClipPositive(std::exp(bucket.logBias), 1e-6, 1e6);
#else
  (void)targetClass;
  (void)skipClass;
  (void)ctuClass;
  if (outCount != nullptr)
  {
    *outCount = 0;
  }
  return 1.0;
#endif
}

double rc360IeffOnlyHistSpendGate(int targetClass, int skipClass, int ctuClass,
                                  double* outRatio = nullptr, int* outCount = nullptr)
{
#if IBRC360IeffOnlySpendabilityGate
  int count = 0;
  const double ratio = rc360IeffOnlyHistSpendRatio(targetClass, skipClass, ctuClass, &count);
  if (outRatio != nullptr)
  {
    *outRatio = ratio;
  }
  if (outCount != nullptr)
  {
    *outCount = count;
  }
  if (count < int(IBRC360IeffOnlySpendHistMinCount) || ratio >= 1.0)
  {
    return 1.0;
  }
  const double gate = std::pow(rc360ClipPositive(ratio, 1e-6, 1.0),
                               rc360ClipPositive(double(IBRC360IeffOnlySpendHistAlpha), 0.0, 4.0));
  return rc360ClipPositive(gate, double(IBRC360IeffOnlySpendGateMin), 1.0);
#else
  (void)targetClass;
  (void)skipClass;
  (void)ctuClass;
  if (outRatio != nullptr)
  {
    *outRatio = 1.0;
  }
  if (outCount != nullptr)
  {
    *outCount = 0;
  }
  return 1.0;
#endif
}

void rc360IeffOnlySpendabilityUpdate(int targetClass, int skipClass, int ctuClass,
                                     double predBits, int actualBits, int poc, int ctuRsAddr)
{
#if IBRC360IeffOnlySpendabilityGate
  if (!std::isfinite(predBits) || predBits < 1.0)
  {
    return;
  }
  const double actual = std::max(0.25, double(std::max(0, actualBits)));
  const double residualRaw = std::log(actual / rc360ClipPositive(predBits, 1e-9, 1e12));
  if (!std::isfinite(residualRaw))
  {
    return;
  }
  const double residualClip = std::max(0.0, double(IBRC360IeffOnlySpendHistResidualClip));
  const double residual = Clip3(-residualClip, residualClip, residualRaw);
  const int t = Clip3(0, 3, targetClass);
  const int s = Clip3(0, 3, skipClass);
  const int c = Clip3(0, 3, ctuClass);
  Rc360RateBiasBucket& bucket = g_rc360IeffOnlySpendability[t][s][c];
  const double lr = rc360ClipPositive(double(IBRC360IeffOnlySpendHistLearnRate), 0.0, 1.0);
  const double before = std::exp(bucket.logBias);
  bucket.logBias = Clip3(std::log(1e-3), std::log(1e3), bucket.logBias + lr * residual);
  bucket.count++;
  if (ctuRsAddr < 50)
  {
    std::printf("[RC360IBRC][IeffSpendUpdate] POC=%d ctu=%d targetClass=%d skipClass=%d ctuClass=%d actualBits=%d predBits=%.9f residualRaw=%.9f residualLog=%.9f spendRatioBefore=%.9f spendRatioAfter=%.9f count=%d learnRate=%.9f\n",
                poc, ctuRsAddr, t, s, c, actualBits, predBits, residualRaw, residual,
                before, std::exp(bucket.logBias), bucket.count, lr);
    std::fflush(stdout);
  }
#else
  (void)targetClass;
  (void)skipClass;
  (void)ctuClass;
  (void)predBits;
  (void)actualBits;
  (void)poc;
  (void)ctuRsAddr;
#endif
}

[[maybe_unused]] void rc360RateBiasUpdate(int targetClass, int skipClass, int ctuClass,
                         double predBitsCorrected, int actualBits, int poc, int ctuRsAddr)
{
#if IBRC360RateBias
  const double pred = rc360ClipPositive(predBitsCorrected, 1e-9, 1e12);
  const double actual = rc360ClipPositive(std::max(1.0, double(actualBits)), 1.0, 1e12);
  const double residualRaw = std::log(actual / pred);
  if (!std::isfinite(residualRaw))
  {
    return;
  }
  const double residualClip = std::max(0.0, double(IBRC360RateBiasResidualClip));
  const double residual = Clip3(-residualClip, residualClip, residualRaw);
  const int t = Clip3(0, 3, targetClass);
  const int s = Clip3(0, 3, skipClass);
  const int c = Clip3(0, 3, ctuClass);
  Rc360RateBiasBucket& bucket = g_rc360RateBias[t][s][c];
  const double lr = rc360ClipPositive(double(IBRC360RateBiasLearnRate), 0.0, 1.0);
  const double minLog = std::log(std::max(1e-9, double(IBRC360RateBiasMin)));
  const double maxLog = std::log(std::max(double(IBRC360RateBiasMin), double(IBRC360RateBiasMax)));
  const double before = std::exp(bucket.logBias);
  bucket.logBias = Clip3(minLog, maxLog, bucket.logBias + lr * residual);
  bucket.count++;
  if (ctuRsAddr < 50)
  {
    std::printf("[RC360IBRC][RateBiasUpdate] POC=%d ctu=%d targetClass=%d skipClass=%d ctuClass=%d actualBits=%d predBitsCorrected=%.9f residualRaw=%.9f residualLog=%.9f biasBefore=%.9f biasAfter=%.9f count=%d learnRate=%.9f\n",
                poc, ctuRsAddr, t, s, c, actualBits, predBitsCorrected, residualRaw,
                residual, before, std::exp(bucket.logBias), bucket.count, lr);
    std::fflush(stdout);
  }
#endif
}

struct Rc360IbrcOracleMapCache
{
  std::string fileName;
  bool loaded = false;
  std::map<std::pair<int, int>, double> weights;
};

std::vector<std::string> rc360SplitCsvLine(const std::string& line)
{
  std::vector<std::string> out;
  std::stringstream ss(line);
  std::string item;
  while (std::getline(ss, item, ','))
  {
    out.push_back(item);
  }
  return out;
}

double rc360IbrcOracleWeight(const std::string& fileName, int poc, int ctuRsAddr)
{
  static Rc360IbrcOracleMapCache cache;
  if (fileName.empty())
  {
    return 1.0;
  }
  if (!cache.loaded || cache.fileName != fileName)
  {
    cache.fileName = fileName;
    cache.loaded = true;
    cache.weights.clear();

    std::ifstream in(fileName.c_str());
    if (!in.good())
    {
      std::fprintf(stderr, "[RC360IBRC][OracleMap] failed to open CSV: %s\n", fileName.c_str());
      return 1.0;
    }

    std::string line;
    if (!std::getline(in, line))
    {
      return 1.0;
    }
    const std::vector<std::string> header = rc360SplitCsvLine(line);
    int pocCol = -1;
    int ctuCol = -1;
    int weightCol = -1;
    for (int i = 0; i < int(header.size()); i++)
    {
      if (header[i] == "poc")
      {
        pocCol = i;
      }
      else if (header[i] == "ctu")
      {
        ctuCol = i;
      }
      else if (header[i] == "weight")
      {
        weightCol = i;
      }
    }
    if (pocCol < 0 || ctuCol < 0 || weightCol < 0)
    {
      std::fprintf(stderr, "[RC360IBRC][OracleMap] expected columns poc,ctu,weight: %s\n", fileName.c_str());
      return 1.0;
    }

    while (std::getline(in, line))
    {
      const std::vector<std::string> fields = rc360SplitCsvLine(line);
      if (int(fields.size()) <= std::max(pocCol, std::max(ctuCol, weightCol)))
      {
        continue;
      }
      try
      {
        const int rowPoc = std::stoi(fields[pocCol]);
        const int rowCtu = std::stoi(fields[ctuCol]);
        const double parsedWeight = std::stod(fields[weightCol]);
        const double weight = std::isfinite(parsedWeight) ? Clip3(0.25, 4.0, parsedWeight) : 1.0;
        cache.weights[std::make_pair(rowPoc, rowCtu)] = weight;
      }
      catch (...)
      {
      }
    }
    std::printf("[RC360IBRC][OracleMap] loaded file=%s entries=%d\n",
                fileName.c_str(), int(cache.weights.size()));
    std::fflush(stdout);
  }

  const auto it = cache.weights.find(std::make_pair(poc, ctuRsAddr));
  return it != cache.weights.end() ? it->second : 1.0;
}

double rc360CtuOrdinaryMse(Picture* pcPic, CodingStructure& cs, Slice* pcSlice, const UnitArea& ctuArea)
{
  const CompArea lumaArea = clipArea(ctuArea.Y(), cs.area.Y());
  if (!lumaArea.valid() || lumaArea.width <= 0 || lumaArea.height <= 0)
  {
    return 0.0;
  }

  const CPelBuf org = pcPic->getOrigBuf(lumaArea);
  const CPelBuf reco = pcPic->getRecoBuf(lumaArea);
  const int bitDepth = pcSlice->getSPS()->getBitDepth(ChannelType::LUMA);
  const double norm = bitDepth > 8 ? double(1 << (bitDepth - 8)) : 1.0;
  const double norm2 = norm * norm;
  const int numPixels = std::max(1, int(lumaArea.width * lumaArea.height));
  uint64_t sse = 0;
  for (int y = 0; y < org.height; y++)
  {
    const Pel* pOrg = org.bufAt(0, y);
    const Pel* pReco = reco.bufAt(0, y);
    for (int x = 0; x < org.width; x++)
    {
      const int d = int(pOrg[x]) - int(pReco[x]);
      sse += uint64_t(d * d);
    }
  }
  return double(sse) / double(numPixels) / norm2;
}

[[maybe_unused]] double rc360CtuChromaGradient(Picture* pcPic, CodingStructure& cs, const UnitArea& ctuArea)
{
  (void)cs;
  if (pcPic == nullptr || !isChromaEnabled(pcPic->chromaFormat))
  {
    return 0.0;
  }

  const auto compGradient = [&](ComponentID compID) -> double
  {
    const CompArea area = clipArea(CompArea(compID, pcPic->chromaFormat, Area(ctuArea.lumaPos(), ctuArea.lumaSize()), true),
                                   pcPic->block(compID));
    if (!area.valid() || area.width <= 1 || area.height <= 1)
    {
      return 0.0;
    }
    const CPelBuf org = pcPic->getOrigBuf(area);
    uint64_t sum = 0;
    int count = 0;
    for (int y = 0; y < org.height; y++)
    {
      const Pel* row = org.bufAt(0, y);
      for (int x = 1; x < org.width; x++)
      {
        sum += uint64_t(std::abs(int(row[x]) - int(row[x - 1])));
        count++;
      }
    }
    for (int y = 1; y < org.height; y++)
    {
      const Pel* row = org.bufAt(0, y);
      const Pel* prev = org.bufAt(0, y - 1);
      for (int x = 0; x < org.width; x++)
      {
        sum += uint64_t(std::abs(int(row[x]) - int(prev[x])));
        count++;
      }
    }
    return count > 0 ? double(sum) / double(count) : 0.0;
  };

  return 0.5 * (compGradient(COMPONENT_Cb) + compGradient(COMPONENT_Cr));
}

[[maybe_unused]] double rc360CtuLumaGradient(Picture* pcPic, CodingStructure& cs, const UnitArea& ctuArea)
{
  (void)cs;
  if (pcPic == nullptr)
  {
    return 0.0;
  }

  const CompArea area = clipArea(ctuArea.Y(), pcPic->block(COMPONENT_Y));
  if (!area.valid() || area.width <= 1 || area.height <= 1)
  {
    return 0.0;
  }

  const CPelBuf org = pcPic->getOrigBuf(area);
  uint64_t sum = 0;
  int count = 0;
  for (int y = 0; y < org.height; y++)
  {
    const Pel* row = org.bufAt(0, y);
    for (int x = 1; x < org.width; x++)
    {
      sum += uint64_t(std::abs(int(row[x]) - int(row[x - 1])));
      count++;
    }
  }
  for (int y = 1; y < org.height; y++)
  {
    const Pel* row = org.bufAt(0, y);
    const Pel* prev = org.bufAt(0, y - 1);
    for (int x = 0; x < org.width; x++)
    {
      sum += uint64_t(std::abs(int(row[x]) - int(prev[x])));
      count++;
    }
  }
  return count > 0 ? double(sum) / double(count) : 0.0;
}

[[maybe_unused]] double rc360PercentileValue(std::vector<double> values, double p, double fallback)
{
  values.erase(std::remove_if(values.begin(), values.end(),
                              [](double v) { return !std::isfinite(v); }),
               values.end());
  if (values.empty())
  {
    return fallback;
  }

  std::sort(values.begin(), values.end());
  const double clippedP = Clip3(0.0, 1.0, p);
  const double pos = clippedP * double(values.size() - 1);
  const int lo = int(std::floor(pos));
  const int hi = std::min<int>(lo + 1, int(values.size() - 1));
  const double frac = pos - double(lo);
  return values[lo] * (1.0 - frac) + values[hi] * frac;
}

void rc360IbrcUpdateModelState(Rc360IbrcModelState& model,
                               double stepR, double stepD, double qs, double ieffNorm,
                               double predBpp, double actualBpp,
                               double predD, double actualD,
                               double& rateErrOut, double& distErrOut)
{
  const double x = std::log(rc360ClipPositive(qs, 0.125, 512.0));
  const double rateErr = std::log(rc360ClipPositive(actualBpp, 1e-12, 1e6))
                       - std::log(rc360ClipPositive(predBpp, 1e-12, 1e6));
  const double distErr = std::log(rc360ClipPositive(actualD, 1e-12, 1e12))
                       - std::log(rc360ClipPositive(predD, 1e-12, 1e12));
  rateErrOut = rateErr;
  distErrOut = distErr;

  if (stepR > 0.0 && std::isfinite(rateErr))
  {
    model.rate.c0 += stepR * rateErr;
    model.rate.c1 += stepR * rateErr * x;
    model.rate.c1 = Clip3(-4.0, -0.05, model.rate.c1);
  }
  if (stepD > 0.0 && std::isfinite(distErr))
  {
    model.dist.c0 += stepD * distErr;
    model.dist.c1 += stepD * distErr * x;
    model.dist.c1 = Clip3(-2.0, -0.01, model.dist.c1);
  }
}

[[maybe_unused]] void rc360IbrcOnlineModelUpdate(double stepR, double stepD, double qs, double ieffNorm,
                                double predBpp, double actualBpp,
                                double predD, double actualD,
                                int poc, int ctuRsAddr)
{
  rc360IbrcInitModelFromEnv();
  Rc360IbrcModelState model = { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL };
  double rateErr = 0.0;
  double distErr = 0.0;
  rc360IbrcUpdateModelState(model, stepR, stepD, qs, ieffNorm, predBpp, actualBpp, predD, actualD,
                            rateErr, distErr);
  RC360_IBRC_RATE_MODEL = model.rate;
  RC360_IBRC_DIST_MODEL = model.dist;

  if (ctuRsAddr < 50)
  {
    std::printf("[RC360IBRC][ModelUpdate] POC=%d ctu=%d stepR=%.9f stepD=%.9f actualBpp=%.12f predBpp=%.12f rateErr=%.9f rateC0=%.9f rateC1=%.9f actualOrdMse=%.9f predOrdMse=%.9f distErr=%.9f distC0=%.9f distC1=%.9f\n",
                poc, ctuRsAddr, stepR, stepD, actualBpp, predBpp, rateErr,
                RC360_IBRC_RATE_MODEL.c0, RC360_IBRC_RATE_MODEL.c1,
                actualD, predD, distErr, RC360_IBRC_DIST_MODEL.c0, RC360_IBRC_DIST_MODEL.c1);
    std::fflush(stdout);
  }
}

double rc360IbrcPredSkipRatio(RateCtrl* rateCtrl, int ctuRsAddr)
{
  if (!rateCtrl || !rateCtrl->getRCPic() || !rateCtrl->getRCSeq())
  {
    return 0.0;
  }
  const int frameLevel = rateCtrl->getRCPic()->getFrameLevel();
  return rc360ClipPositive(rateCtrl->getRCSeq()->getLCUPara(frameLevel, ctuRsAddr).m_skipRatio, 0.0, 1.0);
}

#if IBRC360SplitSkipModel
struct Rc360IbrcModelSample
{
  double qs = 1.0;
  double ieffNorm = 1.0;
  double actualBpp = 0.0;
  double actualD = 0.0;
  int poc = 0;
  int ctu = 0;
  int predSkipClass = 0;
  int actualSkipClass = 0;
  double predSkipRatio = 0.0;
  double actualSkipRatio = 0.0;
};

[[maybe_unused]] void rc360IbrcUpdateCtuSkipModel(double stepR, double stepD, const Rc360IbrcModelSample& sample)
{
  Rc360IbrcModelState& model = rc360IbrcCtuSkipModel(sample.actualSkipClass);
  const double predBpp = rc360IbrcRateBpp(model, sample.qs, sample.ieffNorm);
  const double predD = rc360IbrcDistMse(model, sample.qs, sample.ieffNorm);
  double rateErr = 0.0;
  double distErr = 0.0;
  rc360IbrcUpdateModelState(model, stepR, stepD, sample.qs, sample.ieffNorm,
                            predBpp, sample.actualBpp, predD, sample.actualD,
                            rateErr, distErr);
  if (sample.ctu < 50)
  {
    std::printf("[RC360IBRC][SplitCtuModelUpdate] POC=%d ctu=%d predSkipRatio=%.9f actualSkipRatio=%.9f predSkipClass=%d actualSkipClass=%d actualBpp=%.12f predBpp=%.12f rateErr=%.9f rateC0=%.9f rateC1=%.9f actualOrdMse=%.9f predOrdMse=%.9f distErr=%.9f distC0=%.9f distC1=%.9f\n",
                sample.poc, sample.ctu, sample.predSkipRatio, sample.actualSkipRatio,
                sample.predSkipClass, sample.actualSkipClass, sample.actualBpp, predBpp, rateErr,
                model.rate.c0, model.rate.c1, sample.actualD, predD, distErr, model.dist.c0, model.dist.c1);
    std::fflush(stdout);
  }
}

[[maybe_unused]] void rc360IbrcUpdateFrameModelAfterPicture(double stepR, double stepD, const std::vector<Rc360IbrcModelSample>& samples, int poc)
{
  Rc360IbrcModelState& model = rc360IbrcFrameModel();
  int count = 0;
  double sumRateErr = 0.0;
  double sumDistErr = 0.0;
  for (const Rc360IbrcModelSample& sample : samples)
  {
    const double predBpp = rc360IbrcRateBpp(model, sample.qs, sample.ieffNorm);
    const double predD = rc360IbrcDistMse(model, sample.qs, sample.ieffNorm);
    double rateErr = 0.0;
    double distErr = 0.0;
    rc360IbrcUpdateModelState(model, stepR, stepD, sample.qs, sample.ieffNorm,
                              predBpp, sample.actualBpp, predD, sample.actualD,
                              rateErr, distErr);
    if (std::isfinite(rateErr))
    {
      sumRateErr += rateErr;
    }
    if (std::isfinite(distErr))
    {
      sumDistErr += distErr;
    }
    count++;
  }
  if (count > 0)
  {
    std::printf("[RC360IBRC][SplitFrameModelUpdate] POC=%d samples=%d meanRateErr=%.9f meanDistErr=%.9f rateC0=%.9f rateC1=%.9f distC0=%.9f distC1=%.9f\n",
                poc, count, sumRateErr / double(count), sumDistErr / double(count),
                model.rate.c0, model.rate.c1, model.dist.c0, model.dist.c1);
    std::fflush(stdout);
  }
}
#endif

int rc360CtuNumPixels(const PreCalcValues& pcv, int ctuRsAddr)
{
  const int ctuX = ctuRsAddr % pcv.widthInCtus;
  const int ctuY = ctuRsAddr / pcv.widthInCtus;
  const int x = ctuX * pcv.maxCUWidth;
  const int y = ctuY * pcv.maxCUHeight;
  const int w = std::max(0, std::min<int>(pcv.maxCUWidth,  pcv.lumaWidth  - x));
  const int h = std::max(0, std::min<int>(pcv.maxCUHeight, pcv.lumaHeight - y));
  return std::max(1, w * h);
}

int rc360IbrcQpFromQs(double qs, int qpMin, int qpMax)
{
  const double q = rc360ClipPositive(qs, 0.125, 512.0);
  const int qp = int(std::floor(6.0 * std::log(q) / std::log(2.0) + 4.0 + 0.5));
  return Clip3(qpMin, qpMax, qp);
}

int rc360IbrcQpFromQsUnclipped(double qs)
{
  const double q = rc360ClipPositive(qs, 0.125, 512.0);
  return int(std::floor(6.0 * std::log(q) / std::log(2.0) + 4.0 + 0.5));
}

double rc360AblationEffectiveWref(double wRef)
{
#if IBRC360AblationMode == 1
  return 1.0;
#elif IBRC360AblationMode == 3
  const double w = rc360ClipPositive(wRef, 1e-6, 1e6);
  return rc360ClipPositive(w, double(IBRC360AblationWrefMin), double(IBRC360AblationWrefMax));
#else
  const double w = rc360ClipPositive(wRef, 1e-6, 1e6);
  return w;
#endif
}

double rc360WrefSpendabilityGateFromSkip(double skipRatio)
{
#if IBRC360WrefSpendabilityGate
  const double skip = rc360ClipPositive(skipRatio, 0.0, 1.0);
  const double start = rc360ClipPositive(double(IBRC360WrefSpendSkipStart), 0.0, 1.0);
  const double full = rc360ClipPositive(double(IBRC360WrefSpendSkipFull), start + 1e-6, 1.0);
  const double minGate = rc360ClipPositive(double(IBRC360WrefSpendGateMin), 0.0, 1.0);
  if (skip <= start)
  {
    return 1.0;
  }
  const double t = rc360ClipPositive((skip - start) / std::max(1e-9, full - start), 0.0, 1.0);
  const double smooth = t * t * (3.0 - 2.0 * t);
  return rc360ClipPositive(1.0 - (1.0 - minGate) * smooth, minGate, 1.0);
#else
  (void)skipRatio;
  return 1.0;
#endif
}

double rc360SpendabilityEffectiveWref(double rawWref, double predSkipRatio)
{
  const double w = rc360AblationEffectiveWref(rawWref);
#if IBRC360AblationMode == 7
  int oracleGroup = IBRC360GainOracleGroup;
  double oracleWref = IBRC360GainOracleWref;
  if (const char* groupEnv = std::getenv("RC360_GAIN_ORACLE_GROUP"))
  {
    try { oracleGroup = std::stoi(groupEnv); } catch (...) {}
  }
  if (const char* wEnv = std::getenv("RC360_GAIN_ORACLE_WREF"))
  {
    try
    {
      const double parsed = std::stod(wEnv);
      if (std::isfinite(parsed))
      {
        oracleWref = parsed;
      }
    }
    catch (...) {}
  }
  const double skip = rc360ClipPositive(predSkipRatio, 0.0, 1.0);
  const bool selected =
    (oracleGroup == 6 && skip <= 0.25)
    || (oracleGroup == 7 && skip >= 0.85);
  if (oracleGroup == 6 || oracleGroup == 7)
  {
    if (selected)
    {
      return rc360ClipPositive(oracleWref, double(IBRC360GainWrefMin), double(IBRC360GainWrefMax));
    }
    return 1.0;
  }
#endif
#if IBRC360WrefSpendabilityGate
  const double gate = rc360WrefSpendabilityGateFromSkip(predSkipRatio);
  if (w > 1.0 || IBRC360WrefSpendGateLowWref)
  {
    return rc360ClipPositive(1.0 + gate * (w - 1.0), 1e-6, 1e6);
  }
#else
  (void)predSkipRatio;
#endif
  return w;
}

int rc360ClosedLoopRateTemporalSegment(int poc)
{
#if IBRC360ClosedLoopRateSegmentSplit
  return poc >= int(IBRC360ClosedLoopRateSegmentPoc) ? 1 : 0;
#else
  (void)poc;
  return 0;
#endif
}

double rc360IeffOnlyModelIeff(const LatFbTempComp* fb, int ctuRsAddr)
{
  const double raw = fb ? fb->getCtuModelIeff(ctuRsAddr) : 1.0;
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyLogQuantileNorm
  return rc360ClipPositive(raw, 1e-12, 1e12);
#elif IBRC360IeffOnlyCtuRD
  return rc360ClipPositive(raw,
                           double(IBRC360IeffOnlyCtuIeffMin),
                           double(IBRC360IeffOnlyCtuIeffMax));
#else
  return rc360ClipPositive(raw, 1e-9, 1e9);
#endif
}

double rc360IeffOnlyImportance(double ieffNorm)
{
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyLogQuantileNorm
  const double u = std::log(rc360ClipPositive(ieffNorm, 1e-12, 1e12));
  const double gamma =
#if IBRC360IeffOnlyLogQuantileAsymmetric
    u >= 0.0 ? double(IBRC360IeffOnlyLogQuantileGamma)
             : double(IBRC360IeffOnlyLogQuantileGammaNegative);
#else
    double(IBRC360IeffOnlyLogQuantileGamma);
#endif
  return rc360ClipPositive(std::exp(gamma * u),
                           double(IBRC360IeffOnlyImportanceMin),
                           double(IBRC360IeffOnlyImportanceMax));
#elif IBRC360IeffOnlyCtuRD
  const double ieff =
    rc360ClipPositive(ieffNorm,
                      double(IBRC360IeffOnlyCtuIeffMin),
                      double(IBRC360IeffOnlyCtuIeffMax));
  return rc360ClipPositive(std::pow(ieff, double(IBRC360IeffOnlyImportanceAlpha)),
                           double(IBRC360IeffOnlyImportanceMin),
                           double(IBRC360IeffOnlyImportanceMax));
#else
  (void)ieffNorm;
  return 1.0;
#endif
}

double rc360IeffOnlyEffectiveImportance(const LatFbTempComp* fb, RateCtrl* rateCtrl, const PreCalcValues& pcv,
                                        int ctuRsAddr, double* outBaseImportance = nullptr,
                                        double* outSpendGate = nullptr, double* outSkipGate = nullptr,
                                        double* outHistGate = nullptr, double* outHistRatio = nullptr,
                                        int* outHistCount = nullptr)
{
  const double ieffNorm = rc360IeffOnlyModelIeff(fb, ctuRsAddr);
  const double baseImportance = rc360IeffOnlyImportance(ieffNorm);
  double spendGate = 1.0;
  double skipGate = 1.0;
  double histGate = 1.0;
  double histRatio = 1.0;
  int histCount = 0;
#if IBRC360IeffOnlySpendabilityGate
  const double skipRatio = rc360RateBiasPredSkipRatio(rateCtrl, ctuRsAddr);
  const int targetClass = rc360RateBiasTargetClass(rateCtrl, pcv);
  const int skipClass = rc360RateBiasSkipClass(skipRatio);
  const int ctuClass = rc360RateBiasCtuClass(fb, ctuRsAddr);
  skipGate = rc360IeffOnlySkipSpendGate(skipRatio);
  histGate = rc360IeffOnlyHistSpendGate(targetClass, skipClass, ctuClass, &histRatio, &histCount);
  spendGate = std::min(skipGate, histGate);
#else
  (void)rateCtrl;
  (void)pcv;
#endif
  if (outBaseImportance != nullptr)
  {
    *outBaseImportance = baseImportance;
  }
  if (outSpendGate != nullptr)
  {
    *outSpendGate = spendGate;
  }
  if (outSkipGate != nullptr)
  {
    *outSkipGate = skipGate;
  }
  if (outHistGate != nullptr)
  {
    *outHistGate = histGate;
  }
  if (outHistRatio != nullptr)
  {
    *outHistRatio = histRatio;
  }
  if (outHistCount != nullptr)
  {
    *outHistCount = histCount;
  }
  return rc360ClipPositive(1.0 + spendGate * (baseImportance - 1.0), 1e-6, 1e6);
}

double rc360QsFromQp(int qp)
{
  return rc360ClipPositive(std::pow(2.0, (double(qp) - 4.0) / 6.0), 0.125, 512.0);
}

double rc360IbrcSumRemainingBits(const LatFbTempComp* fb, const Rc360Uprop* uprop, const PreCalcValues& pcv,
                                 RateCtrl* rateCtrl, int firstCtu, double lambdaPic, int temporalSegment, int poc)
{
  double sumBits = 0.0;
  const int targetClass = rc360RateBiasTargetClass(rateCtrl, pcv);
  for (int ctu = firstCtu; ctu < pcv.sizeInCtus; ctu++)
  {
    const int pixels = rc360CtuNumPixels(pcv, ctu);
    const double predSkipRatio = rc360IbrcPredSkipRatio(rateCtrl, ctu);
#if IBRC360IeffOnlyCtuRD
    (void)predSkipRatio;
    const double ieffNorm = rc360IeffOnlyModelIeff(fb, ctu);
    const double importance = rc360IeffOnlyEffectiveImportance(fb, rateCtrl, pcv, ctu)
                            * (uprop != nullptr ? uprop->getCtuScale(poc, ctu) : 1.0);
    const double lambdaCtu = lambdaPic / std::max(1e-9, importance);
#else
    const double wRef = rc360SpendabilityEffectiveWref(fb->getCtuWeight(ctu), predSkipRatio);
    const double ieffNorm = rc360ClipPositive(fb->getCtuModelIeff(ctu), 1e-9, 1e9);
    const double lambdaCtu = lambdaPic / wRef;
#endif
    const int skipClass = rc360RateBiasSkipClass(rc360RateBiasPredSkipRatio(rateCtrl, ctu));
    const int ctuClass = rc360RateBiasCtuClass(fb, ctu);
    const double rateBias = rc360RateBiasValue(targetClass, skipClass, ctuClass);
#if IBRC360SplitSkipModel
    const int predSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkipRatio(rateCtrl, ctu));
    const double qs = rc360IbrcQsFromLambda(lambdaCtu, ieffNorm);
    sumBits += rc360IbrcClosedLoopRateBits(predSkipClass, targetClass, temporalSegment, qs, ieffNorm, pixels) * rateBias;
#else
    const double qs = rc360IbrcQsFromLambda(lambdaCtu, ieffNorm);
    sumBits += rc360IbrcRateBits(qs, ieffNorm, pixels) * rateBias;
#endif
  }
  return sumBits;
}

[[maybe_unused]] double rc360IbrcSoftControlLog(const LatFbTempComp* fb, int ctuRsAddr, double ieffAlpha)
{
  const double wRef = rc360AblationEffectiveWref(fb->getCtuWeight(ctuRsAddr));
  const double ieffNorm = rc360ClipPositive(fb->getCtuIeff(ctuRsAddr), 1e-6, 1e6);
  return std::log(wRef) + ieffAlpha * std::log(ieffNorm);
}

[[maybe_unused]] double rc360IbrcMeanSoftControlLog(const LatFbTempComp* fb, const PreCalcValues& pcv, double ieffAlpha)
{
  double sum = 0.0;
  int count = 0;
  for (int ctu = 0; ctu < pcv.sizeInCtus; ctu++)
  {
    const double v = rc360IbrcSoftControlLog(fb, ctu, ieffAlpha);
    if (std::isfinite(v))
    {
      sum += v;
      count++;
    }
  }
  return count > 0 ? sum / double(count) : 0.0;
}

double rc360IbrcSpendableSoftControlLog(const LatFbTempComp* fb, RateCtrl* rateCtrl,
                                        int ctuRsAddr, double ieffAlpha)
{
  const double rawWref = fb->getCtuWeight(ctuRsAddr);
  const double predSkipRatio = rc360IbrcPredSkipRatio(rateCtrl, ctuRsAddr);
  const double wRef = rc360SpendabilityEffectiveWref(rawWref, predSkipRatio);
  const double ieffNorm = rc360ClipPositive(fb->getCtuIeff(ctuRsAddr), 1e-6, 1e6);
  return std::log(wRef) + ieffAlpha * std::log(ieffNorm);
}

double rc360IbrcMeanSpendableSoftControlLog(const LatFbTempComp* fb, const PreCalcValues& pcv,
                                            RateCtrl* rateCtrl, double ieffAlpha)
{
  double sum = 0.0;
  int count = 0;
  for (int ctu = 0; ctu < pcv.sizeInCtus; ctu++)
  {
    const double v = rc360IbrcSpendableSoftControlLog(fb, rateCtrl, ctu, ieffAlpha);
    if (std::isfinite(v))
    {
      sum += v;
      count++;
    }
  }
  return count > 0 ? sum / double(count) : 0.0;
}

Rc360IbrcDecision rc360IbrcSolveCtu(const LatFbTempComp* fb, const Rc360Uprop* uprop, const PreCalcValues& pcv,
                                    RateCtrl* rateCtrl, int ctuRsAddr, int remBits, int qpMin, int qpMax, int poc)
{
  rc360IbrcInitModelFromEnv();
  Rc360IbrcDecision out;
  const double targetBits = std::max(1.0, double(remBits));
  const int temporalSegment = rc360ClosedLoopRateTemporalSegment(poc);

  double lo = 1e-6;
  double hi = 1e8;
  for (int i = 0; i < 20 && rc360IbrcSumRemainingBits(fb, uprop, pcv, rateCtrl, ctuRsAddr, lo, temporalSegment, poc) < targetBits; i++)
  {
    lo *= 0.1;
  }
  double prevHiBits = std::numeric_limits<double>::max();
  for (int i = 0; i < 20; i++)
  {
    const double hiBits = rc360IbrcSumRemainingBits(fb, uprop, pcv, rateCtrl, ctuRsAddr, hi, temporalSegment, poc);
    if (hiBits <= targetBits || std::abs(prevHiBits - hiBits) < 1e-6)
    {
      break;
    }
    prevHiBits = hiBits;
    hi *= 10.0;
  }

  for (int iter = 0; iter < 48; iter++)
  {
    const double mid = std::sqrt(lo * hi);
    const double bits = rc360IbrcSumRemainingBits(fb, uprop, pcv, rateCtrl, ctuRsAddr, mid, temporalSegment, poc);
    out.iterations = iter + 1;
    if (bits > targetBits)
    {
      lo = mid;
    }
    else
    {
      hi = mid;
    }
  }

  out.lambdaPic = std::sqrt(lo * hi);
  out.sumRemBits = rc360IbrcSumRemainingBits(fb, uprop, pcv, rateCtrl, ctuRsAddr, out.lambdaPic, temporalSegment, poc);

  const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
  const double ieffNorm = rc360IeffOnlyModelIeff(fb, ctuRsAddr);
#if IBRC360IeffOnlyCtuRD
  const double wRef = rc360IeffOnlyEffectiveImportance(fb, rateCtrl, pcv, ctuRsAddr)
                    * (uprop != nullptr ? uprop->getCtuScale(poc, ctuRsAddr) : 1.0);
  out.lambdaCtu = out.lambdaPic / std::max(1e-9, wRef);
#else
  const double predSkipRatioForWref = rc360IbrcPredSkipRatio(rateCtrl, ctuRsAddr);
  const double wRef = rc360SpendabilityEffectiveWref(fb->getCtuWeight(ctuRsAddr), predSkipRatioForWref);
  out.lambdaCtu = out.lambdaPic / wRef;
#endif
  out.rateBiasTargetClass = rc360RateBiasTargetClass(rateCtrl, pcv);
  out.rateBiasSkipClass = rc360RateBiasSkipClass(rc360RateBiasPredSkipRatio(rateCtrl, ctuRsAddr));
  out.rateBiasCtuClass = rc360RateBiasCtuClass(fb, ctuRsAddr);
  out.rateBias = rc360RateBiasValue(out.rateBiasTargetClass, out.rateBiasSkipClass, out.rateBiasCtuClass);
#if IBRC360SplitSkipModel
  const int predSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkipRatio(rateCtrl, ctuRsAddr));
  out.qs = rc360IbrcQsFromLambda(out.lambdaCtu, ieffNorm);
  out.predBitsRaw = rc360IbrcClosedLoopRateBits(predSkipClass, out.rateBiasTargetClass, temporalSegment,
                                                out.qs, ieffNorm, pixels);
  out.predBits = out.predBitsRaw * out.rateBias;
  out.predBpp = out.predBits / double(pixels);
  out.predD = rc360IbrcDistMse(out.qs, ieffNorm);
#else
  out.qs = rc360IbrcQsFromLambda(out.lambdaCtu, ieffNorm);
  out.predBitsRaw = rc360IbrcRateBits(out.qs, ieffNorm, pixels);
  out.predBits = out.predBitsRaw * out.rateBias;
  out.predBpp = out.predBits / double(pixels);
  out.predD = rc360IbrcDistMse(out.qs, ieffNorm);
#endif
  out.qp = rc360IbrcQpFromQs(out.qs, qpMin, qpMax);
  return out;
}
}

// ====================================================================================================================
// Constructor / destructor / create / destroy
// ====================================================================================================================

EncSlice::EncSlice()
 : m_encCABACTableIdx(I_SLICE)
#if ENABLE_QPA
 , m_adaptedLumaQP(-1)
#endif
{
}

EncSlice::~EncSlice()
{
  destroy();
}

void EncSlice::create(int width, int height, ChromaFormat chromaFormat, uint32_t iMaxCUWidth, uint32_t iMaxCUHeight,
                      uint8_t uhTotalDepth)
{
}

void EncSlice::destroy()
{
  // free lambda and QP arrays
  m_vdRdPicLambda.clear();
  m_vdRdPicQp.clear();
  m_viRdPicQp.clear();
}

void EncSlice::init( EncLib* pcEncLib, const SPS& sps )
{
  m_pcCfg             = pcEncLib;
  m_pcLib             = pcEncLib;
  m_pcListPic         = pcEncLib->getListPic();

  m_pcGOPEncoder      = pcEncLib->getGOPEncoder();
  m_pcCuEncoder       = pcEncLib->getCuEncoder();
  m_pcInterSearch     = pcEncLib->getInterSearch();
  m_CABACWriter       = pcEncLib->getCABACEncoder()->getCABACWriter   (&sps);
  m_CABACEstimator    = pcEncLib->getCABACEncoder()->getCABACEstimator(&sps);
  m_pcTrQuant         = pcEncLib->getTrQuant();
  m_pcRdCost          = pcEncLib->getRdCost();

  // create lambda and QP arrays
  m_vdRdPicLambda.resize(m_pcCfg->getDeltaQpRD() * 2 + 1 );
  m_vdRdPicQp.resize(    m_pcCfg->getDeltaQpRD() * 2 + 1 );
  m_viRdPicQp.resize(    m_pcCfg->getDeltaQpRD() * 2 + 1 );
  m_pcRateCtrl        = pcEncLib->getRateCtrl();
}

void EncSlice::setUpLambda(Slice *slice, const double dLambda, int qp)
{
  m_pcRdCost->resetStore();
  m_pcTrQuant->resetStore();
  // store lambda
  m_pcRdCost ->setLambda( dLambda, slice->getSPS()->getBitDepths() );

  // for RDO
  // in RdCost there is only one lambda because the luma and chroma bits are not separated, instead we weight the distortion of chroma.
  double dLambdas[MAX_NUM_COMPONENT] = { dLambda };
  for( uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++ )
  {
    const ComponentID compID = ComponentID( compIdx );
    int chromaQPOffset       = slice->getPPS()->getQpOffset( compID ) + slice->getSliceChromaQpDelta( compID );
    int               qpc                  = slice->getSPS()->getMappedChromaQpValue(compID, qp) + chromaQPOffset;
    double tmpWeight = pow(2.0, (qp - qpc) / 3.0);   // takes into account of the chroma qp mapping and chroma qp Offset
    if (slice->getDepQuantEnabledFlag())
    {
      tmpWeight *= ( m_pcCfg->getGOPSize() >= 8 ? pow( 2.0, 0.1/3.0 ) : pow( 2.0, 0.2/3.0 ) );  // increase chroma weight for dependent quantization (in order to reduce bit rate shift from chroma to luma)
    }
    m_pcRdCost->setDistortionWeight( compID, tmpWeight );
    dLambdas[compIdx] = dLambda / tmpWeight;
  }

#if RDOQ_CHROMA_LAMBDA
  // for RDOQ
  m_pcTrQuant->setLambdas( dLambdas );
#else
  m_pcTrQuant->setLambda( dLambda );
#endif

  // for SAO
  slice->setLambdas( dLambdas );
}

#if ENABLE_QPA

static inline int apprI3Log2 (const double d) // rounded 3*log2(d)
{
  return d < 1.5e-13 ? -128 : int (floor (3.0 * log (d) / log (2.0) + 0.5));
}

static inline int lumaDQPOffset (const uint32_t avgLumaValue, const int bitDepth)
{
  return (1 - int ((3 * uint64_t (avgLumaValue * avgLumaValue)) >> uint64_t (2 * bitDepth - 1)));
}

static void filterAndCalculateAverageEnergies(const Pel *pSrc, const ptrdiff_t srcStride, double &hpEner,
                                              const int height, const int width,
                                              const uint32_t bitDepth /* luma bit-depth (4-16) */)
{
  uint64_t saAct = 0;

  // skip first row as there may be a black border frame
  pSrc += srcStride;
  // center rows
  for (int y = 1; y < height - 1; y++)
  {
    // skip column as there may be a black border frame

    for (int x = 1; x < width - 1; x++)   // and columns
    {
      const int f = 12 * pSrc[x] - 2 * (pSrc[x - 1] + pSrc[x + 1] + pSrc[x - srcStride] + pSrc[x + srcStride])
                    - pSrc[x - 1 - srcStride] - pSrc[x + 1 - srcStride] - pSrc[x - 1 + srcStride]
                    - pSrc[x + 1 + srcStride];
      saAct += abs (f);
    }
    // skip column as there may be a black border frame
    pSrc += srcStride;
  }
  // skip last row as there may be a black border frame

  hpEner = double(saAct) / double((width - 2) * (height - 2));

  // lower limit, compensate for highpass amplification
  if (hpEner < double(1 << (bitDepth - 4)))
  {
    hpEner = double(1 << (bitDepth - 4));
  }
}

#ifndef GLOBAL_AVERAGING
  #define GLOBAL_AVERAGING 1 // "global" averaging of a_k across a set instead of one picture
#endif

#if GLOBAL_AVERAGING
static double getAveragePictureEnergy(const CPelBuf picOrig, const uint32_t bitDepth)
{
  const double hpEnerPic =
    16.0 * sqrt((3840.0 * 2160.0) / double(picOrig.width * picOrig.height)) * double(1 << (2 * bitDepth - 10));

  return sqrt (hpEnerPic); // square-root of a_pic value
}
#endif

static int getGlaringColorQPOffset (Picture* const pcPic, const int ctuAddr, Slice* const pcSlice,
                                    const int bitDepth,   uint32_t &avgLumaValue)
{
  const PreCalcValues& pcv  = *pcPic->cs->pcv;
  const ChromaFormat chrFmt = pcPic->chromaFormat;
  const uint32_t       chrWidth   = pcv.maxCUWidth >> getChannelTypeScaleX(ChannelType::CHROMA, chrFmt);
  const uint32_t       chrHeight  = pcv.maxCUHeight >> getChannelTypeScaleY(ChannelType::CHROMA, chrFmt);
  const int      midLevel   = 1 << (bitDepth - 1);
  int chrValue = MAX_INT;
  avgLumaValue = (pcSlice != nullptr) ? 0 : (uint32_t)pcPic->getOrigBuf().Y().computeAvg();

  if (ctuAddr >= 0) // luma
  {
    avgLumaValue = (uint32_t)pcPic->m_iOffsetCtu[ctuAddr];
  }
  else if (pcSlice != nullptr)
  {
    for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
    {
      uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );
      avgLumaValue += pcPic->m_iOffsetCtu[ctuRsAddr];
    }
    avgLumaValue = (avgLumaValue + (pcSlice->getNumCtuInSlice() >> 1)) / pcSlice->getNumCtuInSlice();
  }

  for (uint32_t comp = COMPONENT_Cb; comp < MAX_NUM_COMPONENT; comp++)
  {
    const ComponentID compID = (ComponentID)comp;
    int avgCompValue;

    if (ctuAddr >= 0) // chroma
    {
      const CompArea chrArea = clipArea (CompArea (compID, chrFmt, Area ((ctuAddr % pcv.widthInCtus) * chrWidth, (ctuAddr / pcv.widthInCtus) * chrHeight, chrWidth, chrHeight)), pcPic->block (compID));

      avgCompValue = pcPic->getOrigBuf (chrArea).computeAvg();
    }
    else
    {
      avgCompValue = pcPic->getOrigBuf(pcPic->block(compID)).computeAvg();
    }

    if (chrValue > avgCompValue)
    {
      chrValue = avgCompValue;   // minimum of the DC offsets
    }
  }
  CHECK (chrValue < 0, "DC offset cannot be negative!");

  chrValue = (int)avgLumaValue - chrValue;

  if (chrValue > midLevel)
  {
    return apprI3Log2(double(chrValue * chrValue) / double(midLevel * midLevel));
  }

  return 0;
}

static int applyQPAdaptationChroma (Picture* const pcPic, Slice* const pcSlice, EncCfg* const pcEncCfg, const int sliceQP)
{
  const int bitDepth                  = pcSlice->getSPS()->getBitDepth(ChannelType::LUMA);   // overall image bit-depth
  double hpEner[MAX_NUM_COMPONENT] = {0.0, 0.0, 0.0};
  int    optSliceChromaQpOffset[2] = {0, 0};
  int    savedLumaQP               = -1;
  uint32_t meanLuma                = MAX_UINT;

  for (uint32_t comp = 0; comp < getNumberValidComponents (pcPic->chromaFormat); comp++)
  {
    const ComponentID compID = (ComponentID)comp;
    const CPelBuf    picOrig = pcPic->getOrigBuf (pcPic->block (compID));

    filterAndCalculateAverageEnergies (picOrig.buf,    picOrig.stride, hpEner[comp],
                                       picOrig.height, picOrig.width,  bitDepth - (isChroma (compID) ? 1 : 0));
    if (isChroma (compID))
    {
      const int  adaptChromaQPOffset = 2.0 * hpEner[comp] <= hpEner[0] ? 0 : apprI3Log2 (2.0 * hpEner[comp] / hpEner[0]);

      if (savedLumaQP < 0)
      {
#if GLOBAL_AVERAGING
        int     averageAdaptedLumaQP = Clip3 (0, MAX_QP, sliceQP + apprI3Log2 (hpEner[0] / getAveragePictureEnergy (pcPic->getOrigBuf().Y(), bitDepth)));
#else
        int     averageAdaptedLumaQP = Clip3 (0, MAX_QP, sliceQP); // mean slice QP
#endif

        averageAdaptedLumaQP += getGlaringColorQPOffset (pcPic, -1 /*ctuRsAddr*/, nullptr /*pcSlice*/, bitDepth, meanLuma);

        if (averageAdaptedLumaQP > MAX_QP
#if SHARP_LUMA_DELTA_QP
            && (pcEncCfg->getLumaLevelToDeltaQPMapping().mode != LUMALVL_TO_DQP_NUM_MODES)
#endif
            ) averageAdaptedLumaQP = MAX_QP;
#if SHARP_LUMA_DELTA_QP

        // change mean picture QP index based on picture's average luma value (Sharp)
        if (pcEncCfg->getLumaLevelToDeltaQPMapping().mode == LUMALVL_TO_DQP_NUM_MODES)
        {
          if (meanLuma == MAX_UINT)
          {
            meanLuma = pcPic->getOrigBuf().Y().computeAvg();
          }

          averageAdaptedLumaQP = Clip3 (0, MAX_QP, averageAdaptedLumaQP + lumaDQPOffset (meanLuma, bitDepth));
        }
#endif

        savedLumaQP = averageAdaptedLumaQP;
      } // savedLumaQP < 0

      const int lumaChromaMappingDQP = savedLumaQP - pcSlice->getSPS()->getMappedChromaQpValue(compID, savedLumaQP);

      optSliceChromaQpOffset[comp-1] = std::min (3 + lumaChromaMappingDQP, adaptChromaQPOffset + lumaChromaMappingDQP);
    }
  }

  pcEncCfg->setSliceChromaOffsetQpIntraOrPeriodic (pcEncCfg->getSliceChromaOffsetQpPeriodicity(), optSliceChromaQpOffset);

  return savedLumaQP;
}

#endif // ENABLE_QPA

/**
 - non-referenced frame marking
 - QP computation based on temporal structure
 - lambda computation based on QP
 - set temporal layer ID and the parameter sets
 .
 \param pcPic         picture class
 \param pocLast       POC of last picture
 \param pocCurr       current POC
 \param numPicRcvd   number of received pictures
 \param gopId        POC offset for hierarchical structure
 \param rpcSlice      slice header class
 \param isField       true for field coding
 */
void EncSlice::initEncSlice(Picture *pcPic, const int pocLast, const int pocCurr, const int gopId, Slice *&rpcSlice,
                            const bool isField, bool isEncodeLtRef, int layerId, NalUnitType nalType)
{
  double dQP;
  double dLambda;
  PicHeader *picHeader = pcPic->cs->picHeader;
  pcPic->cs->resetPrevPLT(pcPic->cs->prevPLT);

  rpcSlice = pcPic->slices[0];
  rpcSlice->setSliceBits(0);
  rpcSlice->setPic( pcPic );
  rpcSlice->setPicHeader( picHeader );
  rpcSlice->initSlice();
  rpcSlice->setNalUnitLayerId(layerId);

  int multipleFactor = m_pcCfg->getUseCompositeRef() ? 2 : 1;
  if (m_pcCfg->getUseCompositeRef() && isEncodeLtRef)
  {
    picHeader->setPicOutputFlag(false);
  }
  else
  {
    picHeader->setPicOutputFlag(true);
  }
  rpcSlice->setPOC( pocCurr );

  if( m_pcCfg->getCostMode() != COST_LOSSLESS_CODING )
  {
    rpcSlice->setDepQuantEnabledFlag( m_pcCfg->getDepQuantEnabledFlag() );
    rpcSlice->setSignDataHidingEnabledFlag( m_pcCfg->getSignDataHidingEnabledFlag() );
    rpcSlice->setTSResidualCodingDisabledFlag( false );

    CHECK( (m_pcCfg->getDepQuantEnabledFlag() || m_pcCfg->getSignDataHidingEnabledFlag() )
           && rpcSlice->getTSResidualCodingDisabledFlag() , "TSRC cannot be bypassed if either DQ or SDH are enabled at slice level.");
  }
  else
  {
    rpcSlice->setDepQuantEnabledFlag( false ); //should be disabled for lossless
    rpcSlice->setSignDataHidingEnabledFlag( false ); //should be disabled for lossless
    if( m_pcCfg->getTSRCdisableLL() )
    {
      rpcSlice->setTSResidualCodingDisabledFlag( true );
    }
  }

#if SHARP_LUMA_DELTA_QP
  pcPic->fieldPic = isField;
  m_gopID         = gopId;
#endif

  // depth computation based on GOP size
  int hierPredLayerIdx;
  {
    int poc = rpcSlice->getPOC();
    if(isField)
    {
      poc = (poc/2) % (m_pcCfg->getGOPSize()/2);
    }
    else
    {
      poc = poc % (m_pcCfg->getGOPSize() * multipleFactor);
    }

    if ( poc == 0 )
    {
      hierPredLayerIdx = 0;
    }
    else
    {
      int step = m_pcCfg->getGOPSize() * multipleFactor;
      hierPredLayerIdx = 0;
      for( int i=step>>1; i>=1; i>>=1 )
      {
        for (int j = i; j<(m_pcCfg->getGOPSize() * multipleFactor); j += step)
        {
          if ( j == poc )
          {
            i=0;
            break;
          }
        }
        step >>= 1;
        hierPredLayerIdx++;
      }
    }

    if(m_pcCfg->getHarmonizeGopFirstFieldCoupleEnabled() && poc != 0)
    {
      if (isField && ((rpcSlice->getPOC() % 2) == 1))
      {
        hierPredLayerIdx++;
      }
    }
  }

  // slice type
  SliceType eSliceType;

  eSliceType=B_SLICE;
  const bool useIlRef = m_pcCfg->getAvoidIntraInDepLayer() && rpcSlice->getPic()->cs->vps && m_pcCfg->getNumRefLayers(rpcSlice->getPic()->cs->vps->getGeneralLayerIdx(layerId));
  if (m_pcCfg->getIntraPeriod() > 0 )
  {
    if(!(isField && pocLast == 1) || !m_pcCfg->getEfficientFieldIRAPEnabled())
    {
      if(m_pcCfg->getDecodingRefreshType() == 3)
      {
        eSliceType = (pocLast == 0 || pocCurr % (m_pcCfg->getIntraPeriod() * multipleFactor) == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
#if GDR_ENABLED
        if (m_pcCfg->getGdrEnabled() && (pocCurr >= m_pcCfg->getGdrPocStart()) && ((pocCurr - m_pcCfg->getGdrPocStart()) % m_pcCfg->getGdrPeriod() == 0))
        {
          eSliceType = B_SLICE;
        }
#endif
      }
      else
      {
        eSliceType = (pocLast == 0 || (pocCurr - (isField ? 1 : 0)) % (m_pcCfg->getIntraPeriod() * multipleFactor) == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
#if GDR_ENABLED
        if (m_pcCfg->getGdrEnabled() && (pocCurr >= m_pcCfg->getGdrPocStart()) && ((pocCurr - m_pcCfg->getGdrPocStart()) % m_pcCfg->getGdrPeriod() == 0))
        {
          eSliceType = B_SLICE;
        }
#endif
      }
    }
  }
  else
  {
    eSliceType = (pocLast == 0 || pocCurr == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
  }

  rpcSlice->setHierPredLayerIdx(hierPredLayerIdx);
  rpcSlice->setSliceType    ( eSliceType );

  // ------------------------------------------------------------------------------------------------------------------
  // Non-referenced frame marking
  // ------------------------------------------------------------------------------------------------------------------

  pcPic->referenced = true;

  // ------------------------------------------------------------------------------------------------------------------
  // QP setting
  // ------------------------------------------------------------------------------------------------------------------

  rpcSlice->setNalUnitType(nalType);
  dQP = m_pcCfg->getQPForPicture(gopId, rpcSlice);

  // ------------------------------------------------------------------------------------------------------------------
  // Lambda computation
  // ------------------------------------------------------------------------------------------------------------------

  const int temporalId = m_pcCfg->getGOPEntry(gopId).m_temporalId;
#if !SHARP_LUMA_DELTA_QP
  const std::vector<double> &intraLambdaModifiers=m_pcCfg->getIntraLambdaModifier();
#endif
  int    qp;
  double dOrigQP = dQP;

  // pre-compute lambda and QP values for all possible QP candidates
  for ( int iDQpIdx = 0; iDQpIdx < 2 * m_pcCfg->getDeltaQpRD() + 1; iDQpIdx++ )
  {
    // compute QP value
    dQP = dOrigQP + ((iDQpIdx+1)>>1)*(iDQpIdx%2 ? -1 : 1);
    // compute lambda value
#if SHARP_LUMA_DELTA_QP
    dLambda = calculateLambda(rpcSlice, gopId, dQP, dQP, qp);
#else
    dLambda = initializeLambda(rpcSlice, gopId, int(dQP + 0.5), dQP);
    qp      = Clip3(-rpcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, int(dQP + 0.5));
#endif

    m_vdRdPicLambda[iDQpIdx] = dLambda;
    m_vdRdPicQp    [iDQpIdx] = dQP;
    m_viRdPicQp[iDQpIdx]     = qp;
  }

  // obtain dQP = 0 case
  dLambda = m_vdRdPicLambda[0];
  dQP     = m_vdRdPicQp    [0];
  qp      = m_viRdPicQp[0];


#if W0038_CQP_ADJ
 #if ENABLE_QPA
  m_adaptedLumaQP = -1;

  if ((m_pcCfg->getUsePerceptQPA() || m_pcCfg->getSliceChromaOffsetQpPeriodicity() > 0) && !m_pcCfg->getUseRateCtrl() && rpcSlice->getPPS()->getSliceChromaQpFlag() &&
      (rpcSlice->isIntra() || (m_pcCfg->getSliceChromaOffsetQpPeriodicity() > 0 && (rpcSlice->getPOC() % m_pcCfg->getSliceChromaOffsetQpPeriodicity()) == 0)))
  {
    m_adaptedLumaQP = applyQPAdaptationChroma(pcPic, rpcSlice, m_pcCfg, qp);
  }
 #endif
  if(rpcSlice->getPPS()->getSliceChromaQpFlag())
  {
    const bool bUseIntraOrPeriodicOffset = (rpcSlice->isIntra() && !rpcSlice->getSPS()->getIBCFlag()) || (m_pcCfg->getSliceChromaOffsetQpPeriodicity() > 0 && (rpcSlice->getPOC() % m_pcCfg->getSliceChromaOffsetQpPeriodicity()) == 0);
    int        cbQP   = bUseIntraOrPeriodicOffset ? m_pcCfg->getSliceChromaOffsetQpIntraOrPeriodic(false)
                                                  : m_pcCfg->getGOPEntry(gopId).m_CbQPoffset;
    int        crQP   = bUseIntraOrPeriodicOffset ? m_pcCfg->getSliceChromaOffsetQpIntraOrPeriodic(true)
                                                  : m_pcCfg->getGOPEntry(gopId).m_CrQPoffset;
    // adjust chroma QP such that it corresponds to the luma QP change when encoding in reduced resolution
    if (m_pcCfg->getGOPBasedRPREnabledFlag() || m_pcCfg->getRprFunctionalityTestingEnabledFlag())
    {
      auto mappedQpDelta = [&](ComponentID c, int qpOffset) -> int {
        int lumaQpBefore = Clip3(-rpcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, qp - qpOffset);
        const int mappedQpBefore = rpcSlice->getSPS()->getMappedChromaQpValue(c, lumaQpBefore);
        const int mappedQpAfter = rpcSlice->getSPS()->getMappedChromaQpValue(c, qp);
        return mappedQpBefore - mappedQpAfter + qpOffset;
      };
      if (m_pcCfg->getRprFunctionalityTestingEnabledFlag())
      {
        int currPoc = rpcSlice->getPOC() + m_pcCfg->getFrameSkip();
        int rprSegment = m_pcCfg->getRprSwitchingSegment(currPoc);
        cbQP += mappedQpDelta(COMPONENT_Cb, m_pcCfg->getRprSwitchingQPOffsetOrderList(rprSegment));
        crQP += mappedQpDelta(COMPONENT_Cr, m_pcCfg->getRprSwitchingQPOffsetOrderList(rprSegment));
      }
      else
      {
        if (rpcSlice->getPPS()->getPPSId() == (ENC_PPS_ID_RPR + rpcSlice->getNalUnitLayerId())) // ScalingRatioHor/ScalingRatioVer
        {
          cbQP += mappedQpDelta(COMPONENT_Cb, m_pcCfg->getQpOffsetChromaRPR());
          crQP += mappedQpDelta(COMPONENT_Cr, m_pcCfg->getQpOffsetChromaRPR());
        }
        if (rpcSlice->getPPS()->getPPSId() == (ENC_PPS_ID_RPR2 + rpcSlice->getNalUnitLayerId())) // ScalingRatioHor/ScalingRatioVer
        {
          cbQP += mappedQpDelta(COMPONENT_Cb, m_pcCfg->getQpOffsetChromaRPR2());
          crQP += mappedQpDelta(COMPONENT_Cr, m_pcCfg->getQpOffsetChromaRPR2());
        }
        if (rpcSlice->getPPS()->getPPSId() == (ENC_PPS_ID_RPR3 + rpcSlice->getNalUnitLayerId())) // ScalingRatioHor/ScalingRatioVer
        {
          cbQP += mappedQpDelta(COMPONENT_Cb, m_pcCfg->getQpOffsetChromaRPR3());
          crQP += mappedQpDelta(COMPONENT_Cr, m_pcCfg->getQpOffsetChromaRPR3());
        }
      }
    }
    int cbCrQP = (cbQP + crQP) >> 1; // use floor of average chroma QP offset for joint-Cb/Cr coding

    cbQP = Clip3( -12, 12, cbQP + rpcSlice->getPPS()->getQpOffset(COMPONENT_Cb) ) - rpcSlice->getPPS()->getQpOffset(COMPONENT_Cb);
    crQP = Clip3( -12, 12, crQP + rpcSlice->getPPS()->getQpOffset(COMPONENT_Cr) ) - rpcSlice->getPPS()->getQpOffset(COMPONENT_Cr);
    rpcSlice->setSliceChromaQpDelta(COMPONENT_Cb, Clip3( -12, 12, cbQP));
    CHECK(!(rpcSlice->getSliceChromaQpDelta(COMPONENT_Cb)+rpcSlice->getPPS()->getQpOffset(COMPONENT_Cb)<=12 && rpcSlice->getSliceChromaQpDelta(COMPONENT_Cb)+rpcSlice->getPPS()->getQpOffset(COMPONENT_Cb)>=-12), "Unspecified error");
    rpcSlice->setSliceChromaQpDelta(COMPONENT_Cr, Clip3( -12, 12, crQP));
    CHECK(!(rpcSlice->getSliceChromaQpDelta(COMPONENT_Cr)+rpcSlice->getPPS()->getQpOffset(COMPONENT_Cr)<=12 && rpcSlice->getSliceChromaQpDelta(COMPONENT_Cr)+rpcSlice->getPPS()->getQpOffset(COMPONENT_Cr)>=-12), "Unspecified error");
    if (rpcSlice->getSPS()->getJointCbCrEnabledFlag())
    {
      cbCrQP = Clip3(-12, 12, cbCrQP + rpcSlice->getPPS()->getQpOffset(JOINT_CbCr)) - rpcSlice->getPPS()->getQpOffset(JOINT_CbCr);
      rpcSlice->setSliceChromaQpDelta(JOINT_CbCr, Clip3( -12, 12, cbCrQP ));
    }
  }
  else
  {
    rpcSlice->setSliceChromaQpDelta( COMPONENT_Cb, 0 );
    rpcSlice->setSliceChromaQpDelta( COMPONENT_Cr, 0 );
    rpcSlice->setSliceChromaQpDelta( JOINT_CbCr, 0 );
  }
#endif


#if RDOQ_CHROMA_LAMBDA
  m_pcRdCost->setDistortionWeight (COMPONENT_Y, 1.0); // no chroma weighting for luma
#endif
  setUpLambda(rpcSlice, dLambda, qp);

#if WCG_EXT
  // cost = Distortion + Lambda*R,
  // when QP is adjusted by luma, distortion is changed, so we have to adjust lambda to match the distortion, then the cost function becomes
  // costA = Distortion + AdjustedLambda * R          -- currently, costA is still used when calculating intermediate cost of using SAD, HAD, resisual etc.
  // an alternative way is to weight the distortion to before the luma QP adjustment, then the cost function becomes
  // costB = weightedDistortion + Lambda * R          -- currently, costB is used to calculat final cost, and when DF_FUNC is DF_DEFAULT
  m_pcRdCost->saveUnadjustedLambda();
#endif

  if (m_pcCfg->getFastMEForGenBLowDelayEnabled())
  {
    // restore original slice type

    if (m_pcCfg->getIntraPeriod() > 0 )
    {
      if(!(isField && pocLast == 1) || !m_pcCfg->getEfficientFieldIRAPEnabled())
      {
        if(m_pcCfg->getDecodingRefreshType() == 3)
        {
          eSliceType = (pocLast == 0 || pocCurr % (m_pcCfg->getIntraPeriod() * multipleFactor) == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
#if GDR_ENABLED
          if (m_pcCfg->getGdrEnabled() && (pocCurr >= m_pcCfg->getGdrPocStart()) && ((pocCurr - m_pcCfg->getGdrPocStart()) % m_pcCfg->getGdrPeriod() == 0))
          {
            eSliceType = B_SLICE;
          }
#endif
        }
        else
        {
          eSliceType = (pocLast == 0 || (pocCurr - (isField ? 1 : 0)) % (m_pcCfg->getIntraPeriod() * multipleFactor) == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
#if GDR_ENABLED
          if (m_pcCfg->getGdrEnabled() && (pocCurr >= m_pcCfg->getGdrPocStart()) && ((pocCurr - m_pcCfg->getGdrPocStart()) % m_pcCfg->getGdrPeriod() == 0))
          {
            eSliceType = B_SLICE;
          }
#endif
        }
      }
    }
    else
    {
      eSliceType = (pocLast == 0 || pocCurr == 0 || m_pcGOPEncoder->getGOPSize() == 0) && (!useIlRef) ? I_SLICE : eSliceType;
    }

    rpcSlice->setSliceType        ( eSliceType );
  }

  if (m_pcCfg->getUseRecalculateQPAccordingToLambda())
  {
    dQP = xGetQPValueAccordingToLambda( dLambda );
    qp  = Clip3(-rpcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, (int) floor(dQP + 0.5));
  }

  rpcSlice->setSliceQp(qp);
  rpcSlice->setSliceQpDelta      ( 0 );
  pcPic->setLossyQPValue(qp);
  if ((!rpcSlice->getTSResidualCodingDisabledFlag()) && ( rpcSlice->getSPS()->getSpsRangeExtension().getTSRCRicePresentFlag() ))
  {
    rpcSlice->setTsrcIndex(Clip3(MIN_TSRC_RICE, MAX_TSRC_RICE, (int) ((19 - qp) / 6)) - 1);
  }
#if !W0038_CQP_ADJ
  rpcSlice->setSliceChromaQpDelta( COMPONENT_Cb, 0 );
  rpcSlice->setSliceChromaQpDelta( COMPONENT_Cr, 0 );
  rpcSlice->setSliceChromaQpDelta( JOINT_CbCr,   0 );
#endif
  rpcSlice->setUseChromaQpAdj( rpcSlice->getPPS()->getCuChromaQpOffsetListEnabledFlag() && m_pcCfg->getCuChromaQpOffsetEnabled() );
  rpcSlice->setNumRefIdx(REF_PIC_LIST_0, m_pcCfg->getRPLEntry(0, gopId).m_numRefPicsActive);
  rpcSlice->setNumRefIdx(REF_PIC_LIST_1, m_pcCfg->getRPLEntry(1, gopId).m_numRefPicsActive);

  if ( m_pcCfg->getDeblockingFilterMetric() )
  {
    rpcSlice->setDeblockingFilterOverrideFlag(true);
    rpcSlice->setDeblockingFilterDisable(false);
    rpcSlice->setDeblockingFilterBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterTcOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCbBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCbTcOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCrBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCrTcOffsetDiv2( 0 );
  }
  else if (rpcSlice->getPPS()->getDeblockingFilterControlPresentFlag())
  {
    rpcSlice->setDeblockingFilterOverrideFlag(rpcSlice->getPPS()->getDeblockingFilterOverrideEnabledFlag() && !rpcSlice->getPPS()->getPPSDeblockingFilterDisabledFlag());
    rpcSlice->setDeblockingFilterDisable( rpcSlice->getPPS()->getPPSDeblockingFilterDisabledFlag() );
    if ( !rpcSlice->getDeblockingFilterDisable())
    {
      if ( rpcSlice->getDeblockingFilterOverrideFlag() && eSliceType!=I_SLICE)
      {
        rpcSlice->setDeblockingFilterBetaOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_betaOffsetDiv2
                                                    + m_pcCfg->getDeblockingFilterBetaOffset());
        rpcSlice->setDeblockingFilterTcOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_tcOffsetDiv2
                                                  + m_pcCfg->getDeblockingFilterTcOffset());
        if( rpcSlice->getPPS()->getPPSChromaToolFlag() )
        {
          rpcSlice->setDeblockingFilterCbBetaOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_CbBetaOffsetDiv2
                                                        + m_pcCfg->getDeblockingFilterCbBetaOffset());
          rpcSlice->setDeblockingFilterCbTcOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_CbTcOffsetDiv2
                                                      + m_pcCfg->getDeblockingFilterCbTcOffset());
          rpcSlice->setDeblockingFilterCrBetaOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_CrBetaOffsetDiv2
                                                        + m_pcCfg->getDeblockingFilterCrBetaOffset());
          rpcSlice->setDeblockingFilterCrTcOffsetDiv2(m_pcCfg->getGOPEntry(gopId).m_CrTcOffsetDiv2
                                                      + m_pcCfg->getDeblockingFilterCrTcOffset());
        }
        else
        {
          rpcSlice->setDeblockingFilterCbBetaOffsetDiv2( rpcSlice->getDeblockingFilterBetaOffsetDiv2() );
          rpcSlice->setDeblockingFilterCbTcOffsetDiv2  ( rpcSlice->getDeblockingFilterTcOffsetDiv2() );
          rpcSlice->setDeblockingFilterCrBetaOffsetDiv2( rpcSlice->getDeblockingFilterBetaOffsetDiv2() );
          rpcSlice->setDeblockingFilterCrTcOffsetDiv2  ( rpcSlice->getDeblockingFilterTcOffsetDiv2() );
        }
      }
      else
      {
        rpcSlice->setDeblockingFilterBetaOffsetDiv2  ( m_pcCfg->getDeblockingFilterBetaOffset() );
        rpcSlice->setDeblockingFilterTcOffsetDiv2    ( m_pcCfg->getDeblockingFilterTcOffset() );
        rpcSlice->setDeblockingFilterCbBetaOffsetDiv2( m_pcCfg->getDeblockingFilterCbBetaOffset() );
        rpcSlice->setDeblockingFilterCbTcOffsetDiv2  ( m_pcCfg->getDeblockingFilterCbTcOffset() );
        rpcSlice->setDeblockingFilterCrBetaOffsetDiv2( m_pcCfg->getDeblockingFilterCrBetaOffset() );
        rpcSlice->setDeblockingFilterCrTcOffsetDiv2  ( m_pcCfg->getDeblockingFilterCrTcOffset() );
      }
    }
  }
  else
  {
    rpcSlice->setDeblockingFilterOverrideFlag( false );
    rpcSlice->setDeblockingFilterDisable( false );
    rpcSlice->setDeblockingFilterBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterTcOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCbBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCbTcOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCrBetaOffsetDiv2( 0 );
    rpcSlice->setDeblockingFilterCrTcOffsetDiv2( 0 );
  }

  pcPic->temporalId =  temporalId;
  if(eSliceType==I_SLICE)
  {
    pcPic->temporalId = 0;
  }
  rpcSlice->setTLayer( pcPic->temporalId );

  rpcSlice->setDisableSATDForRD(false);

  if( ( m_pcCfg->getIBCHashSearch() && m_pcCfg->getIBCMode() ) || m_pcCfg->getAllowDisFracMMVD() )
  {
    m_pcCuEncoder->getIbcHashMap().destroy();
    m_pcCuEncoder->getIbcHashMap().init( pcPic->cs->pps->getPicWidthInLumaSamples(), pcPic->cs->pps->getPicHeightInLumaSamples() );
  }
#if GDR_ENABLED
  if (m_pcCfg->getGdrEnabled())
  {
    int gdrPocStart = m_pcCuEncoder->getEncCfg()->getGdrPocStart();
    int gdrPeriod = m_pcCuEncoder->getEncCfg()->getGdrPeriod();
    int gdrInterval = m_pcCuEncoder->getEncCfg()->getGdrInterval();

    int picWidth = rpcSlice->getPPS()->getPicWidthInLumaSamples();

    int curPoc = rpcSlice->getPOC();
    int gdrPoc = (curPoc - gdrPocStart) % gdrPeriod;

    pcPic->cs->picHeader->setGdrPicFlag(false);
    pcPic->cs->picHeader->setRecoveryPocCnt(0);

    pcPic->gdrParam.inGdrInterval = false;

    pcPic->cs->picHeader->setVirtualBoundariesPresentFlag(false);

    int  offset = (curPoc < gdrPocStart) ? 0 : (((curPoc - gdrPocStart) / gdrPeriod) * gdrPeriod);
    int  actualGdrStart = gdrPocStart + offset;
    int  actualGdrInterval = std::min(gdrInterval, (int) (pcPic->getPicWidthInLumaSamples() / 8));
    int  recoveryPocCnt = actualGdrInterval - 1;
    int  recoveryPicPoc = actualGdrStart + recoveryPocCnt;

    bool isInGdrInterval = (curPoc >= actualGdrStart) && (curPoc < recoveryPicPoc);
    bool isOutGdrInterval = !isInGdrInterval;
    bool isGdrPic = (actualGdrStart == curPoc);

#if GDR_ENC_TRACE
    printf("\n");
    printf("-poc:%d gdrPocStart:%d actualGdrStart:%d actualGdrInterval:%d actualGdrEndPoc:%d\n", rpcSlice->getPOC(), gdrPocStart, actualGdrStart, actualGdrInterval, recoveryPicPoc - 1);
#endif

    // for none gdr period pictures
    if ((curPoc < gdrPocStart) || isOutGdrInterval)
    {
      pcPic->gdrParam.inGdrInterval = false;
      pcPic->gdrParam.verBoundary = -1;
      pcPic->cs->picHeader->setVirtualBoundariesPresentFlag(false);

      pcPic->cs->picHeader->setNumHorVirtualBoundaries(0);
      pcPic->cs->picHeader->setNumVerVirtualBoundaries(0);

#if GDR_ENC_TRACE
      printf("-poc:%d no virtual boundary\n", rpcSlice->getPOC());
#endif
    }
    // for gdr inteval pictures
    else
    {
      if (curPoc == recoveryPicPoc)
      {
        pcPic->gdrParam.inGdrInterval = false;
      }
      else
      {
        pcPic->gdrParam.inGdrInterval = true;
      }

      pcPic->cs->picHeader->setVirtualBoundariesPresentFlag(true);

      if (isGdrPic)
      {
        pcPic->cs->picHeader->setGdrOrIrapPicFlag(true);
        pcPic->cs->picHeader->setGdrPicFlag(true);

        pcPic->cs->picHeader->setRecoveryPocCnt(recoveryPocCnt);
        m_pcGOPEncoder->setLastGdrIntervalPoc(recoveryPicPoc - 1);
      }

      pcPic->cs->picHeader->setNumHorVirtualBoundaries(0);
      pcPic->cs->picHeader->setNumVerVirtualBoundaries(1);

      int begGdrX;
      int endGdrX;
      int m1, m2, n1;

      double dd = (picWidth / (double)gdrInterval);
      int mm = (int)((picWidth / (double)gdrInterval) + 0.49999);
      m1 = ((mm + 7) >> 3) << 3;
      m2 = ((mm + 0) >> 3) << 3;

      if (dd > mm && m1 == m2)
      {
        m1 = m1 + 8;
      }

      n1 = (picWidth - m2 * gdrInterval) / 8;

      if (gdrPoc < n1)
      {
        begGdrX = m1 * gdrPoc;
        endGdrX = begGdrX + m1;
      }
      else
      {
        begGdrX = m1 * n1 + m2 * (gdrPoc - n1);
        endGdrX = begGdrX + m2;
        if (picWidth <= begGdrX)
        {
          begGdrX = picWidth;
          endGdrX = picWidth;
        }
      }

      pcPic->cs->picHeader->setVirtualBoundariesPosX(endGdrX, 0);
      pcPic->gdrParam.verBoundary = endGdrX;

#if GDR_ENC_TRACE
      printf("\n");
      printf("-poc:%d beg:%d end:%d\n", rpcSlice->getPOC(), begGdrX, endGdrX);
#endif
    }
  }
#endif

  if (rpcSlice->getSPS()->getSpsRangeExtension().getRrcRiceExtensionEnableFlag())
  {
    int bitDepth  = rpcSlice->getSPS()->getBitDepth(ChannelType::LUMA);
    int baseLevel = (bitDepth > 12) ? (rpcSlice->isIntra() ? 5 : 2 * 5) : (rpcSlice->isIntra() ? 2 * 5 : 3 * 5);
    rpcSlice->setRiceBaseLevel(baseLevel);
  }
  else
  {
    rpcSlice->setRiceBaseLevel(4);
  }
}

double EncSlice::initializeLambda(const Slice *slice, const int gopId, const int refQP, const double dQP)
{
  const int                  bitDepthLuma         = slice->getSPS()->getBitDepth(ChannelType::LUMA);
  const int   bitDepthShift = 6 * (bitDepthLuma - 8 - DISTORTION_PRECISION_ADJUSTMENT(bitDepthLuma)) - 12;
  const int   numberBFrames = m_pcCfg->getGOPSize() - 1;
  const SliceType sliceType = slice->getSliceType();
  const int                  temporalId           = m_pcCfg->getGOPEntry(gopId).m_temporalId;
  const std::vector<double> &intraLambdaModifiers = m_pcCfg->getIntraLambdaModifier();
  // case #1: I or P slices (key-frame)
  double dQPFactor = m_pcCfg->getGOPEntry(gopId).m_QPFactor;
  double dLambda, lambdaModifier;

  if (sliceType == I_SLICE)
  {
    if ((m_pcCfg->getIntraQpFactor() >= 0.0) && (m_pcCfg->getGOPEntry(gopId).m_sliceType != I_SLICE))
    {
      dQPFactor = m_pcCfg->getIntraQpFactor();
    }
    else
    {
      if (m_pcCfg->getLambdaFromQPEnable())
      {
        dQPFactor = 0.57;
      }
      else
      {
        dQPFactor =
          0.57 * (1.0 - Clip3(0.0, 0.5, 0.05 * double(slice->getPic()->fieldPic ? numberBFrames >> 1 : numberBFrames)));
      }
    }
  }
  else if (m_pcCfg->getLambdaFromQPEnable())
  {
    dQPFactor = 0.57;
  }

  dLambda = dQPFactor * pow(2.0, (dQP + bitDepthShift) / 3.0);

  if (slice->getHierPredLayerIdx() > 0 && !m_pcCfg->getLambdaFromQPEnable())
  {
    dLambda *= Clip3(2.0, 4.0, ((refQP + bitDepthShift) / 6.0));
  }
  // if Hadamard is used in motion estimation process
  if (!m_pcCfg->getUseHADME() && (sliceType != I_SLICE))
  {
    dLambda *= 0.95;
  }
  if ((sliceType != I_SLICE) || intraLambdaModifiers.empty())
  {
    lambdaModifier = m_pcCfg->getLambdaModifier(temporalId);
  }
  else
  {
    lambdaModifier = intraLambdaModifiers[temporalId < intraLambdaModifiers.size() ? temporalId : intraLambdaModifiers.size() - 1];
  }
  dLambda *= lambdaModifier;

  return dLambda;
}

#if SHARP_LUMA_DELTA_QP || ENABLE_QPA_SUB_CTU
double EncSlice::calculateLambda(const Slice *slice,
                                 const int    gopId,   // entry in the GOP table
                                 const double refQP,   // initial slice-level QP
                                 const double dQP,     // initial double-precision QP
                                 int &        qp)              // returned integer QP.
{
  double dLambda = initializeLambda(slice, gopId, int(refQP + 0.5), dQP);
  qp             = Clip3(-slice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, int(dQP + 0.5));

  if (slice->getDepQuantEnabledFlag())
  {
    dLambda *= pow( 2.0, 0.25/3.0 ); // slight lambda adjustment for dependent quantization (due to different slope of quantizer)
  }

  // NOTE: the lambda modifiers that are sometimes applied later might be best always applied in here.
  return dLambda;
}
#endif

void EncSlice::resetQP( Picture* pic, int sliceQP, double lambda )
{
  Slice* slice = pic->slices[0];

  // store lambda
  slice->setSliceQp( sliceQP );
#if RDOQ_CHROMA_LAMBDA
  m_pcRdCost->setDistortionWeight (COMPONENT_Y, 1.0); // no chroma weighting for luma
#endif
  setUpLambda(slice, lambda, sliceQP);
#if WCG_EXT
  if (!m_pcCfg->getLumaLevelToDeltaQPMapping().isEnabled())
  {
    m_pcRdCost->saveUnadjustedLambda();
  }
#endif
}

#if ENABLE_QPA
static bool applyQPAdaptation (Picture* const pcPic,       Slice* const pcSlice,        const PreCalcValues& pcv,
                               const bool useSharpLumaDQP,
                               const bool useFrameWiseQPA, const int previouslyAdaptedLumaQP = -1)
{
  const int  bitDepth        = pcSlice->getSPS()->getBitDepth(ChannelType::LUMA);
  const int  iQPIndex    = pcSlice->getSliceQp(); // initial QP index for current slice, used in following loops
  bool   sliceQPModified = false;
  uint32_t   meanLuma    = MAX_UINT;
  double     hpEnerAvg   = 0.0;

#if GLOBAL_AVERAGING
  if (!useFrameWiseQPA || previouslyAdaptedLumaQP < 0)  // mean visual activity value and luma value in each CTU
#endif
  {
    for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
    {
      uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );
      const Position pos ((ctuRsAddr % pcv.widthInCtus) * pcv.maxCUWidth, (ctuRsAddr / pcv.widthInCtus) * pcv.maxCUHeight);
      const CompArea ctuArea    = clipArea (CompArea (COMPONENT_Y, pcPic->chromaFormat, Area (pos.x, pos.y, pcv.maxCUWidth, pcv.maxCUHeight)), pcPic->Y());
      const CompArea fltArea    = clipArea (CompArea (COMPONENT_Y, pcPic->chromaFormat, Area (pos.x > 0 ? pos.x - 1 : 0, pos.y > 0 ? pos.y - 1 : 0, pcv.maxCUWidth + (pos.x > 0 ? 2 : 1), pcv.maxCUHeight + (pos.y > 0 ? 2 : 1))), pcPic->Y());
      const CPelBuf  picOrig    = pcPic->getOrigBuf (fltArea);
      double hpEner = 0.0;

      filterAndCalculateAverageEnergies (picOrig.buf,    picOrig.stride, hpEner,
                                         picOrig.height, picOrig.width,  bitDepth);
      hpEnerAvg += hpEner;
      pcPic->m_uEnerHpCtu[ctuRsAddr] = hpEner;
      pcPic->m_iOffsetCtu[ctuRsAddr] = pcPic->getOrigBuf (ctuArea).computeAvg();
    }

    hpEnerAvg /= double (pcSlice->getNumCtuInSlice());
  }
#if GLOBAL_AVERAGING
  const double hpEnerPic = 1.0 / getAveragePictureEnergy (pcPic->getOrigBuf().Y(), bitDepth);  // inverse, speed
#else
  const double hpEnerPic = 1.0 / hpEnerAvg; // speedup: multiply instead of divide in loop below; 1.0 for tuning
#endif

  if (useFrameWiseQPA || (iQPIndex >= MAX_QP))
  {
    int iQPFixed = (previouslyAdaptedLumaQP < 0) ? Clip3 (0, MAX_QP, iQPIndex + apprI3Log2 (hpEnerAvg * hpEnerPic)) : previouslyAdaptedLumaQP;

    if (isChromaEnabled (pcPic->chromaFormat) && (iQPIndex < MAX_QP) && (previouslyAdaptedLumaQP < 0))
    {
      iQPFixed += getGlaringColorQPOffset (pcPic, -1 /*ctuRsAddr*/, pcSlice, bitDepth, meanLuma);

      if (iQPFixed > MAX_QP
#if SHARP_LUMA_DELTA_QP
          && !useSharpLumaDQP
#endif
      )
      {
        iQPFixed = MAX_QP;
      }
    }
#if SHARP_LUMA_DELTA_QP

    // change new fixed QP based on average CTU luma value (Sharp)
    if (useSharpLumaDQP && (iQPIndex < MAX_QP) && (previouslyAdaptedLumaQP < 0))
    {
      if (meanLuma == MAX_UINT) // collect picture mean luma value
      {
        meanLuma = 0;

        for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
        {
          uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );

          meanLuma += pcPic->m_iOffsetCtu[ctuRsAddr];  // CTU mean
        }
        meanLuma = (meanLuma + (pcSlice->getNumCtuInSlice() >> 1)) / pcSlice->getNumCtuInSlice();
      }
      iQPFixed = Clip3 (0, MAX_QP, iQPFixed + lumaDQPOffset (meanLuma, bitDepth));
    }
#endif

    if (iQPIndex >= MAX_QP)
    {
      iQPFixed = MAX_QP;
    }
    else if (iQPFixed != iQPIndex)
    {
      const double* oldLambdas = pcSlice->getLambdas();
      const double  corrFactor = pow (2.0, double(iQPFixed - iQPIndex) / 3.0);
      const double  newLambdas[MAX_NUM_COMPONENT] = {oldLambdas[0] * corrFactor, oldLambdas[1] * corrFactor, oldLambdas[2] * corrFactor};

      CHECK (iQPIndex != pcSlice->getSliceQpBase(), "Invalid slice QP!");
      pcSlice->setLambdas (newLambdas);
      pcSlice->setSliceQp (iQPFixed); // update the slice/base QPs
      pcSlice->setSliceQpBase (iQPFixed);

      sliceQPModified = true;
    }

    for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
    {
      uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );

      pcPic->m_iOffsetCtu[ctuRsAddr] = (Pel)iQPFixed; // fixed QPs
    }
  }
  else // CTU-wise QPA
  {
    for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
    {
      uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );

      int iQPAdapt = Clip3 (0, MAX_QP, iQPIndex + apprI3Log2 (pcPic->m_uEnerHpCtu[ctuRsAddr] * hpEnerPic));

      if (pcv.widthInCtus > 1) // try to enforce CTU SNR greater than zero dB
      {
        meanLuma = (uint32_t)pcPic->m_iOffsetCtu[ctuRsAddr];

        if (isChromaEnabled (pcPic->chromaFormat))
        {
          iQPAdapt += getGlaringColorQPOffset (pcPic, (int)ctuRsAddr, nullptr, bitDepth, meanLuma);

          if (iQPAdapt > MAX_QP
#if SHARP_LUMA_DELTA_QP
              && !useSharpLumaDQP
#endif
          )
          {
            iQPAdapt = MAX_QP;
          }
          CHECK (meanLuma != (uint32_t)pcPic->m_iOffsetCtu[ctuRsAddr], "luma DC offsets don't match");
        }
#if SHARP_LUMA_DELTA_QP

        // change adaptive QP based on mean CTU luma value (Sharp)
        if (useSharpLumaDQP)
        {
 #if ENABLE_QPA_SUB_CTU
          pcPic->m_uEnerHpCtu[ctuRsAddr] = (double)meanLuma; // for sub-CTU QPA
 #endif
          iQPAdapt = Clip3 (0, MAX_QP, iQPAdapt + lumaDQPOffset (meanLuma, bitDepth));
        }

#endif
        const uint32_t uRefScale  = g_invQuantScales[0][iQPAdapt % 6] << ((iQPAdapt / 6) + bitDepth - 4);
        const CompArea subArea    = clipArea (CompArea (COMPONENT_Y, pcPic->chromaFormat, Area ((ctuRsAddr % pcv.widthInCtus) * pcv.maxCUWidth, (ctuRsAddr / pcv.widthInCtus) * pcv.maxCUHeight, pcv.maxCUWidth, pcv.maxCUHeight)), pcPic->Y());
        const Pel*     pSrc       = pcPic->getOrigBuf (subArea).buf;
        const ptrdiff_t srcStride  = pcPic->getOrigBuf(subArea).stride;
        const SizeType srcHeight  = pcPic->getOrigBuf(subArea).height;
        const SizeType srcWidth   = pcPic->getOrigBuf(subArea).width;
        uint32_t uAbsDCless = 0;

        // compute sum of absolute DC-less (high-pass) luma values
        for (SizeType h = 0; h < srcHeight; h++)
        {
          for (SizeType w = 0; w < srcWidth; w++)
          {
            uAbsDCless += (uint32_t)abs (pSrc[w] - (Pel)meanLuma);
          }
          pSrc += srcStride;
        }

        if (srcHeight >= 64 || srcWidth >= 64)   // normalization
        {
          const uint64_t blockSize = uint64_t(srcWidth * srcHeight);

          uAbsDCless = uint32_t((uint64_t(uAbsDCless) * 64*64 + (blockSize >> 1)) / blockSize);
        }

        if (uAbsDCless < 64 * 64)
        {
          uAbsDCless = 64 * 64;   // limit to 1
        }

        // reduce QP index if CTU would be fully quantized to zero
        if (uAbsDCless < uRefScale)
        {
          const int limit  = std::min (0, ((iQPIndex + 4) >> 3) - 6);
          const int redVal = std::max (limit, apprI3Log2 ((double)uAbsDCless / (double)uRefScale));

          iQPAdapt = std::max (0, iQPAdapt + redVal);
        }
      }

      pcPic->m_iOffsetCtu[ctuRsAddr] = (Pel)iQPAdapt; // adapted QPs

#if ENABLE_QPA_SUB_CTU
      if (pcv.widthInCtus > 1 && pcSlice->getCuQpDeltaSubdiv() == 0)  // reduce local DQP rate peaks
#elif ENABLE_QPA_SUB_CTU
      if (pcv.widthInCtus > 1 && pcSlice->getPPS()->getMaxCuDQPDepth() == 0)  // reduce local DQP rate peaks
#else
      if (pcv.widthInCtus > 1) // try to reduce local bitrate peaks via minimum smoothing of the adapted QPs
#endif
      {
        iQPAdapt = ctuRsAddr % pcv.widthInCtus; // horizontal offset
        if (iQPAdapt == 0)
        {
          iQPAdapt = (ctuRsAddr > 1) ? pcPic->m_iOffsetCtu[ctuRsAddr - 2] : 0;
        }
        else // iQPAdapt >= 1
        {
          iQPAdapt = (iQPAdapt > 1) ? std::min (pcPic->m_iOffsetCtu[ctuRsAddr - 2], pcPic->m_iOffsetCtu[ctuRsAddr]) : pcPic->m_iOffsetCtu[ctuRsAddr];
        }
        if (ctuRsAddr > pcv.widthInCtus)
        {
          iQPAdapt = std::min (iQPAdapt, (int)pcPic->m_iOffsetCtu[ctuRsAddr - 1 - pcv.widthInCtus]);
        }
        if ((ctuRsAddr > 0) && (pcPic->m_iOffsetCtu[ctuRsAddr - 1] < (Pel)iQPAdapt))
        {
          pcPic->m_iOffsetCtu[ctuRsAddr - 1] = (Pel)iQPAdapt;
        }
        if ((ctuIdx == pcSlice->getNumCtuInSlice() - 1) && (ctuRsAddr > pcv.widthInCtus)) // last CTU in the given slice
        {
          iQPAdapt = std::min (pcPic->m_iOffsetCtu[ctuRsAddr - 1], pcPic->m_iOffsetCtu[ctuRsAddr - pcv.widthInCtus]);
          if (pcPic->m_iOffsetCtu[ctuRsAddr] < (Pel)iQPAdapt)
          {
            pcPic->m_iOffsetCtu[ctuRsAddr] = (Pel)iQPAdapt;
          }
        }
      }
    } // end iteration over all CTUs in current slice
  }

  return sliceQPModified;
}

#if ENABLE_QPA_SUB_CTU
static int applyQPAdaptationSubCtu (CodingStructure &cs, const UnitArea ctuArea, const uint32_t ctuAddr, const bool useSharpLumaDQP)
{
  const PreCalcValues &pcv = *cs.pcv;
  const Picture     *pcPic = cs.picture;
  const int            bitDepth     = cs.slice->getSPS()->getBitDepth(ChannelType::LUMA);   // overall image bit-depth
  const int   adaptedCtuQP = pcPic ? pcPic->m_iOffsetCtu[ctuAddr] : cs.slice->getSliceQpBase();

  if (!pcPic || cs.slice->getCuQpDeltaSubdiv() == 0)
  {
    return adaptedCtuQP;
  }

  for (unsigned addr = 0; addr < cs.picture->m_subCtuQP.size(); addr++)
  {
    cs.picture->m_subCtuQP[addr] = (int8_t)adaptedCtuQP;
  }
  if (cs.slice->getSliceQp() < MAX_QP && pcv.widthInCtus > 1)
  {
#if SHARP_LUMA_DELTA_QP
    const int   lumaCtuDQP = useSharpLumaDQP ? lumaDQPOffset ((uint32_t)pcPic->m_uEnerHpCtu[ctuAddr], bitDepth) : 0;
#endif
    const unsigned     mts = std::min (cs.sps->getMaxTbSize(), pcv.maxCUWidth);
    const unsigned mtsLog2 = (unsigned)floorLog2(mts);
    const unsigned  stride = pcv.maxCUWidth >> mtsLog2;
    unsigned numAct = 0;    // number of block activities
    double   sumAct = 0.0; // sum of all block activities
    double   subAct[16];   // individual block activities
#if SHARP_LUMA_DELTA_QP
    uint32_t subMLV[16];   // individual mean luma values
#endif

    CHECK (mts * 4 < pcv.maxCUWidth || mts * 4 < pcv.maxCUHeight, "max. transform size is too small for given CTU size");

    for (unsigned h = 0; h < (pcv.maxCUHeight >> mtsLog2); h++)
    {
      for (unsigned w = 0; w < stride; w++)
      {
        const unsigned addr    = w + h * stride;
        const PosType  x       = ctuArea.lx() + w * mts;
        const PosType  y       = ctuArea.ly() + h * mts;
        const CompArea fltArea = clipArea (CompArea (COMPONENT_Y, pcPic->chromaFormat, Area (x > 0 ? x - 1 : 0, y > 0 ? y - 1 : 0, mts + (x > 0 ? 2 : 1), mts + (y > 0 ? 2 : 1))), pcPic->Y());
        const CPelBuf  picOrig = pcPic->getOrigBuf (fltArea);

        if (x >= pcPic->lwidth() || y >= pcPic->lheight())
        {
          continue;
        }
        filterAndCalculateAverageEnergies (picOrig.buf,    picOrig.stride, subAct[addr],
                                           picOrig.height, picOrig.width,  bitDepth);
        numAct++;
        sumAct += subAct[addr];
#if SHARP_LUMA_DELTA_QP

        if (useSharpLumaDQP)
        {
          const CompArea subArea = clipArea (CompArea (COMPONENT_Y, pcPic->chromaFormat, Area (x, y, mts, mts)), pcPic->Y());

          subMLV[addr] = pcPic->getOrigBuf (subArea).computeAvg();
        }
#endif
      }
    }
    if (sumAct <= 0.0)
    {
      return adaptedCtuQP;
    }

    sumAct = double(numAct) / sumAct; // 1.0 / (average CTU activity)

    for (unsigned h = 0; h < (pcv.maxCUHeight >> mtsLog2); h++)
    {
      for (unsigned w = 0; w < stride; w++)
      {
        const unsigned addr = w + h * stride;

        if (ctuArea.lx() + w * mts >= pcPic->lwidth() || ctuArea.ly() + h * mts >= pcPic->lheight())
        {
          continue;
        }
        cs.picture->m_subCtuQP[addr] = (int8_t)Clip3 (0, MAX_QP, adaptedCtuQP + apprI3Log2 (subAct[addr] * sumAct));
#if SHARP_LUMA_DELTA_QP

        // change adapted QP based on mean sub-CTU luma value (Sharp)
        if (useSharpLumaDQP)
        {
          cs.picture->m_subCtuQP[addr] = (int8_t)Clip3 (0, MAX_QP, (int)cs.picture->m_subCtuQP[addr] - lumaCtuDQP + lumaDQPOffset (subMLV[addr], bitDepth));
        }
#endif
      }
    }
  }

  return adaptedCtuQP;
}
#endif // ENABLE_QPA_SUB_CTU
#endif // ENABLE_QPA

// ====================================================================================================================
// Public member functions
// ====================================================================================================================

//! set adaptive search range based on poc difference
void EncSlice::setSearchRange( Slice* pcSlice )
{
  int currPoc = pcSlice->getPOC();
  int iRefPOC;
  int iGOPSize = m_pcCfg->getGOPSize();
  int offset      = (iGOPSize >> 1);
  int iMaxSR = m_pcCfg->getSearchRange();
  int iNumPredDir = pcSlice->isInterP() ? 1 : 2;

  for (int dir = 0; dir < iNumPredDir; dir++)
  {
    RefPicList e = (dir ? REF_PIC_LIST_1 : REF_PIC_LIST_0);
    for (int refIdx = 0; refIdx < pcSlice->getNumRefIdx(e); refIdx++)
    {
      iRefPOC            = pcSlice->getRefPic(e, refIdx)->getPOC();
      int newSearchRange = Clip3(m_pcCfg->getMinSearchWindow(), iMaxSR,
                                 (iMaxSR * ADAPT_SR_SCALE * abs(currPoc - iRefPOC) + offset) / iGOPSize);
      m_pcInterSearch->setAdaptiveSearchRange(dir, refIdx, newSearchRange);
    }
  }
}

void EncSlice::setLosslessSlice(Picture* pcPic, bool islossless)
{
  Slice* slice = pcPic->slices[getSliceSegmentIdx()];
  slice->setLossless(islossless);

  if (m_pcCfg->getCostMode() == COST_LOSSLESS_CODING)
  {
    if (islossless)
    {
      int losslessQp =
        LOSSLESS_AND_MIXED_LOSSLESS_RD_COST_TEST_QP - ((slice->getSPS()->getBitDepth(ChannelType::LUMA) - 8) * 6);
      slice->setSliceQp(losslessQp); // update the slice/base QPs

      slice->setTSResidualCodingDisabledFlag(m_pcCfg->getTSRCdisableLL() ? true : false);
    }
    else
    {
      slice->setSliceQp(pcPic->getLossyQPValue());
      slice->setTSResidualCodingDisabledFlag(false);
    }
  }
}


/**
 Multi-loop slice encoding for different slice QP

 \param pcPic    picture class
 */
void EncSlice::precompressSlice( Picture* pcPic )
{
  // if deltaQP RD is not used, simply return
  if ( m_pcCfg->getDeltaQpRD() == 0 )
  {
    return;
  }

  if ( m_pcCfg->getUseRateCtrl() )
  {
    THROW("\nMultiple QP optimization is not allowed when rate control is enabled." );
  }

  Slice* pcSlice        = pcPic->slices[getSliceSegmentIdx()];

  double     dPicRdCostBest = MAX_DOUBLE;
  uint32_t       uiQpIdxBest = 0;

  double dFrameLambda;
  int    SHIFT_QP = 12
                 + 6
                     * (pcSlice->getSPS()->getBitDepth(ChannelType::LUMA) - 8
                        - DISTORTION_PRECISION_ADJUSTMENT(pcSlice->getSPS()->getBitDepth(ChannelType::LUMA)));

  // set frame lambda
  if (m_pcCfg->getGOPSize() > 1)
  {
    dFrameLambda = 0.68 * pow (2, (m_viRdPicQp[0]  - SHIFT_QP) / 3.0) * (pcSlice->isInterB()? 2 : 1);
  }
  else
  {
    dFrameLambda = 0.68 * pow (2, (m_viRdPicQp[0] - SHIFT_QP) / 3.0);
  }

  // for each QP candidate
  for ( uint32_t uiQpIdx = 0; uiQpIdx < 2 * m_pcCfg->getDeltaQpRD() + 1; uiQpIdx++ )
  {
    pcSlice       ->setSliceQp             ( m_viRdPicQp    [uiQpIdx] );
    setUpLambda(pcSlice, m_vdRdPicLambda[uiQpIdx], m_viRdPicQp    [uiQpIdx]);

    // try compress
    compressSlice   ( pcPic, true, m_pcCfg->getFastDeltaQp());

    uint64_t uiPicDist        = m_uiPicDist; // Distortion, as calculated by compressSlice.
    // NOTE: This distortion is the chroma-weighted SSE distortion for the slice.
    //       Previously a standard SSE distortion was calculated (for the entire frame).
    //       Which is correct?
    // TODO: Update loop filter, SAO and distortion calculation to work on one slice only.
    // uiPicDist = m_pcGOPEncoder->preLoopFilterPicAndCalcDist( pcPic );
    // compute RD cost and choose the best
    double dPicRdCost = double( uiPicDist ) + dFrameLambda * double( m_uiPicTotalBits );

    if ( dPicRdCost < dPicRdCostBest )
    {
      uiQpIdxBest    = uiQpIdx;
      dPicRdCostBest = dPicRdCost;
    }
  }

  // set best values
  pcSlice       ->setSliceQp             ( m_viRdPicQp    [uiQpIdxBest] );
  setUpLambda(pcSlice, m_vdRdPicLambda[uiQpIdxBest], m_viRdPicQp    [uiQpIdxBest]);
}

void EncSlice::calCostSliceI(Picture* pcPic) // TODO: this only analyses the first slice segment. What about the others?
{
  double         iSumHadSlice      = 0;
  Slice * const  pcSlice           = pcPic->slices[getSliceSegmentIdx()];
  const PreCalcValues& pcv         = *pcPic->cs->pcv;
  const SPS     &sps               = *(pcSlice->getSPS());
  const int            shift             = sps.getBitDepth(ChannelType::LUMA) - 8;
  const int      offset            = (shift>0)?(1<<(shift-1)):0;

  for( uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++ )
  {
    uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );
    Position pos( (ctuRsAddr % pcv.widthInCtus) * pcv.maxCUWidth, (ctuRsAddr / pcv.widthInCtus) * pcv.maxCUHeight);

    const int height  = std::min( pcv.maxCUHeight, pcv.lumaHeight - pos.y );
    const int width   = std::min( pcv.maxCUWidth,  pcv.lumaWidth  - pos.x );
    const CompArea blk( COMPONENT_Y, pcv.chrFormat, pos, Size( width, height));
    int iSumHad = m_pcCuEncoder->updateCtuDataISlice( pcPic->getOrigBuf( blk ) );

    (m_pcRateCtrl->getRCPic()->getLCU(ctuRsAddr)).m_costIntra=(iSumHad+offset)>>shift;
    iSumHadSlice += (m_pcRateCtrl->getRCPic()->getLCU(ctuRsAddr)).m_costIntra;
  }
  m_pcRateCtrl->getRCPic()->setTotalIntraCost(iSumHadSlice);
}

void EncSlice::calCostPictureI(Picture* picture)
{
  double         sumHadPicture = 0;
  Slice * const  slice = picture->slices[getSliceSegmentIdx()];
  const PreCalcValues& pcv = *picture->cs->pcv;
  const SPS     &sps = *(slice->getSPS());
  const int            shift         = sps.getBitDepth(ChannelType::LUMA) - 8;
  const int      offset = (shift>0) ? (1 << (shift - 1)) : 0;

  for (uint32_t ctuIdx = 0; ctuIdx < picture->m_ctuNums; ctuIdx++)
  {
    Position pos((ctuIdx % pcv.widthInCtus) * pcv.maxCUWidth, (ctuIdx / pcv.widthInCtus) * pcv.maxCUHeight);

    const int height = std::min(pcv.maxCUHeight, pcv.lumaHeight - pos.y);
    const int width = std::min(pcv.maxCUWidth, pcv.lumaWidth - pos.x);
    const CompArea blk(COMPONENT_Y, pcv.chrFormat, pos, Size(width, height));
    int sumHad = m_pcCuEncoder->updateCtuDataISlice(picture->getOrigBuf(blk));

    (m_pcRateCtrl->getRCPic()->getLCU(ctuIdx)).m_costIntra = (sumHad + offset) >> shift;
    sumHadPicture += (m_pcRateCtrl->getRCPic()->getLCU(ctuIdx)).m_costIntra;
  }
  m_pcRateCtrl->getRCPic()->setTotalIntraCost(sumHadPicture);
}

/** \param pcPic   picture class
 */
void EncSlice::compressSlice( Picture* pcPic, const bool bCompressEntireSlice, const bool bFastDeltaQP )
{
  // if bCompressEntireSlice is true, then the entire slice (not slice segment) is compressed,
  //   effectively disabling the slice-segment-mode.

  Slice* const pcSlice    = pcPic->slices[getSliceSegmentIdx()];

  if (pcSlice->getSPS()->getSpsRangeExtension().getRrcRiceExtensionEnableFlag())
  {
    int bitDepth  = pcSlice->getSPS()->getBitDepth(ChannelType::LUMA);
    int baseLevel = (bitDepth > 12) ? (pcSlice->isIntra() ? 5 : 2 * 5 ) : (pcSlice->isIntra() ? 2 * 5 : 3 * 5);
    pcSlice->setRiceBaseLevel(baseLevel);
  }
  else
  {
    pcSlice->setRiceBaseLevel(4);
  }

  // initialize cost values - these are used by precompressSlice (they should be parameters).
  m_uiPicTotalBits  = 0;
  m_uiPicDist       = 0;

  pcSlice->setSliceQpBase( pcSlice->getSliceQp() );

  m_CABACEstimator->initCtxModels( *pcSlice );

  m_pcCuEncoder->getModeCtrl()->setFastDeltaQp(bFastDeltaQP);


  //------------------------------------------------------------------------------
  //  Weighted Prediction parameters estimation.
  //------------------------------------------------------------------------------
  // calculate AC/DC values for current picture
  if( pcSlice->getPPS()->getUseWP() || pcSlice->getPPS()->getWPBiPred() )
  {
    xCalcACDCParamSlice(pcSlice);
  }

  const bool bWp_explicit = (pcSlice->getSliceType()==P_SLICE && pcSlice->getPPS()->getUseWP()) || (pcSlice->getSliceType()==B_SLICE && pcSlice->getPPS()->getWPBiPred());

  if ( bWp_explicit )
  {

    xEstimateWPParamSlice( pcSlice, m_pcCfg->getWeightedPredictionMethod() );
    pcSlice->initWpScaling(pcSlice->getSPS());

    // check WP on/off
    xCheckWPEnable( pcSlice );
  }

  pcPic->m_prevQP.fill(pcSlice->getSliceQp());

  CHECK(pcPic->m_prevQP[ChannelType::LUMA] == std::numeric_limits<int>::max(), "Invalid previous QP");

  CodingStructure&  cs          = *pcPic->cs;
  cs.slice    = pcSlice;
  cs.pcv      = pcSlice->getPPS()->pcv;
  cs.fracBits = 0;

  if( pcSlice->getFirstCtuRsAddrInSlice() == 0 && ( pcSlice->getPOC() != m_pcCfg->getSwitchPOC() || -1 == m_pcCfg->getDebugCTU() ) )
  {
    cs.initStructData (pcSlice->getSliceQp());
  }

#if ENABLE_QPA
  if (m_pcCfg->getUsePerceptQPA() && !m_pcCfg->getUseRateCtrl())
  {
    if (applyQPAdaptation (pcPic, pcSlice, *cs.pcv, m_pcCfg->getLumaLevelToDeltaQPMapping().mode == LUMALVL_TO_DQP_NUM_MODES,
                           (m_pcCfg->getBaseQP() >= 38) || (m_pcCfg->getSourceWidth() <= 512 && m_pcCfg->getSourceHeight() <= 320), m_adaptedLumaQP))
    {
      m_CABACEstimator->initCtxModels (*pcSlice);
      pcPic->m_prevQP.fill(pcSlice->getSliceQp());
      if (pcSlice->getFirstCtuRsAddrInSlice() == 0)
      {
        cs.currQP.fill(pcSlice->getSliceQp());
      }
    }
  }
#endif // ENABLE_QPA

  bool checkPLTRatio = m_pcCfg->getIntraPeriod() != 1 && pcSlice->isIRAP();
  if (checkPLTRatio)
  {
    m_pcCuEncoder->getModeCtrl()->setPltEnc(true);
  }
  else
  {
    bool doPlt = m_pcLib->getPltEnc();
    m_pcCuEncoder->getModeCtrl()->setPltEnc(doPlt);
  }

#if K0149_BLOCK_STATISTICS
  const SPS *sps = pcSlice->getSPS();
  CHECK(sps == 0, "No SPS present");
  writeBlockStatisticsHeader(sps);
#endif
  m_pcInterSearch->resetAffineMVList();
  m_pcInterSearch->resetUniMvList();
  ::memset(g_isReusedUniMVsFilled, 0, sizeof(g_isReusedUniMVsFilled));
  encodeCtus( pcPic, bCompressEntireSlice, bFastDeltaQP, m_pcLib );
  if (checkPLTRatio)
  {
    m_pcLib->checkPltStats(pcPic);
  }
}

void EncSlice::checkDisFracMmvd( Picture* pcPic, uint32_t startCtuTsAddr, uint32_t boundingCtuTsAddr )
{
  CodingStructure&  cs            = *pcPic->cs;
  Slice* pcSlice                  = cs.slice;
  const PreCalcValues& pcv        = *cs.pcv;
  const uint32_t    widthInCtus   = pcv.widthInCtus;
  const uint32_t hashThreshold    = 20;
  uint32_t totalCtu               = 0;
  uint32_t hashRatio              = 0;

  if ( !pcSlice->getSPS()->getFpelMmvdEnabledFlag() )
  {
    return;
  }

  for ( uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++ )
  {
    const uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );
    const uint32_t ctuXPosInCtus        = ctuRsAddr % widthInCtus;
    const uint32_t ctuYPosInCtus        = ctuRsAddr / widthInCtus;

    const Position pos ( ctuXPosInCtus * pcv.maxCUWidth, ctuYPosInCtus * pcv.maxCUHeight );
    const UnitArea ctuArea( cs.area.chromaFormat, Area( pos.x, pos.y, pcv.maxCUWidth, pcv.maxCUHeight ) );

    hashRatio += m_pcCuEncoder->getIbcHashMap().getHashHitRatio( ctuArea.Y() );
    totalCtu++;
  }

  if ( hashRatio > totalCtu * hashThreshold )
  {
    pcPic->cs->picHeader->setDisFracMMVD( true );
  }
  if (!pcPic->cs->picHeader->getDisFracMMVD())
  {
    bool useIntegerMVD = (pcPic->lwidth()*pcPic->lheight() > 1920 * 1080);
    pcPic->cs->picHeader->setDisFracMMVD( useIntegerMVD );
  }
}

void EncSlice::setJointCbCrModes( CodingStructure& cs, const Position topLeftLuma, const Size sizeLuma )
{
  bool              sgnFlag = true;

  if( isChromaEnabled( cs.picture->chromaFormat) )
  {
    const CompArea  cbArea  = CompArea( COMPONENT_Cb, cs.picture->chromaFormat, Area(topLeftLuma,sizeLuma), true );
    const CompArea  crArea  = CompArea( COMPONENT_Cr, cs.picture->chromaFormat, Area(topLeftLuma,sizeLuma), true );
    const CPelBuf   orgCb   = cs.picture->getOrigBuf( cbArea );
    const CPelBuf   orgCr   = cs.picture->getOrigBuf( crArea );
    const int       x0      = ( cbArea.x > 0 ? 0 : 1 );
    const int       y0      = ( cbArea.y > 0 ? 0 : 1 );
    const int       x1      = ( cbArea.x + cbArea.width  < cs.picture->Cb().width  ? cbArea.width  : cbArea.width  - 1 );
    const int       y1      = ( cbArea.y + cbArea.height < cs.picture->Cb().height ? cbArea.height : cbArea.height - 1 );
    const ptrdiff_t cbs     = orgCb.stride;
    const ptrdiff_t crs     = orgCr.stride;
    const Pel*      pCb     = orgCb.buf + y0 * cbs;
    const Pel*      pCr     = orgCr.buf + y0 * crs;
    int64_t         sumCbCr = 0;

    // determine inter-chroma transform sign from correlation between high-pass filtered (i.e., zero-mean) Cb and Cr planes
    for( int y = y0; y < y1; y++, pCb += cbs, pCr += crs )
    {
      for( int x = x0; x < x1; x++ )
      {
        int cb = ( 12*(int)pCb[x] - 2*((int)pCb[x-1] + (int)pCb[x+1] + (int)pCb[x-cbs] + (int)pCb[x+cbs]) - ((int)pCb[x-1-cbs] + (int)pCb[x+1-cbs] + (int)pCb[x-1+cbs] + (int)pCb[x+1+cbs]) );
        int cr = ( 12*(int)pCr[x] - 2*((int)pCr[x-1] + (int)pCr[x+1] + (int)pCr[x-crs] + (int)pCr[x+crs]) - ((int)pCr[x-1-crs] + (int)pCr[x+1-crs] + (int)pCr[x-1+crs] + (int)pCr[x+1+crs]) );
        sumCbCr += cb*cr;
      }
    }

    sgnFlag = ( sumCbCr < 0 );
  }

  cs.picHeader->setJointCbCrSignFlag( sgnFlag );
}


void EncSlice::encodeCtus( Picture* pcPic, const bool bCompressEntireSlice, const bool bFastDeltaQP, EncLib* pEncLib )
{
  CodingStructure&  cs            = *pcPic->cs;
  Slice* pcSlice                  = cs.slice;
  const PreCalcValues& pcv        = *cs.pcv;
  const uint32_t        widthInCtus   = pcv.widthInCtus;
#if ENABLE_QPA
  const int iQPIndex              = pcSlice->getSliceQpBase();
#endif

  CABACWriter*    pCABACWriter    = pEncLib->getCABACEncoder()->getCABACEstimator( pcSlice->getSPS() );
  TrQuant*        pTrQuant        = pEncLib->getTrQuant();
  RdCost*         pRdCost         = pEncLib->getRdCost();
  EncCfg*         pCfg            = pEncLib;
  RateCtrl*       pRateCtrl       = pEncLib->getRateCtrl();
  pRdCost->setLosslessRDCost(pcSlice->isLossless());
#if RDOQ_CHROMA_LAMBDA
  pTrQuant    ->setLambdas( pcSlice->getLambdas() );
#else
  pTrQuant    ->setLambda ( pcSlice->getLambdas()[0] );
#endif
  pRdCost     ->setLambda ( pcSlice->getLambdas()[0], pcSlice->getSPS()->getBitDepths() );
#if WCG_EXT && ER_CHROMA_QP_WCG_PPS && ENABLE_QPA
  if (!pCfg->getWCGChromaQPControl().isEnabled() && pCfg->getUsePerceptQPA() && !pCfg->getUseRateCtrl())
  {
    pRdCost->saveUnadjustedLambda();
  }
#endif

  EnumArray<int, ChannelType> prevQP;
  EnumArray<int, ChannelType> currQP;

  prevQP.fill(pcSlice->getSliceQp());
  currQP.fill(pcSlice->getSliceQp());

  if ( pcSlice->getSPS()->getFpelMmvdEnabledFlag() ||
      (pcSlice->getSPS()->getIBCFlag() && m_pcCuEncoder->getEncCfg()->getIBCHashSearch()))
  {
    m_pcCuEncoder->getIbcHashMap().rebuildPicHashMap(cs.picture->getTrueOrigBuf());
    if (!m_pcCfg->getIsLowDelay())
    {
      int hashBlkHitPerc = m_pcCuEncoder->getIbcHashMap().calHashBlkMatchPerc(cs.area.Y());
      cs.slice->setDisableSATDForRD(hashBlkHitPerc > 59);
    }
    if ((pcSlice->getSPS()->getSpsRangeExtension().getTSRCRicePresentFlag())
        && (m_pcGOPEncoder->getPreQP() != pcSlice->getSliceQp()) && (pcPic->cs->pps->getNumSlicesInPic() == 1)
        && (pcSlice->getTsrcIndex() > 0) && (pcSlice->getSPS()->getBitDepth(ChannelType::LUMA) <= 12))
    {
      uint32_t totalCtu  = 0;
      uint32_t hashRatio = 0;
      for (uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++)
      {
        const uint32_t ctuRsAddr     = pcSlice->getCtuAddrInSlice(ctuIdx);
        const uint32_t ctuXPosInCtus = ctuRsAddr % widthInCtus;
        const uint32_t ctuYPosInCtus = ctuRsAddr / widthInCtus;
        const Position pos(ctuXPosInCtus * pcv.maxCUWidth, ctuYPosInCtus * pcv.maxCUHeight);
        const UnitArea ctuArea(cs.area.chromaFormat, Area(pos.x, pos.y, pcv.maxCUWidth, pcv.maxCUHeight));

        hashRatio += m_pcCuEncoder->getIbcHashMap().calHashBlkMatchPerc(cs.area.Y());
        totalCtu++;
      }
      if (totalCtu > 0)
      {
        if ((hashRatio < 4200) || (hashRatio < (41 * totalCtu)))
        {
          pcSlice->setTsrcIndex(0);
        }
      }
    }
  }

#if IBRC360SplitSkipModel
  std::vector<Rc360IbrcModelSample> rc360IbrcFrameModelSamples;
#endif

  double rc360ChromaSafeTakeThreshold = 0.0;
  double rc360LumaSafeTakeThreshold = 0.0;
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafeTake
  std::vector<double> rc360ChromaSafeTakeActivity(pcv.sizeInCtus, 0.0);
  std::vector<double> rc360LumaSafeTakeActivity(pcv.sizeInCtus, 0.0);
  std::vector<double> rc360ChromaSafeTakeSamples;
  std::vector<double> rc360LumaSafeTakeSamples;
  rc360ChromaSafeTakeSamples.reserve(pcv.sizeInCtus);
  rc360LumaSafeTakeSamples.reserve(pcv.sizeInCtus);
  for (uint32_t rsAddr = 0; rsAddr < pcv.sizeInCtus; rsAddr++)
  {
    const uint32_t xCtu = rsAddr % widthInCtus;
    const uint32_t yCtu = rsAddr / widthInCtus;
    const Position ctuPos(xCtu * pcv.maxCUWidth, yCtu * pcv.maxCUHeight);
    const UnitArea preCtuArea(cs.area.chromaFormat, Area(ctuPos.x, ctuPos.y, pcv.maxCUWidth, pcv.maxCUHeight));

    const double chromaActivity = rc360CtuChromaGradient(pcPic, cs, preCtuArea);
    const double lumaActivity = rc360CtuLumaGradient(pcPic, cs, preCtuArea);
    rc360ChromaSafeTakeActivity[rsAddr] = chromaActivity;
    rc360LumaSafeTakeActivity[rsAddr] = lumaActivity;
    rc360ChromaSafeTakeSamples.push_back(chromaActivity);
    rc360LumaSafeTakeSamples.push_back(lumaActivity);
  }

  rc360ChromaSafeTakeThreshold =
    rc360PercentileValue(rc360ChromaSafeTakeSamples, double(IBRC360IeffOnlyChromaSafeTakePercentile), 0.0);
  rc360LumaSafeTakeThreshold =
    rc360PercentileValue(rc360LumaSafeTakeSamples, double(IBRC360IeffOnlyChromaSafeTakeLumaPercentile), 0.0);

  std::printf("[RC360IBRC][ChromaSafeTakeFrame] POC=%d chromaPercentile=%.6f chromaThreshold=%.9f lumaLowGate=%d lumaPercentile=%.6f lumaThreshold=%.9f alphaPos=%.6f asymmetric=%d alphaNeg=%.6f qLo=%.6f qHi=%.6f\n",
              pcPic->getPOC(), double(IBRC360IeffOnlyChromaSafeTakePercentile), rc360ChromaSafeTakeThreshold,
              int(IBRC360IeffOnlyChromaSafeTakeLumaLowGate),
              double(IBRC360IeffOnlyChromaSafeTakeLumaPercentile), rc360LumaSafeTakeThreshold,
              double(IBRC360IeffOnlyLogQuantileGamma),
              int(IBRC360IeffOnlyLogQuantileAsymmetric),
              double(IBRC360IeffOnlyLogQuantileGammaNegative),
              double(IBRC360IeffOnlyPercentileLo), double(IBRC360IeffOnlyPercentileHi));
  std::fflush(stdout);
#endif

  // for every CTU in the slice
  for( uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++ )
  {
    const int32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );

    // update CABAC state
    const uint32_t ctuXPosInCtus        = ctuRsAddr % widthInCtus;
    const uint32_t ctuYPosInCtus        = ctuRsAddr / widthInCtus;

    const Position pos (ctuXPosInCtus * pcv.maxCUWidth, ctuYPosInCtus * pcv.maxCUHeight);
    const UnitArea ctuArea( cs.area.chromaFormat, Area( pos.x, pos.y, pcv.maxCUWidth, pcv.maxCUHeight ) );
    DTRACE_UPDATE( g_trace_ctx, std::make_pair( "ctu", ctuRsAddr ) );

    if( pCfg->getSwitchPOC() != pcPic->poc || -1 == pCfg->getDebugCTU() )
    {
      if ((cs.slice->getSliceType() != I_SLICE || cs.sps->getIBCFlag()) && cs.pps->ctuIsTileColBd(ctuXPosInCtus))
      {
        cs.motionLut.lut.resize(0);
        cs.motionLut.lutIbc.resize(0);
      }
    }

    const SubPic &curSubPic = pcSlice->getPPS()->getSubPicFromPos(pos);
    // padding/restore at slice level
    if (pcSlice->getPPS()->getNumSubPics() >= 2 && curSubPic.getTreatedAsPicFlag() && ctuIdx == 0)
    {
      int subPicX = (int)curSubPic.getSubPicLeft();
      int subPicY = (int)curSubPic.getSubPicTop();
      int subPicWidth = (int)curSubPic.getSubPicWidthInLumaSample();
      int subPicHeight = (int)curSubPic.getSubPicHeightInLumaSample();

      for (int rlist = REF_PIC_LIST_0; rlist < NUM_REF_PIC_LIST_01; rlist++)
      {
        int n = pcSlice->getNumRefIdx((RefPicList)rlist);
        for (int idx = 0; idx < n; idx++)
        {
          Picture *refPic = pcSlice->getRefPic((RefPicList)rlist, idx);

          if( !refPic->getSubPicSaved() && refPic->subPictures.size() > 1 )
          {
            refPic->saveSubPicBorder(refPic->getPOC(), subPicX, subPicY, subPicWidth, subPicHeight);
            refPic->extendSubPicBorder(refPic->getPOC(), subPicX, subPicY, subPicWidth, subPicHeight);
            refPic->setSubPicSaved(true);
          }
        }
      }
    }
    if (cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && cs.pps->ctuIsTileRowBd( ctuYPosInCtus ))
    {
      pCABACWriter->initCtxModels( *pcSlice );
      cs.resetPrevPLT(cs.prevPLT);
      prevQP.fill(pcSlice->getSliceQp());
    }
    else if (cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && pEncLib->getEntropyCodingSyncEnabledFlag())
    {
      // reset and then update contexts to the state at the end of the top CTU (if within current slice and tile).
      pCABACWriter->initCtxModels( *pcSlice );
      cs.resetPrevPLT(cs.prevPLT);
      if (cs.getCURestricted(pos.offset(0, -1), pos, pcSlice->getIndependentSliceIdx(), cs.pps->getTileIdx(pos),
                             ChannelType::LUMA))
      {
        // Top is available, we use it.
        pCABACWriter->getCtx() = pEncLib->m_entropyCodingSyncContextState;
        pCABACWriter->getCtx().riceStatReset(
          pcSlice->getSPS()->getBitDepth(ChannelType::LUMA),
          pcSlice->getSPS()->getSpsRangeExtension().getPersistentRiceAdaptationEnabledFlag());
        cs.setPrevPLT(pEncLib->m_palettePredictorSyncState);
      }
      prevQP.fill(pcSlice->getSliceQp());
    }


#if RDOQ_CHROMA_LAMBDA && ENABLE_QPA && !ENABLE_QPA_SUB_CTU
    double oldLambdaArray[MAX_NUM_COMPONENT] = {0.0};
#endif
    const double oldLambda = pRdCost->getLambda();
    bool   rc360IbrcApplied = false;
    double rc360IbrcRcUpdateLambda = -1.0;
    bool   rc360IbrcRestoreState = false;
    double rc360IbrcRestoreLambda = oldLambda;
    int    rc360IbrcRestoreQpLuma = currQP[ChannelType::LUMA];
    int    rc360IbrcRestoreQpChroma = currQP[ChannelType::CHROMA];
    bool   rc360IbrcModelSampleValid = false;
    [[maybe_unused]] double rc360IbrcModelQs = 1.0;
    [[maybe_unused]] double rc360IbrcModelIeff = 1.0;
    [[maybe_unused]] double rc360IbrcModelPredBits = 0.0;
    double rc360IbrcModelPredBitsRaw = 0.0;
    [[maybe_unused]] double rc360IbrcModelPredBpp = 0.0;
    [[maybe_unused]] double rc360IbrcModelPredD = 0.0;
    double rc360IbrcRateBias = 1.0;
    int rc360IbrcRateBiasTargetClass = 0;
    int rc360IbrcRateBiasSkipClass = 0;
    int rc360IbrcRateBiasCtuClass = 0;
    bool   rc360CtuDiagEnabled = false;
    int    rc360CtuDiagModelUsed = 0;
    double rc360CtuDiagDref = 0.0;
    double rc360CtuDiagIeff = 1.0;
    double rc360CtuDiagIeffRd = 1.0;
    double rc360CtuDiagWref = 1.0;
    double rc360CtuDiagLambdaPic = 0.0;
    double rc360CtuDiagLambdaCtu = 0.0;
    double rc360CtuDiagQs = 1.0;
    int    rc360CtuDiagQpModel = 0;
    int    rc360CtuDiagQpFinal = currQP[ChannelType::LUMA];
    int    rc360CtuDiagQpClipBefore = currQP[ChannelType::LUMA];
    int    rc360CtuDiagQpClipAfter = currQP[ChannelType::LUMA];
    double rc360CtuDiagPredBits = 0.0;
    double rc360CtuDiagPredD = 0.0;
#if IBRC360SplitSkipModel
#if !IBRC360ClosedLoopRateModel
    double rc360IbrcPredSkip = 0.0;
    int rc360IbrcPredSkipClass = 0;
#endif
#endif
    if ( pCfg->getUseRateCtrl() )
    {
      int estQP        = pcSlice->getSliceQp();
      double estLambda = -1.0;
      double bpp       = -1.0;

      if( ( pcPic->slices[0]->isIRAP() && pCfg->getForceIntraQP() ) || !pCfg->getLCULevelRC() )
      {
        estQP = pcSlice->getSliceQp();
      }
      else
      {
        bpp = pRateCtrl->getRCPic()->getLCUTargetBpp(pcSlice->isIRAP());
        if ( pcPic->slices[0]->isIntra())
        {
          estLambda = pRateCtrl->getRCPic()->getLCUEstLambdaAndQP(bpp, pcSlice->getSliceQp(), &estQP);
        }
        else
        {
          estLambda = pRateCtrl->getRCPic()->getLCUEstLambda( bpp );
          estQP     = pRateCtrl->getRCPic()->getLCUEstQP    ( estLambda, pcSlice->getSliceQp() );
        }

        estQP = Clip3(-pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, estQP);
        const int gopSizeForMid = std::max(1, pCfg->getGOPSize());
        const bool earlyPProtected = (pcPic->getPOC() == 1 || pcPic->getPOC() == 2)
                                  && pCfg->getRc360IBRCEarlyPLambdaScale() < 0.999999;
        const bool midGopProtected = pcPic->getPOC() > 0
                                   && (pcPic->getPOC() % gopSizeForMid) == 0
                                   && pCfg->getRc360IBRCMidGopLambdaScale() < 0.999999;
        if (pCfg->getRc360IBRC()
            && (earlyPProtected || midGopProtected)
            && estLambda > 0.0)
        {
          const double picLambda = rc360ClipPositive(pcSlice->getLambdas()[0], 1e-12, 1e12);
          const double cappedLambda = std::min(estLambda, picLambda);
          if (cappedLambda < estLambda)
          {
            const double oldEstLambda = estLambda;
            const int oldEstQP = estQP;
            estLambda = cappedLambda;
            estQP = pRateCtrl->getRCPic()->getLCUEstQP(estLambda, pcSlice->getSliceQp());
            estQP = Clip3(-pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, estQP);
            if (ctuRsAddr < 5)
            {
              std::printf("[RC360IBRC][RefLcuCap] POC=%d ctu=%d oldLambda=%.9f capLambda=%.9f oldQP=%d newQP=%d picLambda=%.9f earlyScale=%.9f midGopScale=%.9f earlyProtected=%d midGopProtected=%d\n",
                          pcPic->getPOC(), ctuRsAddr, oldEstLambda, estLambda, oldEstQP, estQP,
                          picLambda, pCfg->getRc360IBRCEarlyPLambdaScale(), pCfg->getRc360IBRCMidGopLambdaScale(),
                          earlyPProtected ? 1 : 0, midGopProtected ? 1 : 0);
              std::fflush(stdout);
            }
          }
          if (midGopProtected)
          {
            const int oldEstQP = estQP;
            const int midGopQpCap = Clip3(-pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA), MAX_QP, pcSlice->getSliceQp() + 1);
            estQP = std::min(estQP, midGopQpCap);
            if (estQP < oldEstQP && ctuRsAddr < 5)
            {
              std::printf("[RC360IBRC][MidGopLcuQpCap] POC=%d ctu=%d oldQP=%d newQP=%d sliceQP=%d midGopScale=%.9f\n",
                          pcPic->getPOC(), ctuRsAddr, oldEstQP, estQP, pcSlice->getSliceQp(),
                          pCfg->getRc360IBRCMidGopLambdaScale());
              std::fflush(stdout);
            }
          }
        }

        pRdCost->setLambda(estLambda, pcSlice->getSPS()->getBitDepths());
#if WCG_EXT
        pRdCost->saveUnadjustedLambda();
#endif
        for (uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++)
        {
          const ComponentID compID = ComponentID(compIdx);
          int chromaQPOffset = pcSlice->getPPS()->getQpOffset(compID) + pcSlice->getSliceChromaQpDelta(compID);
          int qpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, estQP) + chromaQPOffset;
          double tmpWeight = pow(2.0, (estQP - qpc) / 3.0);  // takes into account of the chroma qp mapping and chroma qp Offset
          if (m_pcCfg->getDepQuantEnabledFlag())
          {
            tmpWeight *= (m_pcCfg->getGOPSize() >= 8 ? pow(2.0, 0.1 / 3.0) : pow(2.0, 0.2 / 3.0));  // increase chroma weight for dependent quantization (in order to reduce bit rate shift from chroma to luma)
          }
          m_pcRdCost->setDistortionWeight(compID, tmpWeight);
        }
#if RDOQ_CHROMA_LAMBDA
        const double lambdaArray[MAX_NUM_COMPONENT] = {estLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Y),
                                                       estLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Cb),
                                                       estLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Cr)};
        pTrQuant->setLambdas( lambdaArray );
#else
        pTrQuant->setLambda( estLambda );
#endif
      }

      pRateCtrl->setRCQP( estQP );
    }

    if (pCfg->getUseRateCtrl()
        && pCfg->getRc360IBRC()
        && pCfg->getRc360IBRCCtuLevel()
        && pCfg->getRc360IBRCCtuMode() > 0
        && !pEncLib->getRc360CtuExp()
        && pEncLib->getLatFbTempComp()->hasCurrentPictureWeights()
        && pcSlice->isInterP()
        && !bCompressEntireSlice
        && (!IBRC360FrameOnlyWrefTarget || IBRC360IeffFrameWrefProtect)
        && IBRC360AblationMode != 4)
    {
      const int qpBdOffset = pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA);
      const int qpMin = -qpBdOffset;
      const int qpMax = MAX_QP;
      const int remBits = std::max(1, pRateCtrl->getRCPic()->getBitsLeft());
#if IBRC360SplitSkipModel
#if !IBRC360ClosedLoopRateModel
      rc360IbrcPredSkip = rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr);
      rc360IbrcPredSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkip);
#endif
#endif
      Rc360IbrcDecision ibrc =
        rc360IbrcSolveCtu(pEncLib->getLatFbTempComp(), pEncLib->getRc360Uprop(), pcv, pRateCtrl, ctuRsAddr,
                          remBits, qpMin, qpMax, pcSlice->getPOC());

      const double baseLambda = rc360ClipPositive(pRdCost->getLambda(), 1e-12, 1e12);
      const int baseQpLuma = currQP[ChannelType::LUMA];
      const int baseQpChroma = currQP[ChannelType::CHROMA];
      const double rawWRef = rc360ClipPositive(pEncLib->getLatFbTempComp()->getCtuWeight(ctuRsAddr), 1e-6, 1e6);
      const double predSkipRatioForWref = rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr);
      const double wRefSpendGate = rc360WrefSpendabilityGateFromSkip(predSkipRatioForWref);
      const double wRef = rc360SpendabilityEffectiveWref(rawWRef, predSkipRatioForWref);
      const double upropNorm =
        pEncLib->getRc360Uprop() != nullptr ? pEncLib->getRc360Uprop()->getCtuNorm(pcSlice->getPOC(), ctuRsAddr) : 1.0;
      const double upropScale =
        pEncLib->getRc360Uprop() != nullptr ? pEncLib->getRc360Uprop()->getCtuScale(pcSlice->getPOC(), ctuRsAddr) : 1.0;

      int ctuMode = Clip3(0, 4, pCfg->getRc360IBRCCtuMode());
      bool guardFallback = false;
      if (ctuMode == 3)
      {
        const double targetPicBits = std::max(1.0, double(pRateCtrl->getRCPic()->getTargetBits()));
        const double bitsLeftPic = double(std::max(0, pRateCtrl->getRCPic()->getBitsLeft()));
        const double actualUsedBefore = targetPicBits - bitsLeftPic;
        const double expectedUsedBefore = targetPicBits * double(ctuIdx) / double(std::max<uint32_t>(1, pcSlice->getNumCtuInSlice()));
        const double hardLambdaRatio = rc360ClipPositive(ibrc.lambdaCtu / baseLambda, 1e-12, 1e12);
        const int hardDqp = ibrc.qp - baseQpLuma;
        if (ctuIdx > 0 && expectedUsedBefore > 1.0
            && (actualUsedBefore < 0.92 * expectedUsedBefore || actualUsedBefore > 1.08 * expectedUsedBefore))
        {
          ctuMode = 2;
          guardFallback = true;
        }
        if (ctuMode == 3
            && (hardLambdaRatio < 0.5 || hardLambdaRatio > 2.0 || std::abs(hardDqp) > 3
                || remBits <= std::max(4, int(std::floor(0.01 * targetPicBits + 0.5)))))
        {
          ctuMode = 2;
          guardFallback = true;
        }
      }

      auto applyCtuLambdaQp = [&](double finalLambda, int finalQp, int dqp)
      {
        pRdCost->setLambda(finalLambda, pcSlice->getSPS()->getBitDepths());
#if WCG_EXT
        pRdCost->saveUnadjustedLambda();
#endif
        double lambdaArray[MAX_NUM_COMPONENT] = { finalLambda };
        for (uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++)
        {
          const ComponentID compID = ComponentID(compIdx);
          int chromaQPOffset = pcSlice->getPPS()->getQpOffset(compID) + pcSlice->getSliceChromaQpDelta(compID);
          int qpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, finalQp) + chromaQPOffset;
          double tmpWeight = pow(2.0, (finalQp - qpc) / 3.0);
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafe
          if (IBRC360IeffOnlyCtuRD)
          {
            const int baseQpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, baseQpLuma) + chromaQPOffset;
            const double baseWeight = pow(2.0, (baseQpLuma - baseQpc) / 3.0);
            tmpWeight = baseWeight * rc360ClipPositive(finalLambda / baseLambda, 1e-6, 1e6);
          }
#endif
          if (m_pcCfg->getDepQuantEnabledFlag())
          {
            tmpWeight *= (m_pcCfg->getGOPSize() >= 8 ? pow(2.0, 0.1 / 3.0) : pow(2.0, 0.2 / 3.0));
          }
          m_pcRdCost->setDistortionWeight(compID, tmpWeight);
          lambdaArray[compIdx] = finalLambda / tmpWeight;
        }
#if RDOQ_CHROMA_LAMBDA
        lambdaArray[COMPONENT_Y] = finalLambda / m_pcRdCost->getDistortionWeight(COMPONENT_Y);
        pTrQuant->setLambdas(lambdaArray);
#else
        pTrQuant->setLambda(finalLambda);
#endif
        currQP[ChannelType::LUMA] = finalQp;
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafe
        currQP[ChannelType::CHROMA] = baseQpChroma;
#else
        currQP[ChannelType::CHROMA] = Clip3(qpMin, qpMax, baseQpChroma + dqp);
#endif
        pRateCtrl->setRCQP(finalQp);
      };

      double finalLambda = baseLambda;
      int finalQp = baseQpLuma;
      int dqp = 0;
      double weightLambda = baseLambda;
      double modelLambdaForBlend = ibrc.lambdaCtu;
      double lambdaRatio = 1.0;
      int qpClipBefore = baseQpLuma;
      int qpClipAfter = baseQpLuma;
      double rdGuardDistDlnDx = 0.0;
      double rdGuardRawDistDlnDx = 0.0;
      double rdIeffCalibrated = 1.0;
      int rdGuardReason = 0;
      int rdGuardApplied = 0;
      double ieffBaseImportance = 1.0;
      double ieffSpendGate = 1.0;
      double ieffSpendSkipGate = 1.0;
      double ieffSpendHistGate = 1.0;
      double ieffSpendHistRatio = 1.0;
      int ieffSpendHistCount = 0;
      double chromaRisk = 0.0;
      int chromaRiskGuardApplied = 0;
      double chromaSafeTakeActivity = 0.0;
      double lumaSafeTakeActivity = 0.0;
      int chromaSafeTakeApplied = 0;
      double ctuWrefProtectGain = 1.0;
      int ctuWrefProtectApplied = 0;
      constexpr double weightAlpha = double(IBRC360CtuSoftWeightAlpha);
      constexpr double ieffAlpha = double(IBRC360CtuSoftIeffAlpha);
      constexpr double modelBlend = double(IBRC360CtuModelBlend);
      constexpr double lambdaRatioMin = 0.880;
      constexpr double lambdaRatioMax = 1.140;

      const bool rc360DecisionOnly = IBRC360AblationMode == 5;

      if (IBRC360AblationMode == 5)
      {
        const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
        const double ieffNorm = rc360ClipPositive(pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr), 1e-9, 1e9);
        ibrc.lambdaPic = baseLambda;
        ibrc.lambdaCtu = baseLambda;
        ibrc.qs = rc360IbrcQsFromLambda(baseLambda, ieffNorm);
        ibrc.qp = rc360IbrcQpFromQs(ibrc.qs, qpMin, qpMax);
#if IBRC360SplitSkipModel
        const int temporalSegment = rc360ClosedLoopRateTemporalSegment(pcSlice->getPOC());
        const int predSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr));
        ibrc.predBitsRaw = rc360IbrcClosedLoopRateBits(predSkipClass, ibrc.rateBiasTargetClass, temporalSegment,
                                                       ibrc.qs, ieffNorm, pixels);
#else
        ibrc.predBitsRaw = rc360IbrcRateBits(ibrc.qs, ieffNorm, pixels);
#endif
        ibrc.predBits = ibrc.predBitsRaw * ibrc.rateBias;
        ibrc.predBpp = ibrc.predBits / double(std::max(1, pixels));
        ibrc.predD = rc360IbrcDistMse(ibrc.qs, ieffNorm);
        finalLambda = baseLambda;
        finalQp = baseQpLuma;
        dqp = 0;
        lambdaRatio = 1.0;
        modelLambdaForBlend = baseLambda;
        qpClipBefore = ibrc.qp;
        qpClipAfter = ibrc.qp;
      }
      else if (ctuMode == 1 || ctuMode == 3)
      {
        finalLambda = rc360ClipPositive(ibrc.lambdaCtu, 1e-12, 1e12);
        finalQp = ibrc.qp;
        dqp = finalQp - baseQpLuma;
        qpClipBefore = rc360IbrcQpFromQsUnclipped(ibrc.qs);
        qpClipAfter = finalQp;
#if IBRC360IeffOnlyCtuRD
        const int maxDelta = std::max(0, int(IBRC360IeffOnlyQpDeltaMax));
        const int unclippedFinalQp = finalQp;
        const int clippedFinalQp = Clip3(qpMin, qpMax,
                                         Clip3(baseQpLuma - maxDelta, baseQpLuma + maxDelta, finalQp));
        finalQp = clippedFinalQp;
        dqp = finalQp - baseQpLuma;
        qpClipBefore = unclippedFinalQp;
        qpClipAfter = finalQp;
        (void)rc360IeffOnlyEffectiveImportance(pEncLib->getLatFbTempComp(), pRateCtrl, pcv, ctuRsAddr,
                                               &ieffBaseImportance, &ieffSpendGate, &ieffSpendSkipGate,
                                               &ieffSpendHistGate, &ieffSpendHistRatio, &ieffSpendHistCount);
#if IBRC360IeffOnlyChromaRiskGuard
        chromaRisk = rc360CtuChromaGradient(pcPic, cs, ctuArea);
        if (std::abs(dqp) > int(IBRC360IeffOnlyChromaRiskMaxAbsDqp)
            && chromaRisk >= double(IBRC360IeffOnlyChromaRiskThresh))
        {
          chromaRiskGuardApplied = 1;
          dqp = Clip3(-int(IBRC360IeffOnlyChromaRiskMaxAbsDqp),
                      int(IBRC360IeffOnlyChromaRiskMaxAbsDqp), dqp);
          finalQp = Clip3(qpMin, qpMax, baseQpLuma + dqp);
          qpClipAfter = finalQp;
        }
#endif
#if IBRC360IeffOnlyChromaSafeTake
        chromaSafeTakeActivity =
          (ctuRsAddr >= 0 && ctuRsAddr < int(rc360ChromaSafeTakeActivity.size()))
            ? rc360ChromaSafeTakeActivity[ctuRsAddr]
            : rc360CtuChromaGradient(pcPic, cs, ctuArea);
        lumaSafeTakeActivity =
          (ctuRsAddr >= 0 && ctuRsAddr < int(rc360LumaSafeTakeActivity.size()))
            ? rc360LumaSafeTakeActivity[ctuRsAddr]
            : rc360CtuLumaGradient(pcPic, cs, ctuArea);
        chromaRisk = chromaSafeTakeActivity;
        if (dqp > 0)
        {
          const bool chromaBlocksTake = chromaSafeTakeActivity > rc360ChromaSafeTakeThreshold;
          const bool lumaBlocksTake = IBRC360IeffOnlyChromaSafeTakeLumaLowGate
                                   && lumaSafeTakeActivity > rc360LumaSafeTakeThreshold;
          if (chromaBlocksTake || lumaBlocksTake)
          {
            chromaSafeTakeApplied = 1;
            dqp = 0;
            finalQp = baseQpLuma;
            qpClipAfter = finalQp;
          }
        }
#endif
        ibrc.qs = rc360QsFromQp(finalQp);
        const double ieffForLambda = rc360IeffOnlyModelIeff(pEncLib->getLatFbTempComp(), ctuRsAddr);
        const double modelLambdaAfterQpClip = rc360IbrcLambdaFromQs(ibrc.qs, ieffForLambda);
        modelLambdaForBlend = modelLambdaAfterQpClip;
        // The fitted R-D lambda is a model-domain slope, while VTM RDO uses its own
        // lambda scale. After QP clipping, keep VTM lambda/QP consistency by applying
        // only the clipped delta-QP as a relative lambda change around native RC.
        finalLambda = rc360ClipPositive(baseLambda * std::pow(2.0, double(dqp) / 3.0), 1e-12, 1e12);
        ibrc.lambdaCtu = finalLambda;
        lambdaRatio = rc360ClipPositive(finalLambda / baseLambda, 1e-12, 1e12);
        const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
#if IBRC360SplitSkipModel
        const int temporalSegment = rc360ClosedLoopRateTemporalSegment(pcSlice->getPOC());
        const int predSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr));
        ibrc.predBitsRaw = rc360IbrcClosedLoopRateBits(predSkipClass, ibrc.rateBiasTargetClass, temporalSegment,
                                                       ibrc.qs, ieffForLambda, pixels);
#else
        ibrc.predBitsRaw = rc360IbrcRateBits(ibrc.qs, ieffForLambda, pixels);
#endif
        ibrc.predBits = ibrc.predBitsRaw * ibrc.rateBias;
        ibrc.predBpp = ibrc.predBits / double(std::max(1, pixels));
        ibrc.predD = rc360IbrcDistMse(ibrc.qs, ieffForLambda);
#endif
        rc360IbrcRcUpdateLambda = finalLambda;
      }
      else
      {
        if (ctuMode == 4)
        {
          const double oracleWeight =
            rc360IbrcOracleWeight(pCfg->getRc360IBRCCtuOracleMapFile(), pcPic->getPOC(), ctuRsAddr);
          weightLambda = baseLambda / std::pow(rc360ClipPositive(oracleWeight, 0.25, 4.0), weightAlpha);
          lambdaRatio = rc360ClipPositive(weightLambda / baseLambda, lambdaRatioMin, lambdaRatioMax);
        }
        else if (IBRC360AblationMode == 2)
        {
          const double meanLogWref =
            rc360IbrcMeanSpendableSoftControlLog(pEncLib->getLatFbTempComp(), pcv, pRateCtrl, 0.0);
          const double ctuLogWref =
            rc360IbrcSpendableSoftControlLog(pEncLib->getLatFbTempComp(), pRateCtrl, ctuRsAddr, 0.0);
          lambdaRatio = rc360ClipPositive(std::exp(-weightAlpha * (ctuLogWref - meanLogWref)),
                                          lambdaRatioMin, lambdaRatioMax);
          weightLambda = baseLambda * lambdaRatio;
          modelLambdaForBlend = ibrc.lambdaCtu;
        }
        else if (IBRC360AblationMode == 6)
        {
          const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
          const double ieffNorm = rc360ClipPositive(pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr), 1e-9, 1e9);
          ibrc.lambdaPic = baseLambda;
          ibrc.lambdaCtu = baseLambda;
          ibrc.qs = rc360IbrcQsFromLambda(baseLambda, ieffNorm);
          ibrc.qp = rc360IbrcQpFromQs(ibrc.qs, qpMin, qpMax);
#if IBRC360SplitSkipModel
          const int temporalSegment = rc360ClosedLoopRateTemporalSegment(pcSlice->getPOC());
          const int predSkipClass = rc360IbrcSkipClass(rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr));
          ibrc.predBitsRaw = rc360IbrcClosedLoopRateBits(predSkipClass, ibrc.rateBiasTargetClass, temporalSegment,
                                                         ibrc.qs, ieffNorm, pixels);
#else
          ibrc.predBitsRaw = rc360IbrcRateBits(ibrc.qs, ieffNorm, pixels);
#endif
          ibrc.predBits = ibrc.predBitsRaw * ibrc.rateBias;
          ibrc.predBpp = ibrc.predBits / double(std::max(1, pixels));
          ibrc.predD = rc360IbrcDistMse(ibrc.qs, ieffNorm);
          const int rdDqp = Clip3(-int(IBRC360AblationRdQpDelta), int(IBRC360AblationRdQpDelta), ibrc.qp - baseQpLuma);
          lambdaRatio = rc360ClipPositive(std::pow(2.0, double(rdDqp) / 3.0), lambdaRatioMin, lambdaRatioMax);
          weightLambda = baseLambda * lambdaRatio;
          modelLambdaForBlend = baseLambda;
        }
        else
        {
          const double meanSoftControlLog =
            rc360IbrcMeanSpendableSoftControlLog(pEncLib->getLatFbTempComp(), pcv, pRateCtrl, ieffAlpha);
          const double ctuSoftControlLog =
            rc360IbrcSpendableSoftControlLog(pEncLib->getLatFbTempComp(), pRateCtrl, ctuRsAddr, ieffAlpha);
          weightLambda = baseLambda * std::exp(-weightAlpha * (ctuSoftControlLog - meanSoftControlLog));
          const double ieffForGuard = pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr);
          rdIeffCalibrated = rc360IbrcCtuIeffCalibrated(ieffForGuard);
          rdGuardRawDistDlnDx = rc360IbrcRawDistDlnDx(ibrc.qs, ieffForGuard);
          rdGuardDistDlnDx = rc360IbrcDistDlnDx(ibrc.qs, ieffForGuard);
          const bool rdGuardIeffLow = rdIeffCalibrated < double(IBRC360RdGuardIeffMin);
          const bool rdGuardIeffHigh = rdIeffCalibrated > double(IBRC360RdGuardIeffMax);
          const bool rdGuardDInvalid = !std::isfinite(rdGuardRawDistDlnDx);
          const bool rdGuardDNeg = rdGuardRawDistDlnDx < 0.0;
          rdGuardReason = (rdGuardIeffLow ? 1 : 0)
                        | (rdGuardIeffHigh ? 2 : 0)
                        | (rdGuardDInvalid ? 4 : 0)
                        | (rdGuardDNeg ? 8 : 0);
#if IBRC360RdDomainGuard
          rdGuardApplied = rdGuardReason != 0 ? 1 : 0;
#endif
          modelLambdaForBlend = rdGuardApplied
                              ? weightLambda
                              : rc360ClipPositive(ibrc.lambdaCtu, weightLambda * lambdaRatioMin, weightLambda * lambdaRatioMax);
          const double blendedLambda =
            std::exp((1.0 - modelBlend) * std::log(rc360ClipPositive(weightLambda, 1e-12, 1e12))
                     + modelBlend * std::log(rc360ClipPositive(modelLambdaForBlend, 1e-12, 1e12)));
          lambdaRatio = rc360ClipPositive(blendedLambda / baseLambda, lambdaRatioMin, lambdaRatioMax);
        }
        finalLambda = baseLambda * lambdaRatio;
        const int dqpUnclipped = int(std::floor(3.0 * std::log(lambdaRatio) / std::log(2.0) + 0.5));
        qpClipBefore = baseQpLuma + dqpUnclipped;
        dqp = Clip3(-2, 2, dqpUnclipped);
        finalQp = Clip3(qpMin, qpMax, baseQpLuma + dqp);
        qpClipAfter = finalQp;
        rc360IbrcRcUpdateLambda = finalLambda;
      }

#if IBRC360IeffCtuWrefProtect
      ctuWrefProtectGain =
        1.0 + double(IBRC360IeffCtuWrefBeta) * std::max(0.0, rawWRef - 1.0);
      ctuWrefProtectGain = rc360ClipPositive(ctuWrefProtectGain, 1.0, 4.0);
      if (ctuWrefProtectGain > 1.0 + 1e-12)
      {
        ctuWrefProtectApplied = 1;
        const double lambdaBeforeWrefProtect = finalLambda;
        finalLambda = rc360ClipPositive(finalLambda / ctuWrefProtectGain, 1e-12, 1e12);
        ibrc.lambdaCtu = finalLambda;
        lambdaRatio = rc360ClipPositive(finalLambda / baseLambda, 1e-12, 1e12);
        rc360IbrcRcUpdateLambda = finalLambda;
        std::printf("[RC360IBRC][CtuWrefProtect] POC=%d ctu=%d rawWref=%.9f beta=%.6f gain=%.9f lambdaBefore=%.9f lambdaAfter=%.9f lambdaRatio=%.9f baseLambda=%.9f baseQP=%d finalQP=%d\n",
                    pcPic->getPOC(), ctuRsAddr, rawWRef, double(IBRC360IeffCtuWrefBeta),
                    ctuWrefProtectGain, lambdaBeforeWrefProtect, finalLambda, lambdaRatio,
                    baseLambda, baseQpLuma, finalQp);
        std::fflush(stdout);
      }
#endif

      if (!rc360DecisionOnly)
      {
        applyCtuLambdaQp(finalLambda, finalQp, dqp);
        rc360IbrcApplied = true;
#if IBRC360IeffOnlyCtuRD
        rc360IbrcRestoreState = true;
        rc360IbrcRestoreLambda = baseLambda;
        rc360IbrcRestoreQpLuma = baseQpLuma;
        rc360IbrcRestoreQpChroma = baseQpChroma;
#endif
      }
      rc360IbrcModelSampleValid = true;
      rc360IbrcModelQs = ibrc.qs;
#if IBRC360IeffOnlyCtuRD
      rc360IbrcModelIeff = rc360IeffOnlyModelIeff(pEncLib->getLatFbTempComp(), ctuRsAddr);
#else
      rc360IbrcModelIeff = pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr);
#endif
      rc360IbrcModelPredBits = ibrc.predBits;
      rc360IbrcModelPredBitsRaw = ibrc.predBitsRaw;
      rc360IbrcModelPredBpp = ibrc.predBpp;
      rc360IbrcModelPredD = ibrc.predD;
      rc360IbrcRateBias = ibrc.rateBias;
      rc360IbrcRateBiasTargetClass = ibrc.rateBiasTargetClass;
      rc360IbrcRateBiasSkipClass = ibrc.rateBiasSkipClass;
      rc360IbrcRateBiasCtuClass = ibrc.rateBiasCtuClass;
      int rc360DecisionModelUsed =
        (ctuMode == 1 || ctuMode == 3) ? 1
                                      : ((ctuMode == 4 || IBRC360AblationMode == 2 || rdGuardApplied != 0) ? 0 : 1);
      if (IBRC360AblationMode == 5)
      {
        rc360DecisionModelUsed = 0;
      }
      else if (IBRC360AblationMode == 6)
      {
        rc360DecisionModelUsed = 1;
      }
#if IBRC360AblationMode > 0 || IBRC360RdDomainGuard || IBRC360WrefNarrowGuard || IBRC360CtuDiagLog
      rc360CtuDiagEnabled = true;
      rc360CtuDiagModelUsed = rc360DecisionModelUsed;
      rc360CtuDiagDref = pEncLib->getLatFbTempComp()->getCtuDref(ctuRsAddr);
      rc360CtuDiagIeff = rc360IbrcModelIeff;
      rc360CtuDiagIeffRd = rc360IbrcCtuIeffCalibrated(rc360IbrcModelIeff);
      rc360CtuDiagWref = wRef;
      rc360CtuDiagLambdaPic = baseLambda;
      rc360CtuDiagLambdaCtu = finalLambda;
      rc360CtuDiagQs = ibrc.qs;
      rc360CtuDiagQpModel = ibrc.qp;
      rc360CtuDiagQpFinal = finalQp;
      rc360CtuDiagQpClipBefore = qpClipBefore;
      rc360CtuDiagQpClipAfter = qpClipAfter;
      rc360CtuDiagPredBits = ibrc.predBits;
      rc360CtuDiagPredD = ibrc.predD;
#else
      (void)qpClipBefore;
      (void)qpClipAfter;
#endif

      if (ctuRsAddr < 50)
      {
        const double ieffNorm =
#if IBRC360IeffOnlyCtuRD
          rc360IeffOnlyModelIeff(pEncLib->getLatFbTempComp(), ctuRsAddr);
#else
          pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr);
#endif
        const char* ctuTag = (ctuMode == 1 || ctuMode == 3) ? "CtuHard" : "CtuSoft";
        std::printf("[RC360IBRC][%s] POC=%d ctu=%d mode=%d guardFallback=%d remBits=%d remCtus=%d Ieff=%.9f IeffRd=%.9f IeffImportance=%.9f UpropNorm=%.9f UpropScale=%.9f ieffBaseImportance=%.9f ieffSpendGate=%.9f ieffSpendSkipGate=%.9f ieffSpendHistGate=%.9f ieffSpendHistRatio=%.9f ieffSpendHistCount=%d chromaRisk=%.9f chromaRiskGuard=%d chromaSafeTake=%d chromaTakeActivity=%.9f chromaTakeThreshold=%.9f lumaTakeActivity=%.9f lumaTakeThreshold=%.9f predBitsRaw=%.9f predBits=%.9f rateBias=%.9f rateBiasTargetClass=%d rateBiasSkipClass=%d rateBiasCtuClass=%d QS=%.9f lambdaVtm=%.9f lambdaModel=%.9f lambdaModelClipped=%.9f Wref=%.9f rawWref=%.9f predSkipRatio=%.9f wrefSpendGate=%.9f ctuWrefProtectGain=%.9f ctuWrefProtectApplied=%d ctuWrefBeta=%.6f weightLambda=%.9f lambdaFinal=%.9f lambdaRatio=%.9f baseQP=%d baseChromaQP=%d dqp=%d QP=%d chromaQP=%d predBpp=%.12f predOrdMse=%.9f sumRemBits=%.9f iters=%d modelBlend=%.9f weightAlpha=%.9f rdGuardApplied=%d rdGuardReason=%d rdGuardRawDistDlnDx=%.9f rdGuardDistDlnDx=%.9f rdGuardIeffMin=%.9f rdGuardIeffMax=%.9f ablationMode=%d modelUsed=%d ieffOnly=%d qpDeltaMax=%d chromaSafe=%d chromaSafeTakeEnable=%d chromaSafeTakePct=%.6f lumaLowGate=%d\n",
                    ctuTag, pcPic->getPOC(), ctuRsAddr, ctuMode, guardFallback ? 1 : 0,
                    remBits, pcv.sizeInCtus - ctuRsAddr,
                    ieffNorm, rc360IbrcCtuIeffCalibrated(ieffNorm),
                    rc360IeffOnlyImportance(ieffNorm),
                    upropNorm, upropScale,
                    ieffBaseImportance, ieffSpendGate, ieffSpendSkipGate,
                    ieffSpendHistGate, ieffSpendHistRatio, ieffSpendHistCount,
                    chromaRisk, chromaRiskGuardApplied, chromaSafeTakeApplied,
                    chromaSafeTakeActivity, rc360ChromaSafeTakeThreshold,
                    lumaSafeTakeActivity, rc360LumaSafeTakeThreshold,
                    ibrc.predBitsRaw, ibrc.predBits, ibrc.rateBias,
                    ibrc.rateBiasTargetClass, ibrc.rateBiasSkipClass, ibrc.rateBiasCtuClass,
                    ibrc.qs,
                    baseLambda, ibrc.lambdaCtu, modelLambdaForBlend, wRef, rawWRef,
                    predSkipRatioForWref, wRefSpendGate,
                    ctuWrefProtectGain, ctuWrefProtectApplied, double(IBRC360IeffCtuWrefBeta),
                    weightLambda, finalLambda, lambdaRatio, baseQpLuma, baseQpChroma, dqp, finalQp,
                    (IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafe) ? baseQpChroma
                                                                         : Clip3(qpMin, qpMax, baseQpChroma + dqp),
                    ibrc.predBpp, ibrc.predD, ibrc.sumRemBits, ibrc.iterations, modelBlend, weightAlpha,
                    rdGuardApplied, rdGuardReason, rdGuardRawDistDlnDx, rdGuardDistDlnDx,
                    double(IBRC360RdGuardIeffMin), double(IBRC360RdGuardIeffMax),
                    IBRC360AblationMode, rc360DecisionModelUsed,
                    IBRC360IeffOnlyCtuRD ? 1 : 0, int(IBRC360IeffOnlyQpDeltaMax),
                    (IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafe) ? 1 : 0,
                    (IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafeTake) ? 1 : 0,
                    double(IBRC360IeffOnlyChromaSafeTakePercentile),
                    int(IBRC360IeffOnlyChromaSafeTakeLumaLowGate));
        std::fflush(stdout);
      }
    }
#if ENABLE_QPA
    if (!pCfg->getUseRateCtrl() && pCfg->getUsePerceptQPA() && pcSlice->getPPS()->getUseDQP())
    {
#if ENABLE_QPA_SUB_CTU
      const int adaptedQP    = applyQPAdaptationSubCtu (cs, ctuArea, ctuRsAddr, m_pcCfg->getLumaLevelToDeltaQPMapping().mode == LUMALVL_TO_DQP_NUM_MODES);
#else
      const int adaptedQP    = pcPic->m_iOffsetCtu[ctuRsAddr];
#endif
      const double newLambda = pcSlice->getLambdas()[0] * pow (2.0, double (adaptedQP - iQPIndex) / 3.0);
      pcPic->m_uEnerHpCtu[ctuRsAddr] = newLambda; // for ALF and SAO
#if !ENABLE_QPA_SUB_CTU
#if RDOQ_CHROMA_LAMBDA
      pTrQuant->getLambdas (oldLambdaArray); // save the old lambdas
      const double lambdaArray[MAX_NUM_COMPONENT] = {newLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Y),
                                                     newLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Cb),
                                                     newLambda / m_pcRdCost->getDistortionWeight (COMPONENT_Cr)};
      pTrQuant->setLambdas (lambdaArray);
#else
      pTrQuant->setLambda (newLambda);
#endif
      pRdCost->setLambda (newLambda, pcSlice->getSPS()->getBitDepths());
#endif
      currQP.fill(adaptedQP);
    }
#endif

    bool   rc360FbApplied = false;
    double rc360BaseLambda = pRdCost->getLambda();

    int rc360BaseQP0 = currQP[ChannelType::LUMA];
    int rc360BaseQP1 = currQP[ChannelType::CHROMA];

    if ((IBRC360AblationMode == 4 || (IBRC360FrameOnlyWrefTarget && !IBRC360WrefOnlyLambda))
        && pEncLib->getRc360FbTc()
        && !pEncLib->getRc360CtuExp()
        && pEncLib->getLatFbTempComp()->hasCurrentPictureWeights()
        && !pcSlice->isIntra()
        && !bCompressEntireSlice)
    {
      const int qpBdOffset = pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA);
      const int qpMin = -qpBdOffset;
      const int qpMax = MAX_QP;
      const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
      const double wRef = rc360ClipPositive(pEncLib->getLatFbTempComp()->getCtuWeight(ctuRsAddr), 1e-6, 1e6);
      const double ieffNorm = rc360ClipPositive(pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr), 1e-9, 1e9);
      const double lambdaCtu = rc360BaseLambda / wRef;
      const double qs = rc360IbrcQsFromLambda(lambdaCtu, ieffNorm);
      const int qpModelUnclipped = rc360IbrcQpFromQsUnclipped(qs);
      const int qpModel = Clip3(qpMin, qpMax, qpModelUnclipped);
      rc360CtuDiagEnabled = true;
      rc360CtuDiagModelUsed = 0;
      rc360CtuDiagDref = pEncLib->getLatFbTempComp()->getCtuDref(ctuRsAddr);
      rc360CtuDiagIeff = ieffNorm;
      rc360CtuDiagWref = wRef;
      rc360CtuDiagLambdaPic = rc360BaseLambda;
      rc360CtuDiagLambdaCtu = lambdaCtu;
      rc360CtuDiagQs = qs;
      rc360CtuDiagQpModel = qpModel;
      rc360CtuDiagQpFinal = rc360BaseQP0;
      rc360CtuDiagQpClipBefore = qpModelUnclipped;
      rc360CtuDiagQpClipAfter = qpModel;
      rc360CtuDiagPredBits = rc360IbrcRateBits(qs, ieffNorm, pixels);
      rc360CtuDiagPredD = rc360IbrcDistMse(qs, ieffNorm);
    }

    if (pEncLib->getRc360FbTc()
        && !pEncLib->getRc360IBRC()
        && !pEncLib->getRc360CtuExp()
        && pEncLib->getLatFbTempComp()->hasCurrentPictureWeights()
        && !pcSlice->isIntra()
        && !bCompressEntireSlice
        && (!IBRC360WrefOnlyLambda || pCfg->getRc360IBRCCtuLevel())
        && (!IBRC360FrameOnlyWrefTarget || IBRC360FrameWrefSmallCtu || IBRC360WrefOnlyLambda)
        && IBRC360AblationMode != 4)
    {
      const double rawWRef = pEncLib->getLatFbTempComp()->getCtuWeight(ctuRsAddr);
      const double predSkipRatioForWref = pCfg->getUseRateCtrl() ? rc360IbrcPredSkipRatio(pRateCtrl, ctuRsAddr) : 0.0;
      double wRef = rc360SpendabilityEffectiveWref(rawWRef, predSkipRatioForWref);
      double rc360GainBudgetGate = 1.0;
#if IBRC360FrameWrefSmallCtu
      if (IBRC360FrameOnlyWrefTarget && !IBRC360WrefOnlyLambda)
      {
        const double smallWref = Clip3(double(IBRC360FrameWrefSmallCtuMin),
                                       double(IBRC360FrameWrefSmallCtuMax),
                                       wRef);
        const double smallSpendGate = rc360WrefSpendabilityGateFromSkip(predSkipRatioForWref);
        wRef = 1.0 + smallSpendGate * (smallWref - 1.0);
      }
#endif
#if IBRC360AblationMode == 9
      if (pCfg->getUseRateCtrl() && pRateCtrl != nullptr && pRateCtrl->getRCPic() != nullptr && ctuIdx > 0)
      {
        const double targetPicBits = std::max(1.0, double(pRateCtrl->getRCPic()->getTargetBits()));
        const double expectedUsedBefore =
          targetPicBits * double(ctuIdx) / double(std::max<uint32_t>(1, pcSlice->getNumCtuInSlice()));
        const double actualUsedBefore = double(std::max<uint64_t>(0, m_uiPicTotalBits));
        const double overshootRatio = expectedUsedBefore > 1.0 ? actualUsedBefore / expectedUsedBefore : 1.0;
        const double start = std::max(1e-9, double(IBRC360GainBudgetOvershootStart));
        const double full = std::max(start + 1e-9, double(IBRC360GainBudgetOvershootFull));
        const double t = rc360ClipPositive((overshootRatio - start) / (full - start), 0.0, 1.0);
        rc360GainBudgetGate = 1.0 - t;
        if (wRef > 1.0)
        {
          wRef = 1.0 + rc360GainBudgetGate * (wRef - 1.0);
        }
      }
#endif

      if (wRef > 1e-9)
      {
        const double newLambda = rc360BaseLambda / wRef;

        const int qpBdOffset =
          pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA);

        const double log2WRef = std::log(wRef) / std::log(2.0);
        const double dqpFloat = 3.0 * log2WRef;
        const int dqp =
          int(std::floor(dqpFloat + 0.5));

        const int newQP =
          Clip3(-qpBdOffset, MAX_QP, rc360BaseQP0 - dqp);

        pRdCost->setLambda(newLambda, pcSlice->getSPS()->getBitDepths());

#if RDOQ_CHROMA_LAMBDA
        const double lambdaArray[MAX_NUM_COMPONENT] =
        {
          newLambda / pRdCost->getDistortionWeight(COMPONENT_Y),
          newLambda / pRdCost->getDistortionWeight(COMPONENT_Cb),
          newLambda / pRdCost->getDistortionWeight(COMPONENT_Cr)
        };

        pTrQuant->setLambdas(lambdaArray);
#else
        pTrQuant->setLambda(newLambda);
#endif

        currQP[ChannelType::LUMA] = newQP;
        currQP[ChannelType::CHROMA] = newQP;

        if (pCfg->getUseRateCtrl())
        {
          pRateCtrl->setRCQP(newQP);
        }

#if IBRC360WrefOnlyLambda || IBRC360CtuDiagLog
        rc360CtuDiagEnabled = true;
        rc360CtuDiagModelUsed = 0;
        rc360CtuDiagDref = pEncLib->getLatFbTempComp()->getCtuDref(ctuRsAddr);
        rc360CtuDiagIeff = pEncLib->getLatFbTempComp()->getCtuModelIeff(ctuRsAddr);
        rc360CtuDiagIeffRd = 1.0;
        rc360CtuDiagWref = wRef;
        rc360CtuDiagLambdaPic = rc360BaseLambda;
        rc360CtuDiagLambdaCtu = newLambda;
        rc360CtuDiagQs = 1.0;
        rc360CtuDiagQpModel = rc360BaseQP0 - dqp;
        rc360CtuDiagQpFinal = newQP;
        rc360CtuDiagQpClipBefore = rc360BaseQP0 - dqp;
        rc360CtuDiagQpClipAfter = newQP;
        rc360CtuDiagPredBits = 0.0;
        rc360CtuDiagPredD = 0.0;
#endif

        if (ctuRsAddr < 50)
        {
          std::printf("[RC360FbTc][WrefApply] POC=%d ctu=%d wRef=%.9f rawWref=%.9f predSkipRatio=%.9f spendGate=%.9f gainBudgetGate=%.9f lambdaOld=%.9f lambdaNew=%.9f qpOldLuma=%d qpOldChroma=%d qpBdOffset=%d log2WRef=%.9f dqpFloat=%.9f dqp=%d unclippedQP=%d qpMin=%d qpMax=%d qpNew=%d rateCtrl=%d ablationMode=%d oracleGroup=%d frameOnlyWrefTarget=%d smallCtu=%d smallCtuMin=%.9f smallCtuMax=%.9f\n",
                      pcPic->getPOC(), ctuRsAddr, wRef, rawWRef, predSkipRatioForWref,
                      rc360WrefSpendabilityGateFromSkip(predSkipRatioForWref), rc360GainBudgetGate,
                      rc360BaseLambda, newLambda,
                      rc360BaseQP0, rc360BaseQP1, qpBdOffset, log2WRef, dqpFloat, dqp,
                      rc360BaseQP0 - dqp, -qpBdOffset, MAX_QP, newQP, pCfg->getUseRateCtrl() ? 1 : 0,
                      IBRC360AblationMode, IBRC360GainOracleGroup,
                      IBRC360FrameOnlyWrefTarget ? 1 : 0, IBRC360FrameWrefSmallCtu ? 1 : 0,
                      double(IBRC360FrameWrefSmallCtuMin), double(IBRC360FrameWrefSmallCtuMax));
          std::fflush(stdout);
        }

        rc360FbApplied = true;
      }
    }

    bool   rc360PaperTIApplied = false;
    double rc360PaperTIBaseLambda = pRdCost->getLambda();
    double rc360PaperTIFinalLambda = rc360PaperTIBaseLambda;
    int    rc360PaperTIBaseQpLuma = currQP[ChannelType::LUMA];
    int    rc360PaperTIBaseQpChroma = currQP[ChannelType::CHROMA];
    if (pCfg->getUseRateCtrl()
        && pCfg->getRc360PaperTI()
        && pCfg->getRc360PaperTICtu()
        && pEncLib->getRc360PaperTI()->hasPicture(pcPic->getPOC())
        && !pcSlice->isIntra()
        && !bCompressEntireSlice)
    {
      const int qpBdOffset = pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA);
      const int qpMin = -qpBdOffset;
      const int qpMax = MAX_QP;
      const double ctuT = Clip3(pCfg->getRc360PaperTICtuMin(),
                                pCfg->getRc360PaperTICtuMax(),
                                pEncLib->getRc360PaperTI()->getCtuImportance(pcPic->getPOC(), ctuRsAddr));
      const double unclippedLambda =
        rc360ClipPositive(rc360PaperTIBaseLambda / std::max(1e-9, ctuT), 1e-12, 1e12);
      const double unclippedDqpFloat =
        3.0 * (std::log(unclippedLambda / std::max(1e-12, rc360PaperTIBaseLambda)) / std::log(2.0));
      const int unclippedDqp = int(std::floor(unclippedDqpFloat + (unclippedDqpFloat >= 0.0 ? 0.5 : -0.5)));
      const int maxAbsDqp = std::max(0, pCfg->getRc360PaperTIQpDeltaMax());
      const int dqp = Clip3(-maxAbsDqp, maxAbsDqp, pEncLib->getRc360PaperTI()->getCtuDqp(pcPic->getPOC(), ctuRsAddr));
      const int finalQp = Clip3(qpMin, qpMax, rc360PaperTIBaseQpLuma + dqp);
      const double finalLambda =
        rc360ClipPositive(rc360PaperTIBaseLambda * std::pow(2.0, double(finalQp - rc360PaperTIBaseQpLuma) / 3.0),
                          1e-12, 1e12);
      rc360PaperTIFinalLambda = finalLambda;

      pRdCost->setLambda(finalLambda, pcSlice->getSPS()->getBitDepths());
#if WCG_EXT
      pRdCost->saveUnadjustedLambda();
#endif
      double lambdaArray[MAX_NUM_COMPONENT] = { finalLambda };
      for (uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++)
      {
        const ComponentID compID = ComponentID(compIdx);
        int chromaQPOffset = pcSlice->getPPS()->getQpOffset(compID) + pcSlice->getSliceChromaQpDelta(compID);
        int qpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, finalQp) + chromaQPOffset;
        double tmpWeight = std::pow(2.0, (finalQp - qpc) / 3.0);
        if (m_pcCfg->getDepQuantEnabledFlag())
        {
          tmpWeight *= (m_pcCfg->getGOPSize() >= 8 ? std::pow(2.0, 0.1 / 3.0) : std::pow(2.0, 0.2 / 3.0));
        }
        m_pcRdCost->setDistortionWeight(compID, tmpWeight);
        lambdaArray[compIdx] = finalLambda / tmpWeight;
      }
#if RDOQ_CHROMA_LAMBDA
      lambdaArray[COMPONENT_Y] = finalLambda / m_pcRdCost->getDistortionWeight(COMPONENT_Y);
      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(finalLambda);
#endif
      currQP[ChannelType::LUMA] = finalQp;
      currQP[ChannelType::CHROMA] = Clip3(qpMin, qpMax, rc360PaperTIBaseQpChroma + dqp);
      pRateCtrl->setRCQP(finalQp);
      pcPic->m_uEnerHpCtu[ctuRsAddr] = finalLambda;
      rc360PaperTIApplied = true;

      if (ctuRsAddr < 50)
      {
        std::printf("[RC360PaperTI][CtuLambda] POC=%d ctu=%d ctuT=%.9f baseLambda=%.9f unclippedLambda=%.9f finalLambda=%.9f baseQpLuma=%d baseQpChroma=%d dqpFloat=%.9f dqpUnclipped=%d dqp=%d finalQpLuma=%d finalQpChroma=%d qpDeltaMax=%d\n",
                    pcPic->getPOC(), ctuRsAddr, ctuT, rc360PaperTIBaseLambda, unclippedLambda, finalLambda,
                    rc360PaperTIBaseQpLuma, rc360PaperTIBaseQpChroma, unclippedDqpFloat, unclippedDqp,
                    dqp, finalQp, currQP[ChannelType::CHROMA], maxAbsDqp);
        std::fflush(stdout);
      }
    }

    bool   rc360OracleApplied = false;
    double rc360OracleBaseLambda = pRdCost->getLambda();
    double rc360OracleFinalLambda = rc360OracleBaseLambda;
    int    rc360OracleRestoreQpLuma = currQP[ChannelType::LUMA];
    int    rc360OracleRestoreQpChroma = currQP[ChannelType::CHROMA];
    double rc360OracleDumpBaseLambda = std::numeric_limits<double>::quiet_NaN();
    int    rc360OracleDumpBaseQpLuma = g_RCInvalidQPValue;
    int    rc360OracleDumpBaseQpChroma = g_RCInvalidQPValue;
    if (pCfg->getUseRateCtrl()
        && pEncLib->getRc360OracleReplay()->isEnabled()
        && !pcSlice->isIntra()
        && !bCompressEntireSlice)
    {
      Rc360OracleReplay* oracle = pEncLib->getRc360OracleReplay();
      const Rc360OracleReplay::BaseEntry* base = oracle->getBaseEntry(pcPic->getPOC(), ctuRsAddr);
      if (base == nullptr)
      {
        std::fprintf(stderr, "[RC360OracleReplay] missing base entry POC=%d ctu=%d\n",
                     pcPic->getPOC(), ctuRsAddr);
        std::exit(1);
      }

      const int qpBdOffset = pcSlice->getSPS()->getQpBDOffset(ChannelType::LUMA);
      const int qpMin = -qpBdOffset;
      const int dqp = oracle->getReplayDqp(pcPic->getPOC(), ctuRsAddr);
      const int finalQpLuma = Clip3(qpMin, MAX_QP, base->baseQpLuma + dqp);
      const int finalQpChroma = Clip3(qpMin, MAX_QP, base->baseQpChroma);
      const double finalLambda =
        rc360ClipPositive(base->baseLambda * std::pow(2.0, double(finalQpLuma - base->baseQpLuma) / 3.0),
                          1e-12, 1e12);
      rc360OracleFinalLambda = finalLambda;

      pRdCost->setLambda(finalLambda, pcSlice->getSPS()->getBitDepths());
#if WCG_EXT
      pRdCost->saveUnadjustedLambda();
#endif
      double lambdaArray[MAX_NUM_COMPONENT] = { finalLambda };
      for (uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++)
      {
        const ComponentID compID = ComponentID(compIdx);
        const int chromaQPOffset = pcSlice->getPPS()->getQpOffset(compID) + pcSlice->getSliceChromaQpDelta(compID);
        const int qpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, finalQpLuma) + chromaQPOffset;
        double tmpWeight = std::pow(2.0, (finalQpLuma - qpc) / 3.0);
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlyChromaSafe
        if (IBRC360IeffOnlyCtuRD)
        {
          const int baseQpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, base->baseQpLuma) + chromaQPOffset;
          const double baseWeight = std::pow(2.0, (base->baseQpLuma - baseQpc) / 3.0);
          tmpWeight = baseWeight * rc360ClipPositive(finalLambda / base->baseLambda, 1e-6, 1e6);
        }
#endif
        if (m_pcCfg->getDepQuantEnabledFlag())
        {
          tmpWeight *= (m_pcCfg->getGOPSize() >= 8 ? std::pow(2.0, 0.1 / 3.0) : std::pow(2.0, 0.2 / 3.0));
        }
        m_pcRdCost->setDistortionWeight(compID, tmpWeight);
        lambdaArray[compIdx] = finalLambda / tmpWeight;
      }
#if RDOQ_CHROMA_LAMBDA
      lambdaArray[COMPONENT_Y] = finalLambda / m_pcRdCost->getDistortionWeight(COMPONENT_Y);
      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(finalLambda);
#endif
      currQP[ChannelType::LUMA] = finalQpLuma;
      currQP[ChannelType::CHROMA] = finalQpChroma;
      pRateCtrl->setRCQP(finalQpLuma);
      rc360OracleApplied = true;

      if (ctuRsAddr < 8 || dqp != 0)
      {
        std::printf("[RC360OracleReplay][Apply] POC=%d ctu=%d baseQpLuma=%d baseQpChroma=%d dqp=%d finalQpLuma=%d finalQpChroma=%d baseLambda=%.12f finalLambda=%.12f mapFile=%d\n",
                    pcPic->getPOC(), ctuRsAddr, base->baseQpLuma, base->baseQpChroma, dqp,
                    finalQpLuma, finalQpChroma, base->baseLambda, finalLambda,
                    oracle->config().mapFile.empty() ? 0 : 1);
        std::fflush(stdout);
      }
    }

    rc360OracleDumpBaseLambda = pRdCost->getLambda();
    rc360OracleDumpBaseQpLuma = currQP[ChannelType::LUMA];
    rc360OracleDumpBaseQpChroma = currQP[ChannelType::CHROMA];

    bool updateBcwCodingOrder = cs.slice->getSliceType() == B_SLICE && ctuIdx == 0;
    if( updateBcwCodingOrder )
    {
      resetBcwCodingOrder(false, cs);
      m_pcInterSearch->initWeightIdxBits();
    }
    if (pcSlice->getSPS()->getUseLmcs())
    {
      m_pcCuEncoder->setDecCuReshaperInEncCU(m_pcLib->getReshaper(), pcSlice->getSPS()->getChromaFormatIdc());
    }
    if( !cs.slice->isIntra() && pCfg->getMCTSEncConstraint() )
    {
      pcPic->mctsInfo.init( &cs, ctuRsAddr );
    }

    if (pCfg->getSwitchPOC() != pcPic->poc || ctuRsAddr >= pCfg->getDebugCTU())
    {
      m_pcCuEncoder->compressCtu(cs, ctuArea, ctuRsAddr, prevQP, currQP);
#if GREEN_METADATA_SEI_ENABLED
      FeatureCounterStruct m_featureCounter = pcPic->getFeatureCounter();
      countFeatures(m_featureCounter, cs,ctuArea);
      pcPic->setFeatureCounter(m_featureCounter);
#endif
    }
#if K0149_BLOCK_STATISTICS
    getAndStoreBlockStatistics(cs, ctuArea);
#endif

    pCABACWriter->resetBits();
    pCABACWriter->coding_tree_unit( cs, ctuArea, prevQP, ctuRsAddr, true, true );
    const int numberOfWrittenBits = int( pCABACWriter->getEstFracBits() >> SCALE_BITS );

    pcSlice->setSliceBits( ( uint32_t ) ( pcSlice->getSliceBits() + numberOfWrittenBits ) );

    // Store probabilities of first CTU in line into buffer - used only if wavefront-parallel-processing is enabled.
    if( cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && pEncLib->getEntropyCodingSyncEnabledFlag() )
    {
      pEncLib->m_entropyCodingSyncContextState = pCABACWriter->getCtx();
      cs.storePrevPLT(pEncLib->m_palettePredictorSyncState);
    }

    int actualBits = int(cs.fracBits >> SCALE_BITS);
    actualBits    -= (int)m_uiPicTotalBits;
    const double rc360ActualLambda = pRdCost->getLambda();
    double rc360ActualD = std::numeric_limits<double>::quiet_NaN();
    if ((rc360IbrcApplied && rc360IbrcModelSampleValid && pCfg->getRc360IBRCModelUpdate())
        || rc360CtuDiagEnabled)
    {
      rc360ActualD = rc360CtuOrdinaryMse(pcPic, cs, pcSlice, ctuArea);
    }
#if IBRC360SplitSkipModel
#if !IBRC360ClosedLoopRateModel
    int rc360ActualSkipPixel = 0;
    for (auto &cu: cs.traverseCUs(ctuArea, ChannelType::LUMA))
    {
      rc360ActualSkipPixel += cu.skip * cu.lumaSize().area();
    }
    const double rc360ActualSkipRatio =
      double(rc360ActualSkipPixel) / double(std::max<int>(1, ctuArea.lumaSize().area()));
    const int rc360ActualSkipClass = rc360IbrcSkipClass(rc360ActualSkipRatio);
#endif
#endif
    if (rc360IbrcApplied && rc360IbrcModelSampleValid && pCfg->getRc360IBRCModelUpdate())
    {
#if !IBRC360SplitSkipModel || !IBRC360ClosedLoopRateModel
      const int pixels = rc360CtuNumPixels(pcv, ctuRsAddr);
      const double actualBpp = double(std::max(0, actualBits)) / double(std::max(1, pixels));
      rc360RateBiasUpdate(rc360IbrcRateBiasTargetClass,
                          rc360IbrcRateBiasSkipClass,
                          rc360IbrcRateBiasCtuClass,
                          rc360IbrcModelPredBits,
                          actualBits,
                                 pcPic->getPOC(),
                                 ctuRsAddr);
#endif
#if IBRC360SplitSkipModel
#if !IBRC360ClosedLoopRateModel
      Rc360IbrcModelSample sample;
      sample.qs = rc360IbrcModelQs;
      sample.ieffNorm = rc360IbrcModelIeff;
      sample.actualBpp = actualBpp;
      sample.actualD = rc360ActualD;
      sample.poc = pcPic->getPOC();
      sample.ctu = ctuRsAddr;
      sample.predSkipClass = rc360IbrcPredSkipClass;
      sample.actualSkipClass = rc360ActualSkipClass;
      sample.predSkipRatio = rc360IbrcPredSkip;
      sample.actualSkipRatio = rc360ActualSkipRatio;
      rc360IbrcUpdateCtuSkipModel(pCfg->getRc360IBRCModelUpdateStepR(),
                                  pCfg->getRc360IBRCModelUpdateStepD(),
                                  sample);
      rc360IbrcFrameModelSamples.push_back(sample);
#endif
#else
      rc360IbrcOnlineModelUpdate(pCfg->getRc360IBRCModelUpdateStepR(),
                                 pCfg->getRc360IBRCModelUpdateStepD(),
                                 rc360IbrcModelQs,
                                 rc360IbrcModelIeff,
                                 rc360IbrcModelPredBpp,
                                 actualBpp,
                                 rc360IbrcModelPredD,
                                 rc360ActualD,
                                 pcPic->getPOC(),
                                 ctuRsAddr);
#endif
    }
#if IBRC360IeffOnlyCtuRD && IBRC360IeffOnlySpendabilityGate
    if (rc360IbrcApplied && rc360IbrcModelSampleValid)
    {
      rc360IeffOnlySpendabilityUpdate(rc360IbrcRateBiasTargetClass,
                                      rc360IbrcRateBiasSkipClass,
                                      rc360IbrcRateBiasCtuClass,
                                      rc360IbrcModelPredBits,
                                      actualBits,
                                      pcPic->getPOC(),
                                      ctuRsAddr);
    }
#endif
    if (rc360CtuDiagEnabled)
    {
      CodingUnit *diagCu = cs.getCU(ctuArea.lumaPos(), ChannelType::LUMA);
      const int actualQp = diagCu ? diagCu->qp : g_RCInvalidQPValue;
      const int qpFinalForLog = actualQp != g_RCInvalidQPValue ? actualQp : rc360CtuDiagQpFinal;
      const double predBppForRatio =
        rc360CtuNumPixels(pcv, ctuRsAddr) > 0
          ? rc360CtuDiagPredBits / double(rc360CtuNumPixels(pcv, ctuRsAddr))
          : 0.0;
      const double actualBppForRatio =
        double(std::max(0, actualBits)) / double(std::max(1, rc360CtuNumPixels(pcv, ctuRsAddr)));
      const double actualPredRatio = predBppForRatio > 0.0 ? actualBppForRatio / predBppForRatio : 0.0;
      rc360WriteCtuClosedLoopSample(pcPic, cs, pcSlice, pEncLib, pRateCtrl, ctuArea, ctuRsAddr,
                                    actualBits, rc360CtuDiagIeff, rc360CtuDiagIeffRd,
                                    rc360CtuDiagDref, rc360CtuDiagWref,
                                    rc360CtuDiagLambdaPic, rc360CtuDiagLambdaCtu,
                                    rc360CtuDiagQs, rc360CtuDiagQpModel, qpFinalForLog,
                                    rc360CtuDiagQpClipBefore, rc360CtuDiagQpClipAfter,
                                    rc360CtuDiagPredBits, rc360IbrcModelPredBitsRaw,
                                    rc360IbrcRateBias, rc360IbrcRateBiasTargetClass,
                                    rc360IbrcRateBiasSkipClass, rc360IbrcRateBiasCtuClass,
                                    rc360CtuDiagModelUsed);
      std::printf("[RC360IBRC][CtuDiag] POC=%d ctu=%d Dref=%.9f Ieff=%.9f IeffRd=%.9f Wref=%.9f lambdaPic=%.9f lambdaCtu=%.9f QS=%.9f QP_model=%d QP_final=%d predBitsRaw=%.9f predBits=%.9f rateBias=%.9f rateBiasTargetClass=%d rateBiasSkipClass=%d rateBiasCtuClass=%d actualBits=%d predD=%.9f actualD=%.9f QP_clip_before=%d QP_clip_after=%d ablationMode=%d modelUsed=%d actualBitsOverPredBits=%.12f\n",
                  pcPic->getPOC(), ctuRsAddr, rc360CtuDiagDref, rc360CtuDiagIeff, rc360CtuDiagIeffRd, rc360CtuDiagWref,
                  rc360CtuDiagLambdaPic, rc360CtuDiagLambdaCtu, rc360CtuDiagQs,
                  rc360CtuDiagQpModel, qpFinalForLog,
                  rc360IbrcModelPredBitsRaw, rc360CtuDiagPredBits, rc360IbrcRateBias,
                  rc360IbrcRateBiasTargetClass, rc360IbrcRateBiasSkipClass, rc360IbrcRateBiasCtuClass,
                  actualBits,
                  rc360CtuDiagPredD, rc360ActualD, rc360CtuDiagQpClipBefore, rc360CtuDiagQpClipAfter,
                  IBRC360AblationMode, rc360CtuDiagModelUsed, actualPredRatio);
      std::fflush(stdout);
    }
    rc360WriteOracleBaselineSample(pcPic, cs, pcSlice, pEncLib, pRateCtrl, ctuArea, ctuRsAddr,
                                   actualBits, rc360OracleDumpBaseLambda,
                                   rc360OracleDumpBaseQpLuma, rc360OracleDumpBaseQpChroma);
    if (rc360OracleApplied)
    {
      pRdCost->setLambda(rc360OracleBaseLambda, pcSlice->getSPS()->getBitDepths());
#if RDOQ_CHROMA_LAMBDA
      const double lambdaArray[MAX_NUM_COMPONENT] =
      {
        rc360OracleBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Y),
        rc360OracleBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cb),
        rc360OracleBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cr)
      };
      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(rc360OracleBaseLambda);
#endif
      currQP[ChannelType::LUMA] = rc360OracleRestoreQpLuma;
      currQP[ChannelType::CHROMA] = rc360OracleRestoreQpChroma;
      pRateCtrl->setRCQP(rc360OracleRestoreQpLuma);
    }
    if (rc360FbApplied)
    {
      pRdCost->setLambda(rc360BaseLambda, pcSlice->getSPS()->getBitDepths());

#if RDOQ_CHROMA_LAMBDA
      const double lambdaArray[MAX_NUM_COMPONENT] =
      {
        rc360BaseLambda / pRdCost->getDistortionWeight(COMPONENT_Y),
        rc360BaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cb),
        rc360BaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cr)
      };

      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(rc360BaseLambda);
#endif

      currQP[ChannelType::LUMA] = rc360BaseQP0;
      currQP[ChannelType::CHROMA] = rc360BaseQP1;

      if (pCfg->getUseRateCtrl())
      {
        pRateCtrl->setRCQP(rc360BaseQP0);
      }
    }
    if (rc360PaperTIApplied)
    {
      pRdCost->setLambda(rc360PaperTIBaseLambda, pcSlice->getSPS()->getBitDepths());
#if RDOQ_CHROMA_LAMBDA
      const double lambdaArray[MAX_NUM_COMPONENT] =
      {
        rc360PaperTIBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Y),
        rc360PaperTIBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cb),
        rc360PaperTIBaseLambda / pRdCost->getDistortionWeight(COMPONENT_Cr)
      };
      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(rc360PaperTIBaseLambda);
#endif
      currQP[ChannelType::LUMA] = rc360PaperTIBaseQpLuma;
      currQP[ChannelType::CHROMA] = rc360PaperTIBaseQpChroma;
      pRateCtrl->setRCQP(rc360PaperTIBaseQpLuma);
    }
#if IBRC360IeffOnlyCtuRD
    if (rc360IbrcRestoreState)
    {
      pRdCost->setLambda(rc360IbrcRestoreLambda, pcSlice->getSPS()->getBitDepths());
#if RDOQ_CHROMA_LAMBDA
      const double lambdaArray[MAX_NUM_COMPONENT] =
      {
        rc360IbrcRestoreLambda / pRdCost->getDistortionWeight(COMPONENT_Y),
        rc360IbrcRestoreLambda / pRdCost->getDistortionWeight(COMPONENT_Cb),
        rc360IbrcRestoreLambda / pRdCost->getDistortionWeight(COMPONENT_Cr)
      };
      pTrQuant->setLambdas(lambdaArray);
#else
      pTrQuant->setLambda(rc360IbrcRestoreLambda);
#endif
      currQP[ChannelType::LUMA] = rc360IbrcRestoreQpLuma;
      currQP[ChannelType::CHROMA] = rc360IbrcRestoreQpChroma;
      if (pCfg->getUseRateCtrl())
      {
        pRateCtrl->setRCQP(rc360IbrcRestoreQpLuma);
      }
    }
#endif
    if ( pCfg->getUseRateCtrl() )
    {
      int actualQP        = g_RCInvalidQPValue;
      double actualLambda = rc360OracleApplied
        ? rc360OracleFinalLambda
        : (rc360FbApplied
             ? rc360ActualLambda
             : (rc360IbrcApplied ? rc360IbrcRcUpdateLambda
                                 : (rc360PaperTIApplied ? rc360PaperTIFinalLambda : pRdCost->getLambda())));
      int numberOfEffectivePixels    = 0;

      int numberOfSkipPixel = 0;
      for (auto &cu: cs.traverseCUs(ctuArea, ChannelType::LUMA))
      {
        numberOfSkipPixel += cu.skip*cu.lumaSize().area();
      }

      for (auto &cu: cs.traverseCUs(ctuArea, ChannelType::LUMA))
      {
        if( !cu.skip || cu.rootCbf )
        {
          numberOfEffectivePixels += cu.lumaSize().area();
          break;
        }
      }
      double skipRatio = (double)numberOfSkipPixel / ctuArea.lumaSize().area();
      CodingUnit *cu        = cs.getCU(ctuArea.lumaPos(), ChannelType::LUMA);

      if ( numberOfEffectivePixels == 0 )
      {
        actualQP = g_RCInvalidQPValue;
      }
      else
      {
        actualQP = cu->qp;
      }
      pRdCost->setLambda(oldLambda, pcSlice->getSPS()->getBitDepths());
      int estQP        = pcSlice->getSliceQp();
      for (uint32_t compIdx = 1; compIdx < MAX_NUM_COMPONENT; compIdx++)
      {
        const ComponentID compID = ComponentID(compIdx);
        int chromaQPOffset = pcSlice->getPPS()->getQpOffset(compID) + pcSlice->getSliceChromaQpDelta(compID);
        int qpc = pcSlice->getSPS()->getMappedChromaQpValue(compID, estQP) + chromaQPOffset;
        double tmpWeight = pow(2.0, (estQP - qpc) / 3.0);  // takes into account of the chroma qp mapping and chroma qp Offset
        if (m_pcCfg->getDepQuantEnabledFlag())
        {
          tmpWeight *= (m_pcCfg->getGOPSize() >= 8 ? pow(2.0, 0.1 / 3.0) : pow(2.0, 0.2 / 3.0));  // increase chroma weight for dependent quantization (in order to reduce bit rate shift from chroma to luma)
        }
        m_pcRdCost->setDistortionWeight(compID, tmpWeight);
      }
      pRateCtrl->getRCPic()->updateAfterCTU(pRateCtrl->getRCPic()->getLCUCoded(), actualBits, actualQP, actualLambda, skipRatio,
        pcSlice->isIRAP() ? 0 : pCfg->getLCULevelRC());
    }
#if ENABLE_QPA && !ENABLE_QPA_SUB_CTU
    else if (pCfg->getUsePerceptQPA() && pcSlice->getPPS()->getUseDQP())
    {
#if RDOQ_CHROMA_LAMBDA
      pTrQuant->setLambdas (oldLambdaArray);
#else
      pTrQuant->setLambda (oldLambda);
#endif
      pRdCost->setLambda (oldLambda, pcSlice->getSPS()->getBitDepths());
    }
#endif

    rc360WriteCtuHeatmapSample(pcPic, cs, pcSlice, pEncLib, pRateCtrl, ctuRsAddr, actualBits, rc360ActualLambda);
    rc360WriteIeffCompareSample(pcPic, cs, pcSlice, pEncLib, pRateCtrl, ctuRsAddr, actualBits, rc360ActualLambda);
    rc360WriteCtuExpSample(pcPic, cs, pcSlice, pEncLib, ctuArea, ctuRsAddr, actualBits, rc360ActualLambda);

    m_uiPicTotalBits += actualBits;
    m_uiPicDist       = cs.dist;
    // for last Ctu in the slice
    if (pcSlice->getPPS()->getNumSubPics() >= 2 && curSubPic.getTreatedAsPicFlag() && ctuIdx == (pcSlice->getNumCtuInSlice() - 1))
    {
      int subPicX = (int)curSubPic.getSubPicLeft();
      int subPicY = (int)curSubPic.getSubPicTop();
      int subPicWidth = (int)curSubPic.getSubPicWidthInLumaSample();
      int subPicHeight = (int)curSubPic.getSubPicHeightInLumaSample();

      for (int rlist = REF_PIC_LIST_0; rlist < NUM_REF_PIC_LIST_01; rlist++)
      {
        int n = pcSlice->getNumRefIdx((RefPicList)rlist);
        for (int idx = 0; idx < n; idx++)
        {
          Picture *refPic = pcSlice->getRefPic((RefPicList)rlist, idx);
          if (refPic->getSubPicSaved())
          {
            refPic->restoreSubPicBorder(refPic->getPOC(), subPicX, subPicY, subPicWidth, subPicHeight);
            refPic->setSubPicSaved(false);
          }
        }
      }
    }
  }
#if IBRC360SplitSkipModel
#if !IBRC360ClosedLoopRateModel
  if (pCfg->getUseRateCtrl()
      && pCfg->getRc360IBRC()
      && pCfg->getRc360IBRCModelUpdate()
      && !pcSlice->isIntra()
      && !bCompressEntireSlice
      && !rc360IbrcFrameModelSamples.empty())
  {
    rc360IbrcUpdateFrameModelAfterPicture(pCfg->getRc360IBRCModelUpdateStepR(),
                                          pCfg->getRc360IBRCModelUpdateStepD(),
                                          rc360IbrcFrameModelSamples,
                                          pcPic->getPOC());
  }
#endif
#endif
}

void EncSlice::encodeSlice   ( Picture* pcPic, OutputBitstream* pcSubstreams, uint32_t &numBinsCoded )
{

  Slice *const pcSlice                 = pcPic->slices[getSliceSegmentIdx()];
  const bool wavefrontsEnabled         = pcSlice->getSPS()->getEntropyCodingSyncEnabledFlag();
  const bool entryPointsPresentFlag    = pcSlice->getSPS()->getEntryPointsPresentFlag();
  uint32_t substreamSize               = 0;
  pcSlice->resetNumberOfSubstream();


  // setup coding structure
  CodingStructure& cs = *pcPic->cs;
  cs.slice            = pcSlice;
  // initialise entropy coder for the slice
  m_CABACWriter->initCtxModels( *pcSlice );

  DTRACE( g_trace_ctx, D_HEADER, "=========== POC: %d ===========\n", pcSlice->getPOC() );

  pcPic->m_prevQP.fill(pcSlice->getSliceQp());

  const PreCalcValues& pcv = *cs.pcv;
  const uint32_t widthInCtus   = pcv.widthInCtus;
  uint32_t uiSubStrm = 0;

  // for every CTU in the slice...
  for( uint32_t ctuIdx = 0; ctuIdx < pcSlice->getNumCtuInSlice(); ctuIdx++ )
  {
    const uint32_t ctuRsAddr = pcSlice->getCtuAddrInSlice( ctuIdx );
    const uint32_t ctuXPosInCtus        = ctuRsAddr % widthInCtus;
    const uint32_t ctuYPosInCtus        = ctuRsAddr / widthInCtus;

    DTRACE_UPDATE( g_trace_ctx, std::make_pair( "ctu", ctuRsAddr ) );

    const Position pos (ctuXPosInCtus * pcv.maxCUWidth, ctuYPosInCtus * pcv.maxCUHeight);
    const UnitArea ctuArea (cs.area.chromaFormat, Area(pos.x, pos.y, pcv.maxCUWidth, pcv.maxCUHeight));
    m_CABACWriter->initBitstream( &pcSubstreams[uiSubStrm] );

    // set up CABAC contexts' state for this CTU
    if ( cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && cs.pps->ctuIsTileRowBd( ctuYPosInCtus ) )
    {
      if (ctuIdx != 0) // if it is the first CTU, then the entropy coder has already been reset
      {
        numBinsCoded += m_CABACWriter->getNumBins();
        m_CABACWriter->initCtxModels( *pcSlice );
        cs.resetPrevPLT(cs.prevPLT);
      }
    }
    else if (cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && wavefrontsEnabled)
    {
      // Synchronize cabac probabilities with upper CTU if it's available and at the start of a line.
      if (ctuIdx != 0) // if it is the first CTU, then the entropy coder has already been reset
      {
        numBinsCoded += m_CABACWriter->getNumBins();
        m_CABACWriter->initCtxModels( *pcSlice );
        cs.resetPrevPLT(cs.prevPLT);
      }
      if (cs.getCURestricted(pos.offset(0, -1), pos, pcSlice->getIndependentSliceIdx(), cs.pps->getTileIdx(pos),
                             ChannelType::LUMA))
      {
        // Top is available, so use it.
        m_CABACWriter->getCtx() = m_entropyCodingSyncContextState;
        m_CABACWriter->getCtx().riceStatReset(
          pcSlice->getSPS()->getBitDepth(ChannelType::LUMA),
          pcSlice->getSPS()->getSpsRangeExtension().getPersistentRiceAdaptationEnabledFlag());
        cs.setPrevPLT(m_palettePredictorSyncState);
      }
    }

    bool updateBcwCodingOrder = cs.slice->getSliceType() == B_SLICE && ctuIdx == 0;
    if( updateBcwCodingOrder )
    {
      resetBcwCodingOrder(false, cs);
    }

    m_CABACWriter->coding_tree_unit( cs, ctuArea, pcPic->m_prevQP, ctuRsAddr );

    // store probabilities of first CTU in line into buffer
    if( cs.pps->ctuIsTileColBd( ctuXPosInCtus ) && wavefrontsEnabled )
    {
      m_entropyCodingSyncContextState = m_CABACWriter->getCtx();
      cs.storePrevPLT(m_palettePredictorSyncState);
    }

    // terminate the sub-stream, if required (end of slice-segment, end of tile, end of wavefront-CTU-row):
    bool isLastCTUsinSlice = ctuIdx == pcSlice->getNumCtuInSlice()-1;
    bool isLastCTUinTile  = !isLastCTUsinSlice && cs.pps->getTileIdx( ctuRsAddr ) != cs.pps->getTileIdx( pcSlice->getCtuAddrInSlice( ctuIdx + 1 ) );
    bool isLastCTUinWPP    = !isLastCTUsinSlice && !isLastCTUinTile && wavefrontsEnabled && cs.pps->ctuIsTileColBd( pcSlice->getCtuAddrInSlice( ctuIdx + 1 ) % cs.pps->getPicWidthInCtu() );
    if (isLastCTUsinSlice || isLastCTUinTile || isLastCTUinWPP )         // this the the last CTU of the slice, tile, or WPP
    {
      m_CABACWriter->end_of_slice();  // end_of_slice_one_bit, end_of_tile_one_bit, or end_of_subset_one_bit

      // Byte-alignment in slice_data() when new tile
      pcSubstreams[uiSubStrm].writeByteAlignment();

      if (!isLastCTUsinSlice) //Byte alignment only when it is not the last substream in the slice
      {
        // write sub-stream size
        substreamSize += (pcSubstreams[uiSubStrm].getNumberOfWrittenBits() >> 3) + pcSubstreams[uiSubStrm].countStartCodeEmulations();
        pcSlice->increaseNumberOfSubstream();
        if( entryPointsPresentFlag )
        {
          pcSlice->addSubstreamSize(substreamSize);
          substreamSize = 0;
        }
      }
      uiSubStrm++;
    }
  } // CTU-loop


  if(pcSlice->getPPS()->getCabacInitPresentFlag())
  {
    m_encCABACTableIdx = m_CABACWriter->getCtxInitId( *pcSlice );
  }
  else
  {
    m_encCABACTableIdx = pcSlice->getSliceType();
  }
  numBinsCoded += m_CABACWriter->getNumBins();
}


double EncSlice::xGetQPValueAccordingToLambda ( double lambda )
{
  return 4.2005*log(lambda) + 13.7122;
}

//! \}
