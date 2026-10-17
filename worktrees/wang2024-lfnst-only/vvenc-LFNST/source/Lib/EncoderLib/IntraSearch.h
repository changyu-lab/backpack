/* -----------------------------------------------------------------------------
The copyright in this software is being made available under the Clear BSD
License, included below. No patent rights, trademark rights and/or 
other Intellectual Property Rights other than the copyrights concerning 
the Software are granted under this license.

The Clear BSD License

Copyright (c) 2019-2024, Fraunhofer-Gesellschaft zur Förderung der angewandten Forschung e.V. & The VVenC Authors.
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted (subject to the limitations in the disclaimer below) provided that
the following conditions are met:

     * Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

     * Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.

     * Neither the name of the copyright holder nor the names of its
     contributors may be used to endorse or promote products derived from this
     software without specific prior written permission.

NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY
THIS LICENSE. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.


------------------------------------------------------------------------------------------- */
/** \file     IntraSearch.h
    \brief    intra search class (header)
*/

#pragma once

#include "CABACWriter.h"
#include "CommonLib/IntraPrediction.h"
#include "CommonLib/TrQuant.h"
#include "CommonLib/Unit.h"
#include "CommonLib/RdCost.h"
#include "CommonLib/CommonDef.h"

//! \ingroup EncoderLib
//! \{

namespace vvenc {

// ====================================================================================================================
// Class definition
// ====================================================================================================================
class EncPicture;
class EncCu;

/// encoder search class
class IntraSearch : public IntraPrediction
{
private:

  struct ModeInfo
  {
    bool     mipFlg;    // CU::mipFlag
    bool     mipTrFlg;  // CU::mipTransposeFlag
    int8_t   mRefId;    // CU::multiRefIdx
    uint8_t  ispMod;    // CU::ispMode
    uint8_t  modeId;    // CU::intraDir[CH_L]

    ModeInfo() : mipFlg( false ), mipTrFlg( false ), mRefId( 0 ), ispMod( NOT_INTRA_SUBPARTITIONS ), modeId( 0 ) {}
    ModeInfo( const bool mipf, const bool miptf, const int8_t mrid, const uint8_t ispm, const uint8_t mode ) : mipFlg( mipf ), mipTrFlg( miptf ), mRefId( mrid ), ispMod( ispm ), modeId( mode ) {}
    bool operator==( const ModeInfo cmp ) const { return ( 0 == ::memcmp( this, &cmp, sizeof( ModeInfo ) ) ); }
  };

  CodingStructure*    m_pTempCS;
  CodingStructure*    m_pBestCS;
  CodingStructure**   m_pSaveCS;
  bool                m_saveCuCostInSCIPU;
  uint8_t             m_numCuInSCIPU;
  Area                m_cuAreaInSCIPU[NUM_INTER_CU_INFO_SAVE];
  double              m_cuCostInSCIPU[NUM_INTER_CU_INFO_SAVE];
  CompStorage         m_orgResiCb[5], m_orgResiCr[5]; // 0:std, 1-3:jointCbCr, 4:crossComp
  std::vector<ModeInfo>
                      m_parentCandList;

protected:
  // interface to option
  const VVEncCfg* m_pcEncCfg;

  // interface to classes
  TrQuant*        m_pcTrQuant;
  RdCost*         m_pcRdCost;
  // RD computation
  CABACWriter*    m_CABACEstimator;
  CtxCache*       m_CtxCache;

  SortedPelUnitBufs<SORTED_BUFS> *m_SortedPelUnitBufs;
public:
  IntraSearch();
  ~IntraSearch();

  struct ISPTestedModesInfo
  {
    int                                         numTotalParts[2];
    int                                         bestModeSoFar;
    ISPType                                     bestSplitSoFar;
    double                                      bestCost[2];
    bool                                        splitIsFinished[2];
    int                                         subTuCounter;
    PartSplit                                   IspType;
    bool                                        relatedCuIsValid;
    bool                                        intraWasTested;
    int                                         bestIntraMode;
    bool                                        isIntra;
    int                                         bestBefore[3];
    // set everything to default values
    void clear()
    {
      for (int splitIdx = 0; splitIdx < NUM_INTRA_SUBPARTITIONS_MODES - 1; splitIdx++)
      {
        numTotalParts[splitIdx] = 0;
        splitIsFinished[splitIdx] = false;
        bestCost[splitIdx] = MAX_DOUBLE;
      }
      bestModeSoFar = -1;
      bestSplitSoFar = NOT_INTRA_SUBPARTITIONS;
      subTuCounter = -1;
      IspType = TU_NO_ISP;
    }
    void init(const int numTotalPartsHor, const int numTotalPartsVer, bool n)
    {
      if (n)
      {
        intraWasTested = false;
        relatedCuIsValid = false;
        bestIntraMode = 0;
        isIntra   = false;
        std::memset(bestBefore,0, sizeof(bestBefore));
        clear();
      }
      else
      {
        const int horSplit = HOR_INTRA_SUBPARTITIONS - 1, verSplit = VER_INTRA_SUBPARTITIONS - 1;
        numTotalParts[horSplit] = numTotalPartsHor;
        numTotalParts[verSplit] = numTotalPartsVer;
        splitIsFinished[horSplit] = (numTotalParts[horSplit] == 0);
        splitIsFinished[verSplit] = (numTotalParts[verSplit] == 0);
        subTuCounter = -1;
        IspType = TU_NO_ISP;
      }
    }
  };

  ISPTestedModesInfo m_ispTestedModes[ NUM_LFNST_NUM_PER_SET ];

  void init                       ( const VVEncCfg &encCfg, TrQuant *pTrQuant, RdCost *pRdCost, SortedPelUnitBufs<SORTED_BUFS> *pSortedPelUnitBufs, XUCache &unitCache);
  void setCtuEncRsrc              ( CABACWriter* cabacEstimator, CtxCache* ctxCache );
  void destroy                    ();

  CodingStructure  **getSaveCSBuf () { return m_pSaveCS; }

  bool getSaveCuCostInSCIPU       ()               { return m_saveCuCostInSCIPU; }
  void setSaveCuCostInSCIPU       ( bool b )       { m_saveCuCostInSCIPU = b;  }
  void setNumCuInSCIPU            ( uint8_t i )    { m_numCuInSCIPU = i; }
  void saveCuAreaCostInSCIPU      ( Area area, double cost );
  void initCuAreaCostInSCIPU      ();

  bool estIntraPredLumaQT         ( CodingUnit &cu, Partitioner &pm, double bestCost = MAX_DOUBLE);
  void estIntraPredChromaQT       ( CodingUnit& cu, Partitioner& partitioner, const double maxCostAllowed );

private:
  double    xFindInterCUCost          ( CodingUnit &cu );

  struct LahtpFeatures
  {
    double absLatDeg;
    double thetaMaxDeg;
    double thetaSkipDeg;
    double cosLat;
    double rawCosLat;
    double etaHigh;
    double roiEnergyQ;
    double lfRatio;
    double predNz;
    double meanAbsQ;
    double horzRatio;
    double corrProxy;
    double specEnergy[64];
    double roiRaw[48];
    double roiQ[48];
    int    specSide;
    int    roiDim;
    bool   stage1;
    bool   stage2;
  };

  struct LahtpStage1Decision
  {
    double absLatDeg    = 0.0;
    double thetaMaxDeg  = 0.0;
    double thetaSkipDeg = 90.0;
    double cosLat       = 1.0;
    double rawCosLat    = 1.0;
    bool   stage1       = false;
  };

  struct LardLfnstCandDecision
  {
    bool   valid     = false;
    int    mask      = 0x7;
    double gain1     = 0.0;
    double gain2     = 0.0;
    double corrProxy = 0.0;
    double n0        = 0.0;
    double n1        = 0.0;
    double n2        = 0.0;
    int    last0     = 0;
    int    last1     = 0;
    int    last2     = 0;
  };

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
  struct LardLfnst2ndDecision
  {
    bool   valid = false;
    int    mask  = 0x7;
    int    rawMask = 0x7;
    bool   safeGate = false;
    double f1    = 0.0;
    double f2    = 0.0;
    double g1    = 0.0;
    double g2    = 0.0;
    double obs1  = 0.0;
    double obs2  = 0.0;
    double corrStrength = 0.0;
    double offdiagProxy = 0.0;
    double inputEnergy = 0.0;
    double thetaMaxDeg = 0.0;
    double rate0 = 0.0;
    double obsRate0 = 0.0;
    double theoryMh = 0.0;
    double theoryMajorMargin1 = 0.0;
    double theoryMajorMargin2 = 0.0;
    double theoryRate1 = 0.0;
    double theoryRate2 = 0.0;
    double theoryNz0 = 0.0;
    double theoryNz1 = 0.0;
    double theoryNz2 = 0.0;
    int    theoryMajorMask = 0;
    int    theoryReason = 0;
    int    modeGroup = 0;
    int    lfnstSet = 0;
    int    sbSize = 0;
    int    trSize = 0;
    bool   earlyValid = false;
    bool   earlySkip = false;
    bool   earlyGeom = false;
    bool   earlyRoiFull = false;
    bool   earlyRoiProxy = false;
    double earlyMh = 0.0;
    double earlyRoiEnergyQ = 0.0;
    double earlyPredNz = 0.0;
    double earlyLfRatio = 0.0;
    double earlyCorrProxy = 0.0;
    double earlyMeanAbsQ = 0.0;
    double input[48] = {};
  };

  struct LardLfnstCovDecision
  {
    bool   eligible = false;
    bool   valid = false;
    int    latBin = -1;
    int    lfnstSet = -1;
    bool   transpose = false;
    int    kIn = 0;
    int    outN = 0;
    double sigma2 = 0.0;
    double qStep = 0.0;
    double lambdaAdjusted = 0.0;
    double lambdaUnadjusted = 0.0;
    double rate0 = 0.0;
    double rateL[2] = { 0.0, 0.0 };
    double predRateGainBits[2] = { 0.0, 0.0 };
    double g[2] = { 0.0, 0.0 };
    double f[2] = { 0.0, 0.0 };
    double predRateCostGain[2] = { 0.0, 0.0 };
    double predDistLoss[2] = { 0.0, 0.0 };
    double predRDGain[2] = { 0.0, 0.0 };
    double skipThreshold = 0.0;
    int    maskPred = 0x7;
    bool   tableFound = false;
    bool   metadataGatePass = false;
    bool   metadataGateReject = false;
    bool   cheapGatePass = false;
    bool   cheapGateReject = false;
    bool   responsePredictorEntered = false;
    bool   qpEarlyBypass = false;
    bool   sizeEarlyBypass = false;
    bool   roiEnergyGate = false;
    bool   optimizedResponse = false;
    uint64_t timeMetaGateNs = 0;
    uint64_t timeCheapGateNs = 0;
    uint64_t timeResponseFeatureNs = 0;
    uint64_t timePredictScoreNs = 0;
    double predVarY[2][16] = {};
    double roiInput[48] = {};
    bool   actualValid[2] = { false, false };
    int    actualInput[2][48] = {};
    int    actualRawRoi[2][48] = {};
    int    actualOutput[2][16] = {};
    double inputEnergy[2] = { 0.0, 0.0 };
    double outputEnergy[2] = { 0.0, 0.0 };
    double zeroOutEnergy[2] = { 0.0, 0.0 };
    double tableZeroOutEnergy[2] = { 0.0, 0.0 };
    double tableRetainedEnergy[2] = { 0.0, 0.0 };
    double responseZeroOutEnergy[2] = { 0.0, 0.0 };
    double responseRetainedEnergy[2] = { 0.0, 0.0 };
    double responseNnz[2] = { 0.0, 0.0 };
    double responseZeroNnz[2] = { 0.0, 0.0 };
    double responseRetainedNnz[2] = { 0.0, 0.0 };
    double responseLast[2] = { -1.0, -1.0 };
    double responseSigSpan[2] = { 0.0, 0.0 };
    double responseSigDensity[2] = { 0.0, 0.0 };
    double responseHoleCount[2] = { 0.0, 0.0 };
    double responseLevelSum[2] = { 0.0, 0.0 };
    double responseLogLevelSum[2] = { 0.0, 0.0 };
    double responseMaxLevel[2] = { 0.0, 0.0 };
    double baseNnz = 0.0;
    double baseLast = -1.0;
    double baseSigDensity = 0.0;
    double baseLogLevelSum = 0.0;
    double baseRoiEnergy = 0.0;
    double retainedEnergyRatio[2] = { 0.0, 0.0 };
    bool   rdoValid[3] = { false, false, false };
    uint64_t actualRdoTimeNs[3] = { 0, 0, 0 };
    uint64_t actualDist[3] = { 0, 0, 0 };
    uint64_t actualFracBits[3] = { 0, 0, 0 };
    double actualDistCost[3] = { 0.0, 0.0, 0.0 };
    double actualRateCost[3] = { 0.0, 0.0, 0.0 };
  };
#endif

  struct Lard14EarlyProxyDecision
  {
    bool   valid = false;
    bool   skip = false;
    double roiEnergyQ = 0.0;
    double predNz = 0.0;
    double lfRatio = 0.0;
    double corrProxy = 0.0;
    double meanAbsQ = 0.0;
  };

  struct LardLfnstPaperDecision
  {
    bool   valid   = false;
    int    mask    = 0x7;
    double grad1   = 0.0;
    double grad2   = 0.0;
    double th1     = 0.0;
    double th2Idx1 = 0.0;
    double th2Idx2 = 0.0;
  };

  LahtpFeatures xGetLahtpFeatures     ( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred ) const;
  LahtpStage1Decision xGetLahtpStage1Decision( const CodingUnit& cu ) const;
  void          xLahtpAppendTrace      ( const CodingUnit& cu, const LahtpFeatures& f, const int modeId,
                                         const int lfnstIdx, const int mtsIdx, const double cost,
                                         const uint64_t fracBits, const Distortion dist, const uint32_t numSig,
                                         const uint32_t nonZero, const int lastPos, const double absSum,
                                         const bool pruned ) const;
  bool          xLahtpCanApply        ( const CodingUnit& cu, const int modeIdx ) const;
  bool          xLahtpDisableMTS      ( const CodingUnit& cu, const LahtpFeatures& f ) const;
  bool          xLahtpDisableLFNST    ( const CodingUnit& cu, const LahtpFeatures& f ) const;
  bool          xLard14EarlyRoiDisable( const LahtpFeatures& f ) const;
  Lard14EarlyProxyDecision xLard14EarlyRoiProxyDecision( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred, const LahtpFeatures& f ) const;
  bool          xLard14EarlyRoiProxyDisable( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred, const LahtpFeatures& f ) const;
  bool          xLahtpCheckQuantRoi    ( const CodingUnit& cu, const TransformUnit& tu, LahtpFeatures& f ) const;
  LardLfnstCandDecision xLardLfnstPredictCandidates( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f ) const;
  LardLfnstPaperDecision xLardLfnstPaperGradDecision( const CodingUnit& cu, const TransformUnit& tu ) const;
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
  LardLfnst2ndDecision xLardLfnst2ndRespDecision( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f, const int dct2CostBin = 0 ) const;
  LardLfnstCovDecision xLardLfnstCovDecision( const CodingUnit& cu, const TransformUnit& tu ) const;
  void          xLardLfnstCovAppendLog( const CodingUnit& cu, const LardLfnstCovDecision& d, const int bestLfnstIdx,
                                        const double cost0, const double cost1, const double cost2 ) const;
  void          xLardLfnstCovAppendTrace( const CodingUnit& cu, const LardLfnstCovDecision& d ) const;
  void          xLardLfnst2ndTraceVector( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f ) const;
  void          xLardLfnst2ndAppendFinalStats( const CodingUnit& cu, const LardLfnst2ndDecision& d, const int bestLfnstIdx,
                                               const double cost0, const double cost1, const double cost2, const int dct2CostBin ) const;
#endif

  void      xPreCheckMTS              ( TransformUnit &tu, std::vector<TrMode> *trModes, const int maxCand, PelUnitBuf *pPred, const ComponentID& compID = COMP_Y);
  void      xEstimateLumaRdModeList   ( int& numModesForFullRD,
                                        static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& RdModeList,
                                        static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& HadModeList,
                                        static_vector<double, FAST_UDI_MAX_RDMODE_NUM>& CandCostList,
                                        static_vector<double, FAST_UDI_MAX_RDMODE_NUM>& CandHadList, CodingUnit& cu, bool testMip);

  // -------------------------------------------------------------------------------------------------------------------
  // Intra search
  // -------------------------------------------------------------------------------------------------------------------
  uint64_t  xFracModeBitsIntraLuma    ( const CodingUnit& cu, const unsigned* mpmLst );

  void      xEncIntraHeader           ( CodingStructure &cs, Partitioner& pm, const bool luma );
  void      xEncSubdivCbfQT           ( CodingStructure &cs, Partitioner& pm, const bool luma );
  uint64_t  xGetIntraFracBitsQT       ( CodingStructure &cs, Partitioner &pm, const bool luma, CUCtx *cuCtx = nullptr );

  uint64_t  xGetIntraFracBitsQTChroma ( const TransformUnit& tu, const ComponentID compID, CUCtx *cuCtx );

  void     xEncCoeffQT                ( CodingStructure& cs, Partitioner& pm, const ComponentID compID, CUCtx* cuCtx = nullptr, const int subTuIdx = -1, const PartSplit ispType = TU_NO_ISP );

  void      xIntraCodingTUBlock       ( TransformUnit &tu, const ComponentID compID, const bool checkCrossCPrediction, Distortion &ruiDist, uint32_t *numSig = nullptr, PelUnitBuf *pPred = nullptr, const bool loadTr = false);
  ChromaCbfs xIntraChromaCodingQT     ( CodingStructure& cs, Partitioner& pm );
  void     xIntraCodingLumaQT         ( CodingStructure& cs, Partitioner& pm, PelUnitBuf* pPred, const double bestCostSoFar, int numMode, bool disableMTS, bool disableLFNST = false);
  double   xTestISP                   ( CodingStructure& cs, Partitioner& pm, double bestCostSoFar, PartSplit ispType, bool& splitcbf, uint64_t& singleFracBits, Distortion& singleDistLuma, CUCtx& cuCtx);
  int      xSpeedUpISP                ( int speed, bool& testISP, int mode, int& noISP, int& endISP, CodingUnit& cu, static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& RdModeList,const ModeInfo& bestPUMode, int bestISP, int bestLfnstIdx);
  void     xSpeedUpIntra              ( double bestcost, int& EndMode, int& speedIntra, CodingUnit& cu);

  template<typename T, size_t N, int M>
  void      xReduceHadCandList        ( static_vector<T, N>& candModeList, static_vector<double, N>& candCostList, SortedPelUnitBufs<M>& sortedPelBuffer, int& numModesForFullRD, const double thresholdHadCost, const double* mipHadCost, const CodingUnit& cu, const bool fastMip);

};// END CLASS DEFINITION EncSearch

} // namespace vvenc

//! \}

