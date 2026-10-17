#include "SaldanhaLfnst.h"
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


/** \file     EncSearch.cpp
 *  \brief    encoder intra search class
 */

#include "IntraSearch.h"
#include "EncPicture.h"
#include "LardLfnstCovTable.h"
#include "LardLfnstSkip16FitTable.inc"
#include "LardLfnstSkip17FitTable.inc"
#include "LardLfnstSkip18FitTable.inc"
#include "LardLfnstSkip18CheapGate.inc"
#include "LardLfnstSkip20DirectMaskTable.inc"
#include "LardLfnstSkip21TheoryTable.inc"
#include "CommonLib/CommonDef.h"
#include "CommonLib/Rom.h"
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"
#include "CommonLib/dtrace_next.h"
#include "CommonLib/dtrace_buffer.h"
#include "CommonLib/Reshape.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <functional>
#include <math.h>
#include <mutex>
#include <string>
#include "vvenc/vvencCfg.h"

#ifndef LARD_LFNST_SKIP18_QP_BUCKETS
#define LARD_LFNST_SKIP18_QP_BUCKETS 0
#endif

#ifndef LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS
#define LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS 0
#endif

#ifndef LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES
#define LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES 0
#endif

#ifndef LARD_LFNST_SKIP18_META_GATE_KEYS
#define LARD_LFNST_SKIP18_META_GATE_KEYS 0
#endif

#ifndef LARD_LFNST_SKIP20_TABLE_VERSION
#define LARD_LFNST_SKIP20_TABLE_VERSION 1
#endif

#ifndef VVENC_LAHTP_ENABLE
#define VVENC_LAHTP_ENABLE 1
#endif

#ifndef VVENC_LAHTP_TRACE
#define VVENC_LAHTP_TRACE 0
#endif

#ifndef VVENC_LARD_LFNST_GAIN_PRED_ENABLE
#define VVENC_LARD_LFNST_GAIN_PRED_ENABLE 1
#endif

//! \ingroup EncoderLib
//! \{

namespace vvenc {

#define PLTCtx(c) SubCtx( Ctx::Palette, c )

IntraSearch::IntraSearch()
  : m_pSaveCS       (nullptr)
  , m_pcEncCfg      (nullptr)
  , m_pcTrQuant     (nullptr)
  , m_pcRdCost      (nullptr)
  , m_CABACEstimator(nullptr)
  , m_CtxCache      (nullptr)
{
}

void IntraSearch::init(const VVEncCfg &encCfg, TrQuant *pTrQuant, RdCost *pRdCost, SortedPelUnitBufs<SORTED_BUFS> *pSortedPelUnitBufs, XUCache &unitCache )
{
  IntraPrediction::init( encCfg.m_internChromaFormat, encCfg.m_internalBitDepth[ CH_L ] );

  m_pcEncCfg          = &encCfg;
  m_pcTrQuant         = pTrQuant;
  m_pcRdCost          = pRdCost;
  m_SortedPelUnitBufs = pSortedPelUnitBufs;

  const ChromaFormat chrFormat = encCfg.m_internChromaFormat;
  const int maxCUSize          = encCfg.m_CTUSize;

  Area area = Area( 0, 0, maxCUSize, maxCUSize );

  m_pTempCS = new CodingStructure( unitCache, nullptr );
  m_pBestCS = new CodingStructure( unitCache, nullptr );

  m_pTempCS->createForSearch( chrFormat, area );
  m_pBestCS->createForSearch( chrFormat, area );

  const int uiNumSaveLayersToAllocate = 3;
  m_pSaveCS = new CodingStructure*[uiNumSaveLayersToAllocate];
  for( int layer = 0; layer < uiNumSaveLayersToAllocate; layer++ )
  {
    m_pSaveCS[ layer ] = new CodingStructure( unitCache, nullptr );
    m_pSaveCS[ layer ]->createForSearch( chrFormat, Area( 0, 0, maxCUSize, maxCUSize ) );
    m_pSaveCS[ layer ]->initStructData();
  }

  CompArea chromaArea( COMP_Cb, chrFormat, area, true );
  for( int i = 0; i < 5; i++ )
  {
    m_orgResiCb[i].create( chromaArea );
    m_orgResiCr[i].create( chromaArea );
  }
}

void IntraSearch::destroy()
{
  if ( m_pSaveCS )
  {
    const int uiNumSaveLayersToAllocate = 3;
    for( int layer = 0; layer < uiNumSaveLayersToAllocate; layer++ )
    {
      if ( m_pSaveCS[ layer ] ) { m_pSaveCS[ layer ]->destroy(); delete m_pSaveCS[ layer ]; }
    }
    delete[] m_pSaveCS;
    m_pSaveCS = nullptr;
  }

  if( m_pTempCS )
  {
    m_pTempCS->destroy();
    delete m_pTempCS; m_pTempCS = nullptr;
  }

  if( m_pBestCS )
  {
    m_pBestCS->destroy();
    delete m_pBestCS; m_pBestCS = nullptr;
  }
}

IntraSearch::~IntraSearch()
{
  destroy();
}

void IntraSearch::setCtuEncRsrc( CABACWriter* cabacEstimator, CtxCache *ctxCache )
{
  m_CABACEstimator = cabacEstimator;
  m_CtxCache       = ctxCache;
}

//////////////////////////////////////////////////////////////////////////
// INTRA PREDICTION
//////////////////////////////////////////////////////////////////////////
static constexpr double COST_UNKNOWN = -65536.0;

double IntraSearch::xFindInterCUCost( CodingUnit &cu )
{
  if( CU::isConsIntra(cu) && !cu.slice->isIntra() )
  {
    //search corresponding inter CU cost
    for( int i = 0; i < m_numCuInSCIPU; i++ )
    {
      if( cu.lumaPos() == m_cuAreaInSCIPU[i].pos() && cu.lumaSize() == m_cuAreaInSCIPU[i].size() )
      {
        return m_cuCostInSCIPU[i];
      }
    }
  }
  return COST_UNKNOWN;
}

static double xLahtpClipD( const double minVal, const double maxVal, const double val )
{
  return val < minVal ? minVal : ( val > maxVal ? maxVal : val );
}

static double xLahtpQStepApprox( const int qp )
{
  return std::pow( 2.0, ( (double)xLahtpClipD( 0.0, 63.0, (double)qp ) - 4.0 ) / 6.0 );
}

static double xLahtpQStepCached( const int qp )
{
  thread_local double s_qStep[64] = {};
  const int q = Clip3( 0, 63, qp );
  double v = s_qStep[q];
  if( v <= 0.0 )
  {
    v = xLahtpQStepApprox( q );
    s_qStep[q] = v;
  }
  return v;
}

static double xLahtpClosedFormThetaSkip( const double gain, const double cost, const double gamma, const double psi )
{
  if( gain <= cost || cost <= 0.0 || gamma <= 0.0 || psi <= 0.0 )
  {
    return 0.0;
  }

  const double tan2 = std::log( gain / cost ) / ( gamma * psi );
  if( tan2 <= 0.0 )
  {
    return 0.0;
  }

  return std::atan( std::sqrt( tan2 ) );
}

struct LahtpStage1Geom
{
  double absLatDeg;
  double thetaMaxDeg;
  double cosLat;
  double rawCosLat;
  double thetaMaxRad;
};

static LahtpStage1Geom xLahtpStage1GeomCached( const int picHIn, const int y, const int h )
{
  static constexpr double pi = 3.14159265358979323846;
  struct CacheEntry
  {
    int picH = 0;
    int y    = 0;
    int h    = 0;
    LahtpStage1Geom geom { 0.0, 0.0, 1.0, 1.0, 0.0 };
  };
  thread_local CacheEntry s_cache[256];

  const int picH = std::max( 1, picHIn );
  const unsigned hash = ( (unsigned)picH * 1315423911u ) ^ ( (unsigned)y * 2654435761u ) ^ ( (unsigned)h * 2246822519u );
  CacheEntry& e = s_cache[hash & 255u];
  if( e.picH == picH && e.y == y && e.h == h )
  {
    return e.geom;
  }

  const double centerY = (double)y + 0.5 * (double)h;
  const double theta = ( 0.5 * (double)picH - centerY ) * pi / (double)picH;
  const double absTheta = std::fabs( theta );
  const double halfSpan = 0.5 * (double)h * pi / (double)picH;
  const double thetaMax = std::min( 0.5 * pi, absTheta + halfSpan );

  e.picH = picH;
  e.y    = y;
  e.h    = h;
  e.geom.absLatDeg   = absTheta * 180.0 / pi;
  e.geom.thetaMaxDeg = thetaMax * 180.0 / pi;
  e.geom.rawCosLat   = std::max( 0.0, std::cos( absTheta ) );
  e.geom.cosLat      = std::max( 0.05, e.geom.rawCosLat );
  e.geom.thetaMaxRad = thetaMax;
  return e.geom;
}

static double xLahtpStage1ThetaSkipCached( const VVEncCfg* cfg, const int qp )
{
  static constexpr double pi = 3.14159265358979323846;
  struct Cache
  {
    bool   valid = false;
    int    skip = -1;
    double psi = 0.0;
    double gain1 = 0.0;
    double gain2 = 0.0;
    double cost1 = 0.0;
    double cost2 = 0.0;
    double gamma1 = 0.0;
    double gamma2 = 0.0;
    double thetaMinDeg = 0.0;
    double stage1Relax = 0.0;
    double stage1RelaxQp22 = 0.0;
    double stage1RelaxQp27 = 0.0;
    double stage1RelaxQp32 = 0.0;
    double stage1RelaxQp37 = 0.0;
    double thetaSkip[64] = {};
  };
  thread_local Cache s_cache;

  if( !cfg )
  {
    return 0.5 * pi;
  }
  const bool secondResponseStatsOnly = cfg->m_LardLfnstSkip == 0
                                    && cfg->m_LardLfnst2ndMeasureOnly != 0
                                    && cfg->m_LardLfnst2ndFinalStatFile[0] != '\0';
  const bool secondResponseStage = cfg->m_LardLfnstSkip == 10
                                || cfg->m_LardLfnstSkip == 11
                                || cfg->m_LardLfnstSkip == 13
                                || cfg->m_LardLfnstSkip == 14
                                || cfg->m_LardLfnstSkip == 19
                                || secondResponseStatsOnly;

  const bool changed = !s_cache.valid
                    || s_cache.skip             != cfg->m_LardLfnstSkip
                    || s_cache.psi              != cfg->m_LardLfnstPsi
                    || s_cache.gain1            != cfg->m_LardLfnstGain1
                    || s_cache.gain2            != cfg->m_LardLfnstGain2
                    || s_cache.cost1            != cfg->m_LardLfnstCost1
                    || s_cache.cost2            != cfg->m_LardLfnstCost2
                    || s_cache.gamma1           != cfg->m_LardLfnstGamma1
                    || s_cache.gamma2           != cfg->m_LardLfnstGamma2
                    || s_cache.thetaMinDeg      != cfg->m_LardLfnstThetaMinDeg
                    || s_cache.stage1Relax      != cfg->m_LardLfnst2ndStage1Relax
                    || s_cache.stage1RelaxQp22  != cfg->m_LardLfnst2ndStage1RelaxQp22
                    || s_cache.stage1RelaxQp27  != cfg->m_LardLfnst2ndStage1RelaxQp27
                    || s_cache.stage1RelaxQp32  != cfg->m_LardLfnst2ndStage1RelaxQp32
                    || s_cache.stage1RelaxQp37  != cfg->m_LardLfnst2ndStage1RelaxQp37;
  if( changed )
  {
    double cost1 = cfg->m_LardLfnstCost1;
    double cost2 = cfg->m_LardLfnstCost2;
    if( cfg->m_LardLfnstSkip >= 2 || secondResponseStatsOnly )
    {
      cost1 *= 1.35;
      cost2 *= 1.35;
    }

    const double thetaSkip1 = xLahtpClosedFormThetaSkip( cfg->m_LardLfnstGain1, cost1, cfg->m_LardLfnstGamma1, cfg->m_LardLfnstPsi );
    const double thetaSkip2 = xLahtpClosedFormThetaSkip( cfg->m_LardLfnstGain2, cost2, cfg->m_LardLfnstGamma2, cfg->m_LardLfnstPsi );
    double baseThetaSkip = std::max( thetaSkip1, thetaSkip2 );
    if( cfg->m_LardLfnstThetaMinDeg >= 0.0 )
    {
      baseThetaSkip = xLahtpClipD( 0.0, 90.0, cfg->m_LardLfnstThetaMinDeg ) * pi / 180.0;
    }

    for( int q = 0; q < 64; q++ )
    {
      double thetaSkip = baseThetaSkip;
      if( secondResponseStage )
      {
        double relax = cfg->m_LardLfnst2ndStage1Relax;
        const double qpRelax = q <= 24 ? cfg->m_LardLfnst2ndStage1RelaxQp22
                             : q <= 29 ? cfg->m_LardLfnst2ndStage1RelaxQp27
                             : q <= 34 ? cfg->m_LardLfnst2ndStage1RelaxQp32
                                       : cfg->m_LardLfnst2ndStage1RelaxQp37;
        if( qpRelax >= 0.0 )
        {
          relax = qpRelax;
        }
        thetaSkip /= std::max( 0.25, relax );
      }
      s_cache.thetaSkip[q] = thetaSkip;
    }

    s_cache.valid = true;
    s_cache.skip = cfg->m_LardLfnstSkip;
    s_cache.psi = cfg->m_LardLfnstPsi;
    s_cache.gain1 = cfg->m_LardLfnstGain1;
    s_cache.gain2 = cfg->m_LardLfnstGain2;
    s_cache.cost1 = cfg->m_LardLfnstCost1;
    s_cache.cost2 = cfg->m_LardLfnstCost2;
    s_cache.gamma1 = cfg->m_LardLfnstGamma1;
    s_cache.gamma2 = cfg->m_LardLfnstGamma2;
    s_cache.thetaMinDeg = cfg->m_LardLfnstThetaMinDeg;
    s_cache.stage1Relax = cfg->m_LardLfnst2ndStage1Relax;
    s_cache.stage1RelaxQp22 = cfg->m_LardLfnst2ndStage1RelaxQp22;
    s_cache.stage1RelaxQp27 = cfg->m_LardLfnst2ndStage1RelaxQp27;
    s_cache.stage1RelaxQp32 = cfg->m_LardLfnst2ndStage1RelaxQp32;
    s_cache.stage1RelaxQp37 = cfg->m_LardLfnst2ndStage1RelaxQp37;
  }

  return s_cache.thetaSkip[Clip3( 0, 63, qp )];
}

static uint32_t xLahtpCountNonZeroCoeffs( const TransformUnit& tu, const ComponentID compID )
{
  if( !tu.blocks[compID].valid() )
  {
    return 0;
  }

  const CCoeffSigBuf coeff = tu.getCoeffs( compID );
  uint32_t nnz = 0;
  for( int y = 0; y < coeff.height; y++ )
  {
    for( int x = 0; x < coeff.width; x++ )
    {
      nnz += coeff.at( x, y ) != 0;
    }
  }
  return nnz;
}

static double xLahtpSumAbsCoeffs( const TransformUnit& tu, const ComponentID compID )
{
  if( !tu.blocks[compID].valid() )
  {
    return 0.0;
  }

  const CCoeffSigBuf coeff = tu.getCoeffs( compID );
  double sumAbs = 0.0;
  for( int y = 0; y < coeff.height; y++ )
  {
    for( int x = 0; x < coeff.width; x++ )
    {
      sumAbs += std::fabs( (double)coeff.at( x, y ) );
    }
  }
  return sumAbs;
}

static double xLahtpCorrProxyFromRoi( const double* roiQ, const int roiDim )
{
  double energy  = 0.0;
  double pairAbs = 0.0;
  const int dim = std::max( 0, std::min( roiDim, 48 ) );
  for( int i = 0; i < dim; i++ )
  {
    const double c = roiQ[i];
    energy += c * c;
    if( i + 1 < dim )
    {
      pairAbs += std::fabs( c * roiQ[i + 1] );
    }
  }
  return pairAbs / ( energy + 1e-9 );
}

struct LahtpFitParams
{
  int    qp;
  int    sizeGroup;
  int    modeGroup;
  double energyThr;
  double lfRatioThr;
  double nzThr;
  double gain1;
  double cost1;
  double gamma1;
  double gain2;
  double cost2;
  double gamma2;
};

static const LahtpFitParams g_lardLfnstFitTable[] =
{
#include "LardLfnstFitTable.inc"
};

static const LahtpFitParams g_lardLfnstSpeedTable[] =
{
#include "LardLfnstSpeedTable.inc"
};

#if VVENC_LARD_LFNST_GAIN_PRED_ENABLE
struct LardLfnstCandGainParams
{
  int    key;
  int    mask;
  double gain1;
  double gain2;
};

struct LardLfnstModeSkipParams
{
  int    key;
  double gain1;
  double gain2;
};

static const LardLfnstCandGainParams g_lardLfnstCandGainTable[] =
{
#include "LardLfnstCandGainTable.inc"
};

static const LardLfnstModeSkipParams g_lardLfnstModeSkipTable[] =
{
#include "LardLfnstModeSkipTable.inc"
};
#endif

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
struct LardLfnst2ndCorrTableEntry
{
  int     latBucket;
  int     modeGroup;
  int     sizeGroup;
  int     sbClass;
  int     dim;
  int     samples;
  int16_t corr[48][48];
};

static const LardLfnst2ndCorrTableEntry g_lardLfnst2ndCorrTable[] =
{
#include "LardLfnst2ndCorrTable.inc"
};

struct LardLfnstTheoryStatsEntry
{
  double rate0;
  double rateL;
  double deltaR;
  double deltaDNorm;
};

static const LardLfnstTheoryStatsEntry g_lardLfnstTheoryStatsTable[] =
{
#include "LardLfnstTheoryStatsTable.inc"
};

struct LardLfnst2ndScoreEntry
{
  int64_t key;
  int    samples;
  int    mask;
  double score1;
  double score2;
};

struct LardLfnst2ndCoffEntry
{
  int64_t key;
  int     samples;
  int     coffBucket;
  double  coff;
};

static const LardLfnst2ndScoreEntry g_lardLfnst2ndScoreTable[] =
{
#include "LardLfnst2ndScoreTable.inc"
};

static const LardLfnst2ndCoffEntry g_lardLfnst2ndCoffTable[] =
{
#include "LardLfnst2ndCoffTable.inc"
};
#endif

static int xLahtpSizeGroupId( const int w, const int h )
{
  const int area = w * h;
  const int mn   = std::min( w, h );
  const int mx   = std::max( w, h );
  if( area <= 16 )
  {
    return 0;
  }
  if( area <= 32 )
  {
    return 1;
  }
  if( area <= 64 )
  {
    return 2;
  }
  if( area <= 256 )
  {
    return 3;
  }
  if( area <= 1024 )
  {
    return 4;
  }
  return mx >= 4 * mn ? 6 : 5;
}

static int xLahtpModeGroupId( const int mode )
{
  if( mode == PLANAR_IDX )
  {
    return 0;
  }
  if( mode == DC_IDX )
  {
    return 1;
  }
  if( mode <= 17 )
  {
    return 2;
  }
  if( mode <= 34 )
  {
    return 3;
  }
  if( mode <= 50 )
  {
    return 4;
  }
  return 5;
}

#if VVENC_LARD_LFNST_GAIN_PRED_ENABLE
static int xLardLfnstLatBucketId( const double absLatDeg )
{
  if( absLatDeg < 30.0 )
  {
    return 0;
  }
  if( absLatDeg < 50.0 )
  {
    return 1;
  }
  if( absLatDeg < 70.0 )
  {
    return 2;
  }
  return 3;
}

static int xLardLfnstNzBucketId( const double predNz )
{
  if( predNz <= 0.5 )
  {
    return 0;
  }
  if( predNz <= 2.0 )
  {
    return 1;
  }
  if( predNz <= 4.0 )
  {
    return 2;
  }
  if( predNz <= 8.0 )
  {
    return 3;
  }
  if( predNz <= 16.0 )
  {
    return 4;
  }
  return 5;
}

static int xLardLfnstRoiBucketId( const double roiEnergyQ )
{
  if( roiEnergyQ <= 0.5 )
  {
    return 0;
  }
  if( roiEnergyQ <= 2.0 )
  {
    return 1;
  }
  if( roiEnergyQ <= 8.0 )
  {
    return 2;
  }
  if( roiEnergyQ <= 32.0 )
  {
    return 3;
  }
  if( roiEnergyQ <= 128.0 )
  {
    return 4;
  }
  return 5;
}

static int xLardLfnstLastBucketId( const int lastPos )
{
  if( lastPos <= 0 )
  {
    return 0;
  }
  if( lastPos <= 3 )
  {
    return 1;
  }
  if( lastPos <= 7 )
  {
    return 2;
  }
  if( lastPos <= 15 )
  {
    return 3;
  }
  if( lastPos <= 31 )
  {
    return 4;
  }
  return 5;
}

static int xLardLfnstLfBucketId( const double lfRatio )
{
  if( lfRatio < 0.25 )
  {
    return 0;
  }
  if( lfRatio < 0.50 )
  {
    return 1;
  }
  if( lfRatio < 0.75 )
  {
    return 2;
  }
  return 3;
}

static int xLardLfnstCorrBucketId( const double corrProxy )
{
  if( corrProxy < 0.10 )
  {
    return 0;
  }
  if( corrProxy < 0.25 )
  {
    return 1;
  }
  if( corrProxy < 0.50 )
  {
    return 2;
  }
  if( corrProxy < 1.00 )
  {
    return 3;
  }
  return 4;
}

static int xLardLfnstCandPackKey( const int qp, const int sizeGroup, const int modeGroup,
                                  const int latBucket, const int nzBucket, const int lastBucket,
                                  const int roiBucket, const int lfBucket, const int corrBucket )
{
  return (((((((( qp * 7 + sizeGroup ) * 6 + modeGroup ) * 4 + latBucket ) * 6 + nzBucket ) * 6 + lastBucket ) * 6 + roiBucket ) * 4 + lfBucket ) * 5 + corrBucket);
}

static int xLardLfnstModePackKey( const int qp, const int sizeGroup, const int modeGroup, const int latBucket )
{
  return ((( qp * 7 + sizeGroup ) * 6 + modeGroup ) * 4 + latBucket);
}

static const LardLfnstCandGainParams* xLardLfnstFindCandGainParams( const int key )
{
  int lo = 0;
  int hi = (int)( sizeof( g_lardLfnstCandGainTable ) / sizeof( g_lardLfnstCandGainTable[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( hi - lo ) / 2;
    if( g_lardLfnstCandGainTable[mid].key < key )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  return ( lo < (int)( sizeof( g_lardLfnstCandGainTable ) / sizeof( g_lardLfnstCandGainTable[0] ) )
        && g_lardLfnstCandGainTable[lo].key == key ) ? &g_lardLfnstCandGainTable[lo] : nullptr;
}

static const LardLfnstModeSkipParams* xLardLfnstFindModeSkipParams( const int key )
{
  int lo = 0;
  int hi = (int)( sizeof( g_lardLfnstModeSkipTable ) / sizeof( g_lardLfnstModeSkipTable[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( hi - lo ) / 2;
    if( g_lardLfnstModeSkipTable[mid].key < key )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  return ( lo < (int)( sizeof( g_lardLfnstModeSkipTable ) / sizeof( g_lardLfnstModeSkipTable[0] ) )
        && g_lardLfnstModeSkipTable[lo].key == key ) ? &g_lardLfnstModeSkipTable[lo] : nullptr;
}

static uint32_t xLardLfnstGetIntraMode( const Area& tuArea, const uint32_t dirMode )
{
  if( dirMode < 2 )
  {
    return dirMode;
  }

  static const int modeShift[] = { 0, 6, 10, 12, 14, 15 };
  const int width  = int( tuArea.width );
  const int height = int( tuArea.height );

  if( width > height && dirMode < 2 + modeShift[floorLog2( width ) - floorLog2( height )] )
  {
    return dirMode + ( VDIA_IDX - 1 ) + ( NUM_EXT_LUMA_MODE >> 1 );
  }
  else if( height > width && dirMode > VDIA_IDX - modeShift[floorLog2( height ) - floorLog2( width )] )
  {
    return dirMode - ( VDIA_IDX + 1 ) + ( NUM_EXT_LUMA_MODE >> 1 ) + NUM_LUMA_MODE;
  }

  return dirMode;
}

static bool xLardLfnstTransposeFlag( const uint32_t intraMode )
{
  return ( ( intraMode >= NUM_LUMA_MODE ) && ( intraMode >= ( NUM_LUMA_MODE + ( NUM_EXT_LUMA_MODE >> 1 ) ) ) )
      || ( ( intraMode < NUM_LUMA_MODE ) && ( intraMode > DIA_IDX ) );
}

static double xLardLfnstProxyRate( const double nnz, const int lastPos, const double absSum )
{
  return nnz + 0.35 * std::log2( 2.0 + (double)std::max( 0, lastPos ) )
             + 0.08 * std::log2( 1.0 + std::max( 0.0, absSum ) );
}
#endif

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
static const LardLfnst2ndScoreEntry* xLard2ndFindScoreEntry( const int64_t key )
{
  int lo = 0;
  int hi = (int)( sizeof( g_lardLfnst2ndScoreTable ) / sizeof( g_lardLfnst2ndScoreTable[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( hi - lo ) / 2;
    if( g_lardLfnst2ndScoreTable[mid].key < key )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  return ( lo < (int)( sizeof( g_lardLfnst2ndScoreTable ) / sizeof( g_lardLfnst2ndScoreTable[0] ) )
        && g_lardLfnst2ndScoreTable[lo].key == key ) ? &g_lardLfnst2ndScoreTable[lo] : nullptr;
}

static const LardLfnst2ndCoffEntry* xLard2ndFindCoffEntry( const int64_t key )
{
  int lo = 0;
  int hi = (int)( sizeof( g_lardLfnst2ndCoffTable ) / sizeof( g_lardLfnst2ndCoffTable[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( hi - lo ) / 2;
    if( g_lardLfnst2ndCoffTable[mid].key < key )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  return ( lo < (int)( sizeof( g_lardLfnst2ndCoffTable ) / sizeof( g_lardLfnst2ndCoffTable[0] ) )
        && g_lardLfnst2ndCoffTable[lo].key == key ) ? &g_lardLfnst2ndCoffTable[lo] : nullptr;
}

static uint32_t xLard2ndGetIntraMode( const Area& tuArea, const uint32_t dirMode )
{
  if( dirMode < 2 )
  {
    return dirMode;
  }

  static const int modeShift[] = { 0, 6, 10, 12, 14, 15 };
  const int width  = int( tuArea.width );
  const int height = int( tuArea.height );

  if( width > height && dirMode < 2 + modeShift[floorLog2( width ) - floorLog2( height )] )
  {
    return dirMode + ( VDIA_IDX - 1 ) + ( NUM_EXT_LUMA_MODE >> 1 );
  }
  if( height > width && dirMode > VDIA_IDX - modeShift[floorLog2( height ) - floorLog2( width )] )
  {
    return dirMode - ( VDIA_IDX + 1 ) + ( NUM_EXT_LUMA_MODE >> 1 ) + NUM_LUMA_MODE;
  }

  return dirMode;
}

static bool xLard2ndTransposeFlag( const uint32_t intraMode )
{
  return ( ( intraMode >= NUM_LUMA_MODE ) && ( intraMode >= ( NUM_LUMA_MODE + ( NUM_EXT_LUMA_MODE >> 1 ) ) ) )
      || ( ( intraMode < NUM_LUMA_MODE ) && ( intraMode > DIA_IDX ) );
}

static void xLard2ndStoreInput( double* input, int* uPos, int* vPos, double* energy,
                                const int idx, const TCoeff value, const int u, const int v )
{
  input[idx] = (double)value;
  if( energy )
  {
    *energy += input[idx] * input[idx];
  }
  if( uPos )
  {
    uPos[idx] = u;
  }
  if( vPos )
  {
    vPos[idx] = v;
  }
}

static void xLard2ndCollectLfnstInput( const TCoeff* coeff, const int width, const int sbSize, const bool transposeFlag,
                                       double* input, int* uPos, int* vPos, double* energy = nullptr )
{
  if( energy )
  {
    *energy = 0.0;
  }
  if( transposeFlag )
  {
    if( sbSize == 4 )
    {
      for( int y = 0; y < 4; y++ )
      {
        xLard2ndStoreInput( input, uPos, vPos, energy, y,      coeff[y * width + 0], 0, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 4 + y,  coeff[y * width + 1], 1, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 8 + y,  coeff[y * width + 2], 2, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 12 + y, coeff[y * width + 3], 3, y );
      }
    }
    else
    {
      for( int y = 0; y < 8; y++ )
      {
        xLard2ndStoreInput( input, uPos, vPos, energy, y,       coeff[y * width + 0], 0, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 8 + y,   coeff[y * width + 1], 1, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 16 + y,  coeff[y * width + 2], 2, y );
        xLard2ndStoreInput( input, uPos, vPos, energy, 24 + y,  coeff[y * width + 3], 3, y );
        if( y < 4 )
        {
          xLard2ndStoreInput( input, uPos, vPos, energy, 32 + y, coeff[y * width + 4], 4, y );
          xLard2ndStoreInput( input, uPos, vPos, energy, 36 + y, coeff[y * width + 5], 5, y );
          xLard2ndStoreInput( input, uPos, vPos, energy, 40 + y, coeff[y * width + 6], 6, y );
          xLard2ndStoreInput( input, uPos, vPos, energy, 44 + y, coeff[y * width + 7], 7, y );
        }
      }
    }
  }
  else
  {
    int idx = 0;
    for( int y = 0; y < sbSize; y++ )
    {
      const int stride = ( y < 4 ) ? sbSize : 4;
      for( int x = 0; x < stride; x++ )
      {
        xLard2ndStoreInput( input, uPos, vPos, energy, idx++, coeff[y * width + x], x, y );
      }
    }
  }
}

struct LardCovQuantStats
{
  double retainedEnergy = 0.0;
  double zeroOutEnergy = 0.0;
  double nnz = 0.0;
  double zeroNnz = 0.0;
  double retainedNnz = 0.0;
  double last = -1.0;
  double sigSpan = 0.0;
  double sigDensity = 0.0;
  double holeCount = 0.0;
  double levelSum = 0.0;
  double logLevelSum = 0.0;
  double maxLevel = 0.0;
};

static void xLardCovFinalizeQuantStats( LardCovQuantStats& stats )
{
  stats.sigSpan = stats.last >= 0.0 ? stats.last + 1.0 : 0.0;
  stats.sigDensity = stats.sigSpan > 0.0 ? stats.nnz / stats.sigSpan : 0.0;
  stats.holeCount = stats.sigSpan > 0.0 ? stats.sigSpan - stats.nnz : 0.0;
}

static void xLardCovAccQuantStats( LardCovQuantStats& stats, const int pos, const bool retained, const double value, const double qStep )
{
  const int level = (int)std::floor( std::fabs( value ) / std::max( 1e-9, qStep ) + 0.5 );
  if( level <= 0 )
  {
    return;
  }
  stats.nnz += 1.0;
  if( retained )
  {
    stats.retainedNnz += 1.0;
  }
  else
  {
    stats.zeroNnz += 1.0;
  }
  stats.last = (double)pos;
  stats.levelSum += (double)level;
  stats.logLevelSum += std::log2( 1.0 + (double)level );
  stats.maxLevel = std::max( stats.maxLevel, (double)level );
}

static LardCovQuantStats xLardCovComputeBaseStats( const double* input, const int dim, const double qStep )
{
  LardCovQuantStats stats;
  if( !input || dim <= 0 )
  {
    return stats;
  }
  for( int i = 0; i < dim; i++ )
  {
    xLardCovAccQuantStats( stats, i, true, input[i], qStep );
  }
  xLardCovFinalizeQuantStats( stats );
  return stats;
}

static LardCovQuantStats xLardCovComputeResponseStats( const double* input, const int trSize, const int outN, const int lfnstSet,
                                                       const int cand, const bool sb8, const double qStep )
{
  LardCovQuantStats stats;
  if( !input || trSize <= 0 || outN <= 0 || lfnstSet < 0 || lfnstSet >= 4 || cand < 0 || cand >= 2 )
  {
    return stats;
  }

  const int8_t* trMat = sb8 ? g_lfnstFwd8x8[lfnstSet][cand][0] : g_lfnstFwd4x4[lfnstSet][cand][0];
  for( int row = 0; row < 16; row++ )
  {
    int64_t coef = 0;
    for( int col = 0; col < trSize; col++ )
    {
      coef += (int64_t)std::llround( input[col] ) * (int64_t)trMat[row * trSize + col];
    }
    const int64_t y = ( coef + 64 ) >> 7;
    const double e = (double)y * (double)y;
    if( row < outN )
    {
      stats.retainedEnergy += e;
    }
    else
    {
      stats.zeroOutEnergy += e;
    }
    xLardCovAccQuantStats( stats, row, row < outN, (double)y, qStep );
  }
  xLardCovFinalizeQuantStats( stats );
  return stats;
}

static double xLardSkip18RoiEnergy( const double* input, const int dim )
{
  double energy = 0.0;
  for( int i = 0; i < dim; i++ )
  {
    energy += input[i] * input[i];
  }
  return energy;
}

static double xLardSkip18LevelLogLut( const int level )
{
  static const std::array<double, 4097> lut = []()
  {
    std::array<double, 4097> values {};
    for( int i = 0; i < (int)values.size(); i++ )
    {
      values[i] = std::log2( 1.0 + (double)i );
    }
    return values;
  }();
  return level < (int)lut.size() ? lut[std::max( 0, level )] : std::log2( 1.0 + (double)level );
}

static LardCovQuantStats xLardCovComputeResponseStatsFused( const double* input, const int trSize, const int outN,
                                                            const int lfnstSet, const int cand, const bool sb8,
                                                            const double invQStep )
{
  LardCovQuantStats stats;
  if( !input || trSize <= 0 || outN <= 0 || lfnstSet < 0 || lfnstSet >= 4 || cand < 0 || cand >= 2 )
  {
    return stats;
  }

  int32_t inputInt[48];
  for( int col = 0; col < trSize; col++ )
  {
    inputInt[col] = (int32_t)std::llround( input[col] );
  }
  const int8_t* trMat = sb8 ? g_lfnstFwd8x8[lfnstSet][cand][0] : g_lfnstFwd4x4[lfnstSet][cand][0];
  for( int row = 0; row < 16; row++ )
  {
    int64_t coef = 0;
    const int8_t* matrixRow = trMat + row * trSize;
    for( int col = 0; col < trSize; col++ )
    {
      coef += (int64_t)inputInt[col] * (int64_t)matrixRow[col];
    }
    const int64_t value = ( coef + 64 ) >> 7;
    const double energy = (double)value * (double)value;
    const bool retained = row < outN;
    if( retained )
    {
      stats.retainedEnergy += energy;
    }
    else
    {
      stats.zeroOutEnergy += energy;
    }

    const int level = (int)( std::fabs( (double)value ) * invQStep + 0.5 );
    if( level > 0 )
    {
      stats.nnz += 1.0;
      stats.retainedNnz += retained ? 1.0 : 0.0;
      stats.zeroNnz += retained ? 0.0 : 1.0;
      stats.last = (double)row;
      stats.levelSum += (double)level;
      stats.logLevelSum += xLardSkip18LevelLogLut( level );
      stats.maxLevel = std::max( stats.maxLevel, (double)level );
    }
  }
  xLardCovFinalizeQuantStats( stats );
  return stats;
}

static double xLardSkip18ActualQp5Threshold( const int qp )
{
  static const int qps[4] = { 19, 24, 29, 34 };
  static const double thresholds[4] =
  {
    -5356679.494313986,
    -1792025.6619448862,
    -15963393.063854005,
    -9556709.148067622
  };
  int best = 0;
  int bestDiff = std::abs( qp - qps[0] );
  for( int i = 1; i < 4; i++ )
  {
    const int diff = std::abs( qp - qps[i] );
    if( diff < bestDiff )
    {
      best = i;
      bestDiff = diff;
    }
  }
  return thresholds[best];
}

static bool xLardSkip18FastRealEnabled( const VVEncCfg* cfg )
{
  return cfg && cfg->m_LardLfnstSkip == 18
      && ( cfg->m_LardLfnst18RealSkip == 1 || cfg->m_LardLfnst18RealSkip == 2 )
      && ( !cfg->m_LardLfnstCovLog || cfg->m_LardLfnstCovLog[0] == '\0' );
}

static int64_t xLardSkip18MetaGateKey( const int qp, const int width, const int height, const int latBin, const int setIdx, const bool transpose )
{
  int64_t key = (int64_t)qp;
  key = key * 256 + (int64_t)width;
  key = key * 256 + (int64_t)height;
  key = key * 8 + (int64_t)latBin;
  key = key * 8 + (int64_t)setIdx;
  key = key * 2 + ( transpose ? 1 : 0 );
  return key;
}

static bool xLardSkip18MetaGatePass( const int qp, const int width, const int height, const int latBin, const int setIdx, const bool transpose )
{
#if LARD_LFNST_SKIP18_META_GATE_KEYS > 0
  const int64_t key = xLardSkip18MetaGateKey( qp, width, height, latBin, setIdx, transpose );
  int lo = 0;
  int hi = LARD_LFNST_SKIP18_META_GATE_KEYS - 1;
  while( lo <= hi )
  {
    const int mid = ( lo + hi ) >> 1;
    const int64_t value = (int64_t)LARD_LFNST_SKIP18_META_GATE_KEY[mid];
    if( value == key )
    {
      return true;
    }
    if( value < key )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid - 1;
    }
  }
  return false;
#else
  (void)qp;
  (void)width;
  (void)height;
  (void)latBin;
  (void)setIdx;
  (void)transpose;
  return true;
#endif
}

static bool xLardSkip18MetaGatePassFast( const int qp, const int width, const int height, const int latBin,
                                         const int setIdx, const bool transpose )
{
#if LARD_LFNST_SKIP18_META_GATE_KEYS > 0
  static constexpr int QP_COUNT = 64;
  static constexpr int LOG2_COUNT = 8;
  static constexpr int LAT_COUNT = 7;
  static constexpr int SET_COUNT = 4;
  static constexpr int TR_COUNT = 2;
  static constexpr int TABLE_SIZE = QP_COUNT * LOG2_COUNT * LOG2_COUNT * LAT_COUNT * SET_COUNT * TR_COUNT;
  static const std::array<uint8_t, TABLE_SIZE> enabled = []()
  {
    std::array<uint8_t, TABLE_SIZE> table {};
    for( int i = 0; i < LARD_LFNST_SKIP18_META_GATE_KEYS; i++ )
    {
      int64_t key = (int64_t)LARD_LFNST_SKIP18_META_GATE_KEY[i];
      const int tr = (int)( key % 2 ); key /= 2;
      const int set = (int)( key % 8 ); key /= 8;
      const int lat = (int)( key % 8 ); key /= 8;
      const int h = (int)( key % 256 ); key /= 256;
      const int w = (int)( key % 256 ); key /= 256;
      const int actualQp = (int)key;
      if( actualQp < 0 || actualQp >= QP_COUNT || w <= 0 || h <= 0 || lat < 0 || lat >= LAT_COUNT
          || set < 0 || set >= SET_COUNT || tr < 0 || tr >= TR_COUNT )
      {
        continue;
      }
      const int wi = Clip3( 0, LOG2_COUNT - 1, floorLog2( w ) );
      const int hi = Clip3( 0, LOG2_COUNT - 1, floorLog2( h ) );
      const int index = ( ( ( ( ( actualQp * LOG2_COUNT + wi ) * LOG2_COUNT + hi ) * LAT_COUNT + lat )
                            * SET_COUNT + set ) * TR_COUNT + tr );
      table[index] = 1;
    }
    return table;
  }();
  if( qp < 0 || qp >= QP_COUNT || width <= 0 || height <= 0 || latBin < 0 || latBin >= LAT_COUNT
      || setIdx < 0 || setIdx >= SET_COUNT )
  {
    return false;
  }
  const int wi = Clip3( 0, LOG2_COUNT - 1, floorLog2( width ) );
  const int hi = Clip3( 0, LOG2_COUNT - 1, floorLog2( height ) );
  const int index = ( ( ( ( ( qp * LOG2_COUNT + wi ) * LOG2_COUNT + hi ) * LAT_COUNT + latBin )
                        * SET_COUNT + setIdx ) * TR_COUNT + ( transpose ? 1 : 0 ) );
  return enabled[index] != 0;
#else
  return xLardSkip18MetaGatePass( qp, width, height, latBin, setIdx, transpose );
#endif
}

static double xLardSkip18TablePreGateThreshold( const int qp )
{
#if LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS > 0
  int best = 0;
  int bestDiff = std::abs( qp - LARD_LFNST_SKIP18_CHEAP_GATE_QP[0] );
  for( int i = 1; i < LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS; i++ )
  {
    const int diff = std::abs( qp - LARD_LFNST_SKIP18_CHEAP_GATE_QP[i] );
    if( diff < bestDiff )
    {
      best = i;
      bestDiff = diff;
    }
  }
  return LARD_LFNST_SKIP18_CHEAP_GATE_THRESHOLD[best];
#else
  (void)qp;
  return 0.0;
#endif
}

static bool xLardSkip18TablePreGatePass( const int qp, const double* feat, double* scoreOut = nullptr )
{
#if LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS > 0 && LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES > 0
  int best = 0;
  int bestDiff = std::abs( qp - LARD_LFNST_SKIP18_CHEAP_GATE_QP[0] );
  for( int i = 1; i < LARD_LFNST_SKIP18_CHEAP_GATE_QP_BUCKETS; i++ )
  {
    const int diff = std::abs( qp - LARD_LFNST_SKIP18_CHEAP_GATE_QP[i] );
    if( diff < bestDiff )
    {
      best = i;
      bestDiff = diff;
    }
  }
  double score = LARD_LFNST_SKIP18_CHEAP_GATE_INTERCEPT[best];
  for( int i = 0; i < LARD_LFNST_SKIP18_CHEAP_GATE_FEATURES; i++ )
  {
    const double scale = std::max( 1e-9, LARD_LFNST_SKIP18_CHEAP_GATE_SCALE[best][i] );
    score += LARD_LFNST_SKIP18_CHEAP_GATE_COEFF[best][i] * ( ( feat[i] - LARD_LFNST_SKIP18_CHEAP_GATE_MEAN[best][i] ) / scale );
  }
  if( scoreOut )
  {
    *scoreOut = score;
  }
  return score >= LARD_LFNST_SKIP18_CHEAP_GATE_THRESHOLD[best];
#else
  const double score = feat ? feat[2] : 0.0;
  if( scoreOut )
  {
    *scoreOut = score;
  }
  return score <= xLardSkip18TablePreGateThreshold( qp );
#endif
}

struct Lard18ComplexityRow
{
  std::atomic<uint64_t> numLfnstEligible { 0 };
  std::atomic<uint64_t> numTableFound { 0 };
  std::atomic<uint64_t> numMetadataGateReject { 0 };
  std::atomic<uint64_t> numMetadataGatePass { 0 };
  std::atomic<uint64_t> numCheapGateReject { 0 };
  std::atomic<uint64_t> numCheapGatePass { 0 };
  std::atomic<uint64_t> numResponsePredictorEntered { 0 };
  std::atomic<uint64_t> numQpEarlyBypass { 0 };
  std::atomic<uint64_t> numSizeEarlyBypass { 0 };
  std::atomic<uint64_t> numRoiEnergyGate { 0 };
  std::atomic<uint64_t> numOptimizedResponse { 0 };
  std::atomic<uint64_t> numPredSkip0 { 0 };
  std::atomic<uint64_t> numActualMask0 { 0 };
  std::atomic<uint64_t> numCandidate1Skipped { 0 };
  std::atomic<uint64_t> numCandidate2Skipped { 0 };
  std::atomic<uint64_t> numCandidateRdoSaved { 0 };
  std::atomic<uint64_t> numCandidateRdoActual { 0 };
  std::atomic<uint64_t> numPredMaskCandidate1Rdo { 0 };
  std::atomic<uint64_t> numPredMaskCandidate2Rdo { 0 };
  std::atomic<uint64_t> timeMetaGateNs { 0 };
  std::atomic<uint64_t> timeCheapGateNs { 0 };
  std::atomic<uint64_t> timeResponseFeatureNs { 0 };
  std::atomic<uint64_t> timePredictScoreNs { 0 };
  std::atomic<uint64_t> timeCandidateRdoActualNs { 0 };
  std::atomic<uint64_t> timePredMaskCandidate1RdoNs { 0 };
  std::atomic<uint64_t> timePredMaskCandidate2RdoNs { 0 };
  std::atomic<uint64_t> timeSavedByPredictedMaskNs { 0 };
  std::atomic<uint64_t> timeTotalIntraSearchNs { 0 };
};

class Lard18ComplexityStore
{
public:
  ~Lard18ComplexityStore()
  {
    flush();
  }

  void recordDecision( const char* fileName, const int qp, const int w, const int h,
                       const bool eligible, const bool tableFound,
                       const bool metadataGateReject, const bool metadataGatePass,
                       const bool cheapGateReject, const bool cheapGatePass,
                       const bool responsePredictorEntered,
                       const bool qpEarlyBypass, const bool sizeEarlyBypass,
                       const bool roiEnergyGate, const bool optimizedResponse,
                       const uint64_t timeMetaGateNs, const uint64_t timeCheapGateNs,
                       const uint64_t timeResponseFeatureNs, const uint64_t timePredictScoreNs )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, [&]( Lard18ComplexityRow& row )
    {
      row.numLfnstEligible.fetch_add( eligible ? 1 : 0, std::memory_order_relaxed );
      row.numTableFound.fetch_add( tableFound ? 1 : 0, std::memory_order_relaxed );
      row.numMetadataGateReject.fetch_add( metadataGateReject ? 1 : 0, std::memory_order_relaxed );
      row.numMetadataGatePass.fetch_add( metadataGatePass ? 1 : 0, std::memory_order_relaxed );
      row.numCheapGateReject.fetch_add( cheapGateReject ? 1 : 0, std::memory_order_relaxed );
      row.numCheapGatePass.fetch_add( cheapGatePass ? 1 : 0, std::memory_order_relaxed );
      row.numResponsePredictorEntered.fetch_add( responsePredictorEntered ? 1 : 0, std::memory_order_relaxed );
      row.numQpEarlyBypass.fetch_add( qpEarlyBypass ? 1 : 0, std::memory_order_relaxed );
      row.numSizeEarlyBypass.fetch_add( sizeEarlyBypass ? 1 : 0, std::memory_order_relaxed );
      row.numRoiEnergyGate.fetch_add( roiEnergyGate ? 1 : 0, std::memory_order_relaxed );
      row.numOptimizedResponse.fetch_add( optimizedResponse ? 1 : 0, std::memory_order_relaxed );
      row.timeMetaGateNs.fetch_add( timeMetaGateNs, std::memory_order_relaxed );
      row.timeCheapGateNs.fetch_add( timeCheapGateNs, std::memory_order_relaxed );
      row.timeResponseFeatureNs.fetch_add( timeResponseFeatureNs, std::memory_order_relaxed );
      row.timePredictScoreNs.fetch_add( timePredictScoreNs, std::memory_order_relaxed );
    } );
  }

  void recordPrune( const char* fileName, const int qp, const int w, const int h )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, []( Lard18ComplexityRow& row )
    {
      row.numPredSkip0.fetch_add( 1, std::memory_order_relaxed );
      row.numActualMask0.fetch_add( 1, std::memory_order_relaxed );
      row.numCandidate1Skipped.fetch_add( 1, std::memory_order_relaxed );
      row.numCandidate2Skipped.fetch_add( 1, std::memory_order_relaxed );
      row.numCandidateRdoSaved.fetch_add( 2, std::memory_order_relaxed );
    } );
  }

  void recordShadowPrediction( const char* fileName, const int qp, const int w, const int h )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, []( Lard18ComplexityRow& row )
    {
      row.numPredSkip0.fetch_add( 1, std::memory_order_relaxed );
    } );
  }

  void recordCandidateRdo( const char* fileName, const int qp, const int w, const int h,
                           const int lfnstIdx, const bool predictedMask0, const uint64_t ns )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, [lfnstIdx, predictedMask0, ns]( Lard18ComplexityRow& row )
    {
      row.numCandidateRdoActual.fetch_add( 1, std::memory_order_relaxed );
      row.timeCandidateRdoActualNs.fetch_add( ns, std::memory_order_relaxed );
      if( predictedMask0 )
      {
        if( lfnstIdx == 1 )
        {
          row.numPredMaskCandidate1Rdo.fetch_add( 1, std::memory_order_relaxed );
          row.timePredMaskCandidate1RdoNs.fetch_add( ns, std::memory_order_relaxed );
        }
        else if( lfnstIdx == 2 )
        {
          row.numPredMaskCandidate2Rdo.fetch_add( 1, std::memory_order_relaxed );
          row.timePredMaskCandidate2RdoNs.fetch_add( ns, std::memory_order_relaxed );
        }
        row.timeSavedByPredictedMaskNs.fetch_add( ns, std::memory_order_relaxed );
      }
    } );
  }

  void recordIntraSearch( const char* fileName, const int qp, const int w, const int h, const uint64_t ns )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, [ns]( Lard18ComplexityRow& row )
    {
      row.timeTotalIntraSearchNs.fetch_add( ns, std::memory_order_relaxed );
    } );
  }

private:
  bool enable( const char* fileName )
  {
    if( !fileName || fileName[0] == '\0' )
    {
      return false;
    }
    if( m_enabled.load( std::memory_order_relaxed ) )
    {
      return true;
    }
    std::lock_guard<std::mutex> lock( m_mutex );
    if( !m_enabled.load( std::memory_order_relaxed ) )
    {
      m_fileName = fileName;
      m_enabled.store( true, std::memory_order_relaxed );
    }
    return true;
  }

  template<typename F>
  void forEachRow( const int qp, const int w, const int h, F&& fn )
  {
    fn( m_overall );
    fn( m_qpRows[Clip3( 0, 63, qp )] );
    const int wi = Clip3( 0, 7, floorLog2( std::max( 1, w ) ) );
    const int hi = Clip3( 0, 7, floorLog2( std::max( 1, h ) ) );
    fn( m_sizeRows[wi][hi] );
    fn( m_qpSizeRows[Clip3( 0, 63, qp )][wi][hi] );
  }

  static void writeRow( FILE* fp, const char* scope, const int key1, const int key2, const Lard18ComplexityRow& row )
  {
    const uint64_t eligible = row.numLfnstEligible.load( std::memory_order_relaxed );
    const uint64_t predSkip = row.numPredSkip0.load( std::memory_order_relaxed );
    const uint64_t saved = row.numCandidateRdoSaved.load( std::memory_order_relaxed );
    const uint64_t response = row.numResponsePredictorEntered.load( std::memory_order_relaxed );
    if( eligible == 0 && row.timeTotalIntraSearchNs.load( std::memory_order_relaxed ) == 0 )
    {
      return;
    }
    const double pruneRate = eligible ? (double)predSkip / (double)eligible : 0.0;
    const double candReduction = eligible ? (double)saved / ( 2.0 * (double)eligible ) : 0.0;
    const double responseEnterRate = eligible ? (double)response / (double)eligible : 0.0;
    std::fprintf( fp, "%s,%d,%d,", scope, key1, key2 );
    std::fprintf( fp, "%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,",
      (unsigned long long)eligible,
      (unsigned long long)row.numTableFound.load( std::memory_order_relaxed ),
      (unsigned long long)row.numMetadataGateReject.load( std::memory_order_relaxed ),
      (unsigned long long)row.numMetadataGatePass.load( std::memory_order_relaxed ),
      (unsigned long long)row.numCheapGateReject.load( std::memory_order_relaxed ),
      (unsigned long long)row.numCheapGatePass.load( std::memory_order_relaxed ),
      (unsigned long long)response,
      (unsigned long long)row.numQpEarlyBypass.load( std::memory_order_relaxed ),
      (unsigned long long)row.numSizeEarlyBypass.load( std::memory_order_relaxed ),
      (unsigned long long)row.numRoiEnergyGate.load( std::memory_order_relaxed ),
      (unsigned long long)row.numOptimizedResponse.load( std::memory_order_relaxed ),
      (unsigned long long)predSkip,
      (unsigned long long)row.numActualMask0.load( std::memory_order_relaxed ),
      (unsigned long long)row.numCandidate1Skipped.load( std::memory_order_relaxed ),
      (unsigned long long)row.numCandidate2Skipped.load( std::memory_order_relaxed ),
      (unsigned long long)saved,
      (unsigned long long)row.numCandidateRdoActual.load( std::memory_order_relaxed ) );
    std::fprintf( fp, "%llu,%llu,%llu,%llu,%llu,",
      (unsigned long long)row.numPredMaskCandidate1Rdo.load( std::memory_order_relaxed ),
      (unsigned long long)row.numPredMaskCandidate2Rdo.load( std::memory_order_relaxed ),
      (unsigned long long)row.timePredMaskCandidate1RdoNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timePredMaskCandidate2RdoNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timeSavedByPredictedMaskNs.load( std::memory_order_relaxed ) );
    std::fprintf( fp, "%llu,%llu,%llu,%llu,%llu,%llu,",
      (unsigned long long)row.timeMetaGateNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timeCheapGateNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timeResponseFeatureNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timePredictScoreNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timeCandidateRdoActualNs.load( std::memory_order_relaxed ),
      (unsigned long long)row.timeTotalIntraSearchNs.load( std::memory_order_relaxed ) );
    std::fprintf( fp, "%.9f,%.9f,%.9f\n", pruneRate, candReduction, responseEnterRate );
  }

  void flush()
  {
    if( !m_enabled.load( std::memory_order_relaxed ) || m_fileName.empty() )
    {
      return;
    }
    FILE* fp = std::fopen( m_fileName.c_str(), "w" );
    if( !fp )
    {
      return;
    }
    std::fprintf( fp,
      "scope,key1,key2,numLfnstEligible,numTableFound,numMetadataGateReject,numMetadataGatePass,"
      "numCheapGateReject,numCheapGatePass,numResponsePredictorEntered,numQpEarlyBypass,numSizeEarlyBypass,"
      "numRoiEnergyGate,numOptimizedResponse,numPredSkip0,numActualMask0,"
      "numCandidate1Skipped,numCandidate2Skipped,numCandidateRdoSaved,numCandidateRdoActual,"
      "numPredMaskCandidate1Rdo,numPredMaskCandidate2Rdo,timePredMaskCandidate1RdoNs,"
      "timePredMaskCandidate2RdoNs,timeSavedByPredictedMaskNs,"
      "timeMetaGateNs,timeCheapGateNs,timeResponseFeatureNs,timePredictScoreNs,timeCandidateRdoActualNs,"
      "timeTotalIntraSearchNs,PruneRate,CandReduction,ResponseEnterRate\n" );
    writeRow( fp, "overall", -1, -1, m_overall );
    for( int qp = 0; qp < 64; qp++ )
    {
      writeRow( fp, "actual_qp", qp, -1, m_qpRows[qp] );
    }
    for( int wi = 0; wi < 8; wi++ )
    {
      for( int hi = 0; hi < 8; hi++ )
      {
        writeRow( fp, "size", 1 << wi, 1 << hi, m_sizeRows[wi][hi] );
        for( int qp = 0; qp < 64; qp++ )
        {
          writeRow( fp, "actual_qp_size", qp, ( ( 1 << wi ) << 16 ) | ( 1 << hi ), m_qpSizeRows[qp][wi][hi] );
        }
      }
    }
    std::fclose( fp );
  }

  std::atomic<bool> m_enabled { false };
  std::mutex m_mutex;
  std::string m_fileName;
  Lard18ComplexityRow m_overall;
  Lard18ComplexityRow m_qpRows[64];
  Lard18ComplexityRow m_sizeRows[8][8];
  Lard18ComplexityRow m_qpSizeRows[64][8][8];
};

static Lard18ComplexityStore& xLard18ComplexityStore()
{
  static Lard18ComplexityStore store;
  return store;
}

struct LardSkip21Stage3TimingRow
{
  std::atomic<uint64_t> checkedCount { 0 };
  std::atomic<uint64_t> appliedCount { 0 };
  std::atomic<uint64_t> prunedCandidateTimeNs { 0 };
  std::atomic<uint64_t> stage3EvalTimeNs { 0 };
  std::atomic<uint64_t> seqEnabledCount { 0 };
  std::atomic<uint64_t> seqBestWinSkipCount { 0 };
  std::atomic<uint64_t> seqBestLossSkipCount { 0 };
  std::atomic<uint64_t> seqWrongSkipCount { 0 };
  std::atomic<uint64_t> seqWrongAfterBestWinCount { 0 };
  std::atomic<uint64_t> seqWrongAfterBestLossCount { 0 };
  std::atomic<uint64_t> seqBestWinPrunedTimeNs { 0 };
  std::atomic<uint64_t> seqBestLossPrunedTimeNs { 0 };
  std::atomic<uint64_t> seqOtherBetterThanZeroCount { 0 };
  std::atomic<uint64_t> seqOtherBetterThanBestCount { 0 };
  std::atomic<uint64_t> zdCheckedCount { 0 };
  std::atomic<uint64_t> zdWouldSkipCount { 0 };
  std::atomic<uint64_t> zdWrongSkipCount { 0 };
  std::atomic<uint64_t> zdCandidate1TimeNs { 0 };
  std::atomic<uint64_t> zdCandidate2TimeNs { 0 };
  std::atomic<uint64_t> zdEvalTimeNs { 0 };
};

class LardSkip21Stage3TimingStore
{
public:
  ~LardSkip21Stage3TimingStore()
  {
    flush();
  }

  void recordEval( const char* fileName, const int qp, const int w, const int h, const int selectedIdx,
                   const int prunedIdx, const int diffQ, const int keepQ, const uint64_t evalNs,
                   const bool wouldPrune )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, selectedIdx, prunedIdx, diffQ, keepQ, wouldPrune, [&]( LardSkip21Stage3TimingRow& row )
    {
      row.checkedCount.fetch_add( 1, std::memory_order_relaxed );
      if( wouldPrune )
      {
        row.appliedCount.fetch_add( 1, std::memory_order_relaxed );
      }
      row.stage3EvalTimeNs.fetch_add( evalNs, std::memory_order_relaxed );
    } );
  }

  void recordPrunedCandidate( const char* fileName, const int qp, const int w, const int h, const int selectedIdx,
                              const int prunedIdx, const int diffQ, const int keepQ, const uint64_t prunedNs )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, selectedIdx, prunedIdx, diffQ, keepQ, true, [&]( LardSkip21Stage3TimingRow& row )
    {
      row.prunedCandidateTimeNs.fetch_add( prunedNs, std::memory_order_relaxed );
    } );
  }

  void recordSeqEval( const char* fileName, const int qp, const int w, const int h, const int bestIdx,
                      const int otherIdx, const int diffQ, const int keepQ, const uint64_t evalNs,
                      const bool seqEnabled )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, bestIdx, otherIdx, diffQ, keepQ, seqEnabled, [&]( LardSkip21Stage3TimingRow& row )
    {
      row.checkedCount.fetch_add( 1, std::memory_order_relaxed );
      if( seqEnabled )
      {
        row.seqEnabledCount.fetch_add( 1, std::memory_order_relaxed );
      }
      row.stage3EvalTimeNs.fetch_add( evalNs, std::memory_order_relaxed );
    } );
  }

  void recordSeqOtherCandidate( const char* fileName, const int qp, const int w, const int h, const int bestIdx,
                                const int otherIdx, const int diffQ, const int keepQ, const int skipReason,
                                const uint64_t evalNs, const uint64_t otherNs, const double j0, const double jBest, const double jOther )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    const bool wouldSkip = skipReason == 2 || skipReason == 3;
    const bool validCosts = j0 < MAX_DOUBLE * 0.5 && jBest < MAX_DOUBLE * 0.5 && jOther < MAX_DOUBLE * 0.5;
    const bool otherBetterThanZero = validCosts && jOther < j0;
    const bool otherBetterThanBest = validCosts && jOther < jBest;
    const bool wrongSkip = wouldSkip && otherBetterThanZero && otherBetterThanBest;
    forEachRow( qp, w, h, bestIdx, otherIdx, diffQ, keepQ, true, [&]( LardSkip21Stage3TimingRow& row )
    {
      if( wouldSkip )
      {
        row.appliedCount.fetch_add( 1, std::memory_order_relaxed );
        row.prunedCandidateTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
        if( skipReason == 2 )
        {
          row.seqBestWinSkipCount.fetch_add( 1, std::memory_order_relaxed );
          row.seqBestWinPrunedTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
        }
        else
        {
          row.seqBestLossSkipCount.fetch_add( 1, std::memory_order_relaxed );
          row.seqBestLossPrunedTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
        }
      }
      if( wrongSkip )
      {
        row.seqWrongSkipCount.fetch_add( 1, std::memory_order_relaxed );
        if( skipReason == 2 )
        {
          row.seqWrongAfterBestWinCount.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( skipReason == 3 )
        {
          row.seqWrongAfterBestLossCount.fetch_add( 1, std::memory_order_relaxed );
        }
      }
      if( otherBetterThanZero )
      {
        row.seqOtherBetterThanZeroCount.fetch_add( 1, std::memory_order_relaxed );
      }
      if( otherBetterThanBest )
      {
        row.seqOtherBetterThanBestCount.fetch_add( 1, std::memory_order_relaxed );
      }
    } );
    if( wouldSkip )
    {
      LardSkip21Stage3TimingRow& reasonRow = m_seqSkipReasonRows[Clip3( 0, 4, skipReason )];
      reasonRow.checkedCount.fetch_add( 1, std::memory_order_relaxed );
      reasonRow.appliedCount.fetch_add( 1, std::memory_order_relaxed );
      reasonRow.prunedCandidateTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
      reasonRow.stage3EvalTimeNs.fetch_add( evalNs, std::memory_order_relaxed );
      reasonRow.seqEnabledCount.fetch_add( 1, std::memory_order_relaxed );
      if( skipReason == 2 )
      {
        reasonRow.seqBestWinSkipCount.fetch_add( 1, std::memory_order_relaxed );
        reasonRow.seqBestWinPrunedTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
      }
      else
      {
        reasonRow.seqBestLossSkipCount.fetch_add( 1, std::memory_order_relaxed );
        reasonRow.seqBestLossPrunedTimeNs.fetch_add( otherNs, std::memory_order_relaxed );
      }
      if( wrongSkip )
      {
        reasonRow.seqWrongSkipCount.fetch_add( 1, std::memory_order_relaxed );
        if( skipReason == 2 )
        {
          reasonRow.seqWrongAfterBestWinCount.fetch_add( 1, std::memory_order_relaxed );
        }
        else
        {
          reasonRow.seqWrongAfterBestLossCount.fetch_add( 1, std::memory_order_relaxed );
        }
      }
      if( otherBetterThanZero )
      {
        reasonRow.seqOtherBetterThanZeroCount.fetch_add( 1, std::memory_order_relaxed );
      }
      if( otherBetterThanBest )
      {
        reasonRow.seqOtherBetterThanBestCount.fetch_add( 1, std::memory_order_relaxed );
      }
    }
  }

  void recordZdDecision( const char* fileName, const int qp, const int w, const int h,
                         const bool wouldSkip, const bool wrongSkip,
                         const uint64_t candidate1Ns, const uint64_t candidate2Ns, const uint64_t evalNs )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    auto record = [&]( LardSkip21Stage3TimingRow& row )
    {
      row.zdCheckedCount.fetch_add( 1, std::memory_order_relaxed );
      if( wouldSkip )
      {
        row.zdWouldSkipCount.fetch_add( 1, std::memory_order_relaxed );
        row.zdCandidate1TimeNs.fetch_add( candidate1Ns, std::memory_order_relaxed );
        row.zdCandidate2TimeNs.fetch_add( candidate2Ns, std::memory_order_relaxed );
      }
      if( wrongSkip )
      {
        row.zdWrongSkipCount.fetch_add( 1, std::memory_order_relaxed );
      }
      row.zdEvalTimeNs.fetch_add( evalNs, std::memory_order_relaxed );
    };
    record( m_overall );
    record( m_qpRows[Clip3( 0, 63, qp )] );
    const int wi = Clip3( 0, 7, floorLog2( std::max( 1, w ) ) );
    const int hi = Clip3( 0, 7, floorLog2( std::max( 1, h ) ) );
    record( m_sizeRows[wi][hi] );
  }

private:
  bool enable( const char* fileName )
  {
    if( !fileName || fileName[0] == '\0' )
    {
      return false;
    }
    if( m_enabled.load( std::memory_order_relaxed ) )
    {
      return true;
    }
    std::lock_guard<std::mutex> lock( m_mutex );
    if( !m_enabled.load( std::memory_order_relaxed ) )
    {
      m_fileName = fileName;
      m_enabled.store( true, std::memory_order_relaxed );
    }
    return true;
  }

  static int binDiff( const int value )
  {
    if( value < 20 ) return 0;
    if( value < 40 ) return 1;
    if( value < 80 ) return 2;
    if( value < 160 ) return 3;
    return 4;
  }

  static int binKeep( const int value )
  {
    if( value < 256 ) return 0;
    if( value < 372 ) return 1;
    if( value < 512 ) return 2;
    if( value < 768 ) return 3;
    return 4;
  }

  template<typename F>
  void forEachRow( const int qp, const int w, const int h, const int selectedIdx, const int prunedIdx,
                   const int diffQ, const int keepQ, const bool includeDecisionRows, F&& fn )
  {
    fn( m_overall );
    fn( m_qpRows[Clip3( 0, 63, qp )] );
    const int wi = Clip3( 0, 7, floorLog2( std::max( 1, w ) ) );
    const int hi = Clip3( 0, 7, floorLog2( std::max( 1, h ) ) );
    fn( m_sizeRows[wi][hi] );
    if( includeDecisionRows )
    {
      fn( m_selectedRows[Clip3( 0, 2, selectedIdx )] );
      fn( m_prunedRows[Clip3( 0, 2, prunedIdx )] );
      fn( m_diffRows[binDiff( diffQ )] );
      fn( m_keepRows[binKeep( keepQ )] );
    }
  }

  static void writeRow( FILE* fp, const char* scope, const int key1, const int key2, const LardSkip21Stage3TimingRow& row )
  {
    const uint64_t checked = row.checkedCount.load( std::memory_order_relaxed );
    const uint64_t applied = row.appliedCount.load( std::memory_order_relaxed );
    const uint64_t zdChecked = row.zdCheckedCount.load( std::memory_order_relaxed );
    const uint64_t zdWouldSkip = row.zdWouldSkipCount.load( std::memory_order_relaxed );
    if( checked == 0 && applied == 0 && zdChecked == 0 && zdWouldSkip == 0 )
    {
      return;
    }
    const uint64_t prunedNs = row.prunedCandidateTimeNs.load( std::memory_order_relaxed );
    const uint64_t evalNs = row.stage3EvalTimeNs.load( std::memory_order_relaxed );
    const int64_t netNs = (int64_t)prunedNs - (int64_t)evalNs;
    const double timePerPruned = applied ? (double)prunedNs / (double)applied : 0.0;
    const uint64_t zdCand1Ns = row.zdCandidate1TimeNs.load( std::memory_order_relaxed );
    const uint64_t zdCand2Ns = row.zdCandidate2TimeNs.load( std::memory_order_relaxed );
    const uint64_t zdEvalNs = row.zdEvalTimeNs.load( std::memory_order_relaxed );
    const int64_t zdNetNs = (int64_t)( zdCand1Ns + zdCand2Ns ) - (int64_t)zdEvalNs;
    std::fprintf( fp, "%s,%d,%d,%llu,%llu,%llu,%llu,%lld,%.3f,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%lld\n",
                  scope, key1, key2,
                  (unsigned long long)checked,
                  (unsigned long long)applied,
                  (unsigned long long)prunedNs,
                  (unsigned long long)evalNs,
                  (long long)netNs,
                  timePerPruned,
                  (unsigned long long)row.seqEnabledCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqBestWinSkipCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqBestLossSkipCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqWrongSkipCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqWrongAfterBestWinCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqWrongAfterBestLossCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqBestWinPrunedTimeNs.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqBestLossPrunedTimeNs.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqOtherBetterThanZeroCount.load( std::memory_order_relaxed ),
                  (unsigned long long)row.seqOtherBetterThanBestCount.load( std::memory_order_relaxed ),
                  (unsigned long long)zdChecked,
                  (unsigned long long)zdWouldSkip,
                  (unsigned long long)row.zdWrongSkipCount.load( std::memory_order_relaxed ),
                  (unsigned long long)zdCand1Ns,
                  (unsigned long long)zdCand2Ns,
                  (long long)zdNetNs );
  }

  void flush()
  {
    if( !m_enabled.load( std::memory_order_relaxed ) || m_fileName.empty() )
    {
      return;
    }
    FILE* fp = std::fopen( m_fileName.c_str(), "w" );
    if( !fp )
    {
      return;
    }
    std::fprintf( fp, "scope,key1,key2,stage3_checked,stage3_applied,pruned_candidate_time_ns,stage3_eval_time_ns,net_time_ns,time_per_pruned_candidate_ns,stage3seq_enabled,stage3seq_best_win_skip,stage3seq_best_loss_skip,stage3seq_wrong_skip,stage3seq_wrong_after_best_win,stage3seq_wrong_after_best_loss,stage3seq_best_win_pruned_time_ns,stage3seq_best_loss_pruned_time_ns,stage3seq_other_better_than_zero,stage3seq_other_better_than_best,stage3zd_checked,stage3zd_would_skip,stage3zd_wrong_skip,stage3zd_candidate1_time_ns,stage3zd_candidate2_time_ns,stage3zd_net_time_ns\n" );
    writeRow( fp, "overall", -1, -1, m_overall );
    for( int qp = 0; qp < 64; qp++ )
    {
      writeRow( fp, "by_qp", qp, -1, m_qpRows[qp] );
    }
    for( int wi = 0; wi < 8; wi++ )
    {
      for( int hi = 0; hi < 8; hi++ )
      {
        writeRow( fp, "by_size", 1 << wi, 1 << hi, m_sizeRows[wi][hi] );
      }
    }
    for( int idx = 1; idx <= 2; idx++ )
    {
      writeRow( fp, "by_selected_idx", idx, -1, m_selectedRows[idx] );
      writeRow( fp, "by_pruned_idx", idx, -1, m_prunedRows[idx] );
    }
    for( int bin = 0; bin < 5; bin++ )
    {
      writeRow( fp, "by_diff_bin", bin, -1, m_diffRows[bin] );
      writeRow( fp, "by_keep_score_bin", bin, -1, m_keepRows[bin] );
    }
    for( int reason = 0; reason < 5; reason++ )
    {
      writeRow( fp, "by_seq_skip_reason", reason, -1, m_seqSkipReasonRows[reason] );
    }
    std::fclose( fp );
  }

  std::atomic<bool> m_enabled { false };
  std::mutex m_mutex;
  std::string m_fileName;
  LardSkip21Stage3TimingRow m_overall;
  LardSkip21Stage3TimingRow m_qpRows[64];
  LardSkip21Stage3TimingRow m_sizeRows[8][8];
  LardSkip21Stage3TimingRow m_selectedRows[3];
  LardSkip21Stage3TimingRow m_prunedRows[3];
  LardSkip21Stage3TimingRow m_diffRows[5];
  LardSkip21Stage3TimingRow m_keepRows[5];
  LardSkip21Stage3TimingRow m_seqSkipReasonRows[5];
};

static LardSkip21Stage3TimingStore& xLardSkip21Stage3TimingStore()
{
  static LardSkip21Stage3TimingStore store;
  return store;
}

struct LardSkip21Stage3LbTimingRow
{
  std::atomic<uint64_t> checkedNonzero { 0 };
  std::atomic<uint64_t> wouldTerminate { 0 };
  std::atomic<uint64_t> wrongTerminate { 0 };
  std::atomic<uint64_t> candidateTotalTimeNs { 0 };
  std::atomic<uint64_t> timeBeforeDistortionReadyNs { 0 };
  std::atomic<uint64_t> timeAfterDistortionReadyNs { 0 };
  std::atomic<uint64_t> wouldTerminateTailTimeNs { 0 };
  std::atomic<uint64_t> checkTimeNs { 0 };
};

class LardSkip21Stage3LbTimingStore
{
public:
  ~LardSkip21Stage3LbTimingStore()
  {
    flush();
  }

  void record( const char* fileName, const int qp, const int w, const int h, const int lfnstIdx,
               const int bestIdxBefore, const int distMarginBin, const bool wouldTerminate,
               const bool wrongTerminate, const uint64_t candidateTotalNs,
               const uint64_t beforeDistReadyNs, const uint64_t afterDistReadyNs,
               const uint64_t wouldTerminateTailNs, const uint64_t checkNs )
  {
    if( !enable( fileName ) )
    {
      return;
    }
    forEachRow( qp, w, h, lfnstIdx, bestIdxBefore, distMarginBin, [&]( LardSkip21Stage3LbTimingRow& row )
    {
      row.checkedNonzero.fetch_add( 1, std::memory_order_relaxed );
      if( wouldTerminate )
      {
        row.wouldTerminate.fetch_add( 1, std::memory_order_relaxed );
      }
      if( wrongTerminate )
      {
        row.wrongTerminate.fetch_add( 1, std::memory_order_relaxed );
      }
      row.candidateTotalTimeNs.fetch_add( candidateTotalNs, std::memory_order_relaxed );
      row.timeBeforeDistortionReadyNs.fetch_add( beforeDistReadyNs, std::memory_order_relaxed );
      row.timeAfterDistortionReadyNs.fetch_add( afterDistReadyNs, std::memory_order_relaxed );
      row.wouldTerminateTailTimeNs.fetch_add( wouldTerminateTailNs, std::memory_order_relaxed );
      row.checkTimeNs.fetch_add( checkNs, std::memory_order_relaxed );
    } );
  }

private:
  bool enable( const char* fileName )
  {
    if( !fileName || fileName[0] == '\0' )
    {
      return false;
    }
    if( m_enabled.load( std::memory_order_relaxed ) )
    {
      return true;
    }
    std::lock_guard<std::mutex> lock( m_mutex );
    if( !m_enabled.load( std::memory_order_relaxed ) )
    {
      m_fileName = fileName;
      m_enabled.store( true, std::memory_order_relaxed );
    }
    return true;
  }

  static int binDistMargin( const double distLowerBound, const double bestBefore )
  {
    if( !( bestBefore < MAX_DOUBLE * 0.5 ) )
    {
      return 0;
    }
    const double denom = std::max( bestBefore, 1.0 );
    const double rel = ( distLowerBound - bestBefore ) / denom;
    if( rel < 0.0 ) return 0;
    if( rel < 0.01 ) return 1;
    if( rel < 0.05 ) return 2;
    if( rel < 0.10 ) return 3;
    return 4;
  }

  template<typename F>
  void forEachRow( const int qp, const int w, const int h, const int lfnstIdx,
                   const int bestIdxBefore, const int distMarginBin, F&& fn )
  {
    fn( m_overall );
    fn( m_qpRows[Clip3( 0, 63, qp )] );
    const int wi = Clip3( 0, 7, floorLog2( std::max( 1, w ) ) );
    const int hi = Clip3( 0, 7, floorLog2( std::max( 1, h ) ) );
    fn( m_sizeRows[wi][hi] );
    fn( m_lfnstIdxRows[Clip3( 0, 2, lfnstIdx )] );
    fn( m_bestIdxBeforeRows[Clip3( 0, 2, bestIdxBefore )] );
    fn( m_distMarginRows[Clip3( 0, 4, distMarginBin )] );
  }

  static void writeRow( FILE* fp, const char* scope, const int key1, const int key2, const LardSkip21Stage3LbTimingRow& row )
  {
    const uint64_t checked = row.checkedNonzero.load( std::memory_order_relaxed );
    if( checked == 0 )
    {
      return;
    }
    const uint64_t tailNs = row.wouldTerminateTailTimeNs.load( std::memory_order_relaxed );
    const uint64_t checkNs = row.checkTimeNs.load( std::memory_order_relaxed );
    const int64_t netTailNs = (int64_t)tailNs - (int64_t)checkNs;
    std::fprintf( fp, "%s,%d,%d,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%lld\n",
                  scope, key1, key2,
                  (unsigned long long)checked,
                  (unsigned long long)row.wouldTerminate.load( std::memory_order_relaxed ),
                  (unsigned long long)row.wrongTerminate.load( std::memory_order_relaxed ),
                  (unsigned long long)row.candidateTotalTimeNs.load( std::memory_order_relaxed ),
                  (unsigned long long)row.timeBeforeDistortionReadyNs.load( std::memory_order_relaxed ),
                  (unsigned long long)row.timeAfterDistortionReadyNs.load( std::memory_order_relaxed ),
                  (unsigned long long)tailNs,
                  (unsigned long long)checkNs,
                  (long long)netTailNs );
  }

  void flush()
  {
    if( !m_enabled.load( std::memory_order_relaxed ) || m_fileName.empty() )
    {
      return;
    }
    FILE* fp = std::fopen( m_fileName.c_str(), "w" );
    if( !fp )
    {
      return;
    }
    std::fprintf( fp, "scope,key1,key2,stage3lb_checked_nonzero,stage3lb_would_terminate,stage3lb_wrong_terminate,candidate_total_time_ns,time_before_distortion_ready_ns,time_after_distortion_ready_ns,would_terminate_tail_time_ns,stage3lb_check_time_ns,net_tail_time_ns\n" );
    writeRow( fp, "overall", -1, -1, m_overall );
    for( int qp = 0; qp < 64; qp++ )
    {
      writeRow( fp, "by_qp", qp, -1, m_qpRows[qp] );
    }
    for( int wi = 0; wi < 8; wi++ )
    {
      for( int hi = 0; hi < 8; hi++ )
      {
        writeRow( fp, "by_size", 1 << wi, 1 << hi, m_sizeRows[wi][hi] );
      }
    }
    for( int idx = 1; idx <= 2; idx++ )
    {
      writeRow( fp, "by_lfnstIdx", idx, -1, m_lfnstIdxRows[idx] );
    }
    for( int idx = 0; idx <= 2; idx++ )
    {
      writeRow( fp, "by_bestIdxBefore", idx, -1, m_bestIdxBeforeRows[idx] );
    }
    for( int bin = 0; bin < 5; bin++ )
    {
      writeRow( fp, "by_dist_margin_bin", bin, -1, m_distMarginRows[bin] );
    }
    std::fclose( fp );
  }

  std::atomic<bool> m_enabled { false };
  std::mutex m_mutex;
  std::string m_fileName;
  LardSkip21Stage3LbTimingRow m_overall;
  LardSkip21Stage3LbTimingRow m_qpRows[64];
  LardSkip21Stage3LbTimingRow m_sizeRows[8][8];
  LardSkip21Stage3LbTimingRow m_lfnstIdxRows[3];
  LardSkip21Stage3LbTimingRow m_bestIdxBeforeRows[3];
  LardSkip21Stage3LbTimingRow m_distMarginRows[5];

public:
  static int distMarginBin( const double distLowerBound, const double bestBefore )
  {
    return binDistMargin( distLowerBound, bestBefore );
  }
};

static LardSkip21Stage3LbTimingStore& xLardSkip21Stage3LbTimingStore()
{
  static LardSkip21Stage3LbTimingStore store;
  return store;
}

class Lard18ScopedIntraTimer
{
public:
  Lard18ScopedIntraTimer( const char* fileName, const int qp, const int w, const int h )
    : m_fileName( fileName ), m_qp( qp ), m_w( w ), m_h( h ),
      m_enabled( fileName && fileName[0] != '\0' ),
      m_start( m_enabled ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point() )
  {
  }

  ~Lard18ScopedIntraTimer()
  {
    if( m_enabled )
    {
      const auto end = std::chrono::steady_clock::now();
      const uint64_t ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( end - m_start ).count();
      xLard18ComplexityStore().recordIntraSearch( m_fileName, m_qp, m_w, m_h, ns );
    }
  }

private:
  const char* m_fileName;
  int m_qp;
  int m_w;
  int m_h;
  bool m_enabled;
  std::chrono::steady_clock::time_point m_start;
};

static double xLard2ndEntropyBound( const double var, const double qStep, const double kappa )
{
  return 0.5 * std::log2( 1.0 + kappa * std::max( 0.0, var ) / ( qStep * qStep + 1e-9 ) );
}

static void xLard2ndTheoryMetricsFast( const double var, const double qStep, double& rate, double& nz )
{
  static constexpr int    minBin = -96;
  static constexpr int    maxBin = 224;
  static constexpr int    binScale = 8;
  static constexpr int    numBins = maxBin - minBin + 1;
  struct Table
  {
    double rate[numBins];
    double nz[numBins];
    Table()
    {
      for( int b = minBin; b <= maxBin; b++ )
      {
        const double x = std::pow( 2.0, (double)b / (double)binScale );
        const int idx = b - minBin;
        rate[idx] = 0.5 * std::log2( 1.0 + x );
        nz[idx] = std::erfc( 0.5 / ( std::sqrt( 2.0 * x ) + 1e-12 ) );
      }
    }
  };
  static const Table table;

  if( var <= 0.0 )
  {
    rate = 0.0;
    nz = 0.0;
    return;
  }
  const double ratio = std::max( 1e-12, var / ( qStep * qStep + 1e-9 ) );
  const int bin = Clip3( minBin, maxBin, (int)std::floor( std::log2( ratio ) * (double)binScale + 0.5 ) );
  const int idx = bin - minBin;
  rate = table.rate[idx];
  nz = table.nz[idx];
}

static double xLard2ndTheoryRateFast( const double var, const double qStep )
{
  static constexpr int minBin = -96;
  static constexpr int maxBin = 224;
  static constexpr int binScale = 8;
  static constexpr int numBins = maxBin - minBin + 1;
  struct Table
  {
    double rate[numBins];
    Table()
    {
      for( int b = minBin; b <= maxBin; b++ )
      {
        const double x = std::pow( 2.0, (double)b / (double)binScale );
        rate[b - minBin] = 0.5 * std::log2( 1.0 + x );
      }
    }
  };
  static const Table table;
  if( var <= 0.0 )
  {
    return 0.0;
  }
  const double ratio = std::max( 1e-12, var / ( qStep * qStep + 1e-9 ) );
  const int bin = Clip3( minBin, maxBin, (int)std::floor( std::log2( ratio ) * (double)binScale + 0.5 ) );
  return table.rate[bin - minBin];
}

static double xLard2ndTheoryNzFast( const double var, const double qStep )
{
  static constexpr int minBin = -96;
  static constexpr int maxBin = 224;
  static constexpr int binScale = 8;
  static constexpr int numBins = maxBin - minBin + 1;
  struct Table
  {
    double nz[numBins];
    Table()
    {
      for( int b = minBin; b <= maxBin; b++ )
      {
        const double x = std::pow( 2.0, (double)b / (double)binScale );
        nz[b - minBin] = std::erfc( 0.5 / ( std::sqrt( 2.0 * x ) + 1e-12 ) );
      }
    }
  };
  static const Table table;
  if( var <= 0.0 )
  {
    return 0.0;
  }
  const double ratio = std::max( 1e-12, var / ( qStep * qStep + 1e-9 ) );
  const int bin = Clip3( minBin, maxBin, (int)std::floor( std::log2( ratio ) * (double)binScale + 0.5 ) );
  return table.nz[bin - minBin];
}

static double xLard2ndProxyRateFromVector( const double* vec, const int dim, const double qStep, const double idxCost )
{
  double nnz = 0.0;
  double sumLog = 0.0;
  int last = -1;
  const double invQStep = 1.0 / std::max( 1e-9, qStep );

  for( int i = 0; i < dim; i++ )
  {
    const int q = (int)std::floor( std::fabs( vec[i] ) * invQStep + 0.5 );
    if( q )
    {
      nnz += 1.0;
      sumLog += std::log2( 1.0 + (double)q );
      last = i;
    }
  }

  return nnz + 0.08 * sumLog + 0.35 * std::log2( 2.0 + (double)std::max( 0, last ) ) + idxCost;
}

static double xLard2ndProxyRateFromLfnstResponse( const double* input, const int trSize, const int8_t* fwdMat,
                                                  const int zeroOutSize, const double qStep, const double idxCost )
{
  double nnz = 0.0;
  double sumLog = 0.0;
  int last = -1;
  const double invQStep = 1.0 / std::max( 1e-9, qStep );

  for( int row = 0; row < zeroOutSize; row++ )
  {
    double resp = 0.0;
    const int8_t* mat = fwdMat + row * trSize;
    for( int col = 0; col < trSize; col++ )
    {
      resp += ( (double)mat[col] / 128.0 ) * input[col];
    }

    const int q = (int)std::floor( std::fabs( resp ) * invQStep + 0.5 );
    if( q )
    {
      nnz += 1.0;
      sumLog += std::log2( 1.0 + (double)q );
      last = row;
    }
  }

  return nnz + 0.08 * sumLog + 0.35 * std::log2( 2.0 + (double)std::max( 0, last ) ) + idxCost;
}

static double xLard2ndOffdiagProxyFromInput( const double* input, const int dim )
{
  double energy = 0.0;
  double offdiag = 0.0;
  for( int i = 0; i < dim; i++ )
  {
    energy += input[i] * input[i];
    for( int j = i + 1; j < dim; j++ )
    {
      offdiag += std::fabs( input[i] * input[j] );
    }
  }
  if( dim <= 1 || energy <= 0.0 )
  {
    return 0.0;
  }
  return 2.0 * offdiag / ( energy * (double)( dim - 1 ) + 1e-9 );
}

static bool xLard2ndIsMajorizedBy( const double* candVar, const double* baseVar, const int dim, double& margin )
{
  margin = 0.0;
  if( dim <= 1 )
  {
    return true;
  }

  double cand[16];
  double base[16];
  double sumCand = 0.0;
  double sumBase = 0.0;
  for( int i = 0; i < dim; i++ )
  {
    cand[i] = std::max( 0.0, candVar[i] );
    base[i] = std::max( 0.0, baseVar[i] );
    sumCand += cand[i];
    sumBase += base[i];
  }
  if( sumCand <= 1e-12 || sumBase <= 1e-12 )
  {
    return true;
  }

  for( int i = 0; i < dim; i++ )
  {
    cand[i] /= sumCand;
    base[i] /= sumBase;
  }
  std::sort( cand, cand + dim, std::greater<double>() );
  std::sort( base, base + dim, std::greater<double>() );

  double prefixCand = 0.0;
  double prefixBase = 0.0;
  margin = -1.0;
  for( int i = 0; i + 1 < dim; i++ )
  {
    prefixCand += cand[i];
    prefixBase += base[i];
    margin = std::max( margin, prefixCand - prefixBase );
  }
  return margin <= 1e-9;
}

static double xLard2ndGaussianNzProb( const double var, const double qStep )
{
  if( var <= 0.0 )
  {
    return 0.0;
  }
  const double sigma = std::sqrt( var );
  const double x = ( 0.5 * qStep ) / ( std::sqrt( 2.0 ) * sigma + 1e-12 );
  return std::erfc( x );
}

struct Lard2ndLookup
{
  double respVarW[16][48];
  double respCorrW[16][48][48];
  double subErrW[48];
  double subErrCorrW[48][48];
  double traceVVT;
};

struct Lard2ndLookupTable
{
  Lard2ndLookup entry[4][2][2][2];
};

static const Lard2ndLookupTable* xLard2ndBuildLookupTable()
{
  Lard2ndLookupTable* tablePtr = new Lard2ndLookupTable();
  Lard2ndLookupTable& table = *tablePtr;

  for( int lfnstSet = 0; lfnstSet < 4; lfnstSet++ )
  {
    for( int cand = 0; cand < 2; cand++ )
    {
      for( int sbClass = 0; sbClass < 2; sbClass++ )
      {
        const bool sb8 = sbClass != 0;
        const int  trSize = sb8 ? 48 : 16;
        const int8_t* fwdMat = sb8 ? g_lfnstFwd8x8[lfnstSet][cand][0] : g_lfnstFwd4x4[lfnstSet][cand][0];
        const int8_t* invMat = sb8 ? g_lfnstInv8x8[lfnstSet][cand][0] : g_lfnstInv4x4[lfnstSet][cand][0];

        for( int zeroIdx = 0; zeroIdx < 2; zeroIdx++ )
        {
          const int zeroOutSize = zeroIdx == 0 ? 8 : 16;
          Lard2ndLookup& lookup = table.entry[lfnstSet][cand][sbClass][zeroIdx];

          for( int row = 0; row < zeroOutSize; row++ )
          {
            for( int col = 0; col < trSize; col++ )
            {
              const double s = (double)fwdMat[row * trSize + col] / 128.0;
              lookup.respVarW[row][col] = s * s;
              for( int col2 = 0; col2 < trSize; col2++ )
              {
                const double s2 = (double)fwdMat[row * trSize + col2] / 128.0;
                lookup.respCorrW[row][col][col2] = s * s2;
              }
            }
          }

          double errMat[48][48] = {};
          for( int out = 0; out < trSize; out++ )
          {
            for( int col = 0; col < trSize; col++ )
            {
              double a = 0.0;
              for( int row = 0; row < zeroOutSize; row++ )
              {
                const double v = (double)invMat[out * 16 + row] / 128.0;
                const double s = (double)fwdMat[row * trSize + col] / 128.0;
                a += v * s;
              }
              errMat[out][col] = ( out == col ? 1.0 : 0.0 ) - a;
            }
          }

          for( int col = 0; col < trSize; col++ )
          {
            double colErr = 0.0;
            for( int out = 0; out < trSize; out++ )
            {
              colErr += errMat[out][col] * errMat[out][col];
            }
            lookup.subErrW[col] = colErr;
          }

          for( int col = 0; col < trSize; col++ )
          {
            for( int col2 = 0; col2 < trSize; col2++ )
            {
              double crossErr = 0.0;
              for( int out = 0; out < trSize; out++ )
              {
                crossErr += errMat[out][col] * errMat[out][col2];
              }
              lookup.subErrCorrW[col][col2] = crossErr;
            }
          }

          for( int out = 0; out < trSize; out++ )
          {
            for( int row = 0; row < zeroOutSize; row++ )
            {
              const double v = (double)invMat[out * 16 + row] / 128.0;
              lookup.traceVVT += v * v;
            }
          }
        }
      }
    }
  }

  return tablePtr;
}

static const Lard2ndLookup& xLard2ndGetLookup( const int lfnstSet, const int cand, const int sbSize, const int zeroOutSize )
{
  static const Lard2ndLookupTable* lookupTable = xLard2ndBuildLookupTable();
  const int setIdx  = Clip3( 0, 3, lfnstSet );
  const int candIdx = Clip3( 0, 1, cand );
  const int sbIdx   = sbSize > 4 ? 1 : 0;
  const int zeroIdx = zeroOutSize > 8 ? 1 : 0;
  return lookupTable->entry[setIdx][candIdx][sbIdx][zeroIdx];
}

static double xLard2ndCorrDistance( const int modeGroup, const int du, const int dv )
{
  const double adu = (double)std::abs( du );
  const double adv = (double)std::abs( dv );
  switch( modeGroup )
  {
  case 2: return 0.85 * adu + 1.15 * adv;
  case 3: return 1.20 * adu + 0.80 * adv;
  case 4: return 0.80 * adu + 1.20 * adv;
  case 5: return 1.15 * adu + 0.85 * adv;
  default: return adu + adv;
  }
}

static double xLard2ndCorrCoeff( const double corrStrength, const double corrDecay, const int modeGroup,
                                 const int u0, const int v0, const int u1, const int v1 )
{
  if( corrStrength <= 0.0 )
  {
    return 0.0;
  }

  const double dist = xLard2ndCorrDistance( modeGroup, u0 - u1, v0 - v1 );
  return corrStrength * std::exp( -dist / std::max( 1e-9, corrDecay ) );
}

static const LardLfnst2ndCorrTableEntry* xLard2ndFindCorrTableEntry( const int latBucket, const int modeGroup,
                                                                      const int sizeGroup, const int sbClass,
                                                                      const int dim )
{
  const LardLfnst2ndCorrTableEntry* best = nullptr;
  int bestScore = -1;

  for( const LardLfnst2ndCorrTableEntry* e = g_lardLfnst2ndCorrTable; e->latBucket >= 0; e++ )
  {
    if( e->dim != dim )
    {
      continue;
    }
    if( e->latBucket != latBucket && e->latBucket != -1 )
    {
      continue;
    }
    if( e->modeGroup != modeGroup && e->modeGroup != -1 )
    {
      continue;
    }
    if( e->sizeGroup != sizeGroup && e->sizeGroup != -1 )
    {
      continue;
    }
    if( e->sbClass != sbClass && e->sbClass != -1 )
    {
      continue;
    }

    int score = 0;
    score += e->latBucket == latBucket ? 8 : 0;
    score += e->modeGroup == modeGroup ? 4 : 0;
    score += e->sizeGroup == sizeGroup ? 2 : 0;
    score += e->sbClass == sbClass ? 1 : 0;
    if( score > bestScore )
    {
      best = e;
      bestScore = score;
    }
  }

  return best;
}

static int xLard2ndTheoryABin( const double sigmaBase, const double qStep )
{
  const double a = sigmaBase / ( qStep * qStep + 1e-9 );
  return Clip3( -12, 12, (int)std::floor( std::log2( std::max( 1e-12, a ) ) + 0.5 ) );
}

static int xLard2ndTheorySizeIdx( const int size )
{
  switch( size )
  {
  case 4:  return 0;
  case 8:  return 1;
  case 16: return 2;
  case 32: return 3;
  case 64: return 4;
  default: return -1;
  }
}

static const LardLfnstTheoryStatsEntry* xLard2ndFindTheoryStatsEntry( const int latBucket, const int width,
                                                                       const int height, const bool transposeFlag,
                                                                       const int zeroOutSize, const int lfnstSet,
                                                                       const int lfnstIdx, const int aBin )
{
  (void)zeroOutSize;
  const int wIdx = xLard2ndTheorySizeIdx( width );
  const int hIdx = xLard2ndTheorySizeIdx( height );
  if( latBucket < 0 || latBucket >= 4 || wIdx < 0 || hIdx < 0 || lfnstSet < 0 || lfnstSet >= 4
   || lfnstIdx < 1 || lfnstIdx > 2 || aBin < -12 || aBin > 12 )
  {
    return nullptr;
  }
  const int trFlag = transposeFlag ? 1 : 0;
  const int cand = lfnstIdx - 1;
  const int aIdx = aBin + 12;
  const int idx = (((((( latBucket * 5 + wIdx ) * 5 + hIdx ) * 2 + trFlag ) * 4 + lfnstSet ) * 2 + cand ) * 25 + aIdx);
  return &g_lardLfnstTheoryStatsTable[idx];
}

static double xLard2ndCorrTableCoeff( const LardLfnst2ndCorrTableEntry* entry, const int i, const int j )
{
  if( !entry || i < 0 || j < 0 || i >= entry->dim || j >= entry->dim )
  {
    return 0.0;
  }
  return xLahtpClipD( -0.95, 0.95, (double)entry->corr[i][j] / 32767.0 );
}

struct Lard2ndCorrFactors
{
  const LardLfnst2ndCorrTableEntry* entry = nullptr;
  int lfnstSet = -1;
  int cand = -1;
  int sbClass = -1;
  int zeroClass = -1;
  double resp[16] = {};
  double sub = 0.0;
};

static Lard2ndCorrFactors xLard2ndGetCorrFactors( const LardLfnst2ndCorrTableEntry* entry, const int lfnstSet,
                                                  const int cand, const int sbSize, const int zeroOutSize )
{
  Lard2ndCorrFactors empty;
  if( !entry )
  {
    return empty;
  }

  const int sbClass = sbSize > 4 ? 1 : 0;
  const int zeroClass = zeroOutSize > 8 ? 1 : 0;

  static std::mutex s_factorMutex;
  static std::vector<Lard2ndCorrFactors> s_factors;

  std::lock_guard<std::mutex> lock( s_factorMutex );
  for( const Lard2ndCorrFactors& f : s_factors )
  {
    if( f.entry == entry && f.lfnstSet == lfnstSet && f.cand == cand && f.sbClass == sbClass && f.zeroClass == zeroClass )
    {
      return f;
    }
  }

  Lard2ndCorrFactors f;
  f.entry = entry;
  f.lfnstSet = lfnstSet;
  f.cand = cand;
  f.sbClass = sbClass;
  f.zeroClass = zeroClass;

  const Lard2ndLookup& lookup = xLard2ndGetLookup( lfnstSet, cand, sbSize, zeroOutSize );
  const int trSize = entry->dim;
  for( int row = 0; row < zeroOutSize; row++ )
  {
    double resp = 0.0;
    for( int col = 0; col + 1 < trSize; col++ )
    {
      for( int col2 = col + 1; col2 < trSize; col2++ )
      {
        resp += 2.0 * lookup.respCorrW[row][col][col2] * xLard2ndCorrTableCoeff( entry, col, col2 );
      }
    }
    f.resp[row] = resp;
  }

  for( int col = 0; col + 1 < trSize; col++ )
  {
    for( int col2 = col + 1; col2 < trSize; col2++ )
    {
      f.sub += 2.0 * lookup.subErrCorrW[col][col2] * xLard2ndCorrTableCoeff( entry, col, col2 );
    }
  }

  s_factors.push_back( f );
  return f;
}

static void xLard2ndAppendStats( const char* fileName, const CodingUnit& cu, const int intraMode, const int lfnstSet,
                                 const int sbSize, const int zeroOutSize, const double inputEnergy, const double thetaMaxDeg,
                                 const double corrStrength, const double rate0, const double obsRate0,
                                 const double f1, const double f2, const double g1, const double g2,
                                 const double obs1, const double obs2, const int rawMask, const int mask, const bool safeGate,
                                 const int theoryReason = 0, const double theoryMh = 0.0,
                                 const double theoryMajorMargin1 = 0.0, const double theoryMajorMargin2 = 0.0,
                                 const double theoryRate1 = 0.0, const double theoryRate2 = 0.0,
                                 const double theoryNz0 = 0.0, const double theoryNz1 = 0.0, const double theoryNz2 = 0.0,
                                 const int theoryMajorMask = 0 )
{
  if( !fileName || fileName[0] == '\0' )
  {
    return;
  }

  static FILE* s_statFp = nullptr;
  static std::string s_statName;
  static std::mutex s_statMutex;

  std::lock_guard<std::mutex> lock( s_statMutex );

  if( s_statFp && s_statName != fileName )
  {
    std::fclose( s_statFp );
    s_statFp = nullptr;
    s_statName.clear();
  }

  bool writeHeader = false;
  if( !s_statFp )
  {
    if( FILE* fpRead = std::fopen( fileName, "rb" ) )
    {
      std::fseek( fpRead, 0, SEEK_END );
      writeHeader = std::ftell( fpRead ) == 0;
      std::fclose( fpRead );
    }
    else
    {
      writeHeader = true;
    }

    s_statFp = std::fopen( fileName, "ab" );
    if( !s_statFp )
    {
      return;
    }
    s_statName = fileName;
  }

  if( writeHeader )
  {
    std::fprintf( s_statFp, "poc,x,y,w,h,qp,intraMode,lfnstSet,sbSize,zeroOutSize,inputEnergy,thetaMaxDeg,corrStrength,rate0,obsRate0,f1,f2,g1,g2,obs1,obs2,rawMask,mask,safeGate,theoryReason,theoryMh,theoryMajorMargin1,theoryMajorMargin2,theoryRate1,theoryRate2,theoryNz0,theoryNz1,theoryNz2,theoryMajorMask\n" );
  }

  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  std::fprintf( s_statFp,
                "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.9g,%.6f,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d\n",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, intraMode, lfnstSet, sbSize, zeroOutSize,
                inputEnergy, thetaMaxDeg, corrStrength, rate0, obsRate0, f1, f2, g1, g2, obs1, obs2, rawMask, mask, safeGate ? 1 : 0,
                theoryReason, theoryMh, theoryMajorMargin1, theoryMajorMargin2, theoryRate1, theoryRate2,
                theoryNz0, theoryNz1, theoryNz2, theoryMajorMask );
}

void IntraSearch::xLardLfnst2ndAppendFinalStats( const CodingUnit& cu, const LardLfnst2ndDecision& d, const int bestLfnstIdx,
                                                 const double cost0, const double cost1, const double cost2, const int dct2CostBin ) const
{
  const char* fileName = m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndFinalStatFile : nullptr;
  if( !fileName || fileName[0] == '\0' || !d.valid )
  {
    return;
  }

  static FILE* s_finalFp = nullptr;
  static std::string s_finalName;
  static std::mutex s_finalMutex;

  std::lock_guard<std::mutex> lock( s_finalMutex );

  if( s_finalFp && s_finalName != fileName )
  {
    std::fclose( s_finalFp );
    s_finalFp = nullptr;
    s_finalName.clear();
  }

  bool writeHeader = false;
  if( !s_finalFp )
  {
    if( FILE* fpRead = std::fopen( fileName, "rb" ) )
    {
      std::fseek( fpRead, 0, SEEK_END );
      writeHeader = std::ftell( fpRead ) == 0;
      std::fclose( fpRead );
    }
    else
    {
      writeHeader = true;
    }

    s_finalFp = std::fopen( fileName, "ab" );
    if( !s_finalFp )
    {
      return;
    }
    s_finalName = fileName;
  }

  if( writeHeader )
  {
    std::fprintf( s_finalFp, "poc,x,y,w,h,qp,modeGroup,lfnstSet,sbSize,finalLfnstIdx,dct2CostBin,inputEnergy,thetaMaxDeg,offdiagProxy,corrStrength,rate0,obsRate0,f1,f2,g1,g2,obs1,obs2,rawMask,mask,safeGate,cost0,cost1,cost2,trueGain1,trueGain2,trSize,theoryReason,theoryMh,theoryMajorMargin1,theoryMajorMargin2,theoryRate1,theoryRate2,theoryNz0,theoryNz1,theoryNz2,theoryMajorMask,earlyValid,earlySkip,earlyGeom,earlyRoiFull,earlyRoiProxy,earlyMh,earlyRoiEnergyQ,earlyPredNz,earlyLfRatio,earlyCorrProxy,earlyMeanAbsQ" );
    for( int i = 0; i < 48; i++ )
    {
      std::fprintf( s_finalFp, ",x%02d", i );
    }
    std::fprintf( s_finalFp, "\n" );
  }

  const double trueGain1 = ( cost0 < MAX_DOUBLE * 0.5 && cost1 < MAX_DOUBLE * 0.5 ) ? cost0 - cost1 : 0.0;
  const double trueGain2 = ( cost0 < MAX_DOUBLE * 0.5 && cost2 < MAX_DOUBLE * 0.5 ) ? cost0 - cost2 : 0.0;
  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  std::fprintf( s_finalFp,
                "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.9g,%.6f,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%d,%d,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, d.modeGroup, d.lfnstSet, d.sbSize, bestLfnstIdx, dct2CostBin,
                d.inputEnergy, d.thetaMaxDeg, d.offdiagProxy, d.corrStrength, d.rate0, d.obsRate0,
                d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate ? 1 : 0,
                cost0, cost1, cost2, trueGain1, trueGain2, d.trSize, d.theoryReason, d.theoryMh,
                d.theoryMajorMargin1, d.theoryMajorMargin2, d.theoryRate1, d.theoryRate2,
                d.theoryNz0, d.theoryNz1, d.theoryNz2, d.theoryMajorMask,
                d.earlyValid ? 1 : 0, d.earlySkip ? 1 : 0, d.earlyGeom ? 1 : 0,
                d.earlyRoiFull ? 1 : 0, d.earlyRoiProxy ? 1 : 0, d.earlyMh,
                d.earlyRoiEnergyQ, d.earlyPredNz, d.earlyLfRatio, d.earlyCorrProxy, d.earlyMeanAbsQ );
  for( int i = 0; i < 48; i++ )
  {
    std::fprintf( s_finalFp, ",%.9g", d.input[i] );
  }
  std::fprintf( s_finalFp, "\n" );
}

static constexpr int LARD2ND_COST_BINS = 32;
static constexpr int LARD2ND_AREA_GROUPS = 5;
static constexpr int LARD2ND_SHAPE_GROUPS = 5;

static int xLard2ndCostBin( const double cost )
{
  if( !( cost > 0.0 ) || cost >= MAX_DOUBLE * 0.5 )
  {
    return 0;
  }
  return Clip3( 0, LARD2ND_COST_BINS - 1, (int)std::floor( std::log2( cost ) ) );
}

static int xLard2ndEnergyBucket( const double energyNorm )
{
  static const double th[] = { 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0,
                               64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0, 4096.0 };
  for( int i = 0; i < (int)( sizeof( th ) / sizeof( th[0] ) ); i++ )
  {
    if( energyNorm <= th[i] )
    {
      return i;
    }
  }
  return 15;
}

static int xLard2ndObsBucket( const double obsGain )
{
  if( obsGain <= -1000.0 )
  {
    return 0;
  }
  if( obsGain <= -250.0 )
  {
    return 1;
  }
  if( obsGain <= 0.0 )
  {
    return 2;
  }
  if( obsGain <= 50.0 )
  {
    return 3;
  }
  if( obsGain <= 250.0 )
  {
    return 4;
  }
  if( obsGain <= 1000.0 )
  {
    return 5;
  }
  return 6;
}

static int xLard2ndCoffBucket( const double coff )
{
  if( coff < 0.05 )
  {
    return 0;
  }
  if( coff < 0.10 )
  {
    return 1;
  }
  if( coff < 0.15 )
  {
    return 2;
  }
  if( coff < 0.20 )
  {
    return 3;
  }
  if( coff < 0.30 )
  {
    return 4;
  }
  return 5;
}

static int64_t xLard2ndCoffPackKey( const int qp, const int sizeGroup, const int modeGroup, const int latBucket,
                                    const int lfnstSet, const int sbClass, const int dct2CostBin, const int energyBucket )
{
  int64_t key = qp;
  key = key * 7 + sizeGroup;
  key = key * 6 + modeGroup;
  key = key * 4 + latBucket;
  key = key * 4 + Clip3( 0, 3, lfnstSet );
  key = key * 2 + Clip3( 0, 1, sbClass );
  key = key * LARD2ND_COST_BINS + Clip3( 0, LARD2ND_COST_BINS - 1, dct2CostBin );
  key = key * 16 + energyBucket;
  return key;
}

static int64_t xLard2ndScorePackKey( const int qp, const int sizeGroup, const int modeGroup, const int latBucket,
                                     const int lfnstSet, const int sbClass, const int dct2CostBin, const int energyBucket,
                                     const int nzBucket, const int lastBucket, const int coffBucket, const int obsBucket )
{
  int64_t key = xLard2ndCoffPackKey( qp, sizeGroup, modeGroup, latBucket, lfnstSet, sbClass, dct2CostBin, energyBucket );
  key = key * 6 + nzBucket;
  key = key * 6 + lastBucket;
  key = key * 6 + coffBucket;
  key = key * 7 + obsBucket;
  return key;
}

static int xLard2ndAreaGroup( const int area )
{
  return area <= 16 ? 0 : area <= 64 ? 1 : area <= 256 ? 2 : area <= 1024 ? 3 : 4;
}

static int xLard2ndShapeGroup( const int wIn, const int hIn )
{
  const int w = std::max( 1, wIn );
  const int h = std::max( 1, hIn );
  if( w == h )
  {
    return 0;
  }
  const double aspect = (double)std::max( w, h ) / (double)std::min( w, h );
  if( w > h )
  {
    return aspect <= 2.0 ? 1 : 3;
  }
  return aspect <= 2.0 ? 2 : 4;
}

static const char* xLard2ndShapeName( const int shapeGroup )
{
  static const char* names[LARD2ND_SHAPE_GROUPS] = { "SH_SQ", "SH_W2", "SH_H2", "SH_W4", "SH_H4" };
  return names[Clip3( 0, LARD2ND_SHAPE_GROUPS - 1, shapeGroup )];
}

static const char* xLard2ndAreaName( const int areaGroup )
{
  static const char* names[LARD2ND_AREA_GROUPS] = { "A16", "A64", "A256", "A1024", "A4096" };
  return names[Clip3( 0, LARD2ND_AREA_GROUPS - 1, areaGroup )];
}

static const char* xLard2ndModeName( const int modeGroup )
{
  static const char* names[6] = { "MODE_PLANAR", "MODE_DC", "MODE_ANG_02_17", "MODE_ANG_18_34", "MODE_ANG_35_50", "MODE_ANG_51_66" };
  return names[Clip3( 0, 5, modeGroup )];
}

struct Lard2ndCountRow
{
  std::atomic<uint64_t> decisionCalls      { 0 };
  std::atomic<uint64_t> decisionTimeNs     { 0 };
  std::atomic<uint64_t> basicEligible      { 0 };
  std::atomic<uint64_t> policyRejectQp     { 0 };
  std::atomic<uint64_t> policyRejectArea   { 0 };
  std::atomic<uint64_t> lowCostReject      { 0 };
  std::atomic<uint64_t> stage1Reject       { 0 };
  std::atomic<uint64_t> stage1Pass         { 0 };
  std::atomic<uint64_t> noTransformCoeff   { 0 };
  std::atomic<uint64_t> zeroEnergySkip     { 0 };
  std::atomic<uint64_t> obsGateFull        { 0 };
  std::atomic<uint64_t> obsOnlySkip        { 0 };
  std::atomic<uint64_t> fullModelFull      { 0 };
  std::atomic<uint64_t> fullModelSafeFull  { 0 };
  std::atomic<uint64_t> fullModelSkipBoth  { 0 };
  std::atomic<uint64_t> fullModelKeep1     { 0 };
  std::atomic<uint64_t> fullModelKeep2     { 0 };
  std::atomic<uint64_t> candPossible       { 0 };
  std::atomic<uint64_t> skipLfnst1         { 0 };
  std::atomic<uint64_t> skipLfnst2         { 0 };
  std::atomic<uint64_t> candRdoActual      { 0 };
  std::atomic<uint64_t> candRdoTimeNs      { 0 };
  std::atomic<uint64_t> candRdoWouldSkip   { 0 };
  std::atomic<uint64_t> candRdoWouldSkipNs { 0 };
};

class Lard2ndCountStore
{
public:
  ~Lard2ndCountStore()
  {
    flush();
  }

  bool enable( const char* fileName )
  {
    if( !fileName || fileName[0] == '\0' )
    {
      return false;
    }
    if( m_enabled.load( std::memory_order_relaxed ) )
    {
      return true;
    }

    std::lock_guard<std::mutex> lock( m_mutex );
    if( !m_enabled.load( std::memory_order_relaxed ) )
    {
      m_fileName = fileName;
      m_enabled.store( true, std::memory_order_relaxed );
    }
    return true;
  }

  Lard2ndCountRow& row( const int qp )
  {
    return m_rows[Clip3( 0, 63, qp )];
  }

  Lard2ndCountRow& sizeRow( const int qp, const int area )
  {
    const int q = Clip3( 0, 63, qp );
    const int g = xLard2ndAreaGroup( area );
    return m_sizeRows[q][g];
  }

  Lard2ndCountRow& shapeRow( const int qp, const int w, const int h )
  {
    const int q = Clip3( 0, 63, qp );
    const int g = xLard2ndShapeGroup( w, h );
    return m_shapeRows[q][g];
  }

  Lard2ndCountRow& areaShapeRow( const int qp, const int area, const int w, const int h )
  {
    const int q = Clip3( 0, 63, qp );
    const int a = xLard2ndAreaGroup( area );
    const int s = xLard2ndShapeGroup( w, h );
    return m_areaShapeRows[q][a][s];
  }

  Lard2ndCountRow& costRow( const int qp, const int costBin )
  {
    return m_costRows[Clip3( 0, 63, qp )][Clip3( 0, LARD2ND_COST_BINS - 1, costBin )];
  }

  void flush()
  {
    if( !m_enabled.load( std::memory_order_relaxed ) || m_fileName.empty() )
    {
      return;
    }

    std::lock_guard<std::mutex> lock( m_mutex );
    FILE* fp = std::fopen( m_fileName.c_str(), "wb" );
    if( !fp )
    {
      return;
    }

    std::fprintf( fp, "qp,areaGroup,decisionCalls,basicEligible,policyRejectQp,policyRejectArea,lowCostReject,stage1Reject,stage1Pass,noTransformCoeff,zeroEnergySkip,obsGateFull,obsOnlySkip,fullModelFull,fullModelSafeFull,fullModelSkipBoth,fullModelKeep1,fullModelKeep2,candPossible,skipLfnst1,skipLfnst2,skipTotal,skipRatio,candRdoActual,candRdoTimeNs,avgCandRdoNs,candRdoWouldSkip,candRdoWouldSkipNs,avgWouldSkipRdoNs,decisionTimeNs,avgDecisionNs\n" );

    uint64_t total[30] = {};
    for( int qp = 0; qp <= 63; qp++ )
    {
      uint64_t v[30] =
      {
        m_rows[qp].decisionCalls    .load( std::memory_order_relaxed ),
        m_rows[qp].basicEligible    .load( std::memory_order_relaxed ),
        m_rows[qp].policyRejectQp   .load( std::memory_order_relaxed ),
        m_rows[qp].policyRejectArea .load( std::memory_order_relaxed ),
        m_rows[qp].lowCostReject    .load( std::memory_order_relaxed ),
        m_rows[qp].stage1Reject     .load( std::memory_order_relaxed ),
        m_rows[qp].stage1Pass       .load( std::memory_order_relaxed ),
        m_rows[qp].noTransformCoeff .load( std::memory_order_relaxed ),
        m_rows[qp].zeroEnergySkip   .load( std::memory_order_relaxed ),
        m_rows[qp].obsGateFull      .load( std::memory_order_relaxed ),
        m_rows[qp].obsOnlySkip      .load( std::memory_order_relaxed ),
        m_rows[qp].fullModelFull    .load( std::memory_order_relaxed ),
        m_rows[qp].fullModelSafeFull.load( std::memory_order_relaxed ),
        m_rows[qp].fullModelSkipBoth.load( std::memory_order_relaxed ),
        m_rows[qp].fullModelKeep1   .load( std::memory_order_relaxed ),
        m_rows[qp].fullModelKeep2   .load( std::memory_order_relaxed ),
        m_rows[qp].candPossible     .load( std::memory_order_relaxed ),
        m_rows[qp].skipLfnst1       .load( std::memory_order_relaxed ),
        m_rows[qp].skipLfnst2       .load( std::memory_order_relaxed ),
        m_rows[qp].skipLfnst1       .load( std::memory_order_relaxed ) + m_rows[qp].skipLfnst2.load( std::memory_order_relaxed ),
        m_rows[qp].candRdoActual    .load( std::memory_order_relaxed ),
        m_rows[qp].candRdoTimeNs    .load( std::memory_order_relaxed ),
        0,
        m_rows[qp].candRdoWouldSkip .load( std::memory_order_relaxed ),
        m_rows[qp].candRdoWouldSkipNs.load( std::memory_order_relaxed ),
        0,
        m_rows[qp].decisionTimeNs   .load( std::memory_order_relaxed ),
        0
      };
      v[22] = v[20] ? v[21] / v[20] : 0;
      v[25] = v[23] ? v[24] / v[23] : 0;
      v[27] = v[0] ? v[26] / v[0] : 0;

      bool any = false;
      for( int i = 0; i < 28; i++ )
      {
        if( i != 22 && i != 25 && i != 27 )
        {
          total[i] += v[i];
        }
        any |= v[i] != 0;
      }
      if( !any )
      {
        continue;
      }
      const double skipRatio = v[16] ? (double)v[19] / (double)v[16] : 0.0;
      std::fprintf( fp, "%d,ALL,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%.9f,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu\n",
                    qp,
                    (unsigned long long)v[0],  (unsigned long long)v[1],  (unsigned long long)v[2],
                    (unsigned long long)v[3],  (unsigned long long)v[4],  (unsigned long long)v[5],
                    (unsigned long long)v[6],  (unsigned long long)v[7],  (unsigned long long)v[8],
                    (unsigned long long)v[9],  (unsigned long long)v[10], (unsigned long long)v[11],
                    (unsigned long long)v[12], (unsigned long long)v[13], (unsigned long long)v[14],
                    (unsigned long long)v[15], (unsigned long long)v[16], (unsigned long long)v[17],
                    (unsigned long long)v[18], (unsigned long long)v[19], skipRatio,
                    (unsigned long long)v[20], (unsigned long long)v[21], (unsigned long long)v[22],
                    (unsigned long long)v[23], (unsigned long long)v[24], (unsigned long long)v[25],
                    (unsigned long long)v[26], (unsigned long long)v[27] );
    }

    total[22] = total[20] ? total[21] / total[20] : 0;
    total[25] = total[23] ? total[24] / total[23] : 0;
    total[27] = total[0] ? total[26] / total[0] : 0;
    const double totalSkipRatio = total[16] ? (double)total[19] / (double)total[16] : 0.0;
    std::fprintf( fp, "TOTAL,ALL,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%.9f,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%llu\n",
                  (unsigned long long)total[0],  (unsigned long long)total[1],  (unsigned long long)total[2],
                  (unsigned long long)total[3],  (unsigned long long)total[4],  (unsigned long long)total[5],
                  (unsigned long long)total[6],  (unsigned long long)total[7],  (unsigned long long)total[8],
                  (unsigned long long)total[9],  (unsigned long long)total[10], (unsigned long long)total[11],
                  (unsigned long long)total[12], (unsigned long long)total[13], (unsigned long long)total[14],
                  (unsigned long long)total[15], (unsigned long long)total[16], (unsigned long long)total[17],
                  (unsigned long long)total[18], (unsigned long long)total[19], totalSkipRatio,
                  (unsigned long long)total[20], (unsigned long long)total[21], (unsigned long long)total[22],
                  (unsigned long long)total[23], (unsigned long long)total[24], (unsigned long long)total[25],
                  (unsigned long long)total[26], (unsigned long long)total[27] );

    for( int qp = 0; qp <= 63; qp++ )
    {
      for( int g = 0; g < LARD2ND_AREA_GROUPS; g++ )
      {
        const uint64_t candRdoActual      = m_sizeRows[qp][g].candRdoActual.load( std::memory_order_relaxed );
        const uint64_t candRdoTimeNs      = m_sizeRows[qp][g].candRdoTimeNs.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkip   = m_sizeRows[qp][g].candRdoWouldSkip.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkipNs = m_sizeRows[qp][g].candRdoWouldSkipNs.load( std::memory_order_relaxed );
        if( candRdoActual == 0 && candRdoWouldSkip == 0 )
        {
          continue;
        }
        std::fprintf( fp, "%d,%s,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.000000000,%llu,%llu,%llu,%llu,%llu,%llu,0,0\n",
                      qp, xLard2ndAreaName( g ),
                      (unsigned long long)candRdoActual,
                      (unsigned long long)candRdoTimeNs,
                      (unsigned long long)( candRdoActual ? candRdoTimeNs / candRdoActual : 0 ),
                      (unsigned long long)candRdoWouldSkip,
                      (unsigned long long)candRdoWouldSkipNs,
                      (unsigned long long)( candRdoWouldSkip ? candRdoWouldSkipNs / candRdoWouldSkip : 0 ) );
      }
    }
    for( int qp = 0; qp <= 63; qp++ )
    {
      for( int g = 0; g < LARD2ND_SHAPE_GROUPS; g++ )
      {
        Lard2ndCountRow& row = m_shapeRows[qp][g];
        const uint64_t candPossible       = row.candPossible.load( std::memory_order_relaxed );
        const uint64_t skipLfnst1         = row.skipLfnst1.load( std::memory_order_relaxed );
        const uint64_t skipLfnst2         = row.skipLfnst2.load( std::memory_order_relaxed );
        const uint64_t skipTotal          = skipLfnst1 + skipLfnst2;
        const uint64_t candRdoActual      = row.candRdoActual.load( std::memory_order_relaxed );
        const uint64_t candRdoTimeNs      = row.candRdoTimeNs.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkip   = row.candRdoWouldSkip.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkipNs = row.candRdoWouldSkipNs.load( std::memory_order_relaxed );
        if( candPossible == 0 && candRdoActual == 0 && candRdoWouldSkip == 0 )
        {
          continue;
        }
        const double skipRatio = candPossible ? (double)skipTotal / (double)candPossible : 0.0;
        std::fprintf( fp, "%d,%s,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,%llu,%llu,%llu,%llu,%.9f,%llu,%llu,%llu,%llu,%llu,%llu,0,0\n",
                      qp, xLard2ndShapeName( g ),
                      (unsigned long long)candPossible,
                      (unsigned long long)skipLfnst1,
                      (unsigned long long)skipLfnst2,
                      (unsigned long long)skipTotal,
                      skipRatio,
                      (unsigned long long)candRdoActual,
                      (unsigned long long)candRdoTimeNs,
                      (unsigned long long)( candRdoActual ? candRdoTimeNs / candRdoActual : 0 ),
                      (unsigned long long)candRdoWouldSkip,
                      (unsigned long long)candRdoWouldSkipNs,
                      (unsigned long long)( candRdoWouldSkip ? candRdoWouldSkipNs / candRdoWouldSkip : 0 ) );
      }
    }
    for( int qp = 0; qp <= 63; qp++ )
    {
      for( int a = 0; a < LARD2ND_AREA_GROUPS; a++ )
      {
        for( int s = 0; s < LARD2ND_SHAPE_GROUPS; s++ )
        {
          Lard2ndCountRow& row = m_areaShapeRows[qp][a][s];
          const uint64_t candPossible       = row.candPossible.load( std::memory_order_relaxed );
          const uint64_t skipLfnst1         = row.skipLfnst1.load( std::memory_order_relaxed );
          const uint64_t skipLfnst2         = row.skipLfnst2.load( std::memory_order_relaxed );
          const uint64_t skipTotal          = skipLfnst1 + skipLfnst2;
          const uint64_t candRdoActual      = row.candRdoActual.load( std::memory_order_relaxed );
          const uint64_t candRdoTimeNs      = row.candRdoTimeNs.load( std::memory_order_relaxed );
          const uint64_t candRdoWouldSkip   = row.candRdoWouldSkip.load( std::memory_order_relaxed );
          const uint64_t candRdoWouldSkipNs = row.candRdoWouldSkipNs.load( std::memory_order_relaxed );
          if( candPossible == 0 && candRdoActual == 0 && candRdoWouldSkip == 0 )
          {
            continue;
          }
          char groupName[32];
          std::snprintf( groupName, sizeof( groupName ), "%s_%s", xLard2ndAreaName( a ), xLard2ndShapeName( s ) );
          const double skipRatio = candPossible ? (double)skipTotal / (double)candPossible : 0.0;
          std::fprintf( fp, "%d,%s,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,%llu,%llu,%llu,%llu,%.9f,%llu,%llu,%llu,%llu,%llu,%llu,0,0\n",
                        qp, groupName,
                        (unsigned long long)candPossible,
                        (unsigned long long)skipLfnst1,
                        (unsigned long long)skipLfnst2,
                        (unsigned long long)skipTotal,
                        skipRatio,
                        (unsigned long long)candRdoActual,
                        (unsigned long long)candRdoTimeNs,
                        (unsigned long long)( candRdoActual ? candRdoTimeNs / candRdoActual : 0 ),
                        (unsigned long long)candRdoWouldSkip,
                        (unsigned long long)candRdoWouldSkipNs,
                        (unsigned long long)( candRdoWouldSkip ? candRdoWouldSkipNs / candRdoWouldSkip : 0 ) );
        }
      }
    }
    for( int qp = 0; qp <= 63; qp++ )
    {
      for( int b = 0; b < LARD2ND_COST_BINS; b++ )
      {
        Lard2ndCountRow& row = m_costRows[qp][b];
        const uint64_t decisionCalls      = row.decisionCalls.load( std::memory_order_relaxed );
        const uint64_t candPossible       = row.candPossible.load( std::memory_order_relaxed );
        const uint64_t skipLfnst1         = row.skipLfnst1.load( std::memory_order_relaxed );
        const uint64_t skipLfnst2         = row.skipLfnst2.load( std::memory_order_relaxed );
        const uint64_t skipTotal          = skipLfnst1 + skipLfnst2;
        const uint64_t candRdoActual      = row.candRdoActual.load( std::memory_order_relaxed );
        const uint64_t candRdoTimeNs      = row.candRdoTimeNs.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkip   = row.candRdoWouldSkip.load( std::memory_order_relaxed );
        const uint64_t candRdoWouldSkipNs = row.candRdoWouldSkipNs.load( std::memory_order_relaxed );
        if( decisionCalls == 0 && candRdoActual == 0 && candRdoWouldSkip == 0 )
        {
          continue;
        }
        const double skipRatio = candPossible ? (double)skipTotal / (double)candPossible : 0.0;
        std::fprintf( fp, "%d,COST_L2_%02d,%llu,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,%llu,%llu,%llu,%llu,%.9f,%llu,%llu,%llu,%llu,%llu,%llu,0,0\n",
                      qp, b,
                      (unsigned long long)decisionCalls,
                      (unsigned long long)candPossible,
                      (unsigned long long)skipLfnst1,
                      (unsigned long long)skipLfnst2,
                      (unsigned long long)skipTotal,
                      skipRatio,
                      (unsigned long long)candRdoActual,
                      (unsigned long long)candRdoTimeNs,
                      (unsigned long long)( candRdoActual ? candRdoTimeNs / candRdoActual : 0 ),
                      (unsigned long long)candRdoWouldSkip,
                      (unsigned long long)candRdoWouldSkipNs,
                      (unsigned long long)( candRdoWouldSkip ? candRdoWouldSkipNs / candRdoWouldSkip : 0 ) );
      }
    }
    std::fclose( fp );
  }

private:
  std::atomic<bool> m_enabled { false };
  std::mutex        m_mutex;
  std::string       m_fileName;
  Lard2ndCountRow   m_rows[64];
  Lard2ndCountRow   m_sizeRows[64][LARD2ND_AREA_GROUPS];
  Lard2ndCountRow   m_shapeRows[64][LARD2ND_SHAPE_GROUPS];
  Lard2ndCountRow   m_areaShapeRows[64][LARD2ND_AREA_GROUPS][LARD2ND_SHAPE_GROUPS];
  Lard2ndCountRow   m_costRows[64][LARD2ND_COST_BINS];
};

static Lard2ndCountStore& xLard2ndCountStore()
{
  static Lard2ndCountStore s_store;
  return s_store;
}

static bool xLard2ndCountEnabled( const char* fileName )
{
  return xLard2ndCountStore().enable( fileName );
}

struct Lard14CallerCountRow
{
  std::atomic<uint64_t> eligible          { 0 };
  std::atomic<uint64_t> geom              { 0 };
  std::atomic<uint64_t> roiFull           { 0 };
  std::atomic<uint64_t> roiProxy          { 0 };
  std::atomic<uint64_t> total             { 0 };
  std::atomic<uint64_t> featureCalls      { 0 };
  std::atomic<uint64_t> featureTimeNs     { 0 };
  std::atomic<uint64_t> lfnstTotalActual  { 0 };
  std::atomic<uint64_t> lfnstTotalTimeNs  { 0 };
  std::atomic<uint64_t> lfnstIdx0Actual   { 0 };
  std::atomic<uint64_t> lfnstIdx0TimeNs   { 0 };
  std::atomic<uint64_t> lfnstIdx1Actual   { 0 };
  std::atomic<uint64_t> lfnstIdx1TimeNs   { 0 };
  std::atomic<uint64_t> lfnstIdx2Actual   { 0 };
  std::atomic<uint64_t> lfnstIdx2TimeNs   { 0 };
  std::atomic<uint64_t> candRdoActual     { 0 };
  std::atomic<uint64_t> candRdoTimeNs     { 0 };
  std::atomic<uint64_t> candRdoWouldSkip  { 0 };
  std::atomic<uint64_t> candRdoWouldSkipNs{ 0 };
};

struct Lard14CallerLocalTiming
{
  uint64_t idxActual[3] = { 0, 0, 0 };
  uint64_t idxTimeNs[3] = { 0, 0, 0 };
};

static const char* xLard14LatName( const int latBucket )
{
  switch( Clip3( 0, 3, latBucket ) )
  {
  case 0: return "LAT_0_30";
  case 1: return "LAT_30_50";
  case 2: return "LAT_50_70";
  default: return "LAT_70_90";
  }
}

static const char* xLard14FinalName( const int finalIdx )
{
  switch( Clip3( 0, 2, finalIdx ) )
  {
  case 0: return "FINAL_0";
  case 1: return "FINAL_1";
  default: return "FINAL_2";
  }
}

class Lard14CallerCountStore
{
public:
  ~Lard14CallerCountStore()
  {
    flush();
  }

  bool enable( const char* fileName )
  {
    if( !fileName || fileName[0] == '\0' )
    {
      return false;
    }
    if( m_enabled.load( std::memory_order_relaxed ) )
    {
      return true;
    }

    std::lock_guard<std::mutex> lock( m_mutex );
    if( !m_enabled.load( std::memory_order_relaxed ) )
    {
      m_fileName = std::string( fileName ) + ".caller.csv";
      m_enabled.store( true, std::memory_order_relaxed );
    }
    return true;
  }

  Lard14CallerCountRow& row( const int qp )
  {
    return m_rows[Clip3( 0, 63, qp )];
  }

  Lard14CallerCountRow& sizeRow( const int qp, const int area )
  {
    return m_sizeRows[Clip3( 0, 63, qp )][xLard2ndAreaGroup( area )];
  }

  Lard14CallerCountRow& modeRow( const int qp, const int modeGroup )
  {
    return m_modeRows[Clip3( 0, 63, qp )][Clip3( 0, 5, modeGroup )];
  }

  Lard14CallerCountRow& areaModeRow( const int qp, const int area, const int modeGroup )
  {
    return m_areaModeRows[Clip3( 0, 63, qp )][xLard2ndAreaGroup( area )][Clip3( 0, 5, modeGroup )];
  }

  Lard14CallerCountRow& latRow( const int qp, const int latBucket )
  {
    return m_latRows[Clip3( 0, 63, qp )][Clip3( 0, 3, latBucket )];
  }

  Lard14CallerCountRow& finalRow( const int qp, const int finalIdx )
  {
    return m_finalRows[Clip3( 0, 63, qp )][Clip3( 0, 2, finalIdx )];
  }

  void flush()
  {
    if( !m_enabled.load( std::memory_order_relaxed ) || m_fileName.empty() )
    {
      return;
    }

    std::lock_guard<std::mutex> lock( m_mutex );
    FILE* fp = std::fopen( m_fileName.c_str(), "wb" );
    if( !fp )
    {
      return;
    }

    std::fprintf( fp, "qp,group,eligible,geom,roiFull,roiProxy,total,triggerRatio,"
                      "featureCalls,featureTimeNs,avgFeatureNs,"
                      "lfnstTotalActual,lfnstTotalTimeNs,avgLfnstTotalNs,"
                      "lfnstIdx0Actual,lfnstIdx0TimeNs,avgLfnstIdx0Ns,"
                      "lfnstIdx1Actual,lfnstIdx1TimeNs,avgLfnstIdx1Ns,"
                      "lfnstIdx2Actual,lfnstIdx2TimeNs,avgLfnstIdx2Ns,"
                      "candRdoActual,candRdoTimeNs,avgCandRdoNs,"
                      "candRdoWouldSkip,candRdoWouldSkipNs,avgWouldSkipRdoNs\n" );

    auto writeRow = [fp]( const char* qpName, const char* groupName, Lard14CallerCountRow& r )
    {
      const uint64_t eligible           = r.eligible.load( std::memory_order_relaxed );
      const uint64_t geom               = r.geom.load( std::memory_order_relaxed );
      const uint64_t roiFull            = r.roiFull.load( std::memory_order_relaxed );
      const uint64_t roiProxy           = r.roiProxy.load( std::memory_order_relaxed );
      const uint64_t total              = r.total.load( std::memory_order_relaxed );
      const uint64_t featureCalls       = r.featureCalls.load( std::memory_order_relaxed );
      const uint64_t featureTimeNs      = r.featureTimeNs.load( std::memory_order_relaxed );
      const uint64_t lfnstTotalActual   = r.lfnstTotalActual.load( std::memory_order_relaxed );
      const uint64_t lfnstTotalTimeNs   = r.lfnstTotalTimeNs.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx0Actual    = r.lfnstIdx0Actual.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx0TimeNs    = r.lfnstIdx0TimeNs.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx1Actual    = r.lfnstIdx1Actual.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx1TimeNs    = r.lfnstIdx1TimeNs.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx2Actual    = r.lfnstIdx2Actual.load( std::memory_order_relaxed );
      const uint64_t lfnstIdx2TimeNs    = r.lfnstIdx2TimeNs.load( std::memory_order_relaxed );
      const uint64_t candRdoActual      = r.candRdoActual.load( std::memory_order_relaxed );
      const uint64_t candRdoTimeNs      = r.candRdoTimeNs.load( std::memory_order_relaxed );
      const uint64_t candRdoWouldSkip   = r.candRdoWouldSkip.load( std::memory_order_relaxed );
      const uint64_t candRdoWouldSkipNs = r.candRdoWouldSkipNs.load( std::memory_order_relaxed );
      if( eligible == 0 && total == 0 && featureCalls == 0 && lfnstTotalActual == 0 && candRdoActual == 0 && candRdoWouldSkip == 0 )
      {
        return;
      }
      const double triggerRatio = eligible ? (double)total / (double)eligible : 0.0;
      std::fprintf( fp, "%s,%s,%llu,%llu,%llu,%llu,%llu,%.9f,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu,"
                        "%llu,%llu,%llu\n",
                    qpName, groupName,
                    (unsigned long long)eligible,
                    (unsigned long long)geom,
                    (unsigned long long)roiFull,
                    (unsigned long long)roiProxy,
                    (unsigned long long)total,
                    triggerRatio,
                    (unsigned long long)featureCalls,
                    (unsigned long long)featureTimeNs,
                    (unsigned long long)( featureCalls ? featureTimeNs / featureCalls : 0 ),
                    (unsigned long long)lfnstTotalActual,
                    (unsigned long long)lfnstTotalTimeNs,
                    (unsigned long long)( lfnstTotalActual ? lfnstTotalTimeNs / lfnstTotalActual : 0 ),
                    (unsigned long long)lfnstIdx0Actual,
                    (unsigned long long)lfnstIdx0TimeNs,
                    (unsigned long long)( lfnstIdx0Actual ? lfnstIdx0TimeNs / lfnstIdx0Actual : 0 ),
                    (unsigned long long)lfnstIdx1Actual,
                    (unsigned long long)lfnstIdx1TimeNs,
                    (unsigned long long)( lfnstIdx1Actual ? lfnstIdx1TimeNs / lfnstIdx1Actual : 0 ),
                    (unsigned long long)lfnstIdx2Actual,
                    (unsigned long long)lfnstIdx2TimeNs,
                    (unsigned long long)( lfnstIdx2Actual ? lfnstIdx2TimeNs / lfnstIdx2Actual : 0 ),
                    (unsigned long long)candRdoActual,
                    (unsigned long long)candRdoTimeNs,
                    (unsigned long long)( candRdoActual ? candRdoTimeNs / candRdoActual : 0 ),
                    (unsigned long long)candRdoWouldSkip,
                    (unsigned long long)candRdoWouldSkipNs,
                    (unsigned long long)( candRdoWouldSkip ? candRdoWouldSkipNs / candRdoWouldSkip : 0 ) );
    };

    Lard14CallerCountRow totalRow;
    for( int qp = 0; qp <= 63; qp++ )
    {
      char qpName[8];
      std::snprintf( qpName, sizeof( qpName ), "%d", qp );
      writeRow( qpName, "ALL", m_rows[qp] );
      totalRow.eligible.fetch_add( m_rows[qp].eligible.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.geom.fetch_add( m_rows[qp].geom.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.roiFull.fetch_add( m_rows[qp].roiFull.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.roiProxy.fetch_add( m_rows[qp].roiProxy.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.total.fetch_add( m_rows[qp].total.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.featureCalls.fetch_add( m_rows[qp].featureCalls.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.featureTimeNs.fetch_add( m_rows[qp].featureTimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstTotalActual.fetch_add( m_rows[qp].lfnstTotalActual.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstTotalTimeNs.fetch_add( m_rows[qp].lfnstTotalTimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx0Actual.fetch_add( m_rows[qp].lfnstIdx0Actual.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx0TimeNs.fetch_add( m_rows[qp].lfnstIdx0TimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx1Actual.fetch_add( m_rows[qp].lfnstIdx1Actual.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx1TimeNs.fetch_add( m_rows[qp].lfnstIdx1TimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx2Actual.fetch_add( m_rows[qp].lfnstIdx2Actual.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.lfnstIdx2TimeNs.fetch_add( m_rows[qp].lfnstIdx2TimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.candRdoActual.fetch_add( m_rows[qp].candRdoActual.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.candRdoTimeNs.fetch_add( m_rows[qp].candRdoTimeNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.candRdoWouldSkip.fetch_add( m_rows[qp].candRdoWouldSkip.load( std::memory_order_relaxed ), std::memory_order_relaxed );
      totalRow.candRdoWouldSkipNs.fetch_add( m_rows[qp].candRdoWouldSkipNs.load( std::memory_order_relaxed ), std::memory_order_relaxed );
    }
    writeRow( "TOTAL", "ALL", totalRow );

    for( int qp = 0; qp <= 63; qp++ )
    {
      char qpName[8];
      std::snprintf( qpName, sizeof( qpName ), "%d", qp );
      for( int a = 0; a < LARD2ND_AREA_GROUPS; a++ )
      {
        writeRow( qpName, xLard2ndAreaName( a ), m_sizeRows[qp][a] );
      }
      for( int m = 0; m < 6; m++ )
      {
        writeRow( qpName, xLard2ndModeName( m ), m_modeRows[qp][m] );
      }
      for( int a = 0; a < LARD2ND_AREA_GROUPS; a++ )
      {
        for( int m = 0; m < 6; m++ )
        {
          char groupName[48];
          std::snprintf( groupName, sizeof( groupName ), "%s_%s", xLard2ndAreaName( a ), xLard2ndModeName( m ) );
          writeRow( qpName, groupName, m_areaModeRows[qp][a][m] );
        }
      }
      for( int b = 0; b < 4; b++ )
      {
        writeRow( qpName, xLard14LatName( b ), m_latRows[qp][b] );
      }
      for( int f = 0; f < 3; f++ )
      {
        writeRow( qpName, xLard14FinalName( f ), m_finalRows[qp][f] );
      }
    }
    std::fclose( fp );
  }

private:
  std::atomic<bool> m_enabled { false };
  std::mutex        m_mutex;
  std::string       m_fileName;
  Lard14CallerCountRow m_rows[64];
  Lard14CallerCountRow m_sizeRows[64][LARD2ND_AREA_GROUPS];
  Lard14CallerCountRow m_modeRows[64][6];
  Lard14CallerCountRow m_areaModeRows[64][LARD2ND_AREA_GROUPS][6];
  Lard14CallerCountRow m_latRows[64][4];
  Lard14CallerCountRow m_finalRows[64][3];
};

static Lard14CallerCountStore& xLard14CallerCountStore()
{
  static Lard14CallerCountStore s_store;
  return s_store;
}

static bool xLard14CallerCountEnabled( const char* fileName )
{
  return xLard14CallerCountStore().enable( fileName );
}

static void xLard14CallerCountAddGateRow( Lard14CallerCountRow& row, const bool eligible, const bool geom,
                                          const bool roiFull, const bool roiProxy )
{
  if( !eligible )
  {
    return;
  }
  row.eligible.fetch_add( 1, std::memory_order_relaxed );
  if( geom )
  {
    row.geom.fetch_add( 1, std::memory_order_relaxed );
  }
  if( roiFull )
  {
    row.roiFull.fetch_add( 1, std::memory_order_relaxed );
  }
  if( roiProxy )
  {
    row.roiProxy.fetch_add( 1, std::memory_order_relaxed );
  }
  if( geom || roiFull || roiProxy )
  {
    row.total.fetch_add( 1, std::memory_order_relaxed );
  }
}

static void xLard14CallerCountGate( const char* fileName, const int qp, const int width, const int height,
                                    const int modeGroup, const bool eligible, const bool geom,
                                    const bool roiFull, const bool roiProxy )
{
  if( !xLard14CallerCountEnabled( fileName ) || !eligible )
  {
    return;
  }
  const int area = width * height;
  xLard14CallerCountAddGateRow( xLard14CallerCountStore().row( qp ), eligible, geom, roiFull, roiProxy );
  xLard14CallerCountAddGateRow( xLard14CallerCountStore().sizeRow( qp, area ), eligible, geom, roiFull, roiProxy );
  xLard14CallerCountAddGateRow( xLard14CallerCountStore().modeRow( qp, modeGroup ), eligible, geom, roiFull, roiProxy );
  xLard14CallerCountAddGateRow( xLard14CallerCountStore().areaModeRow( qp, area, modeGroup ), eligible, geom, roiFull, roiProxy );
}

static void xLard14CallerCountCandidateRdoRow( Lard14CallerCountRow& row, const uint64_t ns, const bool wouldSkip )
{
  row.lfnstTotalActual.fetch_add( 1, std::memory_order_relaxed );
  row.lfnstTotalTimeNs.fetch_add( ns, std::memory_order_relaxed );
  if( wouldSkip )
  {
    row.candRdoWouldSkip.fetch_add( 1, std::memory_order_relaxed );
    row.candRdoWouldSkipNs.fetch_add( ns, std::memory_order_relaxed );
  }
}

static void xLard14CallerCountCandidateRdo( const char* fileName, const int qp, const int width, const int height,
                                            const int modeGroup, const int latBucket, const int lfnstIdx,
                                            const uint64_t ns, const bool wouldSkip )
{
  if( !xLard14CallerCountEnabled( fileName ) )
  {
    return;
  }
  auto addIdx = [lfnstIdx, ns, wouldSkip]( Lard14CallerCountRow& row )
  {
    xLard14CallerCountCandidateRdoRow( row, ns, wouldSkip );
    if( lfnstIdx == 0 )
    {
      row.lfnstIdx0Actual.fetch_add( 1, std::memory_order_relaxed );
      row.lfnstIdx0TimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
    else if( lfnstIdx == 1 )
    {
      row.lfnstIdx1Actual.fetch_add( 1, std::memory_order_relaxed );
      row.lfnstIdx1TimeNs.fetch_add( ns, std::memory_order_relaxed );
      row.candRdoActual.fetch_add( 1, std::memory_order_relaxed );
      row.candRdoTimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
    else if( lfnstIdx == 2 )
    {
      row.lfnstIdx2Actual.fetch_add( 1, std::memory_order_relaxed );
      row.lfnstIdx2TimeNs.fetch_add( ns, std::memory_order_relaxed );
      row.candRdoActual.fetch_add( 1, std::memory_order_relaxed );
      row.candRdoTimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
  };
  const int area = width * height;
  addIdx( xLard14CallerCountStore().row( qp ) );
  addIdx( xLard14CallerCountStore().sizeRow( qp, area ) );
  addIdx( xLard14CallerCountStore().modeRow( qp, modeGroup ) );
  addIdx( xLard14CallerCountStore().areaModeRow( qp, area, modeGroup ) );
  addIdx( xLard14CallerCountStore().latRow( qp, latBucket ) );
}

static void xLard14CallerCountFeatureRow( Lard14CallerCountRow& row, const uint64_t ns )
{
  row.featureCalls.fetch_add( 1, std::memory_order_relaxed );
  row.featureTimeNs.fetch_add( ns, std::memory_order_relaxed );
}

static void xLard14CallerCountFeature( const char* fileName, const int qp, const int width, const int height,
                                       const int modeGroup, const int latBucket, const uint64_t ns )
{
  if( !xLard14CallerCountEnabled( fileName ) )
  {
    return;
  }
  const int area = width * height;
  xLard14CallerCountFeatureRow( xLard14CallerCountStore().row( qp ), ns );
  xLard14CallerCountFeatureRow( xLard14CallerCountStore().sizeRow( qp, area ), ns );
  xLard14CallerCountFeatureRow( xLard14CallerCountStore().modeRow( qp, modeGroup ), ns );
  xLard14CallerCountFeatureRow( xLard14CallerCountStore().areaModeRow( qp, area, modeGroup ), ns );
  xLard14CallerCountFeatureRow( xLard14CallerCountStore().latRow( qp, latBucket ), ns );
}

static void xLard14CallerCountFinal( const char* fileName, const int qp, const int finalIdx,
                                     const Lard14CallerLocalTiming& local )
{
  if( !xLard14CallerCountEnabled( fileName ) )
  {
    return;
  }
  Lard14CallerCountRow& row = xLard14CallerCountStore().finalRow( qp, finalIdx );
  for( int idx = 0; idx < 3; idx++ )
  {
    const uint64_t count = local.idxActual[idx];
    const uint64_t ns    = local.idxTimeNs[idx];
    row.lfnstTotalActual.fetch_add( count, std::memory_order_relaxed );
    row.lfnstTotalTimeNs.fetch_add( ns, std::memory_order_relaxed );
    if( idx == 0 )
    {
      row.lfnstIdx0Actual.fetch_add( count, std::memory_order_relaxed );
      row.lfnstIdx0TimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
    else if( idx == 1 )
    {
      row.lfnstIdx1Actual.fetch_add( count, std::memory_order_relaxed );
      row.lfnstIdx1TimeNs.fetch_add( ns, std::memory_order_relaxed );
      row.candRdoActual.fetch_add( count, std::memory_order_relaxed );
      row.candRdoTimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
    else
    {
      row.lfnstIdx2Actual.fetch_add( count, std::memory_order_relaxed );
      row.lfnstIdx2TimeNs.fetch_add( ns, std::memory_order_relaxed );
      row.candRdoActual.fetch_add( count, std::memory_order_relaxed );
      row.candRdoTimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
  }
}

static bool xLard2ndPolicyCanApply( const VVEncCfg* cfg, const CodingUnit& cu )
{
  if( !cfg )
  {
    return false;
  }
  const int w = cu.lwidth();
  const int h = cu.lheight();
  const int area = w * h;
  const double aspect = (double)std::max( std::max( 1, w ), std::max( 1, h ) )
                      / (double)std::min( std::max( 1, w ), std::max( 1, h ) );
  const int shapeBit = 1 << xLard2ndShapeGroup( w, h );
  return cu.qp <= cfg->m_LardLfnst2ndMaxCuQp
      && area >= cfg->m_LardLfnst2ndMinArea
      && w >= cfg->m_LardLfnst2ndMinWidth
      && h >= cfg->m_LardLfnst2ndMinHeight
      && aspect <= cfg->m_LardLfnst2ndMaxAspect
      && ( cfg->m_LardLfnst2ndShapeMask & shapeBit ) != 0;
}

static bool xLard11RespPolicyCanApply( const VVEncCfg* cfg, const CodingUnit& cu )
{
  if( !cfg )
  {
    return false;
  }
  return cu.qp <= cfg->m_LardLfnst11MaxCuQp
      && cu.lwidth() * cu.lheight() >= cfg->m_LardLfnst11MinArea
      && cu.lwidth() >= cfg->m_LardLfnst11MinWidth
      && cu.lheight() >= cfg->m_LardLfnst11MinHeight;
}

static int xLard2ndEffectiveHorizontalCols( const int width, const double rawCosLat )
{
  return std::max( 0, (int)std::floor( (double)std::max( 0, width ) * std::max( 0.0, rawCosLat ) ) );
}

static int xLard14EffectiveLfSupportCols( const int width, const int height, const double rawCosLat )
{
  const int uLowFreq = std::min( width, height ) == 4 ? 4 : 8;
  return std::max( 0, (int)std::floor( (double)uLowFreq * std::max( 0.0, rawCosLat ) + 1e-9 ) );
}

static bool xLard14CanUseCallerEarlyDisable( const VVEncCfg* cfg )
{
  return cfg
      && cfg->m_LardLfnstSkip == 14
      && cfg->m_LardLfnst14EarlyDisable != 0
      && cfg->m_LardLfnst2ndMeasureOnly == 0
      && cfg->m_LardLfnst2ndStatFile[0] == '\0'
      && cfg->m_LardLfnst2ndVecFile[0] == '\0'
      && cfg->m_LardLfnst2ndFinalStatFile[0] == '\0';
}

static bool xLard14NoDecisionTrace( const VVEncCfg* cfg )
{
  return cfg
      && cfg->m_LardLfnst2ndMeasureOnly == 0
      && cfg->m_LardLfnst2ndStatFile[0] == '\0'
      && cfg->m_LardLfnst2ndVecFile[0] == '\0'
      && cfg->m_LardLfnst2ndFinalStatFile[0] == '\0'
      && cfg->m_LardLfnst2ndCountFile[0] == '\0';
}

static int xLard14DecisionModeForQp( const VVEncCfg* cfg, const int qp, double* nzMargin = nullptr,
                                     double* rateMargin = nullptr, double* obsGate = nullptr )
{
  if( !cfg )
  {
    return 0;
  }
  int decisionMode = std::min( 3, std::max( 0, cfg->m_LardLfnst14Mode ) );
  double nz = cfg->m_LardLfnst14NzMargin;
  double rate = cfg->m_LardLfnst14RateMargin;
  double obs = cfg->m_LardLfnst14ObsGate;
  if( decisionMode == 3 )
  {
    if( qp <= 21 )
    {
      decisionMode = 2;
      nz = 1.0;
      rate = 0.0;
    }
    else if( qp <= 26 )
    {
      decisionMode = 2;
      nz = 0.5;
      rate = 0.5;
    }
    else if( qp <= 31 )
    {
      decisionMode = 1;
    }
    else
    {
      decisionMode = 0;
    }
    obs = -1.0e9;
  }
  if( nzMargin )
  {
    *nzMargin = nz;
  }
  if( rateMargin )
  {
    *rateMargin = rate;
  }
  if( obsGate )
  {
    *obsGate = obs;
  }
  return decisionMode;
}

static int xLard19DecisionMask( const int profile, const int mh, const double gain1, const double gain2,
                                const double nz0, const double nz1, const double nz2,
                                const double singleMargin, const double zeroMargin )
{
  if( mh < 2 )
  {
    return 0x1;
  }
  if( profile <= 0 )
  {
    return 0x7;
  }
  if( profile >= 3
   && gain1 <= -zeroMargin
   && gain2 <= -zeroMargin
   && nz1 >= nz0 && nz2 >= nz0 )
  {
    return 0x1;
  }

  const double margin = std::max( 0.0, singleMargin );
  if( gain1 - gain2 >= margin && nz1 <= nz2 )
  {
    return 0x3;
  }
  if( gain2 - gain1 >= margin && nz2 <= nz1 )
  {
    return 0x5;
  }
  return 0x7;
}

static int xLard19QpScheduleMode( const int qp, double& nzMargin, double& rateMargin )
{
  if( qp <= 21 )
  {
    nzMargin = 1.0;
    rateMargin = 0.0;
    return 2;
  }
  if( qp <= 26 )
  {
    nzMargin = 0.5;
    rateMargin = 0.5;
    return 2;
  }
  if( qp <= 31 )
  {
    return 1;
  }
  return 0;
}

static int xLard2ndEffColsMinForQp( const VVEncCfg* cfg, const int qp )
{
  if( !cfg )
  {
    return 0;
  }
  const int q = Clip3( 0, 63, qp );
  const int qpMin = q <= 24 ? cfg->m_LardLfnst2ndEffColsMinQp22
                  : q <= 29 ? cfg->m_LardLfnst2ndEffColsMinQp27
                  : q <= 34 ? cfg->m_LardLfnst2ndEffColsMinQp32
                            : cfg->m_LardLfnst2ndEffColsMinQp37;
  return qpMin >= 0 ? qpMin : cfg->m_LardLfnst2ndEffColsMin;
}

static void xLard2ndCountPolicyReject( const char* fileName, const int qp, const bool rejectQp, const bool rejectArea )
{
  if( !xLard2ndCountEnabled( fileName ) )
  {
    return;
  }
  Lard2ndCountRow& row = xLard2ndCountStore().row( qp );
  if( rejectQp )
  {
    row.policyRejectQp.fetch_add( 1, std::memory_order_relaxed );
  }
  if( rejectArea )
  {
    row.policyRejectArea.fetch_add( 1, std::memory_order_relaxed );
  }
}

static void xLard2ndCountLowCostReject( const char* fileName, const int qp )
{
  if( xLard2ndCountEnabled( fileName ) )
  {
    xLard2ndCountStore().row( qp ).lowCostReject.fetch_add( 1, std::memory_order_relaxed );
  }
}

static void xLard2ndCountCandidateMaskRow( Lard2ndCountRow& row, const int mask, const int startLfnstIdx, const int endLfnstIdx )
{
  for( int idx = std::max( 1, startLfnstIdx ); idx <= std::min( 2, endLfnstIdx ); idx++ )
  {
    row.candPossible.fetch_add( 1, std::memory_order_relaxed );
    if( !( mask & ( 1 << idx ) ) )
    {
      ( idx == 1 ? row.skipLfnst1 : row.skipLfnst2 ).fetch_add( 1, std::memory_order_relaxed );
    }
  }
}

static void xLard2ndCountCandidateMask( const char* fileName, const int qp, const int width, const int height,
                                        const int mask, const int startLfnstIdx, const int endLfnstIdx )
{
  if( !xLard2ndCountEnabled( fileName ) )
  {
    return;
  }

  Lard2ndCountRow& row = xLard2ndCountStore().row( qp );
  xLard2ndCountCandidateMaskRow( row, mask, startLfnstIdx, endLfnstIdx );

  const int area = width * height;
  Lard2ndCountRow& shapeRow = xLard2ndCountStore().shapeRow( qp, width, height );
  xLard2ndCountCandidateMaskRow( shapeRow, mask, startLfnstIdx, endLfnstIdx );
  Lard2ndCountRow& areaShapeRow = xLard2ndCountStore().areaShapeRow( qp, area, width, height );
  xLard2ndCountCandidateMaskRow( areaShapeRow, mask, startLfnstIdx, endLfnstIdx );
}

static void xLard2ndCountCostDecision( const char* fileName, const int qp, const int costBin, const int mask, const int startLfnstIdx, const int endLfnstIdx )
{
  if( !xLard2ndCountEnabled( fileName ) )
  {
    return;
  }

  Lard2ndCountRow& row = xLard2ndCountStore().costRow( qp, costBin );
  row.decisionCalls.fetch_add( 1, std::memory_order_relaxed );
  for( int idx = std::max( 1, startLfnstIdx ); idx <= std::min( 2, endLfnstIdx ); idx++ )
  {
    row.candPossible.fetch_add( 1, std::memory_order_relaxed );
    if( !( mask & ( 1 << idx ) ) )
    {
      ( idx == 1 ? row.skipLfnst1 : row.skipLfnst2 ).fetch_add( 1, std::memory_order_relaxed );
    }
  }
}

static void xLard2ndCountCandidateRdoRow( Lard2ndCountRow& row, const uint64_t ns, const bool wouldSkip )
{
  row.candRdoActual.fetch_add( 1, std::memory_order_relaxed );
  row.candRdoTimeNs.fetch_add( ns, std::memory_order_relaxed );
  if( wouldSkip )
  {
    row.candRdoWouldSkip.fetch_add( 1, std::memory_order_relaxed );
    row.candRdoWouldSkipNs.fetch_add( ns, std::memory_order_relaxed );
  }
}

static void xLard2ndCountCandidateRdo( const char* fileName, const int qp, const int width, const int height,
                                       const int costBin, const uint64_t ns, const bool wouldSkip )
{
  if( !xLard2ndCountEnabled( fileName ) )
  {
    return;
  }

  const int area = width * height;
  Lard2ndCountRow& row = xLard2ndCountStore().row( qp );
  xLard2ndCountCandidateRdoRow( row, ns, wouldSkip );

  Lard2ndCountRow& sizeRow = xLard2ndCountStore().sizeRow( qp, area );
  xLard2ndCountCandidateRdoRow( sizeRow, ns, wouldSkip );

  Lard2ndCountRow& shapeRow = xLard2ndCountStore().shapeRow( qp, width, height );
  xLard2ndCountCandidateRdoRow( shapeRow, ns, wouldSkip );

  Lard2ndCountRow& areaShapeRow = xLard2ndCountStore().areaShapeRow( qp, area, width, height );
  xLard2ndCountCandidateRdoRow( areaShapeRow, ns, wouldSkip );

  Lard2ndCountRow& costRow = xLard2ndCountStore().costRow( qp, costBin );
  xLard2ndCountCandidateRdoRow( costRow, ns, wouldSkip );
}

class Lard2ndCountScope
{
public:
  Lard2ndCountScope( const char* fileName, const int qp )
    : m_enabled( xLard2ndCountEnabled( fileName ) ), m_qp( Clip3( 0, 63, qp ) )
  {
    if( m_enabled )
    {
      xLard2ndCountStore().row( m_qp ).decisionCalls.fetch_add( 1, std::memory_order_relaxed );
      m_start = std::chrono::steady_clock::now();
    }
  }

  ~Lard2ndCountScope()
  {
    if( m_enabled )
    {
      const auto end = std::chrono::steady_clock::now();
      const uint64_t ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( end - m_start ).count();
      xLard2ndCountStore().row( m_qp ).decisionTimeNs.fetch_add( ns, std::memory_order_relaxed );
    }
  }

  bool enabled() const { return m_enabled; }
  Lard2ndCountRow& row() const { return xLard2ndCountStore().row( m_qp ); }

private:
  bool m_enabled;
  int  m_qp;
  std::chrono::steady_clock::time_point m_start;
};

static void xLard2ndAppendVec( const char* fileName, const CodingUnit& cu, const int intraMode, const int lfnstSet,
                               const int sbSize, const int zeroOutSize, const int trSize, const bool transposeFlag,
                               const double absLatDeg, const double thetaMaxDeg, const double inputEnergy,
                               const double* input )
{
  if( !fileName || fileName[0] == '\0' || !input )
  {
    return;
  }

  static FILE* s_vecFp = nullptr;
  static std::string s_vecName;
  static std::mutex s_vecMutex;

  std::lock_guard<std::mutex> lock( s_vecMutex );

  if( s_vecFp && s_vecName != fileName )
  {
    std::fclose( s_vecFp );
    s_vecFp = nullptr;
    s_vecName.clear();
  }

  bool writeHeader = false;
  if( !s_vecFp )
  {
    if( FILE* fpRead = std::fopen( fileName, "rb" ) )
    {
      std::fseek( fpRead, 0, SEEK_END );
      writeHeader = std::ftell( fpRead ) == 0;
      std::fclose( fpRead );
    }
    else
    {
      writeHeader = true;
    }

    s_vecFp = std::fopen( fileName, "ab" );
    if( !s_vecFp )
    {
      return;
    }
    s_vecName = fileName;
  }

  if( writeHeader )
  {
    std::fprintf( s_vecFp, "poc,x,y,w,h,qp,intraMode,lfnstSet,sbSize,zeroOutSize,trSize,transposeFlag,absLatDeg,thetaMaxDeg,modeGroup,sizeGroup,latBucket,sbClass,inputEnergy" );
    for( int i = 0; i < 48; i++ )
    {
      std::fprintf( s_vecFp, ",x%02d", i );
    }
    std::fprintf( s_vecFp, "\n" );
  }

  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  const int modeGroup = xLahtpModeGroupId( cu.intraDir[CH_L] );
  const int sizeGroup = xLahtpSizeGroupId( cu.lwidth(), cu.lheight() );
  const int latBucket = xLardLfnstLatBucketId( absLatDeg );
  const int sbClass   = sbSize > 4 ? 1 : 0;
  std::fprintf( s_vecFp,
                "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.6f,%.6f,%d,%d,%d,%d,%.9g",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, intraMode, lfnstSet,
                sbSize, zeroOutSize, trSize, transposeFlag ? 1 : 0, absLatDeg, thetaMaxDeg,
                modeGroup, sizeGroup, latBucket, sbClass, inputEnergy );
  for( int i = 0; i < 48; i++ )
  {
    std::fprintf( s_vecFp, ",%.9g", i < trSize ? input[i] : 0.0 );
  }
  std::fprintf( s_vecFp, "\n" );
}
#endif

static const LahtpFitParams* xLahtpFindFitParams( const LahtpFitParams* table, const int numEntries, const int qp, const int w, const int h, const int mode )
{
  const int sizeGroup = xLahtpSizeGroupId( w, h );
  const int modeGroup = xLahtpModeGroupId( mode );
  const LahtpFitParams* best = nullptr;
  int bestQpDist = 128;

  for( int i = 0; i < numEntries; i++ )
  {
    const LahtpFitParams& p = table[i];
    if( p.sizeGroup != sizeGroup || p.modeGroup != modeGroup )
    {
      continue;
    }
    const int qpDist = std::abs( p.qp - qp );
    if( qpDist < bestQpDist )
    {
      best = &p;
      bestQpDist = qpDist;
    }
  }

  return best;
}

void IntraSearch::xLahtpAppendTrace( const CodingUnit& cu, const LahtpFeatures& f,
                                     const int modeId, const int lfnstIdx, const int mtsIdx, const double cost,
                                     const uint64_t fracBits, const Distortion dist, const uint32_t numSig,
                                     const uint32_t nonZero, const int lastPos, const double absSum,
                                     const bool pruned ) const
{
  const char* fileName = m_pcEncCfg ? m_pcEncCfg->m_LardLfnstTraceFile : nullptr;
  if( !fileName || fileName[0] == '\0' )
  {
    return;
  }

  static FILE* s_traceFp = nullptr;
  static std::string s_traceName;
  static std::mutex s_traceMutex;

  std::lock_guard<std::mutex> lock( s_traceMutex );

  if( s_traceFp && s_traceName != fileName )
  {
    std::fclose( s_traceFp );
    s_traceFp = nullptr;
    s_traceName.clear();
  }

  bool writeHeader = false;
  if( !s_traceFp )
  {
    if( FILE* fpRead = std::fopen( fileName, "rb" ) )
    {
      std::fseek( fpRead, 0, SEEK_END );
      writeHeader = std::ftell( fpRead ) == 0;
      std::fclose( fpRead );
    }
    else
    {
      writeHeader = true;
    }

    s_traceFp = std::fopen( fileName, "ab" );
    if( !s_traceFp )
    {
      return;
    }
    s_traceName = fileName;
  }

  if( writeHeader )
  {
    std::fprintf( s_traceFp, "poc,x,y,w,h,qp,intraMode,lfnstIdx,mtsIdx,cost,fracBits,dist,numSig,nonZero,lastPos,absSum,corrProxy,absLatDeg,thetaMaxDeg,thetaSkipDeg,etaHigh,roiEnergyQ,lfRatio,predNz,meanAbsQ,horzRatio,stage1,stage2,lfnstPruned,specSide" );
    for( int i = 0; i < 64; i++ )
    {
      std::fprintf( s_traceFp, ",spec%02d", i );
    }
    std::fprintf( s_traceFp, ",roiDim" );
    for( int i = 0; i < 48; i++ )
    {
      std::fprintf( s_traceFp, ",roiRaw%02d", i );
    }
    for( int i = 0; i < 48; i++ )
    {
      std::fprintf( s_traceFp, ",roiQ%02d", i );
    }
    std::fprintf( s_traceFp, "\n" );
  }

  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  std::fprintf( s_traceFp,
                "%d,%d,%d,%d,%d,%d,%d,%d,%d,%.9g,%llu,%llu,%u,%u,%d,%.9g,%.9g,%.6f,%.6f,%.6f,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%d,%d,%d",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, modeId,
                lfnstIdx, mtsIdx, cost, (unsigned long long)fracBits, (unsigned long long)dist, numSig, nonZero, lastPos, absSum, f.corrProxy,
                f.absLatDeg, f.thetaMaxDeg, f.thetaSkipDeg, f.etaHigh, f.roiEnergyQ, f.lfRatio,
                f.predNz, f.meanAbsQ, f.horzRatio, f.stage1 ? 1 : 0, f.stage2 ? 1 : 0, pruned ? 1 : 0, f.specSide );
  const bool writeFeatureVectors = lfnstIdx == 0 && mtsIdx == 0;
  for( int i = 0; i < 64; i++ )
  {
    if( writeFeatureVectors )
    {
      std::fprintf( s_traceFp, ",%.9g", f.specEnergy[i] );
    }
    else
    {
      std::fprintf( s_traceFp, "," );
    }
  }
  if( writeFeatureVectors )
  {
    std::fprintf( s_traceFp, ",%d", f.roiDim );
  }
  else
  {
    std::fprintf( s_traceFp, "," );
  }
  for( int i = 0; i < 48; i++ )
  {
    if( writeFeatureVectors )
    {
      std::fprintf( s_traceFp, ",%.9g", f.roiRaw[i] );
    }
    else
    {
      std::fprintf( s_traceFp, "," );
    }
  }
  for( int i = 0; i < 48; i++ )
  {
    if( writeFeatureVectors )
    {
      std::fprintf( s_traceFp, ",%.9g", f.roiQ[i] );
    }
    else
    {
      std::fprintf( s_traceFp, "," );
    }
  }
  std::fprintf( s_traceFp, "\n" );
}

IntraSearch::LahtpFeatures IntraSearch::xGetLahtpFeatures( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred ) const
{
  LahtpFeatures f;
  f.absLatDeg    = 0.0;
  f.thetaMaxDeg  = 0.0;
  f.thetaSkipDeg = 90.0;
  f.cosLat       = 1.0;
  f.rawCosLat    = 1.0;
  f.etaHigh      = 1.0;
  f.roiEnergyQ   = 0.0;
  f.lfRatio      = 0.0;
  f.predNz       = 48.0;
  f.meanAbsQ     = 999.0;
  f.horzRatio    = 1.0;
  f.corrProxy    = 0.0;
  f.specSide     = 0;
  f.roiDim       = 0;
  f.stage1       = false;
  f.stage2       = false;
  for( int i = 0; i < 64; i++ )
  {
    f.specEnergy[i] = 0.0;
  }
  for( int i = 0; i < 48; i++ )
  {
    f.roiRaw[i] = 0.0;
    f.roiQ[i]   = 0.0;
  }

#if !VVENC_LAHTP_ENABLE
  return f;
#else
  const bool traceEnabled = m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstTraceFile[0] != '\0'
                                        || m_pcEncCfg->m_LardLfnst2ndVecFile[0] != '\0' );
  const bool lard14EarlyRoiGate = m_pcEncCfg
                               && m_pcEncCfg->m_LardLfnstSkip == 14
                               && m_pcEncCfg->m_LardLfnst14EarlyRoiGate == 1;
  if( !m_pcEncCfg || ( m_pcEncCfg->m_LardLfnstSkip <= 0 && !traceEnabled ) )
  {
    return f;
  }
  const bool zeroFeatureVectors = m_pcEncCfg->m_LardLfnstTraceFile[0] != '\0';
  const CompArea& area = cu.Y();
  const int w = (int)area.width;
  const int h = (int)area.height;

  if( w <= 0 || h <= 0 || org.buf == nullptr || pred.buf == nullptr )
  {
    return f;
  }

  const double pi = 3.14159265358979323846;

  int picH = area.y + h;
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }
  picH = std::max( 1, picH );

  const LahtpStage1Geom geom = xLahtpStage1GeomCached( picH, area.y, h );
  const double thetaMax = geom.thetaMaxRad;
  f.absLatDeg   = geom.absLatDeg;
  f.thetaMaxDeg = geom.thetaMaxDeg;
  f.cosLat      = geom.cosLat;
  f.rawCosLat   = geom.rawCosLat;
  const double thetaSkip = xLahtpStage1ThetaSkipCached( m_pcEncCfg, cu.qp );
  const LahtpFitParams* fitParams = nullptr;

  f.thetaSkipDeg = thetaSkip * 180.0 / pi;
  f.stage1 = thetaMax >= thetaSkip;
  if( m_pcEncCfg->m_LardLfnstSkip == 4 )
  {
    f.stage2 = f.stage1;
    return f;
  }
  if( m_pcEncCfg->m_LardLfnstSkip >= 6 && !lard14EarlyRoiGate && !traceEnabled )
  {
    return f;
  }
  if( !f.stage1 && !traceEnabled )
  {
    return f;
  }

  if( m_pcEncCfg->m_LardLfnstSkip == 2 )
  {
    fitParams = xLahtpFindFitParams( g_lardLfnstFitTable, (int)( sizeof( g_lardLfnstFitTable ) / sizeof( g_lardLfnstFitTable[0] ) ), cu.qp, w, h, cu.intraDir[CH_L] );
  }
  else if( m_pcEncCfg->m_LardLfnstSkip >= 3 )
  {
    fitParams = xLahtpFindFitParams( g_lardLfnstSpeedTable, (int)( sizeof( g_lardLfnstSpeedTable ) / sizeof( g_lardLfnstSpeedTable[0] ) ), cu.qp, w, h, cu.intraDir[CH_L] );
  }

  const double qStep = std::max( 1e-6, xLahtpQStepCached( cu.qp ) );
  const double tq = std::max( 1e-9, m_pcEncCfg->m_LardLfnstTqKappa * qStep );
  const double tanTheta = std::tan( std::min( thetaMax, 1.45 ) );
  const double psi = std::max( 0.0, m_pcEncCfg->m_LardLfnstPsi );
  const double u0 = std::max( 1e-6, m_pcEncCfg->m_LardLfnstU0 );

  const int roiSide = ( w >= 8 && h >= 8 ) ? 8 : 4;
  const int maxRoi = ( roiSide == 8 ) ? 48 : 16;
  f.specSide = roiSide;
  if( !zeroFeatureVectors )
  {
    for( int i = 0; i < 64; i++ )
    {
      f.specEnergy[i] = 0.0;
    }
    for( int i = 0; i < 48; i++ )
    {
      f.roiRaw[i] = 0.0;
      f.roiQ[i] = 0.0;
    }
  }

  double roiEnergy = 0.0;
  double lfEnergy  = 0.0;
  double predNz    = 0.0;
  double meanAbs   = 0.0;
  double sumH      = 0.0;
  double sumV      = 0.0;
  int    coeffCnt  = 0;
  int    pixCnt    = 0;

  for( int y = 0; y < h; y++ )
  {
    const Pel* orgLine  = org.buf  + y * org.stride;
    const Pel* predLine = pred.buf + y * pred.stride;

    for( int x = 0; x < w; x++ )
    {
      const int r = (int)orgLine[x] - (int)predLine[x];
      meanAbs += std::fabs( (double)r );
      pixCnt++;

      if( traceEnabled && x > 0 )
      {
        const int rL = (int)orgLine[x - 1] - (int)predLine[x - 1];
        sumH += std::fabs( (double)( r - rL ) );
      }
      if( traceEnabled && y > 0 )
      {
        const Pel* orgPrev  = org.buf  + ( y - 1 ) * org.stride;
        const Pel* predPrev = pred.buf + ( y - 1 ) * pred.stride;
        const int rU = (int)orgPrev[x] - (int)predPrev[x];
        sumV += std::fabs( (double)( r - rU ) );
      }
    }
  }

  f.meanAbsQ  = ( meanAbs / (double)std::max( 1, pixCnt ) ) / qStep;
  f.horzRatio = traceEnabled ? sumH / ( sumH + sumV + 1e-9 ) : 0.0;

  if( !traceEnabled && m_pcEncCfg->m_LardLfnstMeanAbsQGate > 0.0 && f.meanAbsQ > m_pcEncCfg->m_LardLfnstMeanAbsQGate )
  {
    return f;
  }

  for( int v = 0; v < roiSide; v++ )
  {
    for( int u = 0; u < roiSide; u++ )
    {
      if( roiSide == 8 && u >= 4 && v >= 4 )
      {
        continue;
      }

      double coeff = 0.0;
      for( int y = 0; y < h; y++ )
      {
        const Pel* orgLine  = org.buf  + y * org.stride;
        const Pel* predLine = pred.buf + y * pred.stride;
        const double basisY = std::cos( pi * ( (double)y + 0.5 ) * (double)v / (double)h );

        for( int x = 0; x < w; x++ )
        {
          const double basisX = std::cos( pi * ( (double)x + 0.5 ) * (double)u / (double)w );
          coeff += (double)( (int)orgLine[x] - (int)predLine[x] ) * basisX * basisY;
        }
      }

      const double normX = ( u == 0 ) ? std::sqrt( 1.0 / (double)w ) : std::sqrt( 2.0 / (double)w );
      const double normY = ( v == 0 ) ? std::sqrt( 1.0 / (double)h ) : std::sqrt( 2.0 / (double)h );
      coeff *= normX * normY;
      f.specEnergy[v * 8 + u] = coeff * coeff;
      if( coeffCnt < 48 )
      {
        f.roiRaw[coeffCnt] = coeff;
        f.roiQ[coeffCnt] = coeff / qStep;
      }

      const double eta = std::exp( -psi * ( (double)u / u0 ) * ( (double)u / u0 ) * tanTheta * tanTheta );
      const double effVar = coeff * coeff * eta;
      const double b = std::sqrt( std::max( 0.0, effVar ) * 0.5 );
      const double pNz = b > 1e-9 ? std::exp( -tq / b ) : 0.0;

      roiEnergy += coeff * coeff;
      predNz += xLahtpClipD( 0.0, 1.0, pNz );
      coeffCnt++;

      if( u <= 1 && v <= 1 )
      {
        lfEnergy += coeff * coeff;
      }
    }
  }

  f.etaHigh    = std::exp( -psi * ( (double)( roiSide - 1 ) / u0 ) * ( (double)( roiSide - 1 ) / u0 ) * tanTheta * tanTheta );
  f.roiEnergyQ = roiEnergy / ( qStep * qStep * (double)std::max( 1, coeffCnt ) );
  f.lfRatio    = lfEnergy / ( roiEnergy + 1e-9 );
  f.predNz     = predNz * (double)maxRoi / (double)std::max( 1, coeffCnt );
  f.roiDim     = coeffCnt;
  f.corrProxy  = xLahtpCorrProxyFromRoi( f.roiQ, f.roiDim );

  double energyThr = m_pcEncCfg->m_LardLfnstEnergyThr;
  double lfThr     = m_pcEncCfg->m_LardLfnstLfRatioThr;
  double nzThr     = m_pcEncCfg->m_LardLfnstNzThr;
  if( fitParams && m_pcEncCfg->m_LardLfnstSkip >= 2 )
  {
    energyThr = fitParams->energyThr;
    lfThr     = fitParams->lfRatioThr;
    nzThr     = fitParams->nzThr;
  }

  f.stage2 = ( f.roiEnergyQ < energyThr )
          && ( f.lfRatio    > lfThr )
          && ( f.predNz     < nzThr );

  return f;
#endif
}

IntraSearch::LahtpStage1Decision IntraSearch::xGetLahtpStage1Decision( const CodingUnit& cu ) const
{
  LahtpStage1Decision d;

#if !VVENC_LAHTP_ENABLE
  return d;
#else
  const bool secondResponseStatsOnly = m_pcEncCfg
                                    && m_pcEncCfg->m_LardLfnstSkip == 0
                                    && m_pcEncCfg->m_LardLfnst2ndMeasureOnly != 0
                                    && m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] != '\0';
  if( !m_pcEncCfg || ( m_pcEncCfg->m_LardLfnstSkip <= 0 && !secondResponseStatsOnly ) )
  {
    return d;
  }

  const CompArea& area = cu.Y();
  const int h = (int)area.height;
  if( h <= 0 )
  {
    return d;
  }

  int picH = area.y + h;
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }

  const LahtpStage1Geom geom = xLahtpStage1GeomCached( picH, area.y, h );
  const double thetaSkip = xLahtpStage1ThetaSkipCached( m_pcEncCfg, cu.qp );

  d.absLatDeg    = geom.absLatDeg;
  d.thetaMaxDeg  = geom.thetaMaxDeg;
  d.thetaSkipDeg = thetaSkip * 180.0 / 3.14159265358979323846;
  d.cosLat       = geom.cosLat;
  d.rawCosLat    = geom.rawCosLat;
  d.stage1       = geom.thetaMaxRad >= thetaSkip;
  return d;
#endif
}

bool IntraSearch::xLahtpCanApply( const CodingUnit& cu, const int modeIdx ) const
{
#if !VVENC_LAHTP_ENABLE
  return false;
#else
  if( !m_pcEncCfg || m_pcEncCfg->m_LardLfnstSkip <= 0 )
  {
    return false;
  }

  if( modeIdx < 0 )
  {
    return false;
  }

  if( cu.ispMode || cu.mipFlag || cu.multiRefIdx || cu.bdpcmM[CH_L] )
  {
    return false;
  }

  const int w = cu.lwidth();
  const int h = cu.lheight();
  const int area = w * h;

  if( area < 16 || w < 4 || h < 4 )
  {
    return false;
  }

  if( w > 4 * h || h > 4 * w )
  {
    return false;
  }

  return true;
#endif
}

bool IntraSearch::xLahtpDisableMTS( const CodingUnit& cu, const LahtpFeatures& f ) const
{
#if !VVENC_LAHTP_ENABLE
  return false;
#else
  (void)cu;
  (void)f;
  return false;
#endif
}

bool IntraSearch::xLahtpDisableLFNST( const CodingUnit& cu, const LahtpFeatures& f ) const
{
#if !VVENC_LAHTP_ENABLE
  return false;
#else
  if( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 14 )
  {
    return false;
  }
  if( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 9 )
  {
#if VVENC_LARD_LFNST_GAIN_PRED_ENABLE
    const int key = xLardLfnstModePackKey( cu.qp,
                                           xLahtpSizeGroupId( cu.lwidth(), cu.lheight() ),
                                           xLahtpModeGroupId( cu.intraDir[CH_L] ),
                                           xLardLfnstLatBucketId( f.absLatDeg ) );
    if( xLardLfnstFindModeSkipParams( key ) )
    {
      return true;
    }
#endif
  }
  return f.stage1 && f.stage2;
#endif
}

bool IntraSearch::xLard14EarlyRoiDisable( const LahtpFeatures& f ) const
{
  if( !m_pcEncCfg || m_pcEncCfg->m_LardLfnstSkip != 14 || m_pcEncCfg->m_LardLfnst14EarlyRoiGate == 0 )
  {
    return false;
  }

  return f.stage1
      && f.roiDim > 0
      && f.roiEnergyQ <= m_pcEncCfg->m_LardLfnst14EarlyRoiMax
      && f.predNz     <= m_pcEncCfg->m_LardLfnst14EarlyNzMax
      && f.lfRatio    >= m_pcEncCfg->m_LardLfnst14EarlyLfMin
      && f.corrProxy  <= m_pcEncCfg->m_LardLfnst14EarlyCorrMax
      && f.meanAbsQ   <= m_pcEncCfg->m_LardLfnst14EarlyMeanAbsMax;
}

IntraSearch::Lard14EarlyProxyDecision IntraSearch::xLard14EarlyRoiProxyDecision( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred, const LahtpFeatures& f ) const
{
  Lard14EarlyProxyDecision d;
#if !VVENC_LAHTP_ENABLE
  return d;
#else
  if( !m_pcEncCfg || m_pcEncCfg->m_LardLfnstSkip != 14 || m_pcEncCfg->m_LardLfnst14EarlyRoiGate < 2 || !f.stage1 )
  {
    return d;
  }

  const CompArea& area = cu.Y();
  const int w = (int)area.width;
  const int h = (int)area.height;
  if( w <= 0 || h <= 0 || org.buf == nullptr || pred.buf == nullptr )
  {
    return d;
  }

  const double qStep = std::max( 1e-6, xLahtpQStepCached( cu.qp ) );
  double dc = 0.0;
  double hx = 0.0;
  double vy = 0.0;
  double hv = 0.0;
  double sumSq = 0.0;
  double meanAbs = 0.0;
  const double invW = 1.0 / (double)w;
  const double invH = 1.0 / (double)h;

  for( int y = 0; y < h; y++ )
  {
    const Pel* orgLine  = org.buf  + y * org.stride;
    const Pel* predLine = pred.buf + y * pred.stride;
    const double by = ( (double)( 2 * y + 1 ) * invH ) - 1.0;
    for( int x = 0; x < w; x++ )
    {
      const double r = (double)( (int)orgLine[x] - (int)predLine[x] );
      const double bx = ( (double)( 2 * x + 1 ) * invW ) - 1.0;
      dc += r;
      hx += r * bx;
      vy += r * by;
      hv += r * bx * by;
      sumSq += r * r;
      meanAbs += std::fabs( r );
    }
  }

  const double areaD = (double)std::max( 1, w * h );
  const double q2 = qStep * qStep;
  const double c0 = dc / std::sqrt( areaD );
  const double c1 = hx * std::sqrt( 3.0 / areaD );
  const double c2 = vy * std::sqrt( 3.0 / areaD );
  const double c3 = hv * ( 3.0 / std::sqrt( areaD ) );
  const double lowEnergy = c0 * c0 + c1 * c1 + c2 * c2 + c3 * c3;
  const double roiEnergyQ = lowEnergy / ( 4.0 * q2 + 1e-9 );
  const double lfRatio = lowEnergy / ( sumSq + 1e-9 );
  const double meanAbsQ = ( meanAbs / areaD ) / qStep;
  const double predNz = ( std::fabs( c0 ) > 0.5 * qStep ? 1.0 : 0.0 )
                      + ( std::fabs( c1 ) > 0.5 * qStep ? 1.0 : 0.0 )
                      + ( std::fabs( c2 ) > 0.5 * qStep ? 1.0 : 0.0 )
                      + ( std::fabs( c3 ) > 0.5 * qStep ? 1.0 : 0.0 );
  const double corrProxy = ( std::fabs( c1 * c2 ) + std::fabs( c1 * c3 ) + std::fabs( c2 * c3 ) )
                         / ( lowEnergy + 1e-9 );

  d.valid = true;
  d.roiEnergyQ = roiEnergyQ;
  d.predNz = predNz;
  d.lfRatio = lfRatio;
  d.corrProxy = corrProxy;
  d.meanAbsQ = meanAbsQ;
  if( m_pcEncCfg->m_LardLfnst14EarlyRoiGate == 2 )
  {
    d.skip = roiEnergyQ <= m_pcEncCfg->m_LardLfnst14EarlyRoiMax
          && predNz     <= m_pcEncCfg->m_LardLfnst14EarlyNzMax
          && lfRatio    >= m_pcEncCfg->m_LardLfnst14EarlyLfMin
          && corrProxy  <= m_pcEncCfg->m_LardLfnst14EarlyCorrMax
          && meanAbsQ   <= m_pcEncCfg->m_LardLfnst14EarlyMeanAbsMax;
  }
  else
  {
    const int mh = xLard14EffectiveLfSupportCols( w, h, f.rawCosLat );
    const int areaGroup = xLard2ndAreaGroup( w * h );
    const int modeGroup = xLahtpModeGroupId( cu.intraDir[CH_L] );
    const bool g1 = roiEnergyQ <= m_pcEncCfg->m_LardLfnst14EarlyRoiMax
                 && predNz     <= std::min( 1.0, m_pcEncCfg->m_LardLfnst14EarlyNzMax )
                 && meanAbsQ   <= m_pcEncCfg->m_LardLfnst14EarlyMeanAbsMax;
    const bool highCostBin = cu.qp >= 27 && cu.qp <= 31
                          && ( areaGroup == 1 || areaGroup == 2 )
                          && modeGroup >= 2;
    int weakCount = 0;
    weakCount += mh <= 4 ? 1 : 0;
    weakCount += roiEnergyQ <= m_pcEncCfg->m_LardLfnst14EarlyRoiMax ? 1 : 0;
    weakCount += predNz     <= m_pcEncCfg->m_LardLfnst14EarlyNzMax  ? 1 : 0;
    weakCount += lfRatio    >= m_pcEncCfg->m_LardLfnst14EarlyLfMin  ? 1 : 0;
    weakCount += corrProxy  <= m_pcEncCfg->m_LardLfnst14EarlyCorrMax ? 1 : 0;
    weakCount += meanAbsQ   <= m_pcEncCfg->m_LardLfnst14EarlyMeanAbsMax ? 1 : 0;
    d.skip = g1 || ( highCostBin && weakCount >= 3 );
  }
  return d;
#endif
}

bool IntraSearch::xLard14EarlyRoiProxyDisable( const CodingUnit& cu, const CPelBuf& org, const PelBuf& pred, const LahtpFeatures& f ) const
{
  return xLard14EarlyRoiProxyDecision( cu, org, pred, f ).skip;
}

bool IntraSearch::xLahtpCheckQuantRoi( const CodingUnit& cu, const TransformUnit& tu, LahtpFeatures& f ) const
{
#if !VVENC_LAHTP_ENABLE
  return false;
#else
  if( !m_pcEncCfg )
  {
    return false;
  }

  const CompArea& area = tu.blocks[COMP_Y];
  const int w = (int)area.width;
  const int h = (int)area.height;
  if( w < 4 || h < 4 )
  {
    return false;
  }

  const CCoeffSigBuf coeff = tu.getCoeffs( COMP_Y );
  const int roiSide = ( w >= 8 && h >= 8 ) ? 8 : 4;

  double roiEnergy = 0.0;
  double lfEnergy = 0.0;
  double nnz = 0.0;
  int coeffCnt = 0;
  for( int i = 0; i < 48; i++ )
  {
    f.roiQ[i] = 0.0;
  }
  f.roiDim = 0;

  for( int v = 0; v < roiSide; v++ )
  {
    for( int u = 0; u < roiSide; u++ )
    {
      if( roiSide == 8 && u >= 4 && v >= 4 )
      {
        continue;
      }

      const double c = (double)coeff.at( u, v );
      if( coeffCnt < 48 )
      {
        f.roiQ[coeffCnt] = c;
      }
      const double e = c * c;
      roiEnergy += e;
      nnz += c != 0.0 ? 1.0 : 0.0;
      coeffCnt++;

      if( u <= 1 && v <= 1 )
      {
        lfEnergy += e;
      }
    }
  }

  f.roiEnergyQ = roiEnergy / (double)std::max( 1, coeffCnt );
  f.lfRatio    = lfEnergy / ( roiEnergy + 1e-9 );
  f.predNz     = nnz;
  f.roiDim     = coeffCnt;
  f.corrProxy  = xLahtpCorrProxyFromRoi( f.roiQ, f.roiDim );

  double energyThr = m_pcEncCfg->m_LardLfnstEnergyThr;
  double lfThr     = m_pcEncCfg->m_LardLfnstLfRatioThr;
  double nzThr     = m_pcEncCfg->m_LardLfnstNzThr;

  const LahtpFitParams* fitParams = nullptr;
  if( m_pcEncCfg->m_LardLfnstSkip == 8 || m_pcEncCfg->m_LardLfnstSkip == 9 )
  {
    fitParams = xLahtpFindFitParams( g_lardLfnstSpeedTable, (int)( sizeof( g_lardLfnstSpeedTable ) / sizeof( g_lardLfnstSpeedTable[0] ) ), cu.qp, cu.lwidth(), cu.lheight(), cu.intraDir[CH_L] );
  }
  else if( m_pcEncCfg->m_LardLfnstSkip >= 6 )
  {
    fitParams = xLahtpFindFitParams( g_lardLfnstFitTable, (int)( sizeof( g_lardLfnstFitTable ) / sizeof( g_lardLfnstFitTable[0] ) ), cu.qp, cu.lwidth(), cu.lheight(), cu.intraDir[CH_L] );
  }

  if( fitParams )
  {
    energyThr = fitParams->energyThr;
    lfThr     = fitParams->lfRatioThr;
    nzThr     = fitParams->nzThr;
  }

  f.stage2 = ( f.roiEnergyQ < energyThr )
          && ( f.lfRatio    > lfThr )
          && ( f.predNz     < nzThr );

  if( f.stage2 && ( m_pcEncCfg->m_LardLfnstSkip == 7 || m_pcEncCfg->m_LardLfnstSkip == 8 || m_pcEncCfg->m_LardLfnstSkip == 9 ) )
  {
    const int mode = cu.intraDir[CH_L];
    const bool reliableMode = mode == 1 || ( mode >= 2 && mode <= 34 ) || mode >= 51;
    const bool largeBlock = cu.lwidth() * cu.lheight() > 1024 && std::max( cu.lwidth(), cu.lheight() ) < 4 * std::min( cu.lwidth(), cu.lheight() );
    f.stage2 = largeBlock || ( cu.qp <= 20 && reliableMode );
  }

  return f.stage1 && f.stage2;
#endif
}

IntraSearch::LardLfnstCandDecision IntraSearch::xLardLfnstPredictCandidates( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f ) const
{
  LardLfnstCandDecision d;
  d.valid     = false;
  d.mask      = 0x7;
  d.gain1     = 0.0;
  d.gain2     = 0.0;
  d.corrProxy = 0.0;
  d.n0        = 0.0;
  d.n1        = 0.0;
  d.n2        = 0.0;
  d.last0     = 0;
  d.last1     = 0;
  d.last2     = 0;

#if !VVENC_LARD_LFNST_GAIN_PRED_ENABLE
  (void)cu;
  (void)tu;
  (void)f;
  return d;
#else
  if( !m_pcEncCfg || ( m_pcEncCfg->m_LardLfnstSkip != 8 && m_pcEncCfg->m_LardLfnstSkip != 9 ) || !tu.blocks[COMP_Y].valid() )
  {
    return d;
  }

  const int width  = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
  if( width < 4 || height < 4 )
  {
    return d;
  }

  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode >= NUM_INTRA_MODE - 1 )
  {
    return d;
  }

  intraMode = xLardLfnstGetIntraMode( tu.blocks[COMP_Y], intraMode );
  const bool transposeFlag = xLardLfnstTransposeFlag( intraMode );
  const bool whge3         = width >= 8 && height >= 8;
  const int  sbSize        = whge3 ? 8 : 4;
  const int  trSize        = whge3 ? 48 : 16;
  const int  zeroOutSize   = ( ( width == 4 && height == 4 ) || ( width == 8 && height == 8 ) ) ? 8 : 16;
  const CCoeffSigBuf coeff = tu.getCoeffs( COMP_Y );

  int input[48];
  for( int i = 0; i < 48; i++ )
  {
    input[i] = 0;
  }

  int* dst = input;
  if( transposeFlag )
  {
    if( sbSize == 4 )
    {
      for( int y = 0; y < 4; y++ )
      {
        dst[0]  = (int)coeff.at( 0, y );
        dst[4]  = (int)coeff.at( 1, y );
        dst[8]  = (int)coeff.at( 2, y );
        dst[12] = (int)coeff.at( 3, y );
        dst++;
      }
    }
    else
    {
      for( int y = 0; y < 8; y++ )
      {
        dst[0]  = (int)coeff.at( 0, y );
        dst[8]  = (int)coeff.at( 1, y );
        dst[16] = (int)coeff.at( 2, y );
        dst[24] = (int)coeff.at( 3, y );
        if( y < 4 )
        {
          dst[32] = (int)coeff.at( 4, y );
          dst[36] = (int)coeff.at( 5, y );
          dst[40] = (int)coeff.at( 6, y );
          dst[44] = (int)coeff.at( 7, y );
        }
        dst++;
      }
    }
  }
  else
  {
    int idx = 0;
    for( int y = 0; y < sbSize; y++ )
    {
      const int stride = ( y < 4 ) ? sbSize : 4;
      for( int x = 0; x < stride; x++ )
      {
        input[idx++] = (int)coeff.at( x, y );
      }
    }
  }

  double energy0 = 0.0;
  double abs0    = 0.0;
  double pairAbs = 0.0;
  for( int i = 0; i < trSize; i++ )
  {
    const double c = (double)input[i];
    energy0 += c * c;
    abs0    += std::fabs( c );
    d.n0    += input[i] != 0 ? 1.0 : 0.0;
    if( i + 1 < trSize )
    {
      pairAbs += std::fabs( c * (double)input[i + 1] );
    }
  }

  if( d.n0 <= 0.0 )
  {
    d.valid = true;
    d.mask  = 0x1;
    d.gain1 = -m_pcEncCfg->m_LardLfnstCandTau0;
    d.gain2 = -m_pcEncCfg->m_LardLfnstCandTau0;
    return d;
  }

  d.last0     = std::max( 0, std::min( (int)tu.lastPos[COMP_Y], trSize - 1 ) );
  d.corrProxy = pairAbs / ( energy0 + 1e-9 );

  const int candKey = xLardLfnstCandPackKey( cu.qp,
                                             xLahtpSizeGroupId( cu.lwidth(), cu.lheight() ),
                                             xLahtpModeGroupId( cu.intraDir[CH_L] ),
                                             xLardLfnstLatBucketId( f.absLatDeg ),
                                             xLardLfnstNzBucketId( f.predNz ),
                                             xLardLfnstLastBucketId( d.last0 ),
                                             xLardLfnstRoiBucketId( f.roiEnergyQ ),
                                             xLardLfnstLfBucketId( f.lfRatio ),
                                             xLardLfnstCorrBucketId( d.corrProxy ) );
  if( const LardLfnstCandGainParams* candParams = xLardLfnstFindCandGainParams( candKey ) )
  {
    d.valid = true;
    d.mask  = candParams->mask;
    d.gain1 = candParams->gain1;
    d.gain2 = candParams->gain2;
    return d;
  }

  return d;
#endif
}

IntraSearch::LardLfnstPaperDecision IntraSearch::xLardLfnstPaperGradDecision( const CodingUnit& cu, const TransformUnit& tu ) const
{
  LardLfnstPaperDecision d;
  if( !m_pcEncCfg || !m_pcTrQuant
   || ( m_pcEncCfg->m_LardLfnstSkip != 12 && m_pcEncCfg->m_LardLfnstSkip != 13 )
   || !tu.blocks[COMP_Y].valid() )
  {
    return d;
  }

  const int width  = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
  if( width < 2 || height < 2 || tu.mtsIdx[COMP_Y] == MTS_SKIP || cu.ispMode || cu.lfnstIdx != 0 )
  {
    return d;
  }

  const TCoeff* trCoeff = m_pcTrQuant->getLastTransformCoeffs();
  if( !trCoeff )
  {
    return d;
  }

  double rowGrad = 0.0;
  const int lastY = height - 1;
  for( int x = 1; x < width; x++ )
  {
    rowGrad += std::fabs( (double)trCoeff[lastY * width + x] - (double)trCoeff[lastY * width + x - 1] );
  }

  double colGrad = 0.0;
  const int lastX = width - 1;
  for( int y = 1; y < height; y++ )
  {
    colGrad += std::fabs( (double)trCoeff[y * width + lastX] - (double)trCoeff[( y - 1 ) * width + lastX] );
  }

  const double qStep = std::max( 1e-6, xLahtpQStepCached( cu.qp ) );
  d.grad2   = colGrad;
  d.grad1   = rowGrad + colGrad;
  d.th1     = m_pcEncCfg->m_LardLfnstPaperGradTh1;
  d.th2Idx1 = std::max( 0.0, m_pcEncCfg->m_LardLfnstPaperTh2Scale * qStep - m_pcEncCfg->m_LardLfnstPaperTh2Offset1 );
  d.th2Idx2 = std::max( 0.0, m_pcEncCfg->m_LardLfnstPaperTh2Scale * qStep - m_pcEncCfg->m_LardLfnstPaperTh2Offset2 );

  int mask = 0x7;
  if( d.grad2 >= d.th2Idx1 )
  {
    mask &= ~0x2;
  }
  if( d.grad2 >= d.th2Idx2 || d.grad1 <= d.th1 )
  {
    mask &= ~0x4;
  }

  d.mask  = mask;
  d.valid = mask != 0x7;
  return d;
}

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
void IntraSearch::xLardLfnst2ndTraceVector( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f ) const
{
  if( !m_pcEncCfg || !m_pcTrQuant || m_pcEncCfg->m_LardLfnst2ndVecFile[0] == '\0' || !tu.blocks[COMP_Y].valid() )
  {
    return;
  }

  const int width  = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
  if( width < 4 || height < 4 || tu.mtsIdx[COMP_Y] == MTS_SKIP || cu.ispMode || cu.lfnstIdx != 0 )
  {
    return;
  }

  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode >= NUM_INTRA_MODE - 1 )
  {
    return;
  }

  intraMode = xLard2ndGetIntraMode( tu.blocks[COMP_Y], intraMode );
  const bool transposeFlag = xLard2ndTransposeFlag( intraMode );
  const bool whge3         = width >= 8 && height >= 8;
  const int  sbSize        = whge3 ? 8 : 4;
  const int  trSize        = whge3 ? 48 : 16;
  const int  zeroOutSize   = ( ( width == 4 && height == 4 ) || ( width == 8 && height == 8 ) ) ? 8 : 16;
  const int  lfnstSet      = (int)g_lfnstLut[intraMode];
  const int  modeGroup     = xLahtpModeGroupId( cu.intraDir[CH_L] );

  const TCoeff* trCoeff = m_pcTrQuant->getLastTransformCoeffs();
  if( !trCoeff )
  {
    return;
  }

  double input[48];
  xLard2ndCollectLfnstInput( trCoeff, width, sbSize, transposeFlag, input, nullptr, nullptr );

  double inputEnergy = 0.0;
  for( int i = 0; i < trSize; i++ )
  {
    inputEnergy += input[i] * input[i];
  }

  xLard2ndAppendVec( m_pcEncCfg->m_LardLfnst2ndVecFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize, trSize,
                     transposeFlag, f.absLatDeg, f.thetaMaxDeg, inputEnergy, input );
}

static int xLardLfnstCovLatBin( const double absLatDeg )
{
  static const int bins[] = { 0, 15, 30, 45, 60, 75, 85 };
  int best = 0;
  double bestDiff = MAX_DOUBLE;
  for( int i = 0; i < 7; i++ )
  {
    const double diff = std::fabs( absLatDeg - (double)bins[i] );
    if( diff < bestDiff )
    {
      bestDiff = diff;
      best = i;
    }
  }
  return best;
}

static bool xLardSkip18EarlyDispatchPass( const VVEncCfg* cfg, const int actualQp, const int width, const int height,
                                          int* rejectReason = nullptr )
{
  if( rejectReason )
  {
    *rejectReason = 0;
  }
  if( !cfg || cfg->m_LardLfnst18OptLevel <= 0 )
  {
    return true;
  }
  if( cfg->m_LardLfnst18TargetProfile == 1 )
  {
    if( actualQp != 24 )
    {
      if( rejectReason )
      {
        *rejectReason = 1;
      }
      return false;
    }
  }
  else if( cfg->m_LardLfnst18TargetProfile == 2 )
  {
    const bool qp19Size = actualQp == 19 && width == 32 && height == 32;
    const bool qp24Size = actualQp == 24
                       && ( ( width == 16 && height == 16 )
                         || ( width == 32 && height == 16 )
                         || ( width == 16 && height == 32 )
                         || ( width == 32 && height == 32 ) );
    const bool qp34Size = actualQp == 34
                       && ( ( width == 16 && height == 16 )
                         || ( width == 32 && height == 32 ) );
    if( !qp19Size && !qp24Size && !qp34Size )
    {
      if( rejectReason )
      {
        *rejectReason = actualQp == 19 || actualQp == 24 || actualQp == 34 ? 2 : 1;
      }
      return false;
    }
  }
  static constexpr uint64_t skip18QpEnabled = ( 1ull << 19 ) | ( 1ull << 24 ) | ( 1ull << 29 ) | ( 1ull << 34 );
  if( actualQp < 0 || actualQp >= 64 || ( skip18QpEnabled & ( 1ull << actualQp ) ) == 0 )
  {
    if( rejectReason )
    {
      *rejectReason = 1;
    }
    return false;
  }
  if( actualQp == 29 )
  {
    if( rejectReason )
    {
      *rejectReason = 1;
    }
    return false;
  }
  if( cfg->m_LardLfnst18OptLevel >= 2 && ( width < 16 || height < 16 ) )
  {
    if( rejectReason )
    {
      *rejectReason = 2;
    }
    return false;
  }
  return true;
}

static int xLardSkip18LatBinCached( const int picHIn, const int centerYIn )
{
  thread_local int s_picH = 0;
  thread_local std::vector<uint8_t> s_rowToLatBin;
  const int picH = std::max( 1, picHIn );
  if( s_picH != picH )
  {
    s_picH = picH;
    s_rowToLatBin.resize( picH + 1 );
    for( int centerY = 0; centerY <= picH; centerY++ )
    {
      const int lat2Numerator = std::abs( picH - 2 * centerY ) * 180;
      int bin = 0;
      bin += lat2Numerator >= 15 * picH;
      bin += lat2Numerator >= 45 * picH;
      bin += lat2Numerator >= 75 * picH;
      bin += lat2Numerator >= 105 * picH;
      bin += lat2Numerator >= 135 * picH;
      bin += lat2Numerator >= 160 * picH;
      s_rowToLatBin[centerY] = (uint8_t)bin;
    }
  }
  return s_rowToLatBin[Clip3( 0, picH, centerYIn )];
}

#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
static int xLardSkip20CompareKey( const LardLfnstSkip20MaskEntry& entry, const int level, const int key[10] )
{
  const int values[11] =
  {
    entry.level, entry.qp, entry.width, entry.height, entry.modeGroup, entry.setIdx,
    entry.transpose, entry.latBin, entry.energyBin, entry.nnzBin, entry.lastBin
  };
  if( values[0] != level )
  {
    return values[0] < level ? -1 : 1;
  }
  for( int idx = 0; idx < 10; idx++ )
  {
    if( values[idx + 1] != key[idx] )
    {
      return values[idx + 1] < key[idx] ? -1 : 1;
    }
  }
  return 0;
}

static int xLardSkip20FindMask( const int level, const int key[10], const int profile )
{
  int lo = 0;
  int hi = (int)( sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS ) / sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( ( hi - lo ) >> 1 );
    const int cmp = xLardSkip20CompareKey( LARD_LFNST_SKIP20_DIRECT_MASKS[mid], level, key );
    if( cmp < 0 )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  if( lo >= (int)( sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS ) / sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS[0] ) )
      || xLardSkip20CompareKey( LARD_LFNST_SKIP20_DIRECT_MASKS[lo], level, key ) != 0 )
  {
    return -1;
  }
  return LARD_LFNST_SKIP20_DIRECT_MASKS[lo].mask[profile] & 0x7;
}

template<typename T, size_t N>
static const T* xLardSkip20FindThreshold( const T (&table)[N], const int qp, const int width, const int height )
{
  for( const auto& entry : table )
  {
    if( entry.qp == qp && entry.width == width && entry.height == height )
    {
      return &entry;
    }
  }
  return nullptr;
}

template<typename T>
static int xLardSkip20Bin( const double value, const T& threshold )
{
  int bin = 0;
  for( int idx = 0; idx < threshold.count; idx++ )
  {
    bin += value >= threshold.cut[idx];
  }
  return bin;
}
#else
static int xLardSkip20CompareKey( const LardLfnstSkip20MaskEntry& entry, const int key[8] )
{
  const int values[8] =
  {
    entry.qp, entry.width, entry.height, entry.setIdx,
    entry.transpose, entry.latBin, entry.modeGroup, entry.energyBin
  };
  for( int idx = 0; idx < 8; idx++ )
  {
    if( values[idx] != key[idx] )
    {
      return values[idx] < key[idx] ? -1 : 1;
    }
  }
  return 0;
}
#endif

static int xLardSkip20DirectMask( const CodingUnit& cu, const TransformUnit& tu, const TrQuant* trQuant,
                                  const int profile )
{
  if( !trQuant || profile < 0 || profile >= LARD_LFNST_SKIP20_PROFILES
      || !tu.blocks[COMP_Y].valid() || tu.mtsIdx[COMP_Y] == MTS_SKIP || cu.ispMode )
  {
    return 0x7;
  }
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  if( !LARD_LFNST_SKIP20_PROFILE_AVAILABLE[profile] )
  {
    return 0x7;
  }
#endif
  const int width = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  const auto* energyThreshold = xLardSkip20FindThreshold( LARD_LFNST_SKIP20_ENERGY_THRESHOLDS, cu.qp, width, height );
  const auto* nnzThreshold = xLardSkip20FindThreshold( LARD_LFNST_SKIP20_NNZ_THRESHOLDS, cu.qp, width, height );
  const auto* lastThreshold = xLardSkip20FindThreshold( LARD_LFNST_SKIP20_LAST_THRESHOLDS, cu.qp, width, height );
  if( !energyThreshold || !nnzThreshold || !lastThreshold )
  {
    return 0x7;
  }
#else
  const LardLfnstSkip20EnergyThreshold* energyThreshold = nullptr;
  for( const auto& threshold : LARD_LFNST_SKIP20_ENERGY_THRESHOLDS )
  {
    if( threshold.qp == cu.qp && threshold.width == width && threshold.height == height )
    {
      energyThreshold = &threshold;
      break;
    }
  }
  if( !energyThreshold )
  {
    return 0x7;
  }
#endif

  const TCoeff* coeff = trQuant->getLastTransformCoeffs();
  if( !coeff )
  {
    return 0x7;
  }
  const int sbSize = width >= 8 && height >= 8 ? 8 : 4;
  const int kIn = sbSize == 8 ? 48 : 16;
  double input[48] = {};
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode >= NUM_INTRA_MODE - 1 )
  {
    return 0x7;
  }
  intraMode = xLard2ndGetIntraMode( tu.blocks[COMP_Y], intraMode );
  const bool transpose = xLard2ndTransposeFlag( intraMode );
  const int setIdx = (int)g_lfnstLut[intraMode];
  xLard2ndCollectLfnstInput( coeff, width, sbSize, transpose, input, nullptr, nullptr );
#else
  xLard2ndCollectLfnstInput( coeff, width, sbSize, false, input, nullptr, nullptr );
#endif
  double energy = 0.0;
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  int baseNnz = 0;
  int baseLast = -1;
  const double qStep = xLahtpQStepCached( cu.qp );
  for( int idx = 0; idx < kIn; idx++ )
  {
    energy += input[idx] * input[idx];
    const int level = (int)std::floor( std::abs( input[idx] ) / qStep + 0.5 );
    if( level > 0 )
    {
      baseNnz++;
      baseLast = idx;
    }
  }
#else
  for( int idx = 0; idx < kIn; idx++ )
  {
    energy += input[idx] * input[idx];
  }
  const double qStep = xLahtpQStepCached( cu.qp );
#endif
  const double energyQ = energy / ( qStep * qStep );
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  const int energyBin = xLardSkip20Bin( energyQ, *energyThreshold );
  const int nnzBin = xLardSkip20Bin( (double)baseNnz, *nnzThreshold );
  const int lastBin = xLardSkip20Bin( (double)baseLast, *lastThreshold );
#else
  int energyBin = 0;
  for( int idx = 0; idx < LARD_LFNST_SKIP20_ENERGY_CUTS; idx++ )
  {
    energyBin += energyQ >= energyThreshold->cut[idx];
  }
#endif

  int picH = cu.Y().y + cu.lheight();
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }
  const int latBin = xLardSkip18LatBinCached( picH, cu.Y().y + ( cu.lheight() >> 1 ) );
#if LARD_LFNST_SKIP20_TABLE_VERSION >= 2
  const int modeGroup = xLahtpModeGroupId( cu.intraDir[CH_L] );
  const int fullKey[10] =
  {
    cu.qp, width, height, modeGroup, setIdx, transpose ? 1 : 0, latBin, energyBin, nnzBin, lastBin
  };
  int key[10] = {};
  for( int level = LARD_LFNST_SKIP20_LEVEL_FULL; level <= LARD_LFNST_SKIP20_LEVEL_CORE; level++ )
  {
    std::copy( fullKey, fullKey + 10, key );
    if( level >= LARD_LFNST_SKIP20_LEVEL_NO_LAST )
    {
      key[9] = -1;
    }
    if( level >= LARD_LFNST_SKIP20_LEVEL_NO_NNZ )
    {
      key[8] = -1;
    }
    if( level >= LARD_LFNST_SKIP20_LEVEL_NO_MODE )
    {
      key[3] = -1;
    }
    if( level >= LARD_LFNST_SKIP20_LEVEL_NO_LAT )
    {
      key[6] = -1;
    }
    if( level >= LARD_LFNST_SKIP20_LEVEL_CORE )
    {
      key[4] = -1;
      key[5] = -1;
    }
    const int mask = xLardSkip20FindMask( level, key, profile );
    if( mask >= 0 )
    {
      return mask;
    }
  }
  return 0x7;
#else
  const int key[8] = { cu.qp, width, height, -1, -1, latBin, -1, energyBin };
  int lo = 0;
  int hi = (int)( sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS ) / sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS[0] ) );
  while( lo < hi )
  {
    const int mid = lo + ( ( hi - lo ) >> 1 );
    const int cmp = xLardSkip20CompareKey( LARD_LFNST_SKIP20_DIRECT_MASKS[mid], key );
    if( cmp < 0 )
    {
      lo = mid + 1;
    }
    else
    {
      hi = mid;
    }
  }
  if( lo >= (int)( sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS ) / sizeof( LARD_LFNST_SKIP20_DIRECT_MASKS[0] ) )
      || xLardSkip20CompareKey( LARD_LFNST_SKIP20_DIRECT_MASKS[lo], key ) != 0 )
  {
    return 0x7;
  }
  return LARD_LFNST_SKIP20_DIRECT_MASKS[lo].mask[profile] & 0x7;
#endif
}

struct LardSkip21ProfileParams
{
  int supportQ;
  int support2Q;
  int covQ;
  int minLatBin;
};

struct LardSkip21EarlyDecision
{
  bool eligible = false;
  bool stage1EarlyZero = false;
  bool stage2EarlyZero = false;
  bool stage3WouldPrune = false;
  bool stage3Applied = false;
  bool stage1WouldZero = false;
  bool stage2WouldZero = false;
  bool theoryFound = false;
  bool earlyZero = false;
  int actualSource = 0;
  int latBin = -1;
  int sizeId = -1;
  int modeGroup = -1;
  int setIdx = -1;
  int transpose = -1;
  int supportRatioQ = 0;
  int oxQ = -1;
  int diagDominanceQ = -1;
  int gmaxCovQ = -1;
  int diffCovQ = -1;
  int respGainMaxQ = -1;
  int offdiagRespMaxQ = -1;
  int stage3SelectedIdx = 0;
  int stage3Mask = 0x7;
  int stage3DiffQ = 0;
  int stage3Score1Q = 0;
  int stage3Score2Q = 0;
  int stage3KeepScoreQ = 0;
  int stage3RejectedReason = 0;
  uint64_t stage3EvalNs = 0;
  bool stage3SeqEnabled = false;
  bool stage3SeqShouldSkipOther = false;
  int stage3SeqBestIdx = 0;
  int stage3SeqOtherIdx = 0;
  int stage3SeqSkipReason = 0;
  int stage3SeqWinRelQ = 0;
  int stage3SeqLossRelQ = 0;
  bool stage3SeqAllowLossSkip = false;
  int candidateBefore = 0;
  int candidateAfter = 0;
};

static LardSkip21ProfileParams xLardSkip21ProfileParams( const int profile )
{
  static constexpr LardSkip21ProfileParams params[7] =
  {
    { 256, 384,   0, 4 }, // E5:  r_sup <= 0.25
    { 358, 512,  64, 4 }, // E7:  r_sup <= 0.35
    { 461, 640, 128, 4 }, // E10: r_sup <= 0.45
    { 563, 704, 192, 4 }, // E12: r_sup <= 0.55
    { 666, 768, 256, 4 }, // E15: r_sup <= 0.65
    { 563, 704, 192, 0 }, // E12-noLat: r_sup <= 0.55
    { 666, 768, 256, 0 }  // E15-noLat: r_sup <= 0.65
  };
  return params[Clip3( 0, 6, profile )];
}

struct LardSkip21Stage2ProfileParams
{
  int oxQ;
  int diagDominanceQ;
  int gmaxCovQ;
  int respGainMaxQ;
  int offdiagRespMaxQ;
  int highCostMode;
  int gate;
  bool useGmaxGuard;
};

static LardSkip21Stage2ProfileParams xLardSkip21Stage2ProfileParams( const int profile )
{
  static constexpr LardSkip21Stage2ProfileParams params[14] =
  {
#include "LardLfnstSkip21Stage2Profiles.inc"
  };
  return params[Clip3( 0, 13, profile )];
}

struct LardSkip21Stage3ProfileParams
{
  int diffQ;
  int keepQ;
};

struct LardSkip21Stage3SeqProfileParams
{
  int diffQ;
  int keepQ;
  int winRelQ;
  int lossRelQ;
  bool allowLossSkip;
};

struct LardSkip21Stage3ZdProfileParams
{
  int maxNnz;
  int maxLast;
  int respGainMaxQ;
  int offdiagRespMaxQ;
  bool requireZeroCbf;
  bool useOffdiagGuard;
};

struct LardSkip21ZeroStats
{
  bool valid = false;
  double j0 = MAX_DOUBLE;
  double distCost0 = MAX_DOUBLE;
  int baseCbf = 0;
  int baseNnz = 0;
  int baseLast = 0;
  int baseAbsLevelSum = 0;
  int baseCoeffBits = 0;
  int width = 0;
  int height = 0;
  int qp = 0;
};

static LardSkip21Stage3ProfileParams xLardSkip21Stage3ProfileParams( const int profile )
{
  static constexpr LardSkip21Stage3ProfileParams params[3] =
  {
    { 24, 372 }, // T1: positive diff p80, keep p50
    { 20, 372 }, // T2: positive diff p70, keep p50
    { 17, 247 }  // T3: positive diff p60, keep p40
  };
  return params[Clip3( 0, 2, profile )];
}

static LardSkip21Stage3SeqProfileParams xLardSkip21Stage3SeqProfileParams( const int profile )
{
  static constexpr LardSkip21Stage3SeqProfileParams params[6] =
  {
    { 24, 372, 150, 250, true  }, // Tseq1: diff p80, keep p50
    { 20, 310, 100, 200, true  }, // Tseq2: diff p70, keep p45
    { 17, 247,  75, 150, true  }, // Tseq3: diff p60, keep p40
    { 17, 372, 125, 300, true  }, // T3R: T3 diff with stronger keep and RD margins
    { 17, 247,  75,   0, false }, // T3 winOnly: disable best-loss skip
    { 20, 310, 100,   0, false }  // T2 winOnly: disable best-loss skip
  };
  return params[Clip3( 0, 5, profile )];
}

static LardSkip21Stage3ZdProfileParams xLardSkip21Stage3ZdProfileParams( const int profile )
{
  static constexpr LardSkip21Stage3ZdProfileParams params[3] =
  {
    { 0,  0, 512, 32767, true,  false }, // ZD1: zero-CBF plus weak response
    { 2,  7, 512,    59, false, true  }, // ZD2: low NNZ/last plus response/offdiag guards
    { 3, 10, 525, 32767, false, false }  // ZD3: aggressive low NNZ/last plus weak response
  };
  return params[Clip3( 0, 2, profile )];
}

static int xLardSkip21Stage3SeqShouldSkipOther( const LardSkip21EarlyDecision& d, const double j0, const double jBest )
{
  if( !d.stage3SeqEnabled || !( j0 < MAX_DOUBLE * 0.5 ) || !( jBest < MAX_DOUBLE * 0.5 ) )
  {
    return 0;
  }
  const double denom = std::max( std::max( j0, jBest ), 1.0 );
  const int relQ = (int)std::floor( 10000.0 * std::abs( jBest - j0 ) / denom + 0.5 );
  if( jBest < j0 && relQ >= d.stage3SeqWinRelQ )
  {
    return 2;
  }
  if( d.stage3SeqAllowLossSkip && jBest > j0 && relQ >= d.stage3SeqLossRelQ )
  {
    return 3;
  }
  return 4;
}

static bool xLardSkip21Stage3LbWouldTerminate( const double distLowerBound, const double bestBefore )
{
  return bestBefore < MAX_DOUBLE * 0.5 && distLowerBound >= bestBefore;
}

static bool xLardSkip21Stage3ZdWouldSkip( const LardSkip21ZeroStats& zs, const LardSkip21EarlyDecision& d,
                                          const LardSkip21Stage3ZdProfileParams& params )
{
  if( !zs.valid || !d.theoryFound || zs.width < 8 || zs.height < 8 )
  {
    return false;
  }
  if( d.respGainMaxQ < 0 || d.respGainMaxQ > params.respGainMaxQ )
  {
    return false;
  }
  if( params.useOffdiagGuard && ( d.offdiagRespMaxQ < 0 || d.offdiagRespMaxQ > params.offdiagRespMaxQ ) )
  {
    return false;
  }
  if( params.requireZeroCbf )
  {
    return zs.baseCbf == 0;
  }
  return zs.baseNnz <= params.maxNnz && zs.baseLast <= params.maxLast;
}

static const char* xLardSkip21Stage3RejectedReasonName( const int reason )
{
  switch( reason )
  {
  case 0: return "none";
  case 1: return "diff_too_small";
  case 2: return "keep_score_too_low";
  case 3: return "stage1_already_zero";
  case 4: return "stage2_already_zero";
  case 5: return "no_theory_entry";
  case 6: return "debug_nolookup";
  case 7: return "debug_nulllookup";
  case 8: return "high_cost_filter";
  default: return "unknown";
  }
}

static int xLardSkip21CosQCached( const int picHIn, const int centerYIn )
{
  static constexpr double pi = 3.14159265358979323846;
  static constexpr int scaleQ = 1024;
  thread_local int s_picH = 0;
  thread_local std::vector<uint16_t> s_rowToCosQ;
  const int picH = std::max( 1, picHIn );
  if( s_picH != picH )
  {
    s_picH = picH;
    s_rowToCosQ.resize( picH + 1 );
    for( int centerY = 0; centerY <= picH; centerY++ )
    {
      const double theta = ( 0.5 * (double)picH - (double)centerY ) * pi / (double)picH;
      const int cosQ = (int)std::floor( std::max( 0.0, std::cos( std::fabs( theta ) ) ) * (double)scaleQ + 0.5 );
      s_rowToCosQ[centerY] = (uint16_t)Clip3( 0, scaleQ, cosQ );
    }
  }
  return s_rowToCosQ[Clip3( 0, picH, centerYIn )];
}

static int xLardSkip21SizeId( const int width, const int height )
{
  static constexpr int sizes[][2] =
  {
    { 4, 4 }, { 4, 8 }, { 8, 4 }, { 8, 8 }, { 8, 16 },
    { 16, 8 }, { 16, 16 }, { 16, 32 }, { 32, 16 }, { 32, 32 }
  };
  for( int idx = 0; idx < (int)( sizeof( sizes ) / sizeof( sizes[0] ) ); idx++ )
  {
    if( sizes[idx][0] == width && sizes[idx][1] == height )
    {
      return idx;
    }
  }
  return -1;
}

static int xLardSkip21SupportRatioQ( const CodingUnit& cu )
{
  static constexpr int scaleQ = 1024;
  const int width = std::max( 1, (int)cu.lwidth() );
  const int height = std::max( 1, (int)cu.lheight() );
  const int supportCols = std::min( width, std::min( width, height ) == 4 ? 4 : 8 );
  int picH = cu.Y().y + height;
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }
  const int cosQ = xLardSkip21CosQCached( picH, cu.Y().y + ( height >> 1 ) );
  const int effectiveCols = std::max( 1, ( supportCols * cosQ ) >> 10 );
  return Clip3( 0, scaleQ, ( effectiveCols * scaleQ + ( supportCols >> 1 ) ) / supportCols );
}

static const LardLfnstSkip21TheoryCompactEntry* xLardSkip21CompactTheoryEntry( const int latBin, const int sizeId,
                                                                               const int setIdx, const int transpose )
{
  if( latBin < 0 || latBin >= LARD_LFNST_SKIP21_COMPACT_LAT_COUNT
      || sizeId < 0 || sizeId >= LARD_LFNST_SKIP21_COMPACT_SIZE_COUNT
      || setIdx < 0 || setIdx >= LARD_LFNST_SKIP21_COMPACT_SET_COUNT
      || transpose < 0 || transpose >= LARD_LFNST_SKIP21_COMPACT_TRANSPOSE_COUNT )
  {
    return nullptr;
  }
  const int idx = (((latBin * LARD_LFNST_SKIP21_COMPACT_SIZE_COUNT + sizeId)
                    * LARD_LFNST_SKIP21_COMPACT_SET_COUNT + setIdx)
                   * LARD_LFNST_SKIP21_COMPACT_TRANSPOSE_COUNT + transpose);
  const auto& entry = g_lardLfnstSkip21TheoryCompactTable[idx];
  return entry.valid ? &entry : nullptr;
}

static bool xLardSkip21Stage2HighCostPass( const int mode, const int width, const int height )
{
  if( mode <= 0 )
  {
    return true;
  }
  if( mode == 1 )
  {
    return width * height >= 64;
  }
  const bool sbSize8 = width >= 8 && height >= 8;
  const int outN = ( ( width == 4 && height == 4 ) || ( width == 8 && height == 8 ) ) ? 8 : 16;
  return sbSize8 || outN == 16;
}

static bool xLardSkip21Stage3HighCostPass( const int mode, const int width, const int height )
{
  if( mode <= 0 )
  {
    return true;
  }
  if( mode == 1 )
  {
    return width * height >= 64;
  }
  if( mode == 2 )
  {
    return std::min( width, height ) >= 8;
  }
  if( mode == 4 )
  {
    return width == 8 && height == 8;
  }
  return ( width == 8 && height == 8 )
      || ( width == 8 && height == 16 )
      || ( width == 16 && height == 8 )
      || ( width == 16 && height == 16 )
      || ( width == 16 && height == 32 )
      || ( width == 32 && height == 16 )
      || ( width == 32 && height == 32 )
      || ( width == 64 && height == 64 );
}

static bool xLardSkip21Stage2WeakCoupling( const LardLfnstSkip21TheoryCompactEntry& entry, const LardSkip21Stage2ProfileParams& params,
                                           const int highCostMode, const int width, const int height )
{
  if( !xLardSkip21Stage2HighCostPass( highCostMode, width, height ) )
  {
    return false;
  }
  const bool oxWeak = entry.oxQ <= params.oxQ;
  const bool diagDominant = entry.diagDominanceQ >= params.diagDominanceQ;
  const bool gmaxGuard = !params.useGmaxGuard || entry.gmaxCovQ <= params.gmaxCovQ;
  const bool respWeak = entry.respGainMaxQ <= params.respGainMaxQ;
  const bool offdiagWeak = entry.offdiagRespMaxQ <= params.offdiagRespMaxQ;

  if( params.gate == 0 )
  {
    return oxWeak && respWeak;
  }
  if( params.gate == 1 )
  {
    return oxWeak && diagDominant && respWeak && offdiagWeak;
  }
  if( params.gate == 2 )
  {
    return respWeak && offdiagWeak;
  }
  return oxWeak && diagDominant && gmaxGuard;
}

static LardSkip21EarlyDecision xLardSkip21EarlyDecision( const VVEncCfg* cfg, const CodingUnit& cu )
{
  LardSkip21EarlyDecision d;
  if( !cfg || cfg->m_LardLfnstSkip != 21 || cu.ispMode || cu.mipFlag || cu.bdpcmM[CH_L] )
  {
    return d;
  }

  d.eligible = true;
  d.candidateBefore = 2;
  d.candidateAfter = 2;

  const bool stage1Enabled = cfg->m_LardLfnst21Stages == 1 || cfg->m_LardLfnst21Stages == 3 || cfg->m_LardLfnst21Stages == 12 || cfg->m_LardLfnst21Stages == 123;
  const bool stage2Enabled = cfg->m_LardLfnst21Stages == 2 || cfg->m_LardLfnst21Stages == 3 || cfg->m_LardLfnst21Stages == 12 || cfg->m_LardLfnst21Stages == 123;
  const bool stage3Enabled = cfg->m_LardLfnst21Stages == 4 || cfg->m_LardLfnst21Stages == 123;
  const int stage2Debug = Clip3( 0, 2, cfg->m_LardLfnst21Stage2Debug );
  const int stage3Mode = Clip3( 0, 3, cfg->m_LardLfnst21Stage3Mode );
  const int stage3Debug = Clip3( 0, 3, cfg->m_LardLfnst21Stage3Debug );
  const bool traceEnabled = cfg->m_LardLfnst21StatFile[0] != '\0';
  const bool stage2ShadowEnabled = traceEnabled && stage2Enabled;
  const bool stage2MayLookup = stage2Enabled && stage2Debug != 1;
  const bool stage3HighCostCandidate = xLardSkip21Stage3HighCostPass( cfg->m_LardLfnst21Stage3HighCostMode, cu.lwidth(), cu.lheight() );
  const bool stage3MayLookup = stage3Enabled && stage3Mode != 0 && stage3Debug != 1 && stage3HighCostCandidate;
  const bool needLat = stage1Enabled || stage2MayLookup || stage3MayLookup || traceEnabled;
  const bool needSize = stage2MayLookup || stage3MayLookup || traceEnabled;
  const bool needSupport = stage1Enabled || traceEnabled;

  if( needSupport )
  {
    d.supportRatioQ = xLardSkip21SupportRatioQ( cu );
  }
  if( needSize )
  {
    d.sizeId = xLardSkip21SizeId( cu.lwidth(), cu.lheight() );
  }
  if( needLat )
  {
    int picH = cu.Y().y + cu.lheight();
    if( cu.cs && cu.cs->pcv )
    {
      picH = cu.cs->pcv->lumaHeight;
    }
    d.latBin = xLardSkip18LatBinCached( picH, cu.Y().y + ( cu.lheight() >> 1 ) );
  }

  if( stage1Enabled )
  {
    const LardSkip21ProfileParams params = xLardSkip21ProfileParams( cfg->m_LardLfnst21Profile );
    d.stage1WouldZero = d.latBin >= params.minLatBin && d.supportRatioQ <= params.supportQ;
    d.stage1EarlyZero = d.stage1WouldZero;
  }

  const bool stage2ShouldEvaluate = stage2Enabled && ( !d.stage1EarlyZero || stage2ShadowEnabled );
  const bool needModeInfo = traceEnabled || stage3MayLookup || ( stage2ShouldEvaluate && stage2Debug != 1 );
  if( needModeInfo )
  {
    uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
    if( CU::isMIP( cu, CH_L ) )
    {
      intraMode = PLANAR_IDX;
    }
    d.modeGroup = xLahtpModeGroupId( (int)intraMode );
    if( intraMode < NUM_INTRA_MODE - 1 )
    {
      const uint32_t mappedMode = xLard2ndGetIntraMode( cu.Y(), intraMode );
      d.setIdx = (int)g_lfnstLut[mappedMode];
      d.transpose = xLard2ndTransposeFlag( mappedMode ) ? 1 : 0;
    }
  }

  const LardLfnstSkip21TheoryCompactEntry* theoryEntry = nullptr;
  if( ( stage2ShouldEvaluate && stage2Debug != 1 ) || stage3MayLookup || traceEnabled )
  {
    theoryEntry = xLardSkip21CompactTheoryEntry( d.latBin, d.sizeId, d.setIdx, d.transpose );
    if( theoryEntry )
    {
      d.theoryFound = true;
      d.oxQ = theoryEntry->oxQ;
      d.diagDominanceQ = theoryEntry->diagDominanceQ;
      d.gmaxCovQ = theoryEntry->gmaxCovQ;
      d.diffCovQ = theoryEntry->diffCovQ;
      d.respGainMaxQ = theoryEntry->respGainMaxQ;
      d.offdiagRespMaxQ = theoryEntry->offdiagRespMaxQ;
    }
  }

  if( stage2ShouldEvaluate )
  {
    if( stage2Debug == 1 )
    {
      d.stage2EarlyZero = false;
      d.stage2WouldZero = false;
    }
    else
    {
      if( theoryEntry )
      {
        const LardSkip21Stage2ProfileParams params = xLardSkip21Stage2ProfileParams( cfg->m_LardLfnst21Stage2Profile );
        const int highCostMode = cfg->m_LardLfnst21Stage2HighCostMode >= 0 ? cfg->m_LardLfnst21Stage2HighCostMode : params.highCostMode;
        const bool stage2Gate = xLardSkip21Stage2WeakCoupling( *theoryEntry, params, highCostMode, cu.lwidth(), cu.lheight() );
        d.stage2WouldZero = stage2Gate;
        if( stage2Debug == 2 )
        {
          d.stage2EarlyZero = false;
        }
        else
        {
          d.stage2EarlyZero = !d.stage1EarlyZero && stage2Gate;
        }
      }
    }
  }

  if( stage3Enabled && stage3Mode != 0 && stage3Mode != 3 )
  {
    const auto stage3EvalStart = std::chrono::steady_clock::now();
    if( stage3Debug == 1 )
    {
      d.stage3RejectedReason = 6;
    }
    else if( d.stage1EarlyZero )
    {
      d.stage3RejectedReason = 3;
    }
    else if( d.stage2EarlyZero )
    {
      d.stage3RejectedReason = 4;
    }
    else if( !stage3HighCostCandidate )
    {
      d.stage3RejectedReason = 8;
    }
    else if( !theoryEntry )
    {
      d.stage3RejectedReason = 5;
    }
    else
    {
      d.stage3Score1Q = theoryEntry->respGain1Q;
      d.stage3Score2Q = theoryEntry->respGain2Q;
      d.stage3DiffQ = std::abs( d.stage3Score1Q - d.stage3Score2Q );
      d.stage3KeepScoreQ = std::max( d.stage3Score1Q, d.stage3Score2Q );
      const LardSkip21Stage3ProfileParams staticParams = xLardSkip21Stage3ProfileParams( cfg->m_LardLfnst21Stage3Profile );
      const LardSkip21Stage3SeqProfileParams seqParams = xLardSkip21Stage3SeqProfileParams( cfg->m_LardLfnst21Stage3SeqProfile );
      const int diffQ = stage3Mode == 2 ? seqParams.diffQ : staticParams.diffQ;
      const int keepQ = stage3Mode == 2 ? seqParams.keepQ : staticParams.keepQ;
      if( d.stage3DiffQ < diffQ )
      {
        d.stage3RejectedReason = 1;
      }
      else if( d.stage3KeepScoreQ < keepQ )
      {
        d.stage3RejectedReason = 2;
      }
      else
      {
        d.stage3SelectedIdx = d.stage3Score1Q > d.stage3Score2Q ? 1 : 2;
        if( stage3Mode == 2 )
        {
          if( stage3Debug == 2 )
          {
            d.stage3RejectedReason = 7;
          }
          else
          {
            d.stage3SeqEnabled = true;
            d.stage3SeqBestIdx = d.stage3SelectedIdx;
            d.stage3SeqOtherIdx = d.stage3SeqBestIdx == 1 ? 2 : 1;
            d.stage3SeqWinRelQ = seqParams.winRelQ;
            d.stage3SeqLossRelQ = seqParams.lossRelQ;
            d.stage3SeqAllowLossSkip = seqParams.allowLossSkip;
            d.stage3RejectedReason = 0;
          }
        }
        else
        {
          d.stage3Mask = d.stage3SelectedIdx == 1 ? 0x3 : 0x5;
          d.stage3WouldPrune = true;
          if( stage3Debug == 2 )
          {
            d.stage3Applied = false;
            d.stage3RejectedReason = 7;
          }
          else if( cfg->m_LardLfnst21Stage3Shadow != 0 )
          {
            d.stage3Applied = false;
            d.stage3RejectedReason = 0;
          }
          else
          {
            d.stage3Applied = true;
            d.stage3RejectedReason = 0;
          }
        }
      }
    }
    const auto stage3EvalEnd = std::chrono::steady_clock::now();
    d.stage3EvalNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( stage3EvalEnd - stage3EvalStart ).count();
    if( cfg->m_LardLfnst21Stage3TimingFile[0] != '\0' )
    {
      const int prunedIdx = d.stage3SelectedIdx == 1 ? 2 : ( d.stage3SelectedIdx == 2 ? 1 : 0 );
      if( stage3Mode == 2 )
      {
        xLardSkip21Stage3TimingStore().recordSeqEval( cfg->m_LardLfnst21Stage3TimingFile,
                                                       cu.qp, cu.lwidth(), cu.lheight(),
                                                       d.stage3SeqBestIdx, d.stage3SeqOtherIdx,
                                                       d.stage3DiffQ, d.stage3KeepScoreQ,
                                                       d.stage3EvalNs, d.stage3SeqEnabled );
      }
      else if( cfg->m_LardLfnst21Stage3Shadow != 0 )
      {
        xLardSkip21Stage3TimingStore().recordEval( cfg->m_LardLfnst21Stage3TimingFile,
                                                    cu.qp, cu.lwidth(), cu.lheight(),
                                                    d.stage3SelectedIdx, prunedIdx,
                                                    d.stage3DiffQ, d.stage3KeepScoreQ,
                                                    d.stage3EvalNs, d.stage3WouldPrune );
      }
    }
  }
  d.earlyZero = d.stage1EarlyZero || d.stage2EarlyZero;
  d.actualSource = d.stage1EarlyZero ? 1 : ( d.stage2EarlyZero ? 2 : 0 );
  if( d.earlyZero )
  {
    d.candidateAfter = 0;
  }
  else if( d.stage3Applied )
  {
    d.candidateAfter = 1;
  }
  return d;
}

static bool xLardSkip21EarlyNoNonzero( const VVEncCfg* cfg, const CodingUnit& cu )
{
  return xLardSkip21EarlyDecision( cfg, cu ).earlyZero;
}

static void xLardSkip21AppendStage1Stat( const char* fileName, const CodingUnit& cu, const LardSkip21EarlyDecision& d )
{
  if( !fileName || fileName[0] == '\0' || !d.eligible )
  {
    return;
  }

  static std::mutex s_mutex;
  std::lock_guard<std::mutex> lock( s_mutex );
  std::ifstream existing( fileName, std::ios::binary | std::ios::ate );
  const bool newFile = !existing.good() || existing.tellg() == 0;
  FILE* fp = std::fopen( fileName, "a" );
  if( !fp )
  {
    return;
  }
  if( newFile )
  {
    std::fprintf( fp, "QP,x,y,w,h,latBin,sizeId,modeGroup,setIdx,transpose,supportRatioQ,oxQ,diagDominanceQ,gmaxCovQ,diffCovQ,respGainMaxQ,offdiagRespMaxQ,earlyZero,stage1Decision,stage2Decision,candidateBefore,candidateAfter,stage1WouldZero,stage2WouldZero,actualEarlyZero,actualSource,stage3WouldPrune,stage3ActualApplied,stage3SelectedIdx,stage3Mask,stage3DiffQ,stage3Score1Q,stage3Score2Q,stage3KeepScoreQ,stage3RejectedReason\n" );
  }
  const char* actualSourceName = d.actualSource == 1 ? "stage1" : ( d.actualSource == 2 ? "stage2" : "none" );
  std::fprintf( fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%s,%d,%d,%d,%d,%d,%d,%d,%d,%s\n",
                cu.qp, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(),
                d.latBin, d.sizeId, d.modeGroup, d.setIdx, d.transpose,
                d.supportRatioQ, d.oxQ, d.diagDominanceQ, d.gmaxCovQ, d.diffCovQ,
                d.respGainMaxQ, d.offdiagRespMaxQ,
                d.earlyZero ? 1 : 0, d.stage1EarlyZero ? 1 : 0, d.stage2EarlyZero ? 1 : 0,
                d.candidateBefore, d.candidateAfter,
                d.stage1WouldZero ? 1 : 0, d.stage2WouldZero ? 1 : 0, d.earlyZero ? 1 : 0, actualSourceName,
                d.stage3WouldPrune ? 1 : 0, d.stage3Applied ? 1 : 0, d.stage3SelectedIdx, d.stage3Mask,
                d.stage3DiffQ, d.stage3Score1Q, d.stage3Score2Q, d.stage3KeepScoreQ,
                xLardSkip21Stage3RejectedReasonName( d.stage3RejectedReason ) );
  std::fclose( fp );
}

IntraSearch::LardLfnstCovDecision IntraSearch::xLardLfnstCovDecision( const CodingUnit& cu, const TransformUnit& tu ) const
{
  LardLfnstCovDecision d;
  if( !m_pcEncCfg || ( m_pcEncCfg->m_LardLfnstSkip != 15 && m_pcEncCfg->m_LardLfnstSkip != 16 && m_pcEncCfg->m_LardLfnstSkip != 17 && m_pcEncCfg->m_LardLfnstSkip != 18 ) || !m_pcTrQuant || !m_pcRdCost
      || !tu.blocks[COMP_Y].valid() || tu.mtsIdx[COMP_Y] == MTS_SKIP || cu.ispMode )
  {
    return d;
  }
  d.eligible = true;

  const int width = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
  if( width < 4 || height < 4 )
  {
    return d;
  }
  const bool fastRealSkip18 = xLardSkip18FastRealEnabled( m_pcEncCfg );
  int earlyRejectReason = 0;
  if( fastRealSkip18 && !xLardSkip18EarlyDispatchPass( m_pcEncCfg, cu.qp, width, height, &earlyRejectReason ) )
  {
    d.qpEarlyBypass = earlyRejectReason == 1;
    d.sizeEarlyBypass = earlyRejectReason == 2;
    d.valid = true;
    d.maskPred = 0x7;
    d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
    return d;
  }

  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode >= NUM_INTRA_MODE - 1 )
  {
    return d;
  }
  intraMode = xLard2ndGetIntraMode( tu.blocks[COMP_Y], intraMode );
  const bool transpose = xLard2ndTransposeFlag( intraMode );
  const int lfnstSet = (int)g_lfnstLut[intraMode];
  const int sbSize = width >= 8 && height >= 8 ? 8 : 4;
  const int kIn = sbSize == 8 ? 48 : 16;

  int picH = cu.Y().y + cu.lheight();
  if( cu.cs && cu.cs->pcv )
  {
    picH = cu.cs->pcv->lumaHeight;
  }
  const int latBin = fastRealSkip18 && m_pcEncCfg->m_LardLfnst18OptLevel >= 1
                   ? xLardSkip18LatBinCached( picH, cu.Y().y + ( cu.lheight() >> 1 ) )
                   : xLardLfnstCovLatBin( xLahtpStage1GeomCached( std::max( 1, picH ), cu.Y().y, cu.lheight() ).absLatDeg );
  d.latBin = latBin;
  d.lfnstSet = lfnstSet;
  d.transpose = transpose;
  d.kIn = kIn;
  const bool measureComplexity = m_pcEncCfg->m_LardLfnst18StatFile[0] != '\0';
  const auto metaGateStart = measureComplexity ? std::chrono::steady_clock::now()
                                               : std::chrono::steady_clock::time_point();
  const bool metadataPass = !fastRealSkip18
                         || ( m_pcEncCfg->m_LardLfnst18OptLevel >= 1
                              ? xLardSkip18MetaGatePassFast( cu.qp, width, height, latBin, lfnstSet, transpose )
                              : xLardSkip18MetaGatePass( cu.qp, width, height, latBin, lfnstSet, transpose ) );
  if( measureComplexity )
  {
    const auto metaGateEnd = std::chrono::steady_clock::now();
    d.timeMetaGateNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( metaGateEnd - metaGateStart ).count();
  }
  d.metadataGatePass = metadataPass;
  d.metadataGateReject = !metadataPass;
  if( !metadataPass )
  {
    d.valid = true;
    d.maskPred = 0x7;
    d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
    return d;
  }
  const LardLfnstCovEntry* entry = getLardLfnstCovEntry( latBin, width, height, lfnstSet, transpose );
  if( !entry )
  {
    return d;
  }
  d.tableFound = true;
  d.outN = entry->outN;
  d.kIn = entry->kIn;
  if( fastRealSkip18 && m_pcEncCfg->m_LardLfnst18HighCostOnly != 0
      && ( width * height < 64 || entry->outN != 16 ) )
  {
    d.valid = true;
    d.maskPred = 0x7;
    d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
    return d;
  }

  double responseInput[48] = {};
  bool responseInputReady = false;
  if( fastRealSkip18 && m_pcEncCfg->m_LardLfnst18OptLevel >= 3 )
  {
    const TCoeff* coeff = m_pcTrQuant->getLastTransformCoeffs();
    if( !coeff )
    {
      d.valid = true;
      d.maskPred = 0x7;
      d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
      return d;
    }
    xLard2ndCollectLfnstInput( coeff, width, sbSize, transpose, responseInput, nullptr, nullptr );
    responseInputReady = true;
    d.roiEnergyGate = true;
  }

  const auto cheapGateStart = measureComplexity ? std::chrono::steady_clock::now()
                                                : std::chrono::steady_clock::time_point();
  double sigma2 = 0.0;
  if( responseInputReady )
  {
    double templateEnergy = 0.0;
    for( int i = 0; i < entry->kIn; i++ )
    {
      templateEnergy += std::max( 0.0, (double)entry->varX[i] );
    }
    sigma2 = xLardSkip18RoiEnergy( responseInput, entry->kIn ) / std::max( 1e-9, templateEnergy );
  }
  else
  {
    const CPelBuf resi = tu.cs->getResiBuf( tu.blocks[COMP_Y] );
    double sum = 0.0;
    double sum2 = 0.0;
    const int samples = width * height;
    for( int y = 0; y < height; y++ )
    {
      for( int x = 0; x < width; x++ )
      {
        const double value = (double)resi.at( x, y );
        sum += value;
        sum2 += value * value;
      }
    }
    const double mean = samples > 0 ? sum / (double)samples : 0.0;
    sigma2 = samples > 0 ? std::max( 0.0, sum2 / (double)samples - mean * mean ) : 0.0;
  }
  const double qStep = fastRealSkip18 ? xLahtpQStepCached( cu.qp ) : std::pow( 2.0, ( (double)cu.qp - 4.0 ) / 6.0 );
  const double invQStep2 = 1.0 / ( qStep * qStep + 1e-12 );
  const double lambda = std::max( 0.0, m_pcRdCost->getLambda() );

  double rate0 = 0.0;
  for( int i = 0; i < entry->kIn; i++ )
  {
    const double var = sigma2 * (double)entry->varX[i];
    rate0 += fastRealSkip18 ? xLard2ndTheoryRateFast( var, qStep ) : 0.5 * std::log2( 1.0 + var * invQStep2 );
  }

  d.valid = true;
  d.kIn = entry->kIn;
  d.outN = entry->outN;
  d.sigma2 = sigma2;
  d.qStep = qStep;
  d.lambdaAdjusted = lambda;
  d.lambdaUnadjusted = std::max( 0.0, m_pcRdCost->getLambda( true ) );
  d.rate0 = rate0;
  for( int cand = 0; cand < 2; cand++ )
  {
    double rateL = 1.0;
    for( int i = 0; i < entry->outN; i++ )
    {
      d.predVarY[cand][i] = sigma2 * (double)entry->varY[cand][i];
      rateL += fastRealSkip18 ? xLard2ndTheoryRateFast( d.predVarY[cand][i], qStep )
                              : 0.5 * std::log2( 1.0 + d.predVarY[cand][i] * invQStep2 );
    }
    d.tableZeroOutEnergy[cand] = sigma2 * (double)entry->expZeroEnergy[cand];
    d.tableRetainedEnergy[cand] = sigma2 * (double)entry->expRetainedEnergy[cand];
    d.rateL[cand] = rateL;
    d.predRateGainBits[cand] = rate0 - rateL;
    d.g[cand] = lambda * d.predRateGainBits[cand];
    d.f[cand] = d.g[cand];
  }

  // Phase 4 is measure-only: tauSkip is -infinity, so the recorded mask never removes both candidates.
  d.maskPred = std::fabs( d.f[0] - d.f[1] ) > 0.0 ? ( d.f[0] > d.f[1] ? 0x3 : 0x5 ) : 0x7;

  const double log2W = width > 0 ? std::log2( (double)width ) : 0.0;
  const double log2H = height > 0 ? std::log2( (double)height ) : 0.0;
  double cheapFeat[20] = {};
  cheapFeat[0] = d.g[0];
  cheapFeat[1] = d.g[1];
  cheapFeat[2] = std::max( d.g[0], d.g[1] );
  cheapFeat[3] = std::min( d.g[0], d.g[1] );
  cheapFeat[4] = d.predRateGainBits[0];
  cheapFeat[5] = d.predRateGainBits[1];
  cheapFeat[6] = std::log1p( std::max( 0.0, d.tableZeroOutEnergy[0] ) * invQStep2 );
  cheapFeat[7] = std::log1p( std::max( 0.0, d.tableZeroOutEnergy[1] ) * invQStep2 );
  cheapFeat[8] = std::log1p( std::max( 0.0, d.tableRetainedEnergy[0] ) * invQStep2 );
  cheapFeat[9] = std::log1p( std::max( 0.0, d.tableRetainedEnergy[1] ) * invQStep2 );
  cheapFeat[10] = d.tableZeroOutEnergy[0] / ( d.tableZeroOutEnergy[0] + d.tableRetainedEnergy[0] + 1e-12 );
  cheapFeat[11] = d.tableZeroOutEnergy[1] / ( d.tableZeroOutEnergy[1] + d.tableRetainedEnergy[1] + 1e-12 );
  cheapFeat[12] = std::log1p( sigma2 * invQStep2 );
  cheapFeat[13] = log2W;
  cheapFeat[14] = log2H;
  cheapFeat[15] = (double)latBin;
  cheapFeat[16] = (double)lfnstSet;
  cheapFeat[17] = transpose ? 1.0 : 0.0;
  cheapFeat[18] = d.outN == 8 ? 1.0 : 0.0;
  cheapFeat[19] = d.kIn == 48 ? 1.0 : 0.0;
  double tablePreGateScore = 0.0;
  const bool tablePreGatePass = !fastRealSkip18 || xLardSkip18TablePreGatePass( cu.qp, cheapFeat, &tablePreGateScore );
  (void)tablePreGateScore;
  if( measureComplexity )
  {
    const auto cheapGateEnd = std::chrono::steady_clock::now();
    d.timeCheapGateNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( cheapGateEnd - cheapGateStart ).count();
  }
  d.cheapGatePass = tablePreGatePass;
  d.cheapGateReject = !tablePreGatePass;
  if( !tablePreGatePass )
  {
    d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
    d.maskPred = 0x7;
    return d;
  }

  const auto responseFeatureStart = measureComplexity ? std::chrono::steady_clock::now()
                                                      : std::chrono::steady_clock::time_point();
  d.responsePredictorEntered = true;
  if( !responseInputReady )
  {
    if( const TCoeff* coeff = m_pcTrQuant->getLastTransformCoeffs() )
    {
      xLard2ndCollectLfnstInput( coeff, width, sbSize, transpose, responseInput, nullptr, nullptr );
      responseInputReady = true;
    }
  }
  if( responseInputReady )
  {
    for( int i = 0; i < kIn; i++ )
    {
      d.roiInput[i] = responseInput[i];
      const double value = responseInput[i];
      d.baseRoiEnergy += value * value;
    }
    const LardCovQuantStats baseStats = xLardCovComputeBaseStats( responseInput, entry->kIn, qStep );
    d.baseNnz = baseStats.nnz;
    d.baseLast = baseStats.last;
    d.baseSigDensity = baseStats.sigDensity;
    d.baseLogLevelSum = baseStats.logLevelSum;
    for( int cand = 0; cand < 2; cand++ )
    {
      const bool optimizedResponse = fastRealSkip18 && m_pcEncCfg->m_LardLfnst18OptLevel >= 4;
      const LardCovQuantStats responseStats = optimizedResponse
        ? xLardCovComputeResponseStatsFused( responseInput, entry->kIn, entry->outN, lfnstSet,
                                             cand, sbSize == 8, 1.0 / std::max( 1e-9, qStep ) )
        : xLardCovComputeResponseStats( responseInput, entry->kIn, entry->outN, lfnstSet,
                                        cand, sbSize == 8, qStep );
      d.optimizedResponse = optimizedResponse;
      d.responseRetainedEnergy[cand] = responseStats.retainedEnergy;
      d.responseZeroOutEnergy[cand] = responseStats.zeroOutEnergy;
      d.responseNnz[cand] = responseStats.nnz;
      d.responseZeroNnz[cand] = responseStats.zeroNnz;
      d.responseRetainedNnz[cand] = responseStats.retainedNnz;
      d.responseLast[cand] = responseStats.last;
      d.responseSigSpan[cand] = responseStats.sigSpan;
      d.responseSigDensity[cand] = responseStats.sigDensity;
      d.responseHoleCount[cand] = responseStats.holeCount;
      d.responseLevelSum[cand] = responseStats.levelSum;
      d.responseLogLevelSum[cand] = responseStats.logLevelSum;
      d.responseMaxLevel[cand] = responseStats.maxLevel;
    }
  }
  if( measureComplexity )
  {
    const auto responseFeatureEnd = std::chrono::steady_clock::now();
    d.timeResponseFeatureNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( responseFeatureEnd - responseFeatureStart ).count();
  }
  d.skipThreshold = xLardSkip18ActualQp5Threshold( cu.qp );
  const auto predictScoreStart = measureComplexity ? std::chrono::steady_clock::now()
                                                   : std::chrono::steady_clock::time_point();
  for( int cand = 0; cand < 2; cand++ )
  {
    const double zero = std::max( 0.0, d.responseZeroOutEnergy[cand] );
    const double retained = std::max( 0.0, d.responseRetainedEnergy[cand] );
    const double zeroRatio = zero / ( zero + retained + 1e-12 );
    const double logZeroOutQ = std::log1p( zero * invQStep2 );
    const double logRetainedQ = std::log1p( retained * invQStep2 );
    const double rateFeat[LARD_LFNST_SKIP18_RATE_FEATURES] =
    {
      1.0, d.g[cand], (double)cu.qp, log2W, log2H, d.outN == 8 ? 1.0 : 0.0, d.kIn == 48 ? 1.0 : 0.0, (double)( cand + 1 )
    };
    double distFeat[LARD_LFNST_SKIP18_DIST_FEATURES] = {};
#if LARD_LFNST_SKIP18_DIST_FEATURES == 19
    distFeat[0] = 1.0;
    distFeat[1] = d.g[cand];
    distFeat[2] = logZeroOutQ;
    distFeat[3] = zeroRatio;
    distFeat[4] = logRetainedQ;
    distFeat[5] = d.responseNnz[cand];
    distFeat[6] = d.responseZeroNnz[cand];
    distFeat[7] = d.responseLast[cand];
    distFeat[8] = d.responseSigDensity[cand];
    distFeat[9] = d.responseHoleCount[cand];
    distFeat[10] = d.responseLogLevelSum[cand];
    distFeat[11] = d.responseNnz[cand] - d.baseNnz;
    distFeat[12] = d.responseLast[cand] - d.baseLast;
    distFeat[13] = (double)cu.qp;
    distFeat[14] = log2W;
    distFeat[15] = log2H;
    distFeat[16] = d.outN == 8 ? 1.0 : 0.0;
    distFeat[17] = d.kIn == 48 ? 1.0 : 0.0;
    distFeat[18] = (double)( cand + 1 );
#elif LARD_LFNST_SKIP18_DIST_FEATURES == 12
    distFeat[0] = 1.0;
    distFeat[1] = d.g[cand];
    distFeat[2] = std::log1p( zero );
    distFeat[3] = logZeroOutQ;
    distFeat[4] = zeroRatio;
    distFeat[5] = logRetainedQ;
    distFeat[6] = (double)cu.qp;
    distFeat[7] = log2W;
    distFeat[8] = log2H;
    distFeat[9] = d.outN == 8 ? 1.0 : 0.0;
    distFeat[10] = d.kIn == 48 ? 1.0 : 0.0;
    distFeat[11] = (double)( cand + 1 );
#else
#error Unsupported LARD_LFNST_SKIP18_DIST_FEATURES
#endif
#if LARD_LFNST_SKIP18_QP_BUCKETS > 0
    const double* rateCoeff = LARD_LFNST_SKIP18_RATE_COEFF[cand];
    const double* distCoeff = LARD_LFNST_SKIP18_DIST_COEFF[cand];
    int bestBucket = 0;
    int bestDiff = std::abs( cu.qp - LARD_LFNST_SKIP18_QP_BUCKET[0] );
    for( int bucket = 1; bucket < LARD_LFNST_SKIP18_QP_BUCKETS; bucket++ )
    {
      const int diff = std::abs( cu.qp - LARD_LFNST_SKIP18_QP_BUCKET[bucket] );
      if( diff < bestDiff )
      {
        bestBucket = bucket;
        bestDiff = diff;
      }
    }
    rateCoeff = LARD_LFNST_SKIP18_RATE_COEFF_QP[bestBucket][cand];
    distCoeff = LARD_LFNST_SKIP18_DIST_COEFF_QP[bestBucket][cand];
#else
    const double* rateCoeff = LARD_LFNST_SKIP18_RATE_COEFF[cand];
    const double* distCoeff = LARD_LFNST_SKIP18_DIST_COEFF[cand];
#endif
    for( int i = 0; i < LARD_LFNST_SKIP18_RATE_FEATURES; i++ )
    {
      d.predRateCostGain[cand] += rateCoeff[i] * rateFeat[i];
    }
    for( int i = 0; i < LARD_LFNST_SKIP18_DIST_FEATURES; i++ )
    {
      d.predDistLoss[cand] += distCoeff[i] * distFeat[i];
    }
    d.predDistLoss[cand] = std::max( 0.0, d.predDistLoss[cand] );
    d.predRDGain[cand] = d.predRateCostGain[cand] - d.predDistLoss[cand];
  }
  if( measureComplexity )
  {
    const auto predictScoreEnd = std::chrono::steady_clock::now();
    d.timePredictScoreNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( predictScoreEnd - predictScoreStart ).count();
  }
  if( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 18 )
  {
    d.maskPred = std::max( d.predRDGain[0], d.predRDGain[1] ) <= d.skipThreshold ? 0x1 : 0x7;
  }
  return d;
}

void IntraSearch::xLardLfnstCovAppendLog( const CodingUnit& cu, const LardLfnstCovDecision& d, const int bestLfnstIdx,
                                         const double cost0, const double cost1, const double cost2 ) const
{
  const char* fileName = m_pcEncCfg ? m_pcEncCfg->m_LardLfnstCovLog : nullptr;
  if( !fileName || fileName[0] == '\0' || !d.eligible )
  {
    return;
  }
  static FILE* s_fp = nullptr;
  static std::string s_name;
  static std::mutex s_mutex;
  static uint64_t s_rows = 0;
  std::lock_guard<std::mutex> lock( s_mutex );
  if( s_fp && s_name != fileName )
  {
    std::fclose( s_fp );
    s_fp = nullptr;
    s_name.clear();
    s_rows = 0;
  }
  const uint64_t maxRows = m_pcEncCfg && m_pcEncCfg->m_LardLfnstCovMaxRows > 0
                         ? (uint64_t)m_pcEncCfg->m_LardLfnstCovMaxRows : 0;
  if( maxRows && s_rows >= maxRows )
  {
    return;
  }
  bool writeHeader = false;
  if( !s_fp )
  {
    if( FILE* read = std::fopen( fileName, "rb" ) )
    {
      std::fseek( read, 0, SEEK_END );
      writeHeader = std::ftell( read ) == 0;
      std::fclose( read );
    }
    else
    {
      writeHeader = true;
    }
    s_fp = std::fopen( fileName, "ab" );
    if( !s_fp )
    {
      return;
    }
    s_name = fileName;
  }
  if( writeHeader )
  {
    std::fprintf( s_fp, "POC,x,y,W,H,QP,actualCuQp,modeGroup,tableFound,latBin,setIdx,transpose,sigma2,qStep,qStep2,lambdaAdjusted,lambdaUnadjusted,rate0,rateL1,rateL2,predRateGainBits1,predRateGainBits2,G1_cov,G2_cov,F1,F2,maskPred,J0,J1,J2,bestIdx,deltaJ1,deltaJ2,kIn,outN,sbSize,actualValid1,actualValid2" );
    for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",rdoValid%d", idx );
    std::fprintf( s_fp, ",candidateRdoTimeNs1,candidateRdoTimeNs2" );
    for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",dist%d", idx );
    for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",fracBits%d", idx );
    for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",distCost%d", idx );
    for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",rateCost%d", idx );
    std::fprintf( s_fp, ",inputEnergy1,inputEnergy2,outputEnergy1,outputEnergy2,zeroOutEnergy1,zeroOutEnergy2,tableZeroOutEnergy1,tableZeroOutEnergy2,tableRetainedEnergy1,tableRetainedEnergy2,responseZeroOutEnergy1,responseZeroOutEnergy2,responseRetainedEnergy1,responseRetainedEnergy2" );
    std::fprintf( s_fp, ",responseNnz1,responseNnz2,responseZeroNnz1,responseZeroNnz2,responseRetainedNnz1,responseRetainedNnz2,responseLast1,responseLast2,responseSigSpan1,responseSigSpan2,responseSigDensity1,responseSigDensity2,responseHoleCount1,responseHoleCount2,responseLevelSum1,responseLevelSum2,responseLogLevelSum1,responseLogLevelSum2,responseMaxLevel1,responseMaxLevel2,baseNnz,baseLast,baseSigDensity,baseLogLevelSum,baseRoiEnergy" );
    std::fprintf( s_fp, ",featureZeroOutEnergy1,featureZeroOutEnergy2,featureRetainedEnergy1,featureRetainedEnergy2,zeroOutRatio1,zeroOutRatio2,retainedEnergyRatio1,retainedEnergyRatio2,logZeroOutQ1,logZeroOutQ2,logRetainedQ1,logRetainedQ2" );
    std::fprintf( s_fp, ",predRateCostGain1,predRateCostGain2,predDistLoss1,predDistLoss2,predRDGain1,predRDGain2,trueRateCostGain1,trueRateCostGain2,trueDistLoss1,trueDistLoss2,trueRDGain1,trueRDGain2" );
    for( int cand = 0; cand < 2; cand++ )
    {
      for( int i = 0; i < 16; i++ ) std::fprintf( s_fp, ",actualY%dSq_%02d", cand + 1, i );
      for( int i = 0; i < 16; i++ ) std::fprintf( s_fp, ",predVarY%d_%02d", cand + 1, i );
    }
    std::fprintf( s_fp, "\n" );
  }
  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  const double gain1 = cost0 < MAX_DOUBLE * 0.5 && cost1 < MAX_DOUBLE * 0.5 ? cost0 - cost1 : 0.0;
  const double gain2 = cost0 < MAX_DOUBLE * 0.5 && cost2 < MAX_DOUBLE * 0.5 ? cost0 - cost2 : 0.0;
  const double qStep2 = d.qStep * d.qStep;
  const int sbSize = d.kIn == 48 ? 8 : ( d.kIn == 16 ? 4 : 0 );
  double zeroOutRatio[2] = { 0.0, 0.0 };
  double logZeroOutQ[2] = { 0.0, 0.0 };
  double logRetainedQ[2] = { 0.0, 0.0 };
  double predRateCostGain[2] = { 0.0, 0.0 };
  double predDistLoss[2] = { 0.0, 0.0 };
  double predRDGain[2] = { 0.0, 0.0 };
  double trueRateCostGain[2] = { 0.0, 0.0 };
  double trueDistLoss[2] = { 0.0, 0.0 };
  double trueRDGain[2] = { gain1, gain2 };
  const double log2W = cu.lwidth() > 0 ? std::log2( (double)cu.lwidth() ) : 0.0;
  const double log2H = cu.lheight() > 0 ? std::log2( (double)cu.lheight() ) : 0.0;
  const bool useSkip17TableEnergy = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 17;
  const bool useSkip18ResponseEnergy = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 18;
  for( int cand = 0; cand < 2; cand++ )
  {
    const double zero = std::max( 0.0, useSkip18ResponseEnergy ? d.responseZeroOutEnergy[cand] : ( useSkip17TableEnergy ? d.tableZeroOutEnergy[cand] : d.zeroOutEnergy[cand] ) );
    const double retained = std::max( 0.0, useSkip18ResponseEnergy ? d.responseRetainedEnergy[cand] : ( useSkip17TableEnergy ? d.tableRetainedEnergy[cand] : d.outputEnergy[cand] ) );
    zeroOutRatio[cand] = zero / ( zero + retained + 1e-12 );
    logZeroOutQ[cand] = std::log1p( zero / ( qStep2 + 1e-12 ) );
    logRetainedQ[cand] = std::log1p( retained / ( qStep2 + 1e-12 ) );
    const double rateFeat[LARD_LFNST_SKIP16_RATE_FEATURES] =
    {
      1.0, d.g[cand], (double)cu.qp, log2W, log2H, d.outN == 8 ? 1.0 : 0.0, d.kIn == 48 ? 1.0 : 0.0, (double)( cand + 1 )
    };
    const double distFeat[LARD_LFNST_SKIP16_DIST_FEATURES] =
    {
      1.0, d.g[cand], std::log1p( zero ), logZeroOutQ[cand], zeroOutRatio[cand], logRetainedQ[cand],
      (double)cu.qp, log2W, log2H, d.outN == 8 ? 1.0 : 0.0, d.kIn == 48 ? 1.0 : 0.0, (double)( cand + 1 )
    };
    double skip18DistFeat[LARD_LFNST_SKIP18_DIST_FEATURES] = {};
#if LARD_LFNST_SKIP18_DIST_FEATURES == 19
    skip18DistFeat[0] = 1.0;
    skip18DistFeat[1] = d.g[cand];
    skip18DistFeat[2] = logZeroOutQ[cand];
    skip18DistFeat[3] = zeroOutRatio[cand];
    skip18DistFeat[4] = logRetainedQ[cand];
    skip18DistFeat[5] = d.responseNnz[cand];
    skip18DistFeat[6] = d.responseZeroNnz[cand];
    skip18DistFeat[7] = d.responseLast[cand];
    skip18DistFeat[8] = d.responseSigDensity[cand];
    skip18DistFeat[9] = d.responseHoleCount[cand];
    skip18DistFeat[10] = d.responseLogLevelSum[cand];
    skip18DistFeat[11] = d.responseNnz[cand] - d.baseNnz;
    skip18DistFeat[12] = d.responseLast[cand] - d.baseLast;
    skip18DistFeat[13] = (double)cu.qp;
    skip18DistFeat[14] = log2W;
    skip18DistFeat[15] = log2H;
    skip18DistFeat[16] = d.outN == 8 ? 1.0 : 0.0;
    skip18DistFeat[17] = d.kIn == 48 ? 1.0 : 0.0;
    skip18DistFeat[18] = (double)( cand + 1 );
#elif LARD_LFNST_SKIP18_DIST_FEATURES == 12
    for( int i = 0; i < LARD_LFNST_SKIP18_DIST_FEATURES; i++ )
    {
      skip18DistFeat[i] = distFeat[i];
    }
#else
#error Unsupported LARD_LFNST_SKIP18_DIST_FEATURES
#endif
#if LARD_LFNST_SKIP18_QP_BUCKETS > 0
    const double* skip18RateCoeff = LARD_LFNST_SKIP18_RATE_COEFF[cand];
    const double* skip18DistCoeff = LARD_LFNST_SKIP18_DIST_COEFF[cand];
    if( useSkip18ResponseEnergy )
    {
      int bestBucket = 0;
      int bestDiff = std::abs( cu.qp - LARD_LFNST_SKIP18_QP_BUCKET[0] );
      for( int bucket = 1; bucket < LARD_LFNST_SKIP18_QP_BUCKETS; bucket++ )
      {
        const int diff = std::abs( cu.qp - LARD_LFNST_SKIP18_QP_BUCKET[bucket] );
        if( diff < bestDiff )
        {
          bestDiff = diff;
          bestBucket = bucket;
        }
      }
      skip18RateCoeff = LARD_LFNST_SKIP18_RATE_COEFF_QP[bestBucket][cand];
      skip18DistCoeff = LARD_LFNST_SKIP18_DIST_COEFF_QP[bestBucket][cand];
    }
#else
    const double* skip18RateCoeff = LARD_LFNST_SKIP18_RATE_COEFF[cand];
    const double* skip18DistCoeff = LARD_LFNST_SKIP18_DIST_COEFF[cand];
#endif
    for( int i = 0; i < LARD_LFNST_SKIP16_RATE_FEATURES; i++ )
    {
      predRateCostGain[cand] += ( useSkip18ResponseEnergy ? skip18RateCoeff[i] : ( useSkip17TableEnergy ? LARD_LFNST_SKIP17_RATE_COEFF[cand][i] : LARD_LFNST_SKIP16_RATE_COEFF[cand][i] ) ) * rateFeat[i];
    }
    if( useSkip18ResponseEnergy )
    {
      for( int i = 0; i < LARD_LFNST_SKIP18_DIST_FEATURES; i++ )
      {
        predDistLoss[cand] += skip18DistCoeff[i] * skip18DistFeat[i];
      }
    }
    else
    {
      for( int i = 0; i < LARD_LFNST_SKIP16_DIST_FEATURES; i++ )
      {
        predDistLoss[cand] += ( useSkip17TableEnergy ? LARD_LFNST_SKIP17_DIST_COEFF[cand][i] : LARD_LFNST_SKIP16_DIST_COEFF[cand][i] ) * distFeat[i];
      }
    }
    predDistLoss[cand] = std::max( 0.0, predDistLoss[cand] );
    predRDGain[cand] = predRateCostGain[cand] - predDistLoss[cand];
    if( d.rdoValid[0] && d.rdoValid[cand + 1] )
    {
      trueRateCostGain[cand] = d.actualRateCost[0] - d.actualRateCost[cand + 1];
      trueDistLoss[cand] = d.actualDistCost[cand + 1] - d.actualDistCost[0];
    }
  }
  std::fprintf( s_fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%d,%.17g,%.17g,%.17g,%d,%.17g,%.17g,%d,%d,%d,%d,%d",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, cu.qp,
                xLahtpModeGroupId( cu.intraDir[CH_L] ), d.valid ? 1 : 0, d.latBin, d.lfnstSet, d.transpose ? 1 : 0,
                d.sigma2, d.qStep, qStep2, d.lambdaAdjusted, d.lambdaUnadjusted, d.rate0, d.rateL[0], d.rateL[1],
                d.predRateGainBits[0], d.predRateGainBits[1], d.g[0], d.g[1], d.f[0], d.f[1], d.maskPred,
                cost0, cost1, cost2, bestLfnstIdx, gain1, gain2, d.kIn, d.outN,
                sbSize, d.actualValid[0] ? 1 : 0, d.actualValid[1] ? 1 : 0 );
  for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",%d", d.rdoValid[idx] ? 1 : 0 );
  std::fprintf( s_fp, ",%llu,%llu",
                (unsigned long long)d.actualRdoTimeNs[1],
                (unsigned long long)d.actualRdoTimeNs[2] );
  for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",%llu", (unsigned long long)d.actualDist[idx] );
  for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",%llu", (unsigned long long)d.actualFracBits[idx] );
  for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",%.17g", d.actualDistCost[idx] );
  for( int idx = 0; idx < 3; idx++ ) std::fprintf( s_fp, ",%.17g", d.actualRateCost[idx] );
  const double featureZero0 = useSkip18ResponseEnergy ? d.responseZeroOutEnergy[0] : ( useSkip17TableEnergy ? d.tableZeroOutEnergy[0] : d.zeroOutEnergy[0] );
  const double featureZero1 = useSkip18ResponseEnergy ? d.responseZeroOutEnergy[1] : ( useSkip17TableEnergy ? d.tableZeroOutEnergy[1] : d.zeroOutEnergy[1] );
  const double featureRetained0 = useSkip18ResponseEnergy ? d.responseRetainedEnergy[0] : ( useSkip17TableEnergy ? d.tableRetainedEnergy[0] : d.outputEnergy[0] );
  const double featureRetained1 = useSkip18ResponseEnergy ? d.responseRetainedEnergy[1] : ( useSkip17TableEnergy ? d.tableRetainedEnergy[1] : d.outputEnergy[1] );
  std::fprintf( s_fp, ",%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g",
                d.inputEnergy[0], d.inputEnergy[1], d.outputEnergy[0], d.outputEnergy[1],
                d.zeroOutEnergy[0], d.zeroOutEnergy[1],
                d.tableZeroOutEnergy[0], d.tableZeroOutEnergy[1],
                d.tableRetainedEnergy[0], d.tableRetainedEnergy[1],
                d.responseZeroOutEnergy[0], d.responseZeroOutEnergy[1],
                d.responseRetainedEnergy[0], d.responseRetainedEnergy[1] );
  std::fprintf( s_fp, ",%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g",
                d.responseNnz[0], d.responseNnz[1],
                d.responseZeroNnz[0], d.responseZeroNnz[1],
                d.responseRetainedNnz[0], d.responseRetainedNnz[1],
                d.responseLast[0], d.responseLast[1],
                d.responseSigSpan[0], d.responseSigSpan[1],
                d.responseSigDensity[0], d.responseSigDensity[1],
                d.responseHoleCount[0], d.responseHoleCount[1],
                d.responseLevelSum[0], d.responseLevelSum[1],
                d.responseLogLevelSum[0], d.responseLogLevelSum[1],
                d.responseMaxLevel[0], d.responseMaxLevel[1],
                d.baseNnz, d.baseLast, d.baseSigDensity, d.baseLogLevelSum );
  std::fprintf( s_fp, ",%.17g", d.baseRoiEnergy );
  std::fprintf( s_fp, ",%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g",
                featureZero0, featureZero1, featureRetained0, featureRetained1,
                zeroOutRatio[0], zeroOutRatio[1],
                d.retainedEnergyRatio[0], d.retainedEnergyRatio[1],
                logZeroOutQ[0], logZeroOutQ[1], logRetainedQ[0], logRetainedQ[1] );
  std::fprintf( s_fp, ",%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g",
                predRateCostGain[0], predRateCostGain[1], predDistLoss[0], predDistLoss[1],
                predRDGain[0], predRDGain[1],
                trueRateCostGain[0], trueRateCostGain[1], trueDistLoss[0], trueDistLoss[1],
                trueRDGain[0], trueRDGain[1] );
  for( int cand = 0; cand < 2; cand++ )
  {
    for( int i = 0; i < 16; i++ )
    {
      const double value = (double)d.actualOutput[cand][i];
      std::fprintf( s_fp, ",%.9g", value * value );
    }
    for( int i = 0; i < 16; i++ ) std::fprintf( s_fp, ",%.9g", d.predVarY[cand][i] );
  }
  std::fprintf( s_fp, "\n" );
  s_rows++;
}

void IntraSearch::xLardLfnstCovAppendTrace( const CodingUnit& cu, const LardLfnstCovDecision& d ) const
{
  const char* fileName = m_pcEncCfg ? m_pcEncCfg->m_LardLfnstCovTrace : nullptr;
  if( !fileName || fileName[0] == '\0' || !d.valid )
  {
    return;
  }
  static FILE* s_fp = nullptr;
  static std::string s_name;
  static std::mutex s_mutex;
  static uint64_t s_rows = 0;
  std::lock_guard<std::mutex> lock( s_mutex );
  if( s_fp && s_name != fileName )
  {
    std::fclose( s_fp );
    s_fp = nullptr;
    s_name.clear();
    s_rows = 0;
  }
  constexpr uint64_t maxTraceRows = 50000;
  if( s_rows >= maxTraceRows )
  {
    return;
  }
  bool writeHeader = false;
  if( !s_fp )
  {
    if( FILE* read = std::fopen( fileName, "rb" ) )
    {
      std::fseek( read, 0, SEEK_END );
      writeHeader = std::ftell( read ) == 0;
      std::fclose( read );
    }
    else
    {
      writeHeader = true;
    }
    s_fp = std::fopen( fileName, "ab" );
    if( !s_fp )
    {
      return;
    }
    s_name = fileName;
  }
  if( writeHeader )
  {
    std::fprintf( s_fp, "POC,x,y,W,H,QP,tableFound,latBin,setIdx,transpose,kIn,outN,actualValid1,actualValid2" );
    for( int cand = 0; cand < 2; cand++ )
    {
      for( int i = 0; i < 48; i++ ) std::fprintf( s_fp, ",actualX%d_%02d", cand + 1, i );
      for( int i = 0; i < 48; i++ ) std::fprintf( s_fp, ",actualRaw%d_%02d", cand + 1, i );
      for( int i = 0; i < 16; i++ ) std::fprintf( s_fp, ",actualY%d_%02d", cand + 1, i );
    }
    std::fprintf( s_fp, "\n" );
  }
  const int poc = cu.cs && cu.cs->picture ? cu.cs->picture->getPOC() : -1;
  std::fprintf( s_fp, "%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
                poc, cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp, d.valid ? 1 : 0,
                d.latBin, d.lfnstSet, d.transpose ? 1 : 0, d.kIn, d.outN,
                d.actualValid[0] ? 1 : 0, d.actualValid[1] ? 1 : 0 );
  for( int cand = 0; cand < 2; cand++ )
  {
    for( int i = 0; i < 48; i++ ) std::fprintf( s_fp, ",%d", d.actualInput[cand][i] );
    for( int i = 0; i < 48; i++ ) std::fprintf( s_fp, ",%d", d.actualRawRoi[cand][i] );
    for( int i = 0; i < 16; i++ ) std::fprintf( s_fp, ",%d", d.actualOutput[cand][i] );
  }
  std::fprintf( s_fp, "\n" );
  s_rows++;
}

IntraSearch::LardLfnst2ndDecision IntraSearch::xLardLfnst2ndRespDecision( const CodingUnit& cu, const TransformUnit& tu, const LahtpFeatures& f, const int dct2CostBin ) const
{
  LardLfnst2ndDecision d;
  d.valid = false;
  d.mask  = 0x7;
  Lard2ndCountScope countScope( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr, cu.qp );

  const bool secondResponseStatsOnly = m_pcEncCfg
                                    && m_pcEncCfg->m_LardLfnstSkip == 0
                                    && m_pcEncCfg->m_LardLfnst2ndMeasureOnly != 0
                                    && m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] != '\0';
  const bool theorySpaceSkip = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 14;
  const bool t10SpaceSkip = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 19;
  const bool theoryResponseSkip = theorySpaceSkip || t10SpaceSkip;
  if( !m_pcEncCfg || !m_pcTrQuant || !m_pcRdCost
   || ( m_pcEncCfg->m_LardLfnstSkip != 10 && m_pcEncCfg->m_LardLfnstSkip != 11 && m_pcEncCfg->m_LardLfnstSkip != 13
     && !theoryResponseSkip && !secondResponseStatsOnly )
   || !tu.blocks[COMP_Y].valid() )
  {
    return d;
  }

  const int width  = (int)tu.blocks[COMP_Y].width;
  const int height = (int)tu.blocks[COMP_Y].height;
  if( width < 4 || height < 4 || tu.mtsIdx[COMP_Y] == MTS_SKIP || cu.ispMode )
  {
    return d;
  }
  if( t10SpaceSkip && cu.qp > m_pcEncCfg->m_LardLfnst19MaxCuQp
   && m_pcEncCfg->m_LardLfnst2ndStatFile[0] == '\0'
   && m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] == '\0' )
  {
    return d;
  }
  if( theorySpaceSkip && xLard14DecisionModeForQp( m_pcEncCfg, cu.qp ) == 4 && xLard14NoDecisionTrace( m_pcEncCfg ) )
  {
    return d;
  }
  if( countScope.enabled() )
  {
    countScope.row().basicEligible.fetch_add( 1, std::memory_order_relaxed );
  }
  if( !theoryResponseSkip && !f.stage1 )
  {
    if( countScope.enabled() )
    {
      countScope.row().stage1Reject.fetch_add( 1, std::memory_order_relaxed );
    }
    return d;
  }
  if( countScope.enabled() )
  {
    countScope.row().stage1Pass.fetch_add( 1, std::memory_order_relaxed );
  }

  uint32_t intraMode = CU::getFinalIntraMode( cu, CH_L );
  if( CU::isMIP( cu, CH_L ) )
  {
    intraMode = PLANAR_IDX;
  }
  if( intraMode >= NUM_INTRA_MODE - 1 )
  {
    return d;
  }

  intraMode = xLard2ndGetIntraMode( tu.blocks[COMP_Y], intraMode );
  const bool transposeFlag = xLard2ndTransposeFlag( intraMode );
  const bool whge3         = width >= 8 && height >= 8;
  const int  sbSize        = whge3 ? 8 : 4;
  const int  trSize        = whge3 ? 48 : 16;
  const int  zeroOutSize   = ( ( width == 4 && height == 4 ) || ( width == 8 && height == 8 ) ) ? 8 : 16;
  const int  lfnstSet      = (int)g_lfnstLut[intraMode];
  const int  modeGroup     = xLahtpModeGroupId( cu.intraDir[CH_L] );
  const bool statsEnabled = m_pcEncCfg->m_LardLfnst2ndStatFile[0] != '\0';
  const bool finalStatsEnabled = m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] != '\0';
  const int ablation = theorySpaceSkip ? std::min( 4, std::max( 0, m_pcEncCfg->m_LardLfnst14Ablation ) ) : 0;
  const int t10Profile = t10SpaceSkip ? std::min( 4, std::max( 0, m_pcEncCfg->m_LardLfnst19Profile ) ) : 0;
  const bool t10HybridProfile = t10SpaceSkip && t10Profile == 4;
  double nzMargin = 0.0;
  double rateMargin = 0.0;
  double obsGate14 = -1.0e9;
  int decisionMode = theorySpaceSkip ? xLard14DecisionModeForQp( m_pcEncCfg, cu.qp, &nzMargin, &rateMargin, &obsGate14 ) : 0;
  if( t10HybridProfile )
  {
    decisionMode = xLard19QpScheduleMode( cu.qp, nzMargin, rateMargin );
  }

  if( theorySpaceSkip && m_pcEncCfg->m_LardLfnst14PositiveBinsOnly )
  {
    const int areaGroup = xLard2ndAreaGroup( width * height );
    const bool qpBin    = cu.qp <= 24;                              // input QP 22/27 in the current AI setup
    const bool sizeBin  = areaGroup == 1 || areaGroup == 2;          // A64 / A256
    const bool modeBin  = modeGroup == 0 || modeGroup >= 2;          // planar / angular, excluding DC
    if( !( qpBin && sizeBin && modeBin ) )
    {
      return d;
    }
  }

  if( theoryResponseSkip && !statsEnabled && !finalStatsEnabled
   && ( ( theorySpaceSkip && ( ablation == 1 || decisionMode == 1 ) ) || ( t10SpaceSkip && t10Profile == 0 ) ) )
  {
    d.valid = true;
    d.mask = 0x7;
    d.rawMask = 0x7;
    d.modeGroup = modeGroup;
    d.lfnstSet = lfnstSet;
    d.sbSize = sbSize;
    d.trSize = trSize;
    d.thetaMaxDeg = f.thetaMaxDeg;
    const int uLowFreq = std::min( width, height ) == 4 ? 4 : 8;
    const double phi = xLahtpClipD( 0.0, 90.0, f.absLatDeg ) * 3.14159265358979323846 / 180.0;
    const int mh = (int)std::floor( (double)uLowFreq * std::cos( phi ) + 1e-9 );
    d.theoryMh = (double)mh;
    if( mh < 2 )
    {
      d.mask = 0x1;
      d.rawMask = 0x1;
      d.theoryReason = 1;
      if( countScope.enabled() )
      {
        countScope.row().fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
      }
    }
    else
    {
      d.theoryReason = 0;
    }
    return d;
  }

  const TCoeff* trCoeff = m_pcTrQuant->getLastTransformCoeffs();
  if( !trCoeff )
  {
    if( countScope.enabled() )
    {
      countScope.row().noTransformCoeff.fetch_add( 1, std::memory_order_relaxed );
    }
    return d;
  }

  const double obsGate = m_pcEncCfg->m_LardLfnst2ndObsGate;
  const bool obsOnlyFastPath = !theoryResponseSkip && !statsEnabled && obsGate > -1.0e8 && m_pcEncCfg->m_LardLfnst2ndObsOnly;

  double input[48];
  int uPos[48];
  int vPos[48];
  double inputEnergy = 0.0;
  xLard2ndCollectLfnstInput( trCoeff, width, sbSize, transposeFlag, input,
                             obsOnlyFastPath ? nullptr : uPos,
                             obsOnlyFastPath ? nullptr : vPos,
                             &inputEnergy );
  d.inputEnergy  = inputEnergy;
  d.thetaMaxDeg  = f.thetaMaxDeg;
  d.offdiagProxy = xLard2ndOffdiagProxyFromInput( input, trSize );
  d.modeGroup    = modeGroup;
  d.lfnstSet     = lfnstSet;
  d.sbSize       = sbSize;
  d.trSize       = trSize;
  for( int i = 0; i < 48; i++ )
  {
    d.input[i] = i < trSize ? input[i] : 0.0;
  }
  if( inputEnergy <= 0.0 )
  {
    d.valid = true;
    d.mask  = 0x1;
    if( countScope.enabled() )
    {
      countScope.row().zeroEnergySkip.fetch_add( 1, std::memory_order_relaxed );
    }
    return d;
  }

  const double qStep = std::max( 1e-6, xLahtpQStepCached( cu.qp ) );
  const double rIdx  = std::max( 0.0,  m_pcEncCfg->m_LardLfnst2ndRidx );
  const double lambda = std::max( 0.0, m_pcRdCost->getLambda() );
  const int recallGuardMode = theorySpaceSkip ? std::min( 2, std::max( 0, m_pcEncCfg->m_LardLfnst14RecallGuard ) ) : 0;
  const bool needObservedResponse = !theoryResponseSkip || statsEnabled || finalStatsEnabled
                                 || ( ablation == 0 && decisionMode == 2 && obsGate14 > -1.0e8 )
                                 || ( recallGuardMode == 2 && m_pcEncCfg->m_LardLfnst2ndScoreTable != 0 );
  const double obsRate0 = needObservedResponse ? xLard2ndProxyRateFromVector( input, trSize, qStep, 0.0 ) : 0.0;
  d.obsRate0 = obsRate0;

  double obsGain[2] = { 0.0, 0.0 };
  if( needObservedResponse )
  {
    for( int cand = 0; cand < 2; cand++ )
    {
      const int8_t* fwdMat = sbSize > 4 ? g_lfnstFwd8x8[lfnstSet][cand][0] : g_lfnstFwd4x4[lfnstSet][cand][0];
      const double obsRateL = xLard2ndProxyRateFromLfnstResponse( input, trSize, fwdMat, zeroOutSize, qStep, rIdx );
      obsGain[cand] = lambda * ( obsRate0 - obsRateL );
    }
  }

  const double maxObsGain = std::max( obsGain[0], obsGain[1] );
  if( theoryResponseSkip )
  {
    d.valid = true;
    d.mask = 0x7;
    d.rawMask = 0x7;
    d.obs1 = obsGain[0];
    d.obs2 = obsGain[1];
    const int uLowFreq = std::min( width, height ) == 4 ? 4 : 8;
    const double phi = xLahtpClipD( 0.0, 90.0, f.absLatDeg ) * 3.14159265358979323846 / 180.0;
    const int mh = (int)std::floor( (double)uLowFreq * std::cos( phi ) + 1e-9 );
    d.theoryMh = (double)mh;
    if( mh < 2 && ( t10SpaceSkip || ablation == 0 || ablation == 1 ) )
    {
      d.mask = 0x1;
      d.rawMask = 0x1;
      d.theoryReason = 1;
      if( countScope.enabled() )
      {
        countScope.row().fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
      }
      xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                           inputEnergy, f.thetaMaxDeg, 0.0, d.rate0, obsRate0,
                           d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate,
                           d.theoryReason, d.theoryMh, d.theoryMajorMargin1, d.theoryMajorMargin2,
                           d.theoryRate1, d.theoryRate2 );
      return d;
    }
    if( ( theorySpaceSkip && ( ablation == 1 || ( ablation == 0 && decisionMode == 1 ) ) )
     || ( t10SpaceSkip && t10Profile == 0 ) )
    {
      d.theoryReason = 0;
      return d;
    }

    const bool t10TableFastPath = t10SpaceSkip
                               && ( ( t10Profile > 0 && t10Profile < 4 )
                                 || ( t10HybridProfile && cu.qp > 26 && cu.qp <= 31 ) );
    if( t10TableFastPath )
    {
      const double sigmaBase = inputEnergy / (double)trSize;
      const int latBucket = xLardLfnstLatBucketId( f.absLatDeg );
      const int aBin = xLard2ndTheoryABin( sigmaBase, qStep );
      const LardLfnstTheoryStatsEntry* th[2] =
      {
        xLard2ndFindTheoryStatsEntry( latBucket, width, height, transposeFlag, zeroOutSize, lfnstSet, 1, aBin ),
        xLard2ndFindTheoryStatsEntry( latBucket, width, height, transposeFlag, zeroOutSize, lfnstSet, 2, aBin )
      };
      if( th[0] && th[1] )
      {
        const double score1 = qStep * qStep * th[0]->deltaDNorm + lambda * ( th[0]->deltaR + 1.0 - rIdx );
        const double score2 = qStep * qStep * th[1]->deltaDNorm + lambda * ( th[1]->deltaR + 1.0 - rIdx );
        d.rate0 = th[0]->rate0;
        d.theoryRate1 = th[0]->rateL;
        d.theoryRate2 = th[1]->rateL;
        d.theoryNz0 = th[0]->rate0;
        d.theoryNz1 = th[0]->rateL;
        d.theoryNz2 = th[1]->rateL;
        d.g1 = score1;
        d.g2 = score2;
        d.f1 = score1;
        d.f2 = score2;
        const int tablePolicyProfile = t10HybridProfile ? 2 : t10Profile;
        d.mask = xLard19DecisionMask( tablePolicyProfile, mh, score1, score2,
                                      th[0]->rate0, th[0]->rateL, th[1]->rateL,
                                      m_pcEncCfg->m_LardLfnst19SingleMargin,
                                      m_pcEncCfg->m_LardLfnst19ZeroMargin );
      }
      else
      {
        d.mask = 0x7;
      }
      d.rawMask = d.mask;
      d.theoryReason = d.mask == 0x1 ? 3 : ( d.mask == 0x7 ? 0 : 4 );
      if( countScope.enabled() )
      {
        Lard2ndCountRow& row = countScope.row();
        if( d.mask == 0x1 )
        {
          row.fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( d.mask == 0x3 )
        {
          row.fullModelKeep1.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( d.mask == 0x5 )
        {
          row.fullModelKeep2.fetch_add( 1, std::memory_order_relaxed );
        }
        else
        {
          row.fullModelFull.fetch_add( 1, std::memory_order_relaxed );
        }
      }
      xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                           inputEnergy, f.thetaMaxDeg, d.corrStrength, d.rate0, obsRate0,
                           d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate,
                           d.theoryReason, d.theoryMh, d.theoryMajorMargin1, d.theoryMajorMargin2,
                           d.theoryRate1, d.theoryRate2, d.theoryNz0, d.theoryNz1, d.theoryNz2,
                           d.theoryMajorMask );
      return d;
    }

    double var0[48] = {};
    double var0Active[16] = {};
    for( int i = 0; i < trSize; i++ )
    {
      var0[i] = input[i] * input[i];
      if( i < zeroOutSize )
      {
        var0Active[i] = var0[i];
      }
    }

    const int sizeGroup = xLahtpSizeGroupId( cu.lwidth(), cu.lheight() );
    const int latBucket = xLardLfnstLatBucketId( f.absLatDeg );
    const int sbClass   = sbSize > 4 ? 1 : 0;
    const LardLfnst2ndCorrTableEntry* corrTableEntry = m_pcEncCfg->m_LardLfnst2ndCorrTable
                                                     ? xLard2ndFindCorrTableEntry( latBucket, modeGroup, sizeGroup, sbClass, trSize )
                                                     : nullptr;
    const bool useCorrTable = corrTableEntry != nullptr;
    d.corrStrength = useCorrTable ? 1.0 : 0.0;

    const bool needMajorization = theorySpaceSkip && ( ablation == 2 || statsEnabled || finalStatsEnabled );
    const bool needNzMetric = t10SpaceSkip || ablation == 0 || ablation == 3 || statsEnabled || finalStatsEnabled;
    const bool needRateMetric = t10SpaceSkip || ablation == 0 || ablation == 4 || statsEnabled || finalStatsEnabled;

    double rate0 = 0.0;
    double nz0 = 0.0;
    if( needNzMetric && needRateMetric )
    {
      for( int i = 0; i < zeroOutSize; i++ )
      {
        double r = 0.0;
        double n = 0.0;
        xLard2ndTheoryMetricsFast( var0Active[i], qStep, r, n );
        rate0 += r;
        nz0 += n;
      }
    }
    else if( needNzMetric )
    {
      for( int i = 0; i < zeroOutSize; i++ )
      {
        nz0 += xLard2ndTheoryNzFast( var0Active[i], qStep );
      }
    }
    else if( needRateMetric )
    {
      for( int i = 0; i < zeroOutSize; i++ )
      {
        rate0 += xLard2ndTheoryRateFast( var0Active[i], qStep );
      }
    }
    d.rate0 = rate0;
    d.theoryNz0 = nz0;

    double varL[2][16] = {};
    double rateL[2] = { 0.0, 0.0 };
    double nzL[2] = { 0.0, 0.0 };
    bool majorized[2] = { false, false };
    for( int cand = 0; cand < 2; cand++ )
    {
      const Lard2ndLookup& lookup = xLard2ndGetLookup( lfnstSet, cand, sbSize, zeroOutSize );
      rateL[cand] = needRateMetric ? rIdx : 0.0;
      for( int row = 0; row < zeroOutSize; row++ )
      {
        double var = 0.0;
        for( int col = 0; col < trSize; col++ )
        {
          var += lookup.respVarW[row][col] * var0[col];
        }
        if( useCorrTable )
        {
          for( int col = 0; col + 1 < trSize; col++ )
          {
            for( int col2 = col + 1; col2 < trSize; col2++ )
            {
              const double corr = xLard2ndCorrTableCoeff( corrTableEntry, col, col2 );
              const double cov  = corr * std::sqrt( std::max( 0.0, var0[col] * var0[col2] ) );
              var += 2.0 * lookup.respCorrW[row][col][col2] * cov;
            }
          }
        }
        varL[cand][row] = std::max( 0.0, var );
        if( needNzMetric && needRateMetric )
        {
          double r = 0.0;
          double n = 0.0;
          xLard2ndTheoryMetricsFast( varL[cand][row], qStep, r, n );
          rateL[cand] += r;
          nzL[cand] += n;
        }
        else if( needNzMetric )
        {
          nzL[cand] += xLard2ndTheoryNzFast( varL[cand][row], qStep );
        }
        else if( needRateMetric )
        {
          rateL[cand] += xLard2ndTheoryRateFast( varL[cand][row], qStep );
        }
      }
      if( needMajorization )
      {
        double margin = 0.0;
        majorized[cand] = xLard2ndIsMajorizedBy( varL[cand], var0Active, zeroOutSize, margin );
        if( !majorized[cand] )
        {
          d.theoryMajorMask |= 1 << ( cand + 1 );
        }
        if( cand == 0 )
        {
          d.theoryMajorMargin1 = margin;
        }
        else
        {
          d.theoryMajorMargin2 = margin;
        }
      }
    }

    d.theoryRate1 = rateL[0];
    d.theoryRate2 = rateL[1];
    d.theoryNz1 = nzL[0];
    d.theoryNz2 = nzL[1];
    d.g1 = rate0 - rateL[0];
    d.g2 = rate0 - rateL[1];
    d.f1 = d.g1;
    d.f2 = d.g2;

    d.mask = 0x1;
    if( ablation == 0 && decisionMode == 2 && obsGate14 > -1.0e8 && maxObsGain >= obsGate14 )
    {
      d.mask = 0x7;
      d.safeGate = true;
    }
    for( int cand = 0; cand < 2; cand++ )
    {
      bool keep = false;
      if( ablation == 2 )
      {
        keep = !majorized[cand];
      }
      else if( ablation == 3 )
      {
        keep = nzL[cand] < nz0;
      }
      else if( ablation == 4 )
      {
        keep = ( cand == 0 ? d.g1 : d.g2 ) > 0.0;
      }
      else if( decisionMode == 2 )
      {
        const double nzDiff = nzL[cand] - nz0;
        const double gain   = cand == 0 ? d.g1 : d.g2;
        keep = d.safeGate || !( nzDiff >= nzMargin && gain <= -rateMargin );
      }
      else
      {
        keep = nzL[cand] < nz0 && ( cand == 0 ? d.g1 : d.g2 ) > 0.0;
      }
      if( keep )
      {
        d.mask |= 1 << ( cand + 1 );
      }
    }
    if( t10HybridProfile && d.mask == 0x7 )
    {
      d.mask = xLard19DecisionMask( 2, mh, d.g1, d.g2, nz0, nzL[0], nzL[1],
                                    m_pcEncCfg->m_LardLfnst19SingleMargin, 0.0 );
    }
    d.rawMask = d.mask;
    bool recallGuarded = false;
    if( ablation == 0 && recallGuardMode != 0 && d.mask == 0x1 )
    {
      const double guardNzMargin   = std::max( 0.0, m_pcEncCfg->m_LardLfnst14GuardNzMargin );
      const double guardRateMargin = std::max( 0.0, m_pcEncCfg->m_LardLfnst14GuardRateMargin );
      int guardMask = d.mask;
      for( int cand = 0; cand < 2; cand++ )
      {
        const double nzDiff = nzL[cand] - nz0;
        const double gain   = cand == 0 ? d.g1 : d.g2;
        if( nzDiff < guardNzMargin || gain > -guardRateMargin )
        {
          guardMask |= 1 << ( cand + 1 );
        }
      }
      if( guardMask != d.mask )
      {
        d.mask = guardMask;
        recallGuarded = true;
      }
      if( recallGuardMode == 2 && m_pcEncCfg->m_LardLfnst2ndScoreTable != 0 && d.mask == 0x1 )
      {
        const double energyNorm = inputEnergy / ( (double)trSize * qStep * qStep + 1e-9 );
        int n0Q = 0;
        int last0 = -1;
        const double invQStep = 1.0 / std::max( 1e-9, qStep );
        for( int i = 0; i < trSize; i++ )
        {
          const int q = (int)std::floor( std::fabs( input[i] ) * invQStep + 0.5 );
          if( q )
          {
            n0Q++;
            last0 = i;
          }
        }
        const int scoreLatBucket = xLardLfnstLatBucketId( f.thetaMaxDeg );
        const int energyBucket = xLard2ndEnergyBucket( energyNorm );
        const int64_t coffKey = xLard2ndCoffPackKey( cu.qp, sizeGroup, modeGroup, scoreLatBucket, lfnstSet, sbClass, dct2CostBin, energyBucket );
        const LardLfnst2ndCoffEntry* coffEntry = xLard2ndFindCoffEntry( coffKey );
        if( coffEntry )
        {
          const int64_t scoreKey = xLard2ndScorePackKey( cu.qp, sizeGroup, modeGroup, scoreLatBucket, lfnstSet, sbClass,
                                                         dct2CostBin, energyBucket, xLardLfnstNzBucketId( (double)n0Q ),
                                                         xLardLfnstLastBucketId( last0 ), coffEntry->coffBucket,
                                                         xLard2ndObsBucket( maxObsGain ) );
          if( const LardLfnst2ndScoreEntry* score = xLard2ndFindScoreEntry( scoreKey ) )
          {
            const int scoreMask = score->mask & 0x7;
            if( scoreMask != 0x1 )
            {
              d.mask |= scoreMask;
              recallGuarded = true;
            }
          }
        }
      }
    }
    if( d.mask == 0x1 )
    {
      d.theoryReason = ablation == 2 ? 2 : 3;
    }
    else if( recallGuarded )
    {
      d.theoryReason = 5;
    }
    else if( d.mask == 0x7 )
    {
      d.theoryReason = 0;
    }
    else
    {
      d.theoryReason = 4;
    }

    if( countScope.enabled() )
    {
      Lard2ndCountRow& row = countScope.row();
      if( d.mask == 0x1 )
      {
        row.fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
      }
      else if( d.mask == 0x3 )
      {
        row.fullModelKeep1.fetch_add( 1, std::memory_order_relaxed );
      }
      else if( d.mask == 0x5 )
      {
        row.fullModelKeep2.fetch_add( 1, std::memory_order_relaxed );
      }
      else
      {
        row.fullModelFull.fetch_add( 1, std::memory_order_relaxed );
      }
    }

    xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                         inputEnergy, f.thetaMaxDeg, d.corrStrength, d.rate0, obsRate0,
                         d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate,
                         d.theoryReason, d.theoryMh, d.theoryMajorMargin1, d.theoryMajorMargin2,
                         d.theoryRate1, d.theoryRate2, d.theoryNz0, d.theoryNz1, d.theoryNz2,
                         d.theoryMajorMask );
    return d;
  }

  if( m_pcEncCfg->m_LardLfnst2ndScoreTable )
  {
    const double energyNorm = inputEnergy / ( (double)trSize * qStep * qStep + 1e-9 );
    int n0 = 0;
    int last0 = -1;
    const double invQStep = 1.0 / std::max( 1e-9, qStep );
    for( int i = 0; i < trSize; i++ )
    {
      const int q = (int)std::floor( std::fabs( input[i] ) * invQStep + 0.5 );
      if( q )
      {
        n0++;
        last0 = i;
      }
    }
    const int sizeGroup = xLahtpSizeGroupId( cu.lwidth(), cu.lheight() );
    const int latBucket = xLardLfnstLatBucketId( f.thetaMaxDeg );
    const int energyBucket = xLard2ndEnergyBucket( energyNorm );
    const int sbClass = sbSize > 4 ? 1 : 0;
    const int64_t coffKey = xLard2ndCoffPackKey( cu.qp, sizeGroup, modeGroup, latBucket, lfnstSet, sbClass, dct2CostBin, energyBucket );
    const LardLfnst2ndCoffEntry* coffEntry = xLard2ndFindCoffEntry( coffKey );
    const int coffBucket = coffEntry ? coffEntry->coffBucket : -1;
    const int64_t scoreKey = coffEntry
      ? xLard2ndScorePackKey( cu.qp, sizeGroup, modeGroup, latBucket, lfnstSet, sbClass, dct2CostBin, energyBucket,
                              xLardLfnstNzBucketId( (double)n0 ), xLardLfnstLastBucketId( last0 ), coffBucket, xLard2ndObsBucket( maxObsGain ) )
      : -1;
    if( const LardLfnst2ndScoreEntry* score = xLard2ndFindScoreEntry( scoreKey ) )
    {
      d.valid = true;
      d.mask = score->mask;
      d.rawMask = score->mask;
      d.obs1 = obsGain[0];
      d.obs2 = obsGain[1];
      d.f1 = score->score1;
      d.f2 = score->score2;
      d.g1 = d.f1 - d.obs1;
      d.g2 = d.f2 - d.obs2;
      d.corrStrength = 0.0;

      if( obsGate > -1.0e8 && d.mask == 0x1 && maxObsGain >= obsGate )
      {
        d.mask = 0x7;
        d.safeGate = true;
      }

      xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                           inputEnergy, f.thetaMaxDeg, 0.0, d.rate0, obsRate0,
                           d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate );

      return d;
    }

    d.valid = true;
    d.mask = 0x7;
    d.rawMask = 0x7;
    d.safeGate = true;
    d.obs1 = obsGain[0];
    d.obs2 = obsGain[1];
    d.f1 = obsGain[0];
    d.f2 = obsGain[1];
    d.g1 = 0.0;
    d.g2 = 0.0;
    d.corrStrength = 0.0;
    xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                         inputEnergy, f.thetaMaxDeg, 0.0, d.rate0, obsRate0,
                         d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate );
    return d;
  }

  if( !statsEnabled && obsGate > -1.0e8 && maxObsGain >= obsGate )
  {
    d.valid = true;
    d.mask = 0x7;
    d.rawMask = 0x7;
    d.safeGate = true;
    d.obs1 = obsGain[0];
    d.obs2 = obsGain[1];
    if( countScope.enabled() )
    {
      countScope.row().obsGateFull.fetch_add( 1, std::memory_order_relaxed );
    }
    return d;
  }
  if( !statsEnabled && obsGate > -1.0e8 && m_pcEncCfg->m_LardLfnst2ndObsOnly )
  {
    d.valid = true;
    d.mask = 0x1;
    d.rawMask = 0x1;
    d.obs1 = obsGain[0];
    d.obs2 = obsGain[1];
    if( countScope.enabled() )
    {
      countScope.row().obsOnlySkip.fetch_add( 1, std::memory_order_relaxed );
    }
    return d;
  }

  const double kappa = std::max( 1e-9, m_pcEncCfg->m_LardLfnst2ndKappa );
  const double zeta  = std::max( 0.0,  m_pcEncCfg->m_LardLfnst2ndZeta );
  const double delta = std::max( 0.0,  m_pcEncCfg->m_LardLfnst2ndDelta );
  const double corrAlpha = xLahtpClipD( 0.0, 0.95, m_pcEncCfg->m_LardLfnst2ndCorrAlpha );
  const double corrDecay = std::max( 1e-9, m_pcEncCfg->m_LardLfnst2ndCorrDecay );
  const double safeMargin = std::max( 0.0, m_pcEncCfg->m_LardLfnst2ndSafeMargin );

  const double theta = std::min( 1.45, f.thetaMaxDeg * 3.14159265358979323846 / 180.0 );
  const double tanTheta2 = std::tan( theta ) * std::tan( theta );
  const double psi = std::max( 0.0, m_pcEncCfg->m_LardLfnstPsi );
  const double u0  = std::max( 1e-6, m_pcEncCfg->m_LardLfnstU0 );

  double weight[48];
  double meanWeight = 0.0;
  for( int i = 0; i < trSize; i++ )
  {
    const double un = (double)uPos[i] / u0;
    weight[i] = std::exp( -psi * un * un * tanTheta2 );
    meanWeight += weight[i];
  }
  meanWeight = std::max( 1e-9, meanWeight / (double)trSize );

  double var0[48];
  const double sigmaBase = inputEnergy / (double)trSize;
  for( int i = 0; i < trSize; i++ )
  {
    var0[i] = sigmaBase * weight[i] / meanWeight;
  }
  const int sizeGroup = xLahtpSizeGroupId( cu.lwidth(), cu.lheight() );
  const int latBucket = xLardLfnstLatBucketId( f.absLatDeg );
  const int sbClass   = sbSize > 4 ? 1 : 0;
  if( m_pcEncCfg->m_LardLfnstTheoryTable )
  {
    const int aBin = xLard2ndTheoryABin( sigmaBase, qStep );
    const LardLfnstTheoryStatsEntry* th[2] =
    {
      xLard2ndFindTheoryStatsEntry( latBucket, width, height, transposeFlag, zeroOutSize, lfnstSet, 1, aBin ),
      xLard2ndFindTheoryStatsEntry( latBucket, width, height, transposeFlag, zeroOutSize, lfnstSet, 2, aBin )
    };
    if( th[0] && th[1] )
    {
      double fScore[2] = { 0.0, 0.0 };
      double gScore[2] = { 0.0, 0.0 };
      for( int cand = 0; cand < 2; cand++ )
      {
        const double deltaR = (double)th[cand]->deltaR + ( 1.0 - rIdx );
        const double deltaD = qStep * qStep * (double)th[cand]->deltaDNorm;
        const double deltaJ = deltaD + lambda * deltaR;
        gScore[cand] = deltaJ - zeta;
        fScore[cand] = obsGain[cand] + gScore[cand];
      }

      d.valid = true;
      d.g1 = gScore[0];
      d.g2 = gScore[1];
      d.obs1 = obsGain[0];
      d.obs2 = obsGain[1];
      d.f1 = fScore[0];
      d.f2 = fScore[1];
      d.corrStrength = 0.0;
      d.rate0 = (double)th[0]->rate0;

      const double maxF = std::max( d.f1, d.f2 );
      if( maxF <= 0.0 )
      {
        d.mask = 0x1;
      }
      else if( std::fabs( d.f1 - d.f2 ) > delta )
      {
        d.mask = d.f1 > d.f2 ? 0x3 : 0x5;
      }
      else
      {
        d.mask = 0x7;
      }
      d.rawMask = d.mask;

      if( obsGate > -1.0e8 && d.mask == 0x1 && std::max( d.obs1, d.obs2 ) >= obsGate )
      {
        d.mask = 0x7;
        d.safeGate = true;
      }

      if( safeMargin > 0.0 )
      {
        const bool nearSkipBoundary = std::fabs( maxF ) <= safeMargin;
        const bool nearRankBoundary = maxF > 0.0 && std::fabs( std::fabs( d.f1 - d.f2 ) - delta ) <= safeMargin;
        if( nearSkipBoundary || nearRankBoundary )
        {
          d.mask = 0x7;
          d.safeGate = true;
        }
      }

      if( countScope.enabled() )
      {
        Lard2ndCountRow& row = countScope.row();
        if( d.mask == 0x1 )
        {
          row.fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( d.mask == 0x3 )
        {
          row.fullModelKeep1.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( d.mask == 0x5 )
        {
          row.fullModelKeep2.fetch_add( 1, std::memory_order_relaxed );
        }
        else if( d.safeGate && d.rawMask != 0x7 )
        {
          row.fullModelSafeFull.fetch_add( 1, std::memory_order_relaxed );
        }
        else
        {
          row.fullModelFull.fetch_add( 1, std::memory_order_relaxed );
        }
      }

      xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                           inputEnergy, f.thetaMaxDeg, 0.0, (double)th[0]->rate0, obsRate0,
                           d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate );

      return d;
    }
  }
  const LardLfnst2ndCorrTableEntry* corrTableEntry = m_pcEncCfg->m_LardLfnst2ndCorrTable
                                                   ? xLard2ndFindCorrTableEntry( latBucket, modeGroup, sizeGroup, sbClass, trSize )
                                                   : nullptr;
  const bool useCorrTable = corrTableEntry != nullptr;
  const double corrStrength = useCorrTable ? 1.0 : ( ( m_pcEncCfg->m_LardLfnstSkip == 11 || m_pcEncCfg->m_LardLfnstSkip == 13 || secondResponseStatsOnly ) ? 0.0 : corrAlpha );

  double rate0 = 0.0;
  for( int i = 0; i < trSize; i++ )
  {
    rate0 += xLard2ndEntropyBound( var0[i], qStep, kappa );
  }
  d.rate0 = rate0;

  const double d0q = ( qStep * qStep / 12.0 ) * (double)trSize;
  double fScore[2] = { 0.0, 0.0 };
  double gScore[2] = { 0.0, 0.0 };

  for( int cand = 0; cand < 2; cand++ )
  {
    const Lard2ndLookup& lookup = xLard2ndGetLookup( lfnstSet, cand, sbSize, zeroOutSize );
    const Lard2ndCorrFactors corrFactors = useCorrTable ? xLard2ndGetCorrFactors( corrTableEntry, lfnstSet, cand, sbSize, zeroOutSize )
                                                        : Lard2ndCorrFactors();

    double rateL = rIdx;
    double varL[16];
    for( int row = 0; row < zeroOutSize; row++ )
    {
      double var  = 0.0;
      for( int col = 0; col < trSize; col++ )
      {
        var += lookup.respVarW[row][col] * var0[col];
      }
      if( useCorrTable )
      {
        var += sigmaBase * corrFactors.resp[row];
      }
      else if( corrStrength > 0.0 )
      {
        for( int col = 0; col + 1 < trSize; col++ )
        {
          for( int col2 = col + 1; col2 < trSize; col2++ )
          {
            const double corr = useCorrTable ? xLard2ndCorrTableCoeff( corrTableEntry, col, col2 )
                                             : xLard2ndCorrCoeff( corrStrength, corrDecay, modeGroup, uPos[col], vPos[col], uPos[col2], vPos[col2] );
            const double cov  = corr * std::sqrt( std::max( 0.0, var0[col] * var0[col2] ) );
            var += 2.0 * lookup.respCorrW[row][col][col2] * cov;
          }
        }
      }
      varL[row] = std::max( 0.0, var );
      rateL += xLard2ndEntropyBound( varL[row], qStep, kappa );
    }

    double dSub = 0.0;
    for( int col = 0; col < trSize; col++ )
    {
      dSub += var0[col] * lookup.subErrW[col];
    }
    if( useCorrTable )
    {
      dSub += sigmaBase * corrFactors.sub;
    }
    else if( corrStrength > 0.0 )
    {
      for( int col = 0; col + 1 < trSize; col++ )
      {
        for( int col2 = col + 1; col2 < trSize; col2++ )
        {
          const double corr = useCorrTable ? xLard2ndCorrTableCoeff( corrTableEntry, col, col2 )
                                           : xLard2ndCorrCoeff( corrStrength, corrDecay, modeGroup, uPos[col], vPos[col], uPos[col2], vPos[col2] );
          const double cov  = corr * std::sqrt( std::max( 0.0, var0[col] * var0[col2] ) );
          dSub += 2.0 * lookup.subErrCorrW[col][col2] * cov;
        }
      }
    }

    const double dLq = ( qStep * qStep / 12.0 ) * lookup.traceVVT;
    const double deltaR = rate0 - rateL;
    const double deltaD = d0q - dLq - dSub;
    const double deltaJ = deltaD + lambda * deltaR;
    gScore[cand] = deltaJ - zeta;

    fScore[cand] = obsGain[cand] + gScore[cand];
  }

  d.valid = true;
  d.g1 = gScore[0];
  d.g2 = gScore[1];
  d.obs1 = obsGain[0];
  d.obs2 = obsGain[1];
  d.f1 = fScore[0];
  d.f2 = fScore[1];
  d.corrStrength = corrStrength;

  const double maxF = std::max( d.f1, d.f2 );
  if( maxF <= 0.0 )
  {
    d.mask = 0x1;
  }
  else if( std::fabs( d.f1 - d.f2 ) > delta )
  {
    d.mask = d.f1 > d.f2 ? 0x3 : 0x5;
  }
  else
  {
    d.mask = 0x7;
  }
  d.rawMask = d.mask;

  if( obsGate > -1.0e8 && d.mask == 0x1 && std::max( d.obs1, d.obs2 ) >= obsGate )
  {
    d.mask = 0x7;
    d.safeGate = true;
  }

  if( safeMargin > 0.0 )
  {
    const bool nearSkipBoundary = std::fabs( maxF ) <= safeMargin;
    const bool nearRankBoundary = maxF > 0.0 && std::fabs( std::fabs( d.f1 - d.f2 ) - delta ) <= safeMargin;
    if( nearSkipBoundary || nearRankBoundary )
    {
      d.mask = 0x7;
      d.safeGate = true;
    }
  }

  if( countScope.enabled() )
  {
    Lard2ndCountRow& row = countScope.row();
    if( d.mask == 0x1 )
    {
      row.fullModelSkipBoth.fetch_add( 1, std::memory_order_relaxed );
    }
    else if( d.mask == 0x3 )
    {
      row.fullModelKeep1.fetch_add( 1, std::memory_order_relaxed );
    }
    else if( d.mask == 0x5 )
    {
      row.fullModelKeep2.fetch_add( 1, std::memory_order_relaxed );
    }
    else if( d.safeGate && d.rawMask != 0x7 )
    {
      row.fullModelSafeFull.fetch_add( 1, std::memory_order_relaxed );
    }
    else
    {
      row.fullModelFull.fetch_add( 1, std::memory_order_relaxed );
    }
  }

  xLard2ndAppendStats( m_pcEncCfg->m_LardLfnst2ndStatFile, cu, (int)intraMode, lfnstSet, sbSize, zeroOutSize,
                       inputEnergy, f.thetaMaxDeg, corrStrength, rate0, obsRate0,
                       d.f1, d.f2, d.g1, d.g2, d.obs1, d.obs2, d.rawMask, d.mask, d.safeGate );

  return d;
}
#endif

void IntraSearch::xEstimateLumaRdModeList(int& numModesForFullRD,
  static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& RdModeList,
  static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& HadModeList,
  static_vector<double, FAST_UDI_MAX_RDMODE_NUM>& CandCostList,
  static_vector<double, FAST_UDI_MAX_RDMODE_NUM>& CandHadList, CodingUnit& cu, bool testMip )
{
  PROFILER_SCOPE_AND_STAGE_EXT( 1, _TPROF, P_INTRA_EST_RD_CAND, cu.cs, CH_L );
  const uint16_t intra_ctx_size = Ctx::IntraLumaMpmFlag.size() + Ctx::IntraLumaPlanarFlag.size() + Ctx::MultiRefLineIdx.size() + Ctx::ISPMode.size() + Ctx::MipFlag.size();
  const TempCtx  ctxStartIntraCtx(m_CtxCache, SubCtx(CtxSet(Ctx::IntraLumaMpmFlag(), intra_ctx_size), m_CABACEstimator->getCtx()));
  const double   sqrtLambdaForFirstPass = m_pcRdCost->getMotionLambda() * FRAC_BITS_SCALE;
  const int numModesAvailable = NUM_LUMA_MODE; // total number of Intra modes

  CHECK(numModesForFullRD >= numModesAvailable, "Too many modes for full RD search");

  const SPS& sps     = *cu.cs->sps;
  const bool fastMip = sps.MIP && m_pcEncCfg->m_useFastMIP;

  // this should always be true
  CHECK( !cu.Y().valid(), "CU is not valid" );

  const CompArea& area = cu.Y();

  const UnitArea localUnitArea(area.chromaFormat, Area(0, 0, area.width, area.height));
  if( testMip)
  {
    numModesForFullRD += fastMip ? numModesForFullRD - std::min( m_pcEncCfg->m_useFastMIP, numModesForFullRD )
                                 : numModesForFullRD;
    m_SortedPelUnitBufs->prepare( localUnitArea, numModesForFullRD + 1 );
  }
  else
  {
    m_SortedPelUnitBufs->prepare( localUnitArea, numModesForFullRD );
  }

  CPelBuf piOrg   = cu.cs->getOrgBuf(COMP_Y);
  PelBuf piPred  = m_SortedPelUnitBufs->getTestBuf(COMP_Y);

  const ReshapeData& reshapeData = cu.cs->picture->reshapeData;
  if (cu.cs->picHeader->lmcsEnabled && reshapeData.getCTUFlag())
  {
    piOrg = cu.cs->getRspOrgBuf();
  }
  DistParam distParam    = m_pcRdCost->setDistParam( piOrg, piPred, sps.bitDepths[ CH_L ], DF_HAD_2SAD); // Use HAD (SATD) cost

  const int numHadCand = (testMip ? 2 : 1) * 3;

  //*** Derive (regular) candidates using Hadamard
  cu.mipFlag = false;
  cu.multiRefIdx = 0;

  //===== init pattern for luma prediction =====
  initIntraPatternChType(cu, cu.Y(), true);

  bool satdChecked[NUM_INTRA_MODE] = { false };

  unsigned mpmLst[NUM_MOST_PROBABLE_MODES];
  CU::getIntraMPMs(cu, mpmLst);

  const int decMsk = ( 1 << m_pcEncCfg->m_IntraEstDecBit ) - 1;

  m_parentCandList.resize( 0 );
  m_parentCandList.reserve( ( numModesAvailable >> m_pcEncCfg->m_IntraEstDecBit ) + 2 );

  for( unsigned mode = 0; mode < numModesAvailable; mode++ )
  {
    // Skip checking extended Angular modes in the first round of SATD
    if( mode > DC_IDX && ( mode & decMsk ) )
    {
      continue;
    }

    m_parentCandList.push_back( ModeInfo( false, false, 0, NOT_INTRA_SUBPARTITIONS, mode ) );
  }
   
  for( int decDst = 1 << m_pcEncCfg->m_IntraEstDecBit; decDst > 0; decDst >>= 1 )
  {
    for( unsigned idx = 0; idx < m_parentCandList.size(); idx++ )
    {
      int modeParent = m_parentCandList[idx].modeId;

      int off = decDst & decMsk;
      int inc = decDst << 1;

#if 1 // INTRA_AS_IN_VTM
      if( off != 0 && ( modeParent <= ( DC_IDX + 1 ) || modeParent >= ( NUM_LUMA_MODE - 1 ) ) )
      {
        continue;
      }

#endif
      for( int mode = modeParent - off; mode < modeParent + off + 1; mode += inc )
      {
        if( satdChecked[mode] || mode < 0 || mode >= NUM_LUMA_MODE )
        {
          continue;
        }

        cu.intraDir[0] = mode;

        initPredIntraParams( cu, cu.Y(), sps );
        distParam.cur.buf = piPred.buf = m_SortedPelUnitBufs->getTestBuf().Y().buf;
        predIntraAng( COMP_Y, piPred, cu );

        // Use the min between SAD and HAD as the cost criterion
        // SAD is scaled by 2 to align with the scaling of HAD
        Distortion minSadHad = distParam.distFunc( distParam );

        uint64_t fracModeBits = xFracModeBitsIntraLuma( cu, mpmLst );

        //restore ctx
        m_CABACEstimator->getCtx() = SubCtx( CtxSet( Ctx::IntraLumaMpmFlag(), intra_ctx_size ), ctxStartIntraCtx );

        double cost = ( double ) minSadHad + ( double ) fracModeBits * sqrtLambdaForFirstPass;
        DTRACE( g_trace_ctx, D_INTRA_COST, "IntraHAD: %u, %llu, %f (%d)\n", minSadHad, fracModeBits, cost, mode );

        int insertPos = -1;
        updateCandList( ModeInfo( false, false, 0, NOT_INTRA_SUBPARTITIONS, mode ), cost, RdModeList, CandCostList, numModesForFullRD, &insertPos );
        updateCandList( ModeInfo( false, false, 0, NOT_INTRA_SUBPARTITIONS, mode ), ( double ) minSadHad, HadModeList, CandHadList, numHadCand );
        m_SortedPelUnitBufs->insert( insertPos, ( int ) RdModeList.size() );

        satdChecked[mode] = true;
      }
    }

    m_parentCandList.resize( RdModeList.size() );
    std::copy( RdModeList.cbegin(), RdModeList.cend(), m_parentCandList.begin() );
  }

  const bool isFirstLineOfCtu = (((cu.block(COMP_Y).y)&((cu.cs->sps)->CTUSize - 1)) == 0);
  if( m_pcEncCfg->m_MRL && ! isFirstLineOfCtu )
  {
    cu.multiRefIdx = 1;
    unsigned  multiRefMPM [NUM_MOST_PROBABLE_MODES];
    CU::getIntraMPMs(cu, multiRefMPM);

    for (int mRefNum = 1; mRefNum < MRL_NUM_REF_LINES; mRefNum++)
    {
      int multiRefIdx = MULTI_REF_LINE_IDX[mRefNum];

      cu.multiRefIdx = multiRefIdx;
      initIntraPatternChType(cu, cu.Y(), true);

      for (int x = 1; x < NUM_MOST_PROBABLE_MODES; x++)
      {
        cu.intraDir[0] = multiRefMPM[x];
        initPredIntraParams(cu, cu.Y(), sps);
        distParam.cur.buf = piPred.buf = m_SortedPelUnitBufs->getTestBuf().Y().buf;
        predIntraAng(COMP_Y, piPred, cu);

        // Use the min between SAD and SATD as the cost criterion
        // SAD is scaled by 2 to align with the scaling of HAD
        Distortion minSadHad = distParam.distFunc(distParam);

        // NB xFracModeBitsIntra will not affect the mode for chroma that may have already been pre-estimated.
        uint64_t fracModeBits = xFracModeBitsIntraLuma( cu, mpmLst );

        //restore ctx
        m_CABACEstimator->getCtx() = SubCtx(CtxSet(Ctx::IntraLumaMpmFlag(), intra_ctx_size), ctxStartIntraCtx);

        double cost = (double) minSadHad + (double) fracModeBits * sqrtLambdaForFirstPass;
//        DTRACE(g_trace_ctx, D_INTRA_COST, "IntraMRL: %u, %llu, %f (%d)\n", minSadHad, fracModeBits, cost, cu.intraDir[0]);

        int insertPos = -1;
        updateCandList( ModeInfo( false, false, multiRefIdx, NOT_INTRA_SUBPARTITIONS, cu.intraDir[0] ), cost, RdModeList,  CandCostList, numModesForFullRD, &insertPos );
        updateCandList( ModeInfo( false, false, multiRefIdx, NOT_INTRA_SUBPARTITIONS, cu.intraDir[0] ), (double)minSadHad, HadModeList, CandHadList,  numHadCand );
        m_SortedPelUnitBufs->insert(insertPos, (int)RdModeList.size());
      }
    }
    cu.multiRefIdx = 0;
  }

  if (testMip)
  {
    cu.mipFlag = true;
    cu.multiRefIdx = 0;

    double mipHadCost[MAX_NUM_MIP_MODE] = { MAX_DOUBLE };

    initIntraPatternChType(cu, cu.Y());
    initIntraMip( cu );

    const int transpOff    = getNumModesMip( cu.Y() );
    const int numModesFull = (transpOff << 1);
    for( uint32_t uiModeFull = 0; uiModeFull < numModesFull; uiModeFull++ )
    {
      const bool     isTransposed = (uiModeFull >= transpOff ? true : false);
      const uint32_t uiMode       = (isTransposed ? uiModeFull - transpOff : uiModeFull);

      cu.mipTransposedFlag = isTransposed;
      cu.intraDir[CH_L] = uiMode;
      distParam.cur.buf = piPred.buf = m_SortedPelUnitBufs->getTestBuf().Y().buf;
      predIntraMip(piPred, cu);

      // Use the min between SAD and HAD as the cost criterion
      // SAD is scaled by 2 to align with the scaling of HAD
      Distortion minSadHad = distParam.distFunc(distParam);

      uint64_t fracModeBits = xFracModeBitsIntraLuma( cu, mpmLst );

      //restore ctx
      m_CABACEstimator->getCtx() = SubCtx(CtxSet(Ctx::IntraLumaMpmFlag(), intra_ctx_size), ctxStartIntraCtx);

      double cost = double(minSadHad) + double(fracModeBits) * sqrtLambdaForFirstPass;
      mipHadCost[uiModeFull] = cost;
      DTRACE(g_trace_ctx, D_INTRA_COST, "IntraMIP: %u, %llu, %f (%d)\n", minSadHad, fracModeBits, cost, uiModeFull);

      int insertPos = -1;
      updateCandList( ModeInfo( true, isTransposed, 0, NOT_INTRA_SUBPARTITIONS, cu.intraDir[0] ), cost, RdModeList,  CandCostList, numModesForFullRD+1, &insertPos );
      updateCandList( ModeInfo( true, isTransposed, 0, NOT_INTRA_SUBPARTITIONS, cu.intraDir[0] ), 0.8*(double)minSadHad, HadModeList, CandHadList,  numHadCand );
      m_SortedPelUnitBufs->insert(insertPos, (int)RdModeList.size());
    }

    const double thresholdHadCost = 1.0 + 1.4 / sqrt((double)(cu.lwidth()*cu.lheight()));
    xReduceHadCandList(RdModeList, CandCostList, *m_SortedPelUnitBufs, numModesForFullRD, thresholdHadCost, mipHadCost, cu, fastMip);
  }

  if( m_pcEncCfg->m_bFastUDIUseMPMEnabled )
  {
    const int numMPMs = NUM_MOST_PROBABLE_MODES;
    unsigned  intraMpms[numMPMs];

    cu.multiRefIdx = 0;

    const int numCand = CU::getIntraMPMs( cu, intraMpms );
    ModeInfo mostProbableMode(false, false, 0, NOT_INTRA_SUBPARTITIONS, 0);

    for( int j = 0; j < numCand; j++ )
    {
      bool mostProbableModeIncluded = false;
      mostProbableMode.modeId = intraMpms[j];

      for( int i = 0; i < numModesForFullRD; i++ )
      {
        mostProbableModeIncluded |= ( mostProbableMode == RdModeList[i] );
      }
      if( !mostProbableModeIncluded )
      {
        numModesForFullRD++;
        RdModeList.push_back( mostProbableMode );
        CandCostList.push_back(0);
      }
    }
  }
}

bool IntraSearch::estIntraPredLumaQT(CodingUnit &cu, Partitioner &partitioner, double bestCost)
{
  CodingStructure       &cs           = *cu.cs;
  const int             width         = partitioner.currArea().lwidth();
  const int             height        = partitioner.currArea().lheight();

  //===== loop over partitions =====

  const TempCtx ctxStart           ( m_CtxCache, m_CABACEstimator->getCtx() );

  // variables for saving fast intra modes scan results across multiple LFNST passes
  double costInterCU = xFindInterCUCost( cu );

  bool validReturn = false;

  //===== determine set of modes to be tested (using prediction signal only) =====
  int numModesAvailable = NUM_LUMA_MODE; // total number of Intra modes
  static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM> RdModeList;
  static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM> HadModeList;
  static_vector<double, FAST_UDI_MAX_RDMODE_NUM> CandCostList;
  static_vector<double, FAST_UDI_MAX_RDMODE_NUM> CandHadList;

  int numModesForFullRD = g_aucIntraModeNumFast_UseMPM_2D[Log2(width) - MIN_CU_LOG2][Log2(height) - MIN_CU_LOG2];
  if (m_pcEncCfg->m_numIntraModesFullRD > 0)
    numModesForFullRD=m_pcEncCfg->m_numIntraModesFullRD;

#if INTRA_FULL_SEARCH
  numModesForFullRD = numModesAvailable;
#endif
  const SPS& sps = *cu.cs->sps;
  const bool mipAllowed = sps.MIP && cu.lwidth() <= sps.getMaxTbSize() && cu.lheight() <= sps.getMaxTbSize() && ((cu.lfnstIdx == 0) || allowLfnstWithMip(cu.lumaSize()));
  const int SizeThr     = 8 >> std::max( 0, m_pcEncCfg->m_useFastMIP - 1 );
  const bool testMip    = mipAllowed && ( cu.lwidth() <= ( SizeThr * cu.lheight() ) && cu.lheight() <= ( SizeThr * cu.lwidth() ) ) && ( cu.lwidth() <= MIP_MAX_WIDTH && cu.lheight() <= MIP_MAX_HEIGHT );
  bool testISP = sps.ISP && CU::canUseISP(width, height, cu.cs->sps->getMaxTbSize());
  if (testISP)
  {
    int numTotalPartsHor = (int)width >> floorLog2(CU::getISPSplitDim(width, height, TU_1D_VERT_SPLIT));
    int numTotalPartsVer = (int)height >> floorLog2(CU::getISPSplitDim(width, height, TU_1D_HORZ_SPLIT));
    m_ispTestedModes[0].init(numTotalPartsHor, numTotalPartsVer, 0);
    // the total number of subpartitions is modified to take into account the cases where LFNST cannot be combined with
    // ISP due to size restrictions
    numTotalPartsHor = sps.LFNST && CU::canUseLfnstWithISP(cu.Y(), HOR_INTRA_SUBPARTITIONS) ? numTotalPartsHor : 0;
    numTotalPartsVer = sps.LFNST && CU::canUseLfnstWithISP(cu.Y(), VER_INTRA_SUBPARTITIONS) ? numTotalPartsVer : 0;
    for (int j = 1; j < NUM_LFNST_NUM_PER_SET; j++)
    {
      m_ispTestedModes[j].init(numTotalPartsHor, numTotalPartsVer, 0);
    }
    testISP = m_ispTestedModes[0].numTotalParts[0];
  }
  else
  {
    m_ispTestedModes[0].init(0, 0, 0);
  }

  xEstimateLumaRdModeList(numModesForFullRD, RdModeList, HadModeList, CandCostList, CandHadList, cu, testMip);

  CHECK( (size_t)numModesForFullRD != RdModeList.size(), "Inconsistent state!" );

  // after this point, don't use numModesForFullRD
  if( m_pcEncCfg->m_usePbIntraFast && !cs.slice->isIntra() && RdModeList.size() < numModesAvailable )
  {
    double pbintraRatio = m_pcEncCfg->m_usePbIntraFast == 1 && ( cs.area.lwidth() >= 16 && cs.area.lheight() >= 16 ) ? 1.2 : PBINTRA_RATIO;

    int maxSize = -1;
    ModeInfo bestMipMode;
    int bestMipIdx = -1;
    for( int idx = 0; idx < RdModeList.size(); idx++ )
    {
      if( RdModeList[idx].mipFlg )
      {
        bestMipMode = RdModeList[idx];
        bestMipIdx = idx;
        break;
      }
    }
    const int numHadCand = 3;
    for (int k = numHadCand - 1; k >= 0; k--)
    {
      if (CandHadList.size() < (k + 1) || CandHadList[k] > cs.interHad * pbintraRatio) { maxSize = k; }
    }
    if (maxSize > 0)
    {
      RdModeList.resize(std::min<size_t>(RdModeList.size(), maxSize));
      if( bestMipIdx >= 0 )
      {
        if( RdModeList.size() <= bestMipIdx )
        {
          RdModeList.push_back(bestMipMode);
          m_SortedPelUnitBufs->swap( maxSize, bestMipIdx );
        }
      }
    }
    if (maxSize == 0)
    {
      cs.dist = MAX_DISTORTION;
      cs.interHad = 0;
      return false;
    }
  }

  //===== check modes (using r-d costs) =====
  ModeInfo bestPUMode;

  CodingStructure *csTemp = m_pTempCS;
  CodingStructure *csBest = m_pBestCS;

  csTemp->slice   = csBest->slice   = cs.slice;
  csTemp->picture = csBest->picture = cs.picture;
  csTemp->compactResize( cu );
  csBest->compactResize( cu );
  csTemp->initStructData();
  csBest->initStructData();

  int   bestLfnstIdx  = 0;
  const bool useBDPCM = cs.picture->useBDPCM;
  int   NumBDPCMCand  = (useBDPCM && sps.BDPCM && CU::bdpcmAllowed(cu, ComponentID(partitioner.chType))) ? 2 : 0;
  int   bestbdpcmMode = 0;
  int   bestISP       = 0;
  int   bestMrl       = 0;
  bool  bestMip       = 0;
  int   EndMode       = (int)RdModeList.size();
  bool  useISPlfnst   = testISP && sps.LFNST;
  bool  noLFNST_ts    = false;
  double bestCostIsp[2] = { MAX_DOUBLE, MAX_DOUBLE };
  bool disableMTS = false;
  bool disableLFNST = false;
  bool disableDCT2test = false;
  if (m_pcEncCfg->m_FastIntraTools)
  {
    int speedIntra = 0;
    xSpeedUpIntra(bestCost, EndMode, speedIntra, cu);
    disableMTS = (speedIntra >> 2 ) & 0x1;
    disableLFNST = (speedIntra >> 1) & 0x1;
    disableDCT2test = speedIntra>>3;
    if (disableLFNST)
    {
      noLFNST_ts = true;
      useISPlfnst = false;
    }
    if (speedIntra & 0x1)
    {
      testISP = false;
    }
  }

  for (int mode_cur = 0; mode_cur < EndMode + NumBDPCMCand; mode_cur++)
  {
    int mode = mode_cur;
    if (mode_cur >= EndMode)
    {
      mode = mode_cur - EndMode ? -1 : -2;
      testISP = false;
    }
    // set CU/PU to luma prediction mode
    ModeInfo testMode;
    int noISP = 0;
    int endISP = testISP ? 2 : 0;
    bool noLFNST = false || noLFNST_ts;
    if (mode && useISPlfnst)
    {
      noLFNST |= (bestCostIsp[0] > (bestCostIsp[1] * 1.4));
      if (mode > 2)
      {
        endISP = 0;
        testISP = false;
      }
    }
    if (testISP)
    {
      xSpeedUpISP(1, testISP, mode, noISP, endISP, cu, RdModeList, bestPUMode, bestISP, bestLfnstIdx);
    }
    int startISP = 0;
    if (disableDCT2test && mode && bestISP)
    {
      startISP = endISP ? 1 : 0;
    }
    for (int ispM = startISP; ispM <= endISP; ispM++)
    {
      if (ispM && (ispM == noISP))
      {
        continue;
      }

      if (mode < 0)
      {
        cu.bdpcmM[CH_L] = -mode;
        testMode = ModeInfo(false, false, 0, NOT_INTRA_SUBPARTITIONS, cu.bdpcmM[CH_L] == 2 ? VER_IDX : HOR_IDX);
      }
      else
      {
        testMode = RdModeList[mode];
        cu.bdpcmM[CH_L] = 0;
      }

      cu.ispMode = ispM;
      cu.mipFlag = testMode.mipFlg;
      cu.mipTransposedFlag = testMode.mipTrFlg;
      cu.multiRefIdx = testMode.mRefId;
      cu.intraDir[CH_L] = testMode.modeId;
      if (cu.ispMode && xSpeedUpISP(0, testISP, mode, noISP, endISP, cu, RdModeList, bestPUMode, bestISP, 0) )
      {
        continue;
      }
      if (m_pcEncCfg->m_FastIntraTools && (cu.ispMode || sps.LFNST || sps.MTS))
      {
        m_ispTestedModes[0].intraWasTested = true;
      }
      CHECK(cu.mipFlag && cu.multiRefIdx, "Error: combination of MIP and MRL not supported");
      CHECK(cu.multiRefIdx && (cu.intraDir[0] == PLANAR_IDX), "Error: combination of MRL and Planar mode not supported");
      CHECK(cu.ispMode && cu.mipFlag, "Error: combination of ISP and MIP not supported");
      CHECK(cu.ispMode && cu.multiRefIdx, "Error: combination of ISP and MRL not supported");

      // determine residual for partition
      cs.initSubStructure(*csTemp, partitioner.chType, cs.area, true);

      PelUnitBuf* lahtpPredBuf = m_SortedPelUnitBufs->getBufFromSortedList(mode);

      bool lahtpDisableMTS   = false;
      bool lahtpDisableLFNST = false;
      bool lard14CallerEarlyDisableLFNST = false;
      LahtpFeatures lahtpModeF;
      bool lahtpModeFValid = false;
      CPelBuf lahtpModeOrg;

#if VVENC_LAHTP_ENABLE
      if( sps.LFNST && m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstSkip == 5 || m_pcEncCfg->m_LardLfnstSkip == 6 ) )
      {
        lahtpDisableLFNST = true;
      }
      else if( lahtpPredBuf && xLahtpCanApply( cu, mode ) )
      {
        CPelBuf lahtpOrg = cs.getOrgBuf( COMP_Y );

        const ReshapeData& lahtpReshapeData = cs.picture->reshapeData;
        if( cs.picHeader->lmcsEnabled && lahtpReshapeData.getCTUFlag() )
        {
          lahtpOrg = cs.getRspOrgBuf();
        }
        lahtpModeOrg = lahtpOrg;

        lahtpModeF = xGetLahtpFeatures( cu, lahtpOrg, lahtpPredBuf->Y() );
        lahtpModeFValid = true;
        const LahtpFeatures& lahtpF = lahtpModeF;

        if( sps.MTS )
        {
          lahtpDisableMTS = xLahtpDisableMTS( cu, lahtpF );
        }

        if( sps.LFNST )
        {
          lahtpDisableLFNST = xLahtpDisableLFNST( cu, lahtpF );
        }

#if VVENC_LAHTP_TRACE
        if( lahtpDisableMTS || lahtpDisableLFNST )
        {
          printf("[LAHTP] x=%d y=%d w=%d h=%d qp=%d lat=%.2f thetaMax=%.2f thetaSkip=%.2f etaH=%.3f roiQ=%.3f lf=%.3f predNz=%.3f meanAbsQ=%.3f horz=%.3f s1=%d s2=%d skipMTS=%d skipLFNST=%d\n",
                 cu.Y().x, cu.Y().y, cu.lwidth(), cu.lheight(), cu.qp,
                 lahtpF.absLatDeg, lahtpF.thetaMaxDeg, lahtpF.thetaSkipDeg,
                 lahtpF.etaHigh, lahtpF.roiEnergyQ, lahtpF.lfRatio,
                 lahtpF.predNz, lahtpF.meanAbsQ, lahtpF.horzRatio,
                 lahtpF.stage1 ? 1 : 0, lahtpF.stage2 ? 1 : 0,
                 lahtpDisableMTS ? 1 : 0,
                 lahtpDisableLFNST ? 1 : 0 );
        }
#endif
      }
#endif

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
      const bool lard14CallerCount = m_pcEncCfg && m_pcEncCfg->m_LardLfnst2ndCountFile[0] != '\0';
      const bool lard14CallerEligible = sps.LFNST
                                     && m_pcEncCfg
                                     && m_pcEncCfg->m_LardLfnstSkip == 14
                                     && lahtpPredBuf
                                     && xLahtpCanApply( cu, testMode.modeId );
      const bool lard14CallerSupportGate = xLard14CanUseCallerEarlyDisable( m_pcEncCfg );
      bool lard14CallerGeomTrigger = false;
      bool lard14CallerRoiFullTrigger = false;
      bool lard14CallerRoiProxyTrigger = false;
      LahtpStage1Decision lard14CallerStage1;
      const bool lard14CallerFeatureTimed = lard14CallerEligible && lard14CallerCount
                                         && ( lard14CallerSupportGate
                                           || ( m_pcEncCfg && m_pcEncCfg->m_LardLfnst14EarlyRoiGate != 0 ) );
      const auto lard14CallerFeatureStart = lard14CallerFeatureTimed ? std::chrono::steady_clock::now()
                                                                     : std::chrono::steady_clock::time_point();
      if( lard14CallerEligible && lard14CallerSupportGate )
      {
        lard14CallerStage1 = xGetLahtpStage1Decision( cu );
        lard14CallerGeomTrigger = xLard14EffectiveLfSupportCols( cu.lwidth(), cu.lheight(),
                                                                 lard14CallerStage1.rawCosLat ) < 2;
        lard14CallerEarlyDisableLFNST = lard14CallerGeomTrigger;
      }
      if( lard14CallerEligible && ( !lard14CallerEarlyDisableLFNST || lard14CallerCount ) && lahtpModeFValid )
      {
        lard14CallerRoiFullTrigger = xLard14EarlyRoiDisable( lahtpModeF );
        lard14CallerEarlyDisableLFNST = lard14CallerEarlyDisableLFNST || lard14CallerRoiFullTrigger;
      }
      if( lard14CallerEligible && ( !lard14CallerEarlyDisableLFNST || lard14CallerCount ) && lahtpModeFValid )
      {
        lard14CallerRoiProxyTrigger = xLard14EarlyRoiProxyDisable( cu, lahtpModeOrg, lahtpPredBuf->Y(), lahtpModeF );
        lard14CallerEarlyDisableLFNST = lard14CallerEarlyDisableLFNST || lard14CallerRoiProxyTrigger;
      }
      if( lard14CallerFeatureTimed )
      {
        if( lard14CallerStage1.rawCosLat <= 0.0 )
        {
          lard14CallerStage1 = xGetLahtpStage1Decision( cu );
        }
        const auto lard14CallerFeatureEnd = std::chrono::steady_clock::now();
        const uint64_t ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lard14CallerFeatureEnd - lard14CallerFeatureStart ).count();
        xLard14CallerCountFeature( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                    cu.qp, cu.lwidth(), cu.lheight(), xLahtpModeGroupId( testMode.modeId ),
                                    xLardLfnstLatBucketId( lard14CallerStage1.absLatDeg ), ns );
      }
      if( lard14CallerEligible )
      {
        xLard14CallerCountGate( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                cu.qp, cu.lwidth(), cu.lheight(), xLahtpModeGroupId( testMode.modeId ),
                                true, lard14CallerGeomTrigger, lard14CallerRoiFullTrigger, lard14CallerRoiProxyTrigger );
      }
#endif

      const bool finalDisableMTS = disableMTS || lahtpDisableMTS;

      if( lahtpDisableLFNST && !( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 9 ) )
      {
        noLFNST = true;
      }

      const bool lahtpModeLocalDisableLFNST = ( lahtpDisableLFNST && m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 9 )
                                           || lard14CallerEarlyDisableLFNST;
      int doISP = (((cu.ispMode == 0) && noLFNST) ||
                   (useISPlfnst && mode && cu.ispMode && (bestLfnstIdx == 0)) ||
                   disableLFNST ||
                   ( lahtpDisableLFNST && !lahtpModeLocalDisableLFNST )) ? -mode : mode;

      xIntraCodingLumaQT(*csTemp, partitioner, lahtpPredBuf, bestCost, doISP, finalDisableMTS, lahtpModeLocalDisableLFNST);

      DTRACE(g_trace_ctx, D_INTRA_COST, "IntraCost T [x=%d,y=%d,w=%d,h=%d] %f (%d,%d,%d,%d,%d,%d) \n", cu.blocks[0].x,
        cu.blocks[0].y, width, height, csTemp->cost, testMode.modeId, testMode.ispMod,
        cu.multiRefIdx, cu.mipFlag, cu.lfnstIdx, cu.mtsFlag);

      if (cu.ispMode && !csTemp->cus[0]->firstTU->cbf[COMP_Y])
      {
        csTemp->cost = MAX_DOUBLE;
        csTemp->costDbOffset = 0;
      }
      if (useISPlfnst)
      {
        int n = (cu.ispMode == 0) ? 0 : 1;
        bestCostIsp[n] = csTemp->cost < bestCostIsp[n] ? csTemp->cost : bestCostIsp[n];
      }

      // check r-d cost
      if (csTemp->cost < csBest->cost)
      {
        validReturn   = true;
        std::swap(csTemp, csBest);
        bestPUMode    = testMode;
        bestLfnstIdx  = csBest->cus[0]->lfnstIdx;
        bestISP       = csBest->cus[0]->ispMode;
        bestMip       = csBest->cus[0]->mipFlag;
        bestMrl       = csBest->cus[0]->multiRefIdx;
        bestbdpcmMode = cu.bdpcmM[CH_L];
        m_ispTestedModes[bestLfnstIdx].bestSplitSoFar = ISPType(bestISP);
        if (csBest->cost < bestCost)
        {
          bestCost = csBest->cost;
        }
        if ((csBest->getTU(partitioner.chType)->mtsIdx[COMP_Y] == MTS_SKIP) && ( floorLog2(csBest->getTU(partitioner.chType)->blocks[COMP_Y].area()) >= 6 ))
        {
          noLFNST_ts = 1;
        }
      }

      // reset context models
      m_CABACEstimator->getCtx() = ctxStart;

      csTemp->releaseIntermediateData();

      if (m_pcEncCfg->m_fastLocalDualTreeMode && CU::isConsIntra(cu) && !cu.slice->isIntra() && csBest->cost != MAX_DOUBLE && costInterCU != COST_UNKNOWN && mode >= 0)
      {
        if( (m_pcEncCfg->m_fastLocalDualTreeMode == 2) || (csBest->cost > costInterCU * 1.5))
        {
          //Note: only try one intra mode, which is especially useful to reduce EncT for LDB case (around 4%)
          EndMode = 0;
          break;
        }
      }
    }
  } // Mode loop

  if (m_pcEncCfg->m_FastIntraTools && (sps.ISP|| sps.LFNST || sps.MTS))
  {
    int bestMode = csBest->getTU(partitioner.chType)->mtsIdx[COMP_Y] ? 4 : 0;
    bestMode |= bestLfnstIdx ? 2 : 0;
    bestMode |= bestISP ? 1 : 0;
    m_ispTestedModes[0].bestIntraMode = bestMode;
  }
  cu.ispMode = bestISP;
  if( validReturn )
  {
    cs.useSubStructure( *csBest, partitioner.chType, TREE_D, cu.singleChan( CH_L ), true );
    const ReshapeData& reshapeData = cs.picture->reshapeData;
    if (cs.picHeader->lmcsEnabled && reshapeData.getCTUFlag())
    {
      cs.getRspRecoBuf().copyFrom(csBest->getRspRecoBuf());
    }

    //=== update PU data ====
    cu.lfnstIdx           = bestLfnstIdx;
    cu.mipTransposedFlag  = bestPUMode.mipTrFlg;
    cu.intraDir[CH_L]     = bestPUMode.modeId;
    cu.bdpcmM[CH_L]       = bestbdpcmMode;
    cu.mipFlag            = bestMip;
    cu.multiRefIdx        = bestMrl;
  }
  else
  {
    THROW("fix this");
  }

  csBest->releaseIntermediateData();

  return validReturn;
}

void IntraSearch::estIntraPredChromaQT( CodingUnit& cu, Partitioner& partitioner, const double maxCostAllowed )
{
  PROFILER_SCOPE_AND_STAGE_EXT( 0, _TPROF, P_INTRA_CHROMA, cu.cs, CH_C );
  const TempCtx ctxStart( m_CtxCache, m_CABACEstimator->getCtx() );
  CodingStructure &cs   = *cu.cs;
  bool lumaUsesISP      = !CU::isSepTree(cu) && cu.ispMode;
  PartSplit ispType     = lumaUsesISP ? CU::getISPType(cu, COMP_Y) : TU_NO_ISP;
  double bestCostSoFar  = maxCostAllowed;
  const uint32_t numberValidComponents = getNumberValidComponents( cu.chromaFormat );
  const bool useBDPCM   = cs.picture->useBDPCM;

  uint32_t   uiBestMode = 0;
  Distortion uiBestDist = 0;
  double     dBestCost  = MAX_DOUBLE;

  //----- init mode list ----
  {
    uint32_t  uiMinMode = 0;
    uint32_t  uiMaxMode = NUM_CHROMA_MODE;

    const int reducedModeNumber = uiMaxMode >> (m_pcEncCfg->m_reduceIntraChromaModesFullRD ? 1 : 2);
    //----- check chroma modes -----
    uint32_t chromaCandModes[ NUM_CHROMA_MODE ];
    CU::getIntraChromaCandModes( cu, chromaCandModes );

    // create a temporary CS
    CodingStructure &saveCS = *m_pSaveCS[0];
    saveCS.pcv      = cs.pcv;
    saveCS.picture  = cs.picture;
    saveCS.area.repositionTo( cs.area );
    saveCS.clearTUs();

    if( !CU::isSepTree(cu) && cu.ispMode )
    {
      saveCS.clearCUs();
    }

    if( CU::isSepTree(cu) )
    {
      if( partitioner.canSplit( TU_MAX_TR_SPLIT, cs ) )
      {
        partitioner.splitCurrArea( TU_MAX_TR_SPLIT, cs );

        do
        {
          cs.addTU( CS::getArea( cs, partitioner.currArea(), partitioner.chType, partitioner.treeType ), partitioner.chType, &cu ).depth = partitioner.currTrDepth;
        } while( partitioner.nextPart( cs ) );

        partitioner.exitCurrSplit();
      }
      else
        cs.addTU( CS::getArea( cs, partitioner.currArea(), partitioner.chType, partitioner.treeType ), partitioner.chType, &cu );
    }

    // create a store for the TUs
    std::vector<TransformUnit*> orgTUs;
    for( const auto &ptu : cs.tus )
    {
      // for split TUs in HEVC, add the TUs without Chroma parts for correct setting of Cbfs
      if (lumaUsesISP || cu.contains(*ptu, CH_C))
      {
        saveCS.addTU( *ptu, partitioner.chType, nullptr );
        orgTUs.push_back( ptu );
      }
    }

    // SATD pre-selecting.
    int     satdModeList  [NUM_CHROMA_MODE] = { 0 };
    int64_t satdSortedCost[NUM_CHROMA_MODE] = { 0 };
    bool    modeDisable[NUM_INTRA_MODE + 1] = { false }; // use intra mode idx to check whether enable

    CodingStructure& cs = *(cu.cs);
    CompArea areaCb = cu.Cb();
    CompArea areaCr = cu.Cr();
    CPelBuf orgCb  = cs.getOrgBuf (COMP_Cb);
    PelBuf predCb  = cs.getPredBuf(COMP_Cb);
    CPelBuf orgCr  = cs.getOrgBuf (COMP_Cr);
    PelBuf predCr  = cs.getPredBuf(COMP_Cr);

    DistParam distParamSadCb  = m_pcRdCost->setDistParam( orgCb, predCb, cu.cs->sps->bitDepths[ CH_C ], DF_SAD);
    DistParam distParamSatdCb = m_pcRdCost->setDistParam( orgCb, predCb, cu.cs->sps->bitDepths[ CH_C ], DF_HAD);
    DistParam distParamSadCr  = m_pcRdCost->setDistParam( orgCr, predCr, cu.cs->sps->bitDepths[ CH_C ], DF_SAD);
    DistParam distParamSatdCr = m_pcRdCost->setDistParam( orgCr, predCr, cu.cs->sps->bitDepths[ CH_C ], DF_HAD);

    cu.intraDir[1] = MDLM_L_IDX; // temporary assigned, just to indicate this is a MDLM mode. for luma down-sampling operation.

    initIntraPatternChType(cu, cu.Cb());
    initIntraPatternChType(cu, cu.Cr());
    loadLMLumaRecPels(cu, cu.Cb());

    for (int idx = uiMinMode; idx < uiMaxMode; idx++)
    {
      int mode = chromaCandModes[idx];
      satdModeList[idx] = mode;
      if (CU::isLMCMode(mode) && ( !CU::isLMCModeEnabled(cu, mode) || cu.slice->lmChromaCheckDisable ) )
      {
        continue;
      }
      if ((mode == LM_CHROMA_IDX) || (mode == PLANAR_IDX) || (mode == DM_CHROMA_IDX)) // only pre-check regular modes and MDLM modes, not including DM ,Planar, and LM
      {
        continue;
      }

      cu.intraDir[1]    = mode; // temporary assigned, for SATD checking.

      const bool isLMCMode = CU::isLMCMode(mode);
      if( isLMCMode )
      {
        predIntraChromaLM(COMP_Cb, predCb, cu, areaCb, mode);
      }
      else
      {
        initPredIntraParams(cu, cu.Cb(), *cs.sps);
        predIntraAng(COMP_Cb, predCb, cu);
      }
      int64_t sadCb = distParamSadCb.distFunc(distParamSadCb) * 2;
      int64_t satdCb = distParamSatdCb.distFunc(distParamSatdCb);
      int64_t sad = std::min(sadCb, satdCb);

      if( isLMCMode )
      {
        predIntraChromaLM(COMP_Cr, predCr, cu, areaCr, mode);
      }
      else
      {
        initPredIntraParams(cu, cu.Cr(), *cs.sps);
        predIntraAng(COMP_Cr, predCr, cu);
      }
      int64_t sadCr = distParamSadCr.distFunc(distParamSadCr) * 2;
      int64_t satdCr = distParamSatdCr.distFunc(distParamSatdCr);
      sad += std::min(sadCr, satdCr);
      satdSortedCost[idx] = sad;
    }

    // sort the mode based on the cost from small to large.
    for (int i = uiMinMode; i <= uiMaxMode - 1; i++)
    {
      for (int j = i + 1; j <= uiMaxMode - 1; j++)
      {
        if (satdSortedCost[j] < satdSortedCost[i])
        {
          std::swap( satdModeList[i],   satdModeList[j]);
          std::swap( satdSortedCost[i], satdSortedCost[j]);
        }
      }
    }

    for (int i = 0; i < reducedModeNumber; i++)
    {
      modeDisable[satdModeList[uiMaxMode - 1 - i]] = true; // disable the last reducedModeNumber modes
    }

    int bestLfnstIdx = 0;
    // save the dist
    Distortion baseDist = cs.dist;
    int32_t bestbdpcmMode = 0;
    uint32_t numbdpcmModes = ( useBDPCM && CU::bdpcmAllowed(cu, COMP_Cb)
        && ((partitioner.chType == CH_C) || (cu.ispMode == 0 && cu.lfnstIdx == 0 && cu.firstTU->mtsIdx[COMP_Y] == MTS_SKIP))) ? 2 : 0;
    for (int mode_cur = uiMinMode; mode_cur < (int)(uiMaxMode + numbdpcmModes); mode_cur++)
    {
      int mode = mode_cur;
      if (mode_cur >= uiMaxMode)
      {
        mode = mode_cur > uiMaxMode ? -1 : -2; //set bdpcm mode
        if ((mode == -1) && (saveCS.tus[0]->mtsIdx[COMP_Cb] != MTS_SKIP) && (saveCS.tus[0]->mtsIdx[COMP_Cr] != MTS_SKIP))
        {
          continue;
        }
      }
      int chromaIntraMode;
      if (mode < 0)
      {
        cu.bdpcmM[CH_C] = -mode;
        chromaIntraMode = cu.bdpcmM[CH_C] == 2 ? chromaCandModes[1] : chromaCandModes[2];
      }
      else
      {
        cu.bdpcmM[CH_C] = 0;
        chromaIntraMode = chromaCandModes[mode];
        if (CU::isLMCMode(chromaIntraMode) && ( !CU::isLMCModeEnabled(cu, chromaIntraMode) || cu.slice->lmChromaCheckDisable ) )
        {
          continue;
        }
        if (modeDisable[chromaIntraMode] && CU::isLMCModeEnabled(cu, chromaIntraMode)) // when CCLM is disable, then MDLM is disable. not use satd checking
        {
          continue;
        }
      }
      cs.dist = baseDist;
      //----- restore context models -----
      m_CABACEstimator->getCtx() = ctxStart;

      //----- chroma coding -----
      cu.intraDir[1] = chromaIntraMode;
      m_ispTestedModes[0].IspType = ispType;
      m_ispTestedModes[0].subTuCounter = -1;
      xIntraChromaCodingQT( cs, partitioner );
      if (lumaUsesISP && cs.dist == MAX_UINT)
      {
        continue;
      }

      if (cs.sps->transformSkip)
      {
        m_CABACEstimator->getCtx() = ctxStart;
      }
      m_ispTestedModes[0].IspType = ispType;
      m_ispTestedModes[0].subTuCounter = -1;
      uint64_t fracBits   = xGetIntraFracBitsQT( cs, partitioner, false );
      Distortion uiDist = cs.dist;
      double    dCost   = m_pcRdCost->calcRdCost( fracBits, uiDist - baseDist );

      //----- compare -----
      if( dCost < dBestCost )
      {
        if (lumaUsesISP && (dCost < bestCostSoFar))
        {
          bestCostSoFar = dCost;
        }
        for( uint32_t i = getFirstComponentOfChannel( CH_C ); i < numberValidComponents; i++ )
        {
          const CompArea& area = cu.blocks[i];
          saveCS.getRecoBuf     ( area ).copyFrom( cs.getRecoBuf   ( area ) );
          cs.picture->getRecoBuf( area ).copyFrom( cs.getRecoBuf   ( area ) );
          for( uint32_t j = 0; j < saveCS.tus.size(); j++ )
          {
            saveCS.tus[j]->copyComponentFrom( *orgTUs[j], area.compID );
          }
        }
        dBestCost    = dCost;
        uiBestDist   = uiDist;
        uiBestMode   = chromaIntraMode;
        bestLfnstIdx = cu.lfnstIdx;
        bestbdpcmMode = cu.bdpcmM[CH_C];

      }
    }
    cu.lfnstIdx = bestLfnstIdx;
    cu.bdpcmM[CH_C]= bestbdpcmMode;

    for( uint32_t i = getFirstComponentOfChannel( CH_C ); i < numberValidComponents; i++ )
    {
      const CompArea& area = cu.blocks[i];

      cs.getRecoBuf         ( area ).copyFrom( saveCS.getRecoBuf( area ) );
      cs.picture->getRecoBuf( area ).copyFrom( cs.getRecoBuf    ( area ) );

      for( uint32_t j = 0; j < saveCS.tus.size(); j++ )
      {
        orgTUs[ j ]->copyComponentFrom( *saveCS.tus[ j ], area.compID );
      }
    }
  }
  cu.intraDir[1] = uiBestMode;
  cs.dist        = uiBestDist;

  //----- restore context models -----
  m_CABACEstimator->getCtx() = ctxStart;
  if (lumaUsesISP && bestCostSoFar >= maxCostAllowed)
  {
    cu.ispMode = 0;
  }
}

void IntraSearch::saveCuAreaCostInSCIPU( Area area, double cost )
{
  if( m_numCuInSCIPU < NUM_INTER_CU_INFO_SAVE )
  {
    m_cuAreaInSCIPU[m_numCuInSCIPU] = area;
    m_cuCostInSCIPU[m_numCuInSCIPU] = cost;
    m_numCuInSCIPU++;
  }
}

void IntraSearch::initCuAreaCostInSCIPU()
{
  for( int i = 0; i < NUM_INTER_CU_INFO_SAVE; i++ )
  {
    m_cuAreaInSCIPU[i] = Area();
    m_cuCostInSCIPU[i] = 0;
  }
  m_numCuInSCIPU = 0;
}
// -------------------------------------------------------------------------------------------------------------------
// Intra search
// -------------------------------------------------------------------------------------------------------------------

void IntraSearch::xEncIntraHeader( CodingStructure &cs, Partitioner &partitioner, const bool luma )
{
  CodingUnit &cu = *cs.getCU( partitioner.chType, partitioner.treeType );

  if (luma)
  {
    bool isFirst = cu.ispMode ? m_ispTestedModes[0].subTuCounter == 0 : partitioner.currArea().lumaPos() == cs.area.lumaPos();

    // CU header
    if( isFirst )
    {
      if ((!cs.slice->isIntra() || cs.slice->sps->IBC || cs.slice->sps->PLT) && cu.Y().valid())
      {
        m_CABACEstimator->pred_mode   ( cu );
      }
      m_CABACEstimator->bdpcm_mode  ( cu, ComponentID(partitioner.chType) );
    }

    // luma prediction mode
    if (isFirst)
    {
      if ( !cu.Y().valid())
      {
        m_CABACEstimator->pred_mode( cu );
      }
      m_CABACEstimator->intra_luma_pred_mode( cu );
    }
  }
  else //  if (chroma)
  {
    bool isFirst = partitioner.currArea().Cb().valid() && partitioner.currArea().chromaPos() == cs.area.chromaPos();

    if( isFirst )
    {
      m_CABACEstimator->bdpcm_mode(cu, ComponentID(CH_C));
      m_CABACEstimator->intra_chroma_pred_mode(  cu );
    }
  }
}

void IntraSearch::xEncSubdivCbfQT( CodingStructure &cs, Partitioner &partitioner, const bool luma )
{
  const UnitArea& currArea = partitioner.currArea();
  int subTuCounter = m_ispTestedModes[0].subTuCounter;
  TransformUnit  &currTU   = *cs.getTU(currArea.blocks[partitioner.chType], partitioner.chType, subTuCounter);
  CodingUnit     &currCU   = *currTU.cu;
  const uint32_t currDepth = partitioner.currTrDepth;
  const bool  subdiv = currTU.depth > currDepth;
  ComponentID compID = partitioner.chType == CH_L ? COMP_Y : COMP_Cb;

  if (!luma)
  {
    const bool chromaCbfISP = currArea.blocks[COMP_Cb].valid() && currCU.ispMode && !subdiv;
    if (!currCU.ispMode || chromaCbfISP)
    {
      const uint32_t numberValidComponents = getNumberValidComponents(currArea.chromaFormat);
      const uint32_t cbfDepth = (chromaCbfISP ? currDepth - 1 : currDepth);

      for (uint32_t ch = COMP_Cb; ch < numberValidComponents; ch++)
      {
        const ComponentID compID = ComponentID(ch);
        if (currDepth == 0 || TU::getCbfAtDepth(currTU, compID, currDepth - 1) || chromaCbfISP)
        {
          const bool prevCbf = (compID == COMP_Cr ? TU::getCbfAtDepth(currTU, COMP_Cb, currDepth) : false);
          m_CABACEstimator->cbf_comp(currCU, TU::getCbfAtDepth(currTU, compID, currDepth), currArea.blocks[compID], cbfDepth, prevCbf);
        }
      }
    }
  }

  if (subdiv)
  {
    if (partitioner.canSplit(TU_MAX_TR_SPLIT, cs))
    {
      partitioner.splitCurrArea(TU_MAX_TR_SPLIT, cs);
    }
    else if (currCU.ispMode && isLuma(compID))
    {
      partitioner.splitCurrArea(m_ispTestedModes[0].IspType, cs);
    }
    else
      THROW("Cannot perform an implicit split!");

    do
    {
      xEncSubdivCbfQT(cs, partitioner, luma);   //?
      subTuCounter += subTuCounter != -1 ? 1 : 0;
    } while (partitioner.nextPart(cs));

    partitioner.exitCurrSplit();
  }
  else
  {
    //===== Cbfs =====
    if (luma)
    {
      bool previousCbf = false;
      bool lastCbfIsInferred = false;
      if (m_ispTestedModes[0].IspType != TU_NO_ISP)
      {
        bool     rootCbfSoFar = false;
        uint32_t nTus = currCU.ispMode == HOR_INTRA_SUBPARTITIONS ? currCU.lheight() >> floorLog2(currTU.lheight())
          : currCU.lwidth() >> floorLog2(currTU.lwidth());
        if (subTuCounter == nTus - 1)
        {
          TransformUnit* tuPointer = currCU.firstTU;
          for (int tuIdx = 0; tuIdx < nTus - 1; tuIdx++)
          {
            rootCbfSoFar |= TU::getCbfAtDepth(*tuPointer, COMP_Y, currDepth);
            tuPointer = tuPointer->next;
          }
          if (!rootCbfSoFar)
          {
            lastCbfIsInferred = true;
          }
        }
        if (!lastCbfIsInferred)
        {
          previousCbf = TU::getPrevTuCbfAtDepth(currTU, COMP_Y, partitioner.currTrDepth);
        }
      }
      if (!lastCbfIsInferred)
      {
        m_CABACEstimator->cbf_comp(currCU, TU::getCbfAtDepth(currTU, COMP_Y, currDepth), currTU.Y(), currTU.depth, previousCbf, currCU.ispMode);
      }
    }
  }
}
void IntraSearch::xEncCoeffQT(CodingStructure& cs, Partitioner& partitioner, const ComponentID compID, CUCtx* cuCtx, const int subTuIdx, const PartSplit ispType)
{
  const UnitArea& currArea  = partitioner.currArea();

  int subTuCounter          = m_ispTestedModes[0].subTuCounter;
  TransformUnit& currTU     = *cs.getTU(currArea.blocks[partitioner.chType], partitioner.chType, subTuCounter);
  uint32_t   currDepth      = partitioner.currTrDepth;
  const bool subdiv         = currTU.depth > currDepth;

  if (subdiv)
  {
    if (partitioner.canSplit(TU_MAX_TR_SPLIT, cs))
    {
      partitioner.splitCurrArea(TU_MAX_TR_SPLIT, cs);
    }
    else if (currTU.cu->ispMode)
    {
      partitioner.splitCurrArea(m_ispTestedModes[0].IspType, cs);
    }
    else
      THROW("Implicit TU split not available!");

    do
    {
      xEncCoeffQT(cs, partitioner, compID, cuCtx, subTuCounter, m_ispTestedModes[0].IspType);
      subTuCounter += subTuCounter != -1 ? 1 : 0;
    } while( partitioner.nextPart( cs ) );

    partitioner.exitCurrSplit();
  }
  else

  if( currArea.blocks[compID].valid() )
  {
    if( compID == COMP_Cr )
    {
      const int cbfMask = ( TU::getCbf( currTU, COMP_Cb ) ? 2 : 0 ) + ( TU::getCbf( currTU, COMP_Cr ) ? 1 : 0 );
      m_CABACEstimator->joint_cb_cr( currTU, cbfMask );
    }
    if( TU::getCbf( currTU, compID ) )
    {
      if( isLuma(compID) )
      {
        m_CABACEstimator->residual_coding( currTU, compID, cuCtx );
        m_CABACEstimator->mts_idx( *currTU.cu, cuCtx );
      }
      else
        m_CABACEstimator->residual_coding( currTU, compID );
    }
  }
}

uint64_t IntraSearch::xGetIntraFracBitsQT( CodingStructure &cs, Partitioner &partitioner, const bool luma, CUCtx *cuCtx )
{
  m_CABACEstimator->resetBits();

  xEncIntraHeader( cs, partitioner, luma );
  xEncSubdivCbfQT( cs, partitioner, luma );

  if( luma )
  {
    xEncCoeffQT( cs, partitioner, COMP_Y, cuCtx );

    CodingUnit &cu = *cs.cus[0];
    if (cuCtx /*&& CU::isSepTree(cu)*/
      && (!cu.ispMode || (cu.lfnstIdx && m_ispTestedModes[0].subTuCounter == 0)
        || (!cu.lfnstIdx
          && m_ispTestedModes[0].subTuCounter == m_ispTestedModes[cu.lfnstIdx].numTotalParts[cu.ispMode - 1] - 1)))
    {
      m_CABACEstimator->residual_lfnst_mode( cu, *cuCtx );
    }
  }
  else
  {
    xEncCoeffQT( cs, partitioner, COMP_Cb );
    xEncCoeffQT( cs, partitioner, COMP_Cr );
  }

  uint64_t fracBits = m_CABACEstimator->getEstFracBits();
  return fracBits;
}

uint64_t IntraSearch::xGetIntraFracBitsQTChroma(const TransformUnit& currTU, const ComponentID compID, CUCtx *cuCtx)
{
  m_CABACEstimator->resetBits();

  if ( currTU.jointCbCr )
  {
    const int cbfMask = ( TU::getCbf( currTU, COMP_Cb ) ? 2 : 0 ) + ( TU::getCbf( currTU, COMP_Cr ) ? 1 : 0 );
    m_CABACEstimator->cbf_comp( *currTU.cu, cbfMask>>1, currTU.blocks[ COMP_Cb ], currTU.depth, false );
    m_CABACEstimator->cbf_comp( *currTU.cu, cbfMask &1, currTU.blocks[ COMP_Cr ], currTU.depth, cbfMask>>1 );
    if( cbfMask )
      m_CABACEstimator->joint_cb_cr( currTU, cbfMask );
    if (cbfMask >> 1)
      m_CABACEstimator->residual_coding( currTU, COMP_Cb, cuCtx );
    if (cbfMask & 1)
      m_CABACEstimator->residual_coding( currTU, COMP_Cr, cuCtx );
  }
  else
  {
    if ( compID == COMP_Cb )
      m_CABACEstimator->cbf_comp( *currTU.cu, TU::getCbf( currTU, compID ), currTU.blocks[ compID ], currTU.depth, false );
    else
    {
      const bool cbCbf    = TU::getCbf( currTU, COMP_Cb );
      const bool crCbf    = TU::getCbf( currTU, compID );
      const int  cbfMask  = ( cbCbf ? 2 : 0 ) + ( crCbf ? 1 : 0 );
      m_CABACEstimator->cbf_comp( *currTU.cu, crCbf, currTU.blocks[ compID ], currTU.depth, cbCbf );
      m_CABACEstimator->joint_cb_cr( currTU, cbfMask );
    }
  }

  if( !currTU.jointCbCr && TU::getCbf( currTU, compID ) )
  {
    m_CABACEstimator->residual_coding( currTU, compID, cuCtx );
  }

  uint64_t fracBits = m_CABACEstimator->getEstFracBits();
  return fracBits;
}

void IntraSearch::xIntraCodingTUBlock(TransformUnit &tu, const ComponentID compID, const bool checkCrossCPrediction, Distortion &ruiDist, uint32_t *numSig, PelUnitBuf *predBuf, const bool loadTr)
{
  if (!tu.blocks[compID].valid())
  {
    return;
  }

  CodingStructure &cs             = *tu.cs;
  const CompArea      &area       = tu.blocks[compID];
  const SPS           &sps        = *cs.sps;
  const ReshapeData&  reshapeData = cs.picture->reshapeData;

  const ChannelType    chType     = toChannelType(compID);
  const int            bitDepth   = sps.bitDepths[chType];

  CPelBuf        piOrg            = cs.getOrgBuf    (area);
  PelBuf         piPred           = cs.getPredBuf   (area);
  PelBuf         piResi           = cs.getResiBuf   (area);
  PelBuf         piReco           = cs.getRecoBuf   (area);

  const CodingUnit& cu            = *tu.cu;

  //===== init availability pattern =====
  CHECK( tu.jointCbCr && compID == COMP_Cr, "wrong combination of compID and jointCbCr" );
  bool jointCbCr = tu.jointCbCr && compID == COMP_Cb;

  if ( isLuma(compID) )
  {
    bool predRegDiffFromTB = CU::isPredRegDiffFromTB(*tu.cu );
    bool firstTBInPredReg  = false;
    CompArea areaPredReg(COMP_Y, tu.chromaFormat, area);
    if (tu.cu->ispMode )
    {
      firstTBInPredReg = CU::isFirstTBInPredReg(*tu.cu, area);
      if (predRegDiffFromTB)
      {
        if (firstTBInPredReg)
        {
          CU::adjustPredArea(areaPredReg);
          initIntraPatternChTypeISP(*tu.cu, areaPredReg, piReco);
        }
      }
      else
        initIntraPatternChTypeISP(*tu.cu, area, piReco);
    }
    else if( !predBuf )
    {
      initIntraPatternChType(*tu.cu, area);
    }

    //===== get prediction signal =====
    if (predRegDiffFromTB)
    {
      if (firstTBInPredReg)
      {
        PelBuf piPredReg = cs.getPredBuf(areaPredReg);
        predIntraAng(compID, piPredReg, cu);
      }
    }
    else
    {
      if( predBuf )
      {
        piPred.copyFrom( predBuf->Y() );
      }
      else if( CU::isMIP( cu, CH_L ) )
      {
        initIntraMip( cu );
        predIntraMip( piPred, cu );
      }
      else
      {
        predIntraAng(compID, piPred, cu);
      }
    }
  }
  DTRACE( g_trace_ctx, D_PRED, "@(%4d,%4d) [%2dx%2d] IMode=%d\n", tu.lx(), tu.ly(), tu.lwidth(), tu.lheight(), CU::getFinalIntraMode(cu, chType) );
  const Slice &slice = *cs.slice;
  bool flag = cs.picHeader->lmcsEnabled && (slice.isIntra() || (!slice.isIntra() && reshapeData.getCTUFlag()));

  if (isLuma(compID))
  {
    //===== get residual signal =====
    if (cs.picHeader->lmcsEnabled && reshapeData.getCTUFlag() )
    {
      piResi.subtract(cs.getRspOrgBuf(area), piPred);
    }
    else
    {
      piResi.subtract( piOrg, piPred );
    }
  }

  //===== transform and quantization =====
  //--- init rate estimation arrays for RDOQ ---
  //--- transform and quantization           ---
  TCoeff uiAbsSum = 0;
  const QpParam cQP(tu, compID);

  m_pcTrQuant->selectLambda(compID);

  flag =flag && (tu.blocks[compID].width*tu.blocks[compID].height > 4);
  if (flag && isChroma(compID) && cs.picHeader->lmcsChromaResidualScale )
  {
    int cResScaleInv = tu.chromaAdj;
    double cRescale = (double)(1 << CSCALE_FP_PREC) / (double)cResScaleInv;
    m_pcTrQuant->scaleLambda( 1.0/(cRescale*cRescale) );
  }

  if ( jointCbCr )
  {
    // Lambda is loosened for the joint mode with respect to single modes as the same residual is used for both chroma blocks
    const int    absIct = abs( TU::getICTMode(tu) );
    const double lfact  = ( absIct == 1 || absIct == 3 ? 0.8 : 0.5 );
    m_pcTrQuant->scaleLambda( lfact );
  }
  if ( sps.jointCbCr && isChroma(compID) && (tu.cu->cs->slice->sliceQp > 18) )
  {
    m_pcTrQuant->scaleLambda( 1.3 );
  }

  if( isLuma(compID) )
  {
    m_pcTrQuant->transformNxN(tu, compID, cQP, uiAbsSum, m_CABACEstimator->getCtx(), loadTr);

    DTRACE( g_trace_ctx, D_TU_ABS_SUM, "%d: comp=%d, abssum=%d\n", DTRACE_GET_COUNTER( g_trace_ctx, D_TU_ABS_SUM ), compID, uiAbsSum );
    if (tu.cu->ispMode && isLuma(compID) && CU::isISPLast(*tu.cu, area, area.compID) && CU::allLumaCBFsAreZero(*tu.cu))
    {
      // ISP has to have at least one non-zero CBF
      ruiDist = MAX_INT;
      return;
    }
    //--- inverse transform ---
    if (uiAbsSum > 0)
    {
      m_pcTrQuant->invTransformNxN(tu, compID, piResi, cQP);
    }
    else
    {
      piResi.fill(0);
    }
  }
  else // chroma
  {
    PelBuf          crPred = cs.getPredBuf ( COMP_Cr );
    PelBuf          crResi = cs.getResiBuf ( COMP_Cr );
    PelBuf          crReco = cs.getRecoBuf ( COMP_Cr );

    int         codedCbfMask  = 0;
    ComponentID codeCompId    = (tu.jointCbCr ? (tu.jointCbCr >> 1 ? COMP_Cb : COMP_Cr) : compID);
    const QpParam qpCbCr(tu, codeCompId);

    if( tu.jointCbCr )
    {
      ComponentID otherCompId = ( codeCompId==COMP_Cr ? COMP_Cb : COMP_Cr );
      tu.getCoeffs( otherCompId ).fill(0); // do we need that?
      TU::setCbfAtDepth (tu, otherCompId, tu.depth, false );
    }
    PelBuf& codeResi = ( codeCompId == COMP_Cr ? crResi : piResi );
    uiAbsSum = 0;
    m_pcTrQuant->transformNxN(tu, codeCompId, qpCbCr, uiAbsSum, m_CABACEstimator->getCtx(), loadTr);
    DTRACE( g_trace_ctx, D_TU_ABS_SUM, "%d: comp=%d, abssum=%d\n", DTRACE_GET_COUNTER( g_trace_ctx, D_TU_ABS_SUM ), codeCompId, uiAbsSum );
    if( uiAbsSum > 0 )
    {
      m_pcTrQuant->invTransformNxN(tu, codeCompId, codeResi, qpCbCr);
      codedCbfMask += ( codeCompId == COMP_Cb ? 2 : 1 );
    }
    else
    {
      codeResi.fill(0);
    }

    if( tu.jointCbCr )
    {
      if( tu.jointCbCr == 3 && codedCbfMask == 2 )
      {
        codedCbfMask = 3;
        TU::setCbfAtDepth (tu, COMP_Cr, tu.depth, true );
      }
      if( tu.jointCbCr != codedCbfMask )
      {
        ruiDist = MAX_DISTORTION;
        return;
      }
      m_pcTrQuant->invTransformICT( tu, piResi, crResi );
      uiAbsSum = codedCbfMask;
    }

    //===== reconstruction =====
    if ( flag && uiAbsSum > 0 && cs.picHeader->lmcsChromaResidualScale )
    {
      piResi.scaleSignal(tu.chromaAdj, 0, slice.clpRngs[compID]);

      if( jointCbCr )
      {
        crResi.scaleSignal(tu.chromaAdj, 0, slice.clpRngs[COMP_Cr]);
      }
    }

    if( jointCbCr )
    {
      crReco.reconstruct(crPred, crResi, cs.slice->clpRngs[ COMP_Cr ]);
    }
  }
  piReco.reconstruct(piPred, piResi, cs.slice->clpRngs[ compID ]);
  


  //===== update distortion =====
  const bool reshapeIntraCMD = m_pcEncCfg->m_reshapeSignalType == RESHAPE_SIGNAL_PQ;
  if(((cs.picHeader->lmcsEnabled && (reshapeData.getCTUFlag() || (isChroma(compID) && reshapeIntraCMD))) || m_pcEncCfg->m_lumaLevelToDeltaQPEnabled ) )
  {
    const CPelBuf orgLuma = cs.getOrgBuf( cs.area.blocks[COMP_Y] );
    if( compID == COMP_Y && !m_pcEncCfg->m_lumaLevelToDeltaQPEnabled )
    {
      PelBuf tmpRecLuma = cs.getRspRecoBuf(area);
      tmpRecLuma.rspSignal( piReco, reshapeData.getInvLUT());
      ruiDist += m_pcRdCost->getDistPart(piOrg, tmpRecLuma, sps.bitDepths[toChannelType(compID)], compID, DF_SSE_WTD, &orgLuma);
    }
    else
    {
      ruiDist += m_pcRdCost->getDistPart( piOrg, piReco, bitDepth, compID, DF_SSE_WTD, &orgLuma );
      if( jointCbCr )
      {
        CPelBuf         crOrg  = cs.getOrgBuf  ( COMP_Cr );
        PelBuf          crReco = cs.getRecoBuf ( COMP_Cr );
        ruiDist += m_pcRdCost->getDistPart( crOrg, crReco, bitDepth, COMP_Cr, DF_SSE_WTD, &orgLuma );
      }
    }
  }
  else
  {
    ruiDist += m_pcRdCost->getDistPart( piOrg, piReco, bitDepth, compID, DF_SSE );
    if( jointCbCr )
    {
      CPelBuf         crOrg  = cs.getOrgBuf  ( COMP_Cr );
      PelBuf          crReco = cs.getRecoBuf ( COMP_Cr );
      ruiDist += m_pcRdCost->getDistPart( crOrg, crReco, bitDepth, COMP_Cr, DF_SSE );
    }
  }
}

void IntraSearch::xIntraCodingLumaQT(CodingStructure& cs, Partitioner& partitioner, PelUnitBuf* predBuf, const double bestCostSoFar, int numMode, bool disableMTS, bool disableLFNST)
{
  PROFILER_SCOPE_AND_STAGE_EXT( 0, _TPROF, P_INTRA_RD_SEARCH_LUMA, &cs, partitioner.chType );
  saldanha::Runtime& saldanhaRun = saldanha::runtime();
  CHECK(saldanhaRun.mode != saldanha::Runtime::OFF &&
        (m_pcEncCfg->m_LardLfnstSkip != 0 || m_pcEncCfg->m_EarlyForceNoNonzeroLfnst),
        "Saldanha requires project LFNST pruning disabled");
  saldanha::Features saldanhaF{};
  bool saldanhaCaptured = false, saldanhaSkip = false;
  const UnitArea& currArea  = partitioner.currArea();
  uint32_t        currDepth = partitioner.currTrDepth;
  Distortion singleDistLuma = 0;
  uint32_t   numSig         = 0;
  const SPS &sps            = *cs.sps;
  CodingUnit &cu            = *cs.cus[0];
  Lard18ScopedIntraTimer lard18IntraTimer( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst18StatFile : nullptr,
                                           cu.qp, cu.lwidth(), cu.lheight() );
  const bool lfnstPrunedByCaller = numMode < 0;
  bool mtsAllowed = (numMode < 0) || disableMTS ? false : CU::isMTSAllowed(cu, COMP_Y);
  uint64_t singleFracBits   = 0;
  bool   splitCbfLumaSum    = false;
  double bestCostForISP     = bestCostSoFar;
  double dSingleCost        = MAX_DOUBLE;
  int endLfnstIdx           = (partitioner.isSepTree(cs) && partitioner.chType == CH_C && (currArea.lwidth() < 8 || currArea.lheight() < 8))
                           || (currArea.lwidth() > sps.getMaxTbSize() || currArea.lheight() > sps.getMaxTbSize()) || !sps.LFNST || (numMode < 0) || disableLFNST ? 0 : 2;
  const bool useTS          = cs.picture->useTS;
  numMode                   = (numMode < 0) ? -numMode : numMode;

  const bool lahtpTraceEnabled = m_pcEncCfg && m_pcEncCfg->m_LardLfnstTraceFile[0] != '\0' && predBuf != nullptr;
  LahtpFeatures lahtpTraceF;
  if( lahtpTraceEnabled )
  {
    lahtpTraceF = xGetLahtpFeatures( cu, cs.getOrgBuf( COMP_Y ), predBuf->Y() );
  }

  const bool lahtpLazyTwoStage = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip >= 6 && m_pcEncCfg->m_LardLfnstSkip <= 7 && predBuf != nullptr && xLahtpCanApply( cu, numMode );
  LahtpFeatures lahtpLazyF;
  if( lahtpLazyTwoStage )
  {
    lahtpLazyF = xGetLahtpFeatures( cu, cs.getOrgBuf( COMP_Y ), predBuf->Y() );
  }

  const bool lardLfnstCandGain = m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstSkip == 8 || m_pcEncCfg->m_LardLfnstSkip == 9 ) && predBuf != nullptr && xLahtpCanApply( cu, numMode );
  LahtpFeatures lardCandF;
  if( lardLfnstCandGain )
  {
    lardCandF = xGetLahtpFeatures( cu, cs.getOrgBuf( COMP_Y ), predBuf->Y() );
  }

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
  const bool lardLfnst2ndStatsOnly = m_pcEncCfg
                                  && m_pcEncCfg->m_LardLfnstSkip == 0
                                  && m_pcEncCfg->m_LardLfnst2ndMeasureOnly != 0
                                  && m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] != '\0';
  const bool lardLfnstSkip13       = m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstSkip == 13 || lardLfnst2ndStatsOnly );
  const bool lardLfnstSkip14       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 14;
  const bool lardLfnstSkip15       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 15;
  const bool lardLfnstSkip16       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 16;
  const bool lardLfnstSkip17       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 17;
  const bool lardLfnstSkip18       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 18;
  const bool lardLfnstSkip19       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 19;
  const bool lardLfnstSkip20       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 20;
  const bool lardLfnstSkip21       = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 21;
  const bool lardLfnstCovMode      = lardLfnstSkip15 || lardLfnstSkip16 || lardLfnstSkip17 || lardLfnstSkip18;
  const bool lardLfnst2ndMode      = m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstSkip == 10 || m_pcEncCfg->m_LardLfnstSkip == 11 || lardLfnstSkip13 || lardLfnstSkip14 || lardLfnstSkip19 );
  const bool lardLfnstSkip11       = m_pcEncCfg && ( m_pcEncCfg->m_LardLfnstSkip == 11 || lardLfnstSkip13 );
  const int lardLfnst2ndEffColsMin = xLard2ndEffColsMinForQp( m_pcEncCfg, cu.qp );
  const bool lardLfnst2ndVecTrace = m_pcEncCfg && m_pcEncCfg->m_LardLfnst2ndVecFile[0] != '\0' && predBuf != nullptr;
  const int lard2ndArea = cu.lwidth() * cu.lheight();
  const bool lardLfnst2ndCanApply = lardLfnst2ndStatsOnly
                                  ? ( predBuf != nullptr && numMode >= 0
                                   && !cu.ispMode && !cu.mipFlag && !cu.multiRefIdx && !cu.bdpcmM[CH_L]
                                   && lard2ndArea >= 16 && cu.lwidth() >= 4 && cu.lheight() >= 4
                                   && cu.lwidth() <= 4 * cu.lheight() && cu.lheight() <= 4 * cu.lwidth() )
                                  : ( predBuf != nullptr && xLahtpCanApply( cu, numMode ) );
  const bool lardLfnstSkip11NeedsStage = !lardLfnstSkip11
                                       || xLard11RespPolicyCanApply( m_pcEncCfg, cu )
                                       || ( m_pcEncCfg->m_LardLfnst2ndEffColsGate && lardLfnst2ndEffColsMin > 0 )
                                       || lardLfnst2ndVecTrace;
  const bool lardLfnst2ndCandidate = !disableLFNST && lardLfnst2ndMode && lardLfnstSkip11NeedsStage && lardLfnst2ndCanApply;
  const bool lardLfnst2ndPolicy    = lardLfnst2ndCandidate && ( lardLfnstSkip11 || xLard2ndPolicyCanApply( m_pcEncCfg, cu ) );
  if( lardLfnst2ndCandidate && !lardLfnstSkip11 && !lardLfnst2ndPolicy && m_pcEncCfg->m_LardLfnst2ndCountFile[0] != '\0' )
  {
    xLard2ndCountPolicyReject( m_pcEncCfg->m_LardLfnst2ndCountFile, cu.qp,
                               cu.qp > m_pcEncCfg->m_LardLfnst2ndMaxCuQp,
                               lard2ndArea < m_pcEncCfg->m_LardLfnst2ndMinArea
                            || cu.lwidth() < m_pcEncCfg->m_LardLfnst2ndMinWidth
                            || cu.lheight() < m_pcEncCfg->m_LardLfnst2ndMinHeight );
  }
  const bool lardLfnst2ndBase = lardLfnst2ndCandidate && lardLfnst2ndPolicy;
  const bool lardLfnst2ndCount = lardLfnst2ndBase && m_pcEncCfg->m_LardLfnst2ndCountFile[0] != '\0';
  const bool lardLfnst2ndMeasureOnly = lardLfnst2ndBase && m_pcEncCfg->m_LardLfnst2ndMeasureOnly != 0;
  LahtpFeatures lard2ndF;
  if( lardLfnst2ndBase )
  {
    const LahtpStage1Decision stage1 = xGetLahtpStage1Decision( cu );
    lard2ndF.absLatDeg    = stage1.absLatDeg;
    lard2ndF.thetaMaxDeg  = stage1.thetaMaxDeg;
    lard2ndF.thetaSkipDeg = stage1.thetaSkipDeg;
    lard2ndF.cosLat       = stage1.cosLat;
    lard2ndF.rawCosLat    = stage1.rawCosLat;
    lard2ndF.stage1       = stage1.stage1;
    lard2ndF.stage2       = false;
  }
  Lard14EarlyProxyDecision lard14ShadowEarlyProxy;
  bool lard14ShadowEarlyValid = false;
  bool lard14ShadowEarlyGeom = false;
  bool lard14ShadowEarlyRoiFull = false;
  double lard14ShadowEarlyMh = 0.0;
  if( lardLfnstSkip14 && lardLfnst2ndBase && m_pcEncCfg->m_LardLfnst2ndFinalStatFile[0] != '\0' && predBuf != nullptr )
  {
    CPelBuf lard14Org = cs.getOrgBuf( COMP_Y );
    const ReshapeData& lard14ReshapeData = cs.picture->reshapeData;
    if( cs.picHeader->lmcsEnabled && lard14ReshapeData.getCTUFlag() )
    {
      lard14Org = cs.getRspOrgBuf();
    }
    lard14ShadowEarlyValid = true;
    lard14ShadowEarlyMh = (double)xLard14EffectiveLfSupportCols( cu.lwidth(), cu.lheight(), lard2ndF.rawCosLat );
    lard14ShadowEarlyGeom = m_pcEncCfg->m_LardLfnst14EarlyDisable != 0 && lard14ShadowEarlyMh < 2.0;
    lard14ShadowEarlyRoiFull = xLard14EarlyRoiDisable( lard2ndF );
    lard14ShadowEarlyProxy = xLard14EarlyRoiProxyDecision( cu, lard14Org, predBuf->Y(), lard2ndF );
  }
  const bool lardLfnst2ndEffColsSkip = lardLfnst2ndBase
                                    && !lardLfnstSkip14
                                    && m_pcEncCfg->m_LardLfnst2ndEffColsGate
                                    && lardLfnst2ndEffColsMin > 0
                                    && xLard2ndEffectiveHorizontalCols( cu.lwidth(), lard2ndF.rawCosLat ) < lardLfnst2ndEffColsMin;
  const bool lardLfnst2ndEffColsOnly = lardLfnst2ndBase && m_pcEncCfg->m_LardLfnst2ndEffColsOnly != 0;
  const bool lardLfnst11RespGate = lardLfnst2ndBase && lardLfnstSkip11 && !lardLfnst2ndEffColsSkip && xLard11RespPolicyCanApply( m_pcEncCfg, cu );
  const bool lardLfnst14NoTraceSupportMode = lardLfnstSkip14
                                           && m_pcEncCfg->m_LardLfnst14EarlyDisable != 0
                                           && xLard14NoDecisionTrace( m_pcEncCfg )
                                           && xLard14DecisionModeForQp( m_pcEncCfg, cu.qp ) == 1;
  const bool lardLfnst14NoTraceSupportSkip = lardLfnst14NoTraceSupportMode
                                          && xLard14EffectiveLfSupportCols( cu.lwidth(), cu.lheight(), lard2ndF.rawCosLat ) < 2;
  const bool lardLfnst19EarlySupportSkip = lardLfnstSkip19
                                         && lardLfnst2ndBase
                                         && xLard14NoDecisionTrace( m_pcEncCfg )
                                         && xLard14EffectiveLfSupportCols( cu.lwidth(), cu.lheight(), lard2ndF.rawCosLat ) < 2;
  const bool lardLfnst2ndResp = lardLfnst2ndBase
                              && !lardLfnst14NoTraceSupportSkip
                              && !lardLfnst19EarlySupportSkip
                              && ( lardLfnstSkip11 ? lardLfnst11RespGate : ( lardLfnstSkip14 || lardLfnstSkip19 || !lardLfnst2ndEffColsOnly ) )
                              && ( lardLfnst2ndCount || lard2ndF.stage1 || lardLfnstSkip14 || lardLfnstSkip19 );
  LahtpFeatures lard2ndVecF;
  if( lardLfnst2ndVecTrace )
  {
    lard2ndVecF = lardLfnst2ndBase ? lard2ndF : xGetLahtpFeatures( cu, cs.getOrgBuf( COMP_Y ), predBuf->Y() );
  }
  if( lardLfnst2ndEffColsSkip && !lardLfnst2ndMeasureOnly )
  {
    endLfnstIdx = 0;
  }
  if( lardLfnst14NoTraceSupportSkip )
  {
    endLfnstIdx = 0;
  }
  if( lardLfnst19EarlySupportSkip )
  {
    endLfnstIdx = 0;
  }
#endif
  LardSkip21EarlyDecision lardSkip21Decision;
  if( lardLfnstSkip21 && endLfnstIdx > 0 )
  {
    lardSkip21Decision = xLardSkip21EarlyDecision( m_pcEncCfg, cu );
    xLardSkip21AppendStage1Stat( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst21StatFile : nullptr, cu, lardSkip21Decision );
  }
  const bool lardLfnst21EarlySkip = lardSkip21Decision.earlyZero;
  if( lardLfnst21EarlySkip )
  {
    endLfnstIdx = 0;
  }
  if( m_pcEncCfg && m_pcEncCfg->m_EarlyForceNoNonzeroLfnst )
  {
    endLfnstIdx = 0;
  }

  if (cu.mipFlag && !allowLfnstWithMip(cu.lumaSize()))
  {
    endLfnstIdx = 0;
  }
  int bestMTS = 0;
  int EndMTS  = mtsAllowed ? m_pcEncCfg->m_MTSIntraMaxCand : 0;
  if (cu.ispMode && (EndMTS || endLfnstIdx))
  {
    EndMTS = 0;
    if ((m_ispTestedModes[1].numTotalParts[cu.ispMode - 1] == 0)
     && (m_ispTestedModes[2].numTotalParts[cu.ispMode - 1] == 0))
    {
      endLfnstIdx = 0;
    }
  }
  if (cu.bdpcmM[CH_L])
  {
    endLfnstIdx = 0;
    EndMTS = 0;
  }
  bool checkTransformSkip = sps.transformSkip;

  SizeType transformSkipMaxSize = 1 << sps.log2MaxTransformSkipBlockSize;
  bool tsAllowed = useTS  && cu.cs->sps->transformSkip && (!cu.ispMode) && (!cu.bdpcmM[CH_L]) && (!cu.sbtInfo);
  tsAllowed &= cu.blocks[COMP_Y].width <= transformSkipMaxSize && cu.blocks[COMP_Y].height <= transformSkipMaxSize;
  if (tsAllowed)
  {
    EndMTS += 1;
  }
  if (endLfnstIdx || EndMTS)
  {
    bool       splitCbfLuma  = false;
    const PartSplit ispType  = CU::getISPType(cu, COMP_Y);
    CUCtx cuCtx;
    cuCtx.isDQPCoded         = true;
    cuCtx.isChromaQpAdjCoded = true;
    cs.cost                  = 0.0;
    Distortion       singleDistTmpLuma = 0;
    uint64_t         singleTmpFracBits = 0;
    double           singleCostTmp     = 0;
    const TempCtx    ctxStart          (m_CtxCache, m_CABACEstimator->getCtx());
          TempCtx    ctxBest           (m_CtxCache);
    CodingStructure &saveCS            = *m_pSaveCS[cu.ispMode?0:1];
    TransformUnit *  tmpTU             = nullptr;
    int              bestLfnstIdx      = 0;
    int              startLfnstIdx     = 0;
    // speedUps LFNST
    bool   rapidLFNST                  = false;
    bool   rapidDCT                    = false;
    double thresholdDCT                = 1;

    if (m_pcEncCfg->m_MTS == 2)
    {
      thresholdDCT += 1.4 / sqrt(cu.lwidth() * cu.lheight());
    }

    if (m_pcEncCfg->m_LFNST > 1)
    {
      rapidLFNST = true;

      if (m_pcEncCfg->m_LFNST > 2)
      {
        rapidDCT    = true;
        endLfnstIdx = endLfnstIdx ? 1 : 0;
      }
    }

    saveCS.pcv              = cs.pcv;
    saveCS.picture          = cs.picture;
    saveCS.area.repositionTo( cs.area);

    if (cu.ispMode)
    {
      partitioner.splitCurrArea(ispType, cs);
    }

    TransformUnit& tu = cs.addTU(CS::getArea(cs, partitioner.currArea(), partitioner.chType, partitioner.treeType), partitioner.chType, cs.cus[0]);

    if (cu.ispMode)
    {
      saveCS.clearTUs();
      do
      {
        saveCS.addTU(
          CS::getArea(cs, partitioner.currArea(), partitioner.chType, partitioner.treeType),
          partitioner.chType, cs.cus[0]);
      } while (partitioner.nextPart(cs));

      partitioner.exitCurrSplit();
    }
    else
    {
      tmpTU = saveCS.tus.empty() ? &saveCS.addTU( currArea, partitioner.chType, nullptr ) : saveCS.tus.front();
      tmpTU->initData();
      tmpTU->UnitArea::operator=( currArea );
    }


    std::vector<TrMode> trModes{ TrMode(0, true) };
    if (tsAllowed)
    {
      trModes.push_back(TrMode(1, true));
    }
    double dct2Cost           = MAX_DOUBLE;
    double trGrpStopThreshold = 1.001;
    double trGrpBestCost      = MAX_DOUBLE;
    LardLfnstCandDecision lardCandDecision;
    LardLfnstPaperDecision lardPaperDecision;
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
    LardLfnst2ndDecision lard2ndDecision;
    LardLfnstCovDecision lardCovDecision;
    int lard2ndDct2CostBin = 0;
    double lard2ndLfnstCost[3] = { MAX_DOUBLE, MAX_DOUBLE, MAX_DOUBLE };
    double lardSkip21Stage3Cost[3] = { MAX_DOUBLE, MAX_DOUBLE, MAX_DOUBLE };
    LardSkip21ZeroStats lardSkip21ZeroStats;
    bool lardSkip21Stage3ZdChecked = false;
    bool lardSkip21Stage3ZdWouldSkip = false;
    uint64_t lardSkip21Stage3ZdEvalNs = 0;
    uint64_t lardSkip21Stage3ZdCandidateNs[3] = { 0, 0, 0 };
    bool lardCovRdoValid[3] = { false, false, false };
    Distortion lardCovDist[3] = { 0, 0, 0 };
    uint64_t lardCovFracBits[3] = { 0, 0, 0 };
    double lardCovDistCost[3] = { 0.0, 0.0, 0.0 };
    double lardCovRateCost[3] = { 0.0, 0.0, 0.0 };
    int lardSkip20Mask = 0x7;
    Lard14CallerLocalTiming lard14LocalTiming;
#endif

    if (mtsAllowed)
    {
      if (m_pcEncCfg->m_LFNST)
      {
        uint32_t uiIntraMode = cs.cus[0]->intraDir[partitioner.chType];
        int MTScur           = (uiIntraMode < 34) ? MTS_DST7_DCT8 : MTS_DCT8_DST7;

        trModes.push_back(TrMode(     2, true));
        trModes.push_back(TrMode(MTScur, true));

        MTScur = (uiIntraMode < 34) ? MTS_DCT8_DST7 : MTS_DST7_DCT8;

        trModes.push_back(TrMode(MTScur,            true));
        trModes.push_back(TrMode(MTS_DST7_DST7 + 3, true));
      }
      else
      {
        for (int i = 2; i < 6; i++)
        {
          trModes.push_back(TrMode(i, true));
        }
      }
    }

    if ((EndMTS && !m_pcEncCfg->m_LFNST) || (tsAllowed && !mtsAllowed))
    {
      xPreCheckMTS(tu, &trModes, m_pcEncCfg->m_MTSIntraMaxCand, predBuf);
      if (!mtsAllowed && !trModes[1].second)
      {
        EndMTS = 0;
      }
    }

    bool NStopMTS = true;

    for (int modeId = 0; modeId <= EndMTS && NStopMTS; modeId++)
    {
      if (modeId > 1)
      {
        trGrpBestCost = MAX_DOUBLE;
      }
      int lardSkip21LfnstOrder[3] = { 0, 1, 2 };
      int lardSkip21NumLfnstOrder = 0;
      for( int idx = startLfnstIdx; idx <= endLfnstIdx && lardSkip21NumLfnstOrder < 3; idx++ )
      {
        lardSkip21LfnstOrder[lardSkip21NumLfnstOrder++] = idx;
      }
      if( modeId == 0 && lardSkip21Decision.stage3SeqEnabled && startLfnstIdx == 0 && endLfnstIdx >= 2 )
      {
        lardSkip21LfnstOrder[0] = 0;
        lardSkip21LfnstOrder[1] = lardSkip21Decision.stage3SeqBestIdx;
        lardSkip21LfnstOrder[2] = lardSkip21Decision.stage3SeqOtherIdx;
        lardSkip21NumLfnstOrder = 3;
      }
      for( int lardSkip21OrderPos = 0; lardSkip21OrderPos < lardSkip21NumLfnstOrder; lardSkip21OrderPos++ )
      {
        const int lfnstIdx = lardSkip21LfnstOrder[lardSkip21OrderPos];
        if( lfnstIdx < startLfnstIdx || lfnstIdx > endLfnstIdx )
        {
          continue;
        }
        if (lfnstIdx && modeId)
        {
          continue;
        }
        if( lardCandDecision.valid && lfnstIdx > 0 && !( lardCandDecision.mask & ( 1 << lfnstIdx ) ) )
        {
          continue;
        }
        if( !lardLfnstSkip13 && lardPaperDecision.valid && lfnstIdx > 0 && !( lardPaperDecision.mask & ( 1 << lfnstIdx ) ) )
        {
          continue;
        }
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        if( lardLfnstSkip20 && lfnstIdx > 0 && !( lardSkip20Mask & ( 1 << lfnstIdx ) ) )
        {
          continue;
        }
        if( lardSkip21Decision.stage3Applied && lfnstIdx > 0 && !( lardSkip21Decision.stage3Mask & ( 1 << lfnstIdx ) ) )
        {
          continue;
        }
        if( lardSkip21Decision.stage3SeqShouldSkipOther && lfnstIdx == lardSkip21Decision.stage3SeqOtherIdx
            && m_pcEncCfg && m_pcEncCfg->m_LardLfnst21Stage3Debug != 3 )
        {
          continue;
        }
        const bool lard2ndWouldSkipCandidate = lard2ndDecision.valid && lfnstIdx > 0 && !( lard2ndDecision.mask & ( 1 << lfnstIdx ) );
        if( lard2ndWouldSkipCandidate && !lardLfnst2ndMeasureOnly )
        {
          continue;
        }
#endif
        if (mtsAllowed || tsAllowed)
        {
          if (m_pcEncCfg->m_TS && bestMTS == MTS_SKIP)
          {
            break;
          }
          if (!m_pcEncCfg->m_LFNST && !trModes[modeId].second && mtsAllowed)
          {
            continue;
          }

          tu.mtsIdx[COMP_Y] = trModes[modeId].first;
        }

        if (cu.ispMode && lfnstIdx)
        {
          if (m_ispTestedModes[lfnstIdx].numTotalParts[cu.ispMode - 1] == 0)
          {
            if (lfnstIdx == 2)
            {
              endLfnstIdx = 1;
            }
            continue;
          }
        }


        if (modeId == 0 && lfnstIdx > 0 && saldanhaSkip && saldanhaRun.mode == saldanha::Runtime::ON)
        {
          saldanhaRun.suppress();
          continue;
        }
        cu.lfnstIdx                          = lfnstIdx;
        cuCtx.lfnstLastScanPos               = false;
        cuCtx.violatesLfnstConstrained[CH_L] = false;
        cuCtx.violatesLfnstConstrained[CH_C] = false;

        if ((lfnstIdx != startLfnstIdx) || (modeId))
        {
          m_CABACEstimator->getCtx() = ctxStart;
        }

        singleDistTmpLuma = 0;

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        const bool lard2ndTimeCandidateRdo = lardLfnst2ndCount && !cu.ispMode && modeId == 0 && lfnstIdx > 0;
        const bool lard14TimeLfnstRdo      = lardLfnstSkip14 && lardLfnst2ndCount && !cu.ispMode
                                          && modeId == 0 && lfnstIdx >= 0 && lfnstIdx <= 2;
        const bool lard18TimeCandidateRdo  = lardLfnstSkip18 && m_pcEncCfg->m_LardLfnst18StatFile[0] != '\0'
                                          && !cu.ispMode && modeId == 0 && lfnstIdx > 0;
        const bool lardCovTimeCandidateRdo = lardLfnstCovMode && m_pcEncCfg->m_LardLfnstCovLog[0] != '\0'
                                          && !cu.ispMode && modeId == 0 && lfnstIdx > 0;
        const bool lardStage3ShadowTimeCandidate = m_pcEncCfg && m_pcEncCfg->m_LardLfnst21Stage3Shadow != 0
                                          && m_pcEncCfg->m_LardLfnst21Stage3TimingFile[0] != '\0'
                                          && lardSkip21Decision.stage3WouldPrune && !lardSkip21Decision.stage3Applied
                                          && !cu.ispMode && modeId == 0 && lfnstIdx > 0
                                          && !( lardSkip21Decision.stage3Mask & ( 1 << lfnstIdx ) );
        const bool lardStage3SeqShadowTimeCandidate = m_pcEncCfg
                                          && m_pcEncCfg->m_LardLfnst21Stage3Debug == 3
                                          && m_pcEncCfg->m_LardLfnst21Stage3TimingFile[0] != '\0'
                                          && lardSkip21Decision.stage3SeqEnabled
                                          && !cu.ispMode && modeId == 0
                                          && lfnstIdx == lardSkip21Decision.stage3SeqOtherIdx;
        const bool lardStage3ZdShadowTimeCandidate = m_pcEncCfg
                                          && m_pcEncCfg->m_LardLfnst21Stage3Mode == 3
                                          && m_pcEncCfg->m_LardLfnst21Stage3Debug == 3
                                          && m_pcEncCfg->m_LardLfnst21Stage3TimingFile[0] != '\0'
                                          && lardSkip21Stage3ZdWouldSkip
                                          && !cu.ispMode && modeId == 0 && lfnstIdx > 0;
        const bool lardStage3LbCandidate = m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 21
                                          && m_pcEncCfg->m_LardLfnst21Stage3Lb != 0
                                          && modeId == 0 && lfnstIdx > 0 && !cu.ispMode
                                          && dSingleCost < MAX_DOUBLE * 0.5;
        const bool lardStage3LbTimeCandidate = lardStage3LbCandidate
                                          && m_pcEncCfg->m_LardLfnst21Stage3LbTimingFile[0] != '\0'
                                          && m_pcEncCfg->m_LardLfnst21Stage3LbDebug != 1;
        const int lardStage3LbDebug = lardStage3LbCandidate ? Clip3( 0, 3, m_pcEncCfg->m_LardLfnst21Stage3LbDebug ) : 0;
        const double lardStage3LbBestBefore = dSingleCost;
        const int lardStage3LbBestIdxBefore = bestLfnstIdx;
        bool lardStage3LbWouldTerminate = false;
        bool lardStage3LbTerminatedCandidate = false;
        double lardStage3LbDistLowerBound = MAX_DOUBLE;
        uint64_t lardStage3LbCheckNs = 0;
        auto lardStage3LbDistReadyTime = std::chrono::steady_clock::time_point();
        const auto lard2ndCandidateRdoStart = ( lard2ndTimeCandidateRdo || lard14TimeLfnstRdo
                                             || lard18TimeCandidateRdo || lardCovTimeCandidateRdo
                                             || lardStage3ShadowTimeCandidate || lardStage3SeqShadowTimeCandidate
                                             || lardStage3ZdShadowTimeCandidate
                                             || lardStage3LbTimeCandidate )
                                            ? std::chrono::steady_clock::now()
                                            : std::chrono::steady_clock::time_point();
#endif

        if (cu.ispMode)
        {
          splitCbfLuma = false;

          partitioner.splitCurrArea(ispType, cs);

          singleCostTmp = xTestISP(cs, partitioner, bestCostForISP, ispType, splitCbfLuma, singleTmpFracBits, singleDistTmpLuma, cuCtx);

          partitioner.exitCurrSplit();

          if (modeId && (singleCostTmp == MAX_DOUBLE))
          {
            m_ispTestedModes[lfnstIdx].numTotalParts[cu.ispMode - 1] = 0;
          }

          bool storeCost = (numMode == 1) ? true : false;

          if ((m_pcEncCfg->m_ISP >= 2) && (numMode <= 1))
          {
            storeCost = true;
          }

          if (storeCost)
          {
            m_ispTestedModes[0].bestCost[cu.ispMode - 1] = singleCostTmp;
          }
        }
        else
        {
          bool TrLoad = (EndMTS && !m_pcEncCfg->m_LFNST) || (tsAllowed && !mtsAllowed && (lfnstIdx == 0)) ? true : false;

          xIntraCodingTUBlock(tu, COMP_Y, false, singleDistTmpLuma, &numSig, predBuf, TrLoad);

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
          if( lardStage3LbCandidate && lardStage3LbDebug != 1 )
          {
            lardStage3LbDistReadyTime = std::chrono::steady_clock::now();
            const auto lardStage3LbCheckStart = std::chrono::steady_clock::now();
            const double distLowerBound = m_pcRdCost->calcRdCost( 0, singleDistTmpLuma );
            lardStage3LbDistLowerBound = distLowerBound;
            lardStage3LbWouldTerminate = xLardSkip21Stage3LbWouldTerminate( distLowerBound, lardStage3LbBestBefore );
            const auto lardStage3LbCheckEnd = std::chrono::steady_clock::now();
            lardStage3LbCheckNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lardStage3LbCheckEnd - lardStage3LbCheckStart ).count();
            lardStage3LbTerminatedCandidate = lardStage3LbWouldTerminate && lardStage3LbDebug != 2;
          }
#endif

          if( lahtpTraceEnabled && modeId == 0 && lfnstIdx == 0 )
          {
            xLahtpCheckQuantRoi( cu, tu, lahtpTraceF );
          }
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
          if( lardLfnst2ndVecTrace && modeId == 0 && lfnstIdx == 0 && !cu.ispMode )
          {
            xLardLfnst2ndTraceVector( cu, tu, lard2ndVecF );
          }
          if( lardLfnstCovMode && lardCovDecision.valid && modeId == 0 && lfnstIdx >= 1 && lfnstIdx <= 2
              && m_pcTrQuant->getLastLfnstIdx() == lfnstIdx
              && m_pcTrQuant->getLastLfnstSet() == lardCovDecision.lfnstSet
              && m_pcTrQuant->getLastLfnstTranspose() == lardCovDecision.transpose )
          {
            const int cand = lfnstIdx - 1;
            const int inputSize = std::min( 48, m_pcTrQuant->getLastLfnstInputSize() );
            const int outputSize = std::min( 16, m_pcTrQuant->getLastLfnstOutputSize() );
            const TCoeff* actualInput = m_pcTrQuant->getLastLfnstInput();
            const TCoeff* actualOutput = m_pcTrQuant->getLastLfnstOutput();
            const TCoeff* actualRawRoi = m_pcTrQuant->getLastLfnstRawRoi();
            for( int i = 0; i < inputSize; i++ ) lardCovDecision.actualInput[cand][i] = (int)actualInput[i];
            for( int i = 0; i < inputSize; i++ ) lardCovDecision.actualRawRoi[cand][i] = (int)actualRawRoi[i];
            for( int i = 0; i < outputSize; i++ ) lardCovDecision.actualOutput[cand][i] = (int)actualOutput[i];
            lardCovDecision.actualValid[cand] = inputSize == lardCovDecision.kIn && outputSize == lardCovDecision.outN;
            if( lardCovDecision.actualValid[cand] )
            {
              double inputEnergy = 0.0;
              double outputEnergy = 0.0;
              for( int i = 0; i < inputSize; i++ )
              {
                const double value = (double)actualInput[i];
                inputEnergy += value * value;
              }
              for( int i = 0; i < outputSize; i++ )
              {
                const double value = (double)actualOutput[i];
                outputEnergy += value * value;
              }
              lardCovDecision.inputEnergy[cand] = inputEnergy;
              lardCovDecision.outputEnergy[cand] = outputEnergy;
              lardCovDecision.zeroOutEnergy[cand] = std::max( 0.0, inputEnergy - outputEnergy );
              lardCovDecision.retainedEnergyRatio[cand] = outputEnergy / ( inputEnergy + 1e-12 );
            }
          }
#endif

          cuCtx.mtsLastScanPos = false;
          //----- determine rate and r-d cost -----
        if( lardStage3LbTerminatedCandidate )
        {
          singleTmpFracBits = 0;
          singleCostTmp = MAX_DOUBLE;
        }
        else if ((sps.LFNST ? (modeId == EndMTS && modeId != 0 && checkTransformSkip) : (trModes[modeId].first != 0)) && !TU::getCbfAtDepth(tu, COMP_Y, currDepth))
        {
          singleCostTmp = MAX_DOUBLE;
        }
        else
        {
          m_ispTestedModes[0].IspType      = TU_NO_ISP;
          m_ispTestedModes[0].subTuCounter = -1;
          singleTmpFracBits = xGetIntraFracBitsQT(cs, partitioner, true, &cuCtx);

          if (tu.mtsIdx[COMP_Y] > MTS_SKIP)
          {
            if (!cuCtx.mtsLastScanPos)
            {
              singleCostTmp = MAX_DOUBLE;
            }
            else
            {
              singleCostTmp = m_pcRdCost->calcRdCost(singleTmpFracBits, singleDistTmpLuma);
            }
          }
          else
          {
            singleCostTmp = m_pcRdCost->calcRdCost(singleTmpFracBits, singleDistTmpLuma);
          }
        }

          if (!lardStage3LbTerminatedCandidate && ((EndMTS && (m_pcEncCfg->m_MTS == 2)) || rapidLFNST) && modeId == 0 && lfnstIdx == 0)
          {
            if (singleCostTmp > bestCostSoFar * thresholdDCT)
            {
              EndMTS = 0;

              if (rapidDCT)
              {
                endLfnstIdx = 0;   // break the loop but do not cpy best
              }
            }
          }

          if (!lardStage3LbTerminatedCandidate && lfnstIdx && !cuCtx.lfnstLastScanPos && !cu.ispMode)
          {
            bool rootCbfL = false;

            for (uint32_t t = 0; t < getNumberValidTBlocks(*cu.cs->pcv); t++)
            {
              rootCbfL |= tu.cbf[t] != 0;
            }

            if (rapidLFNST && !rootCbfL)
            {
              endLfnstIdx = lfnstIdx; // break the loop
            }
            bool cbfAtZeroDepth = CU::isSepTree(cu)
              ? rootCbfL
              : (cs.area.chromaFormat != CHROMA_400 && std::min(cu.firstTU->blocks[1].width, cu.firstTU->blocks[1].height) < 4)
                ? TU::getCbfAtDepth(tu, COMP_Y, currDepth)
                : rootCbfL;

            if (cbfAtZeroDepth)
            {
              singleCostTmp = MAX_DOUBLE;
            }
          }
        }

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        if( lard2ndTimeCandidateRdo || lard14TimeLfnstRdo || lard18TimeCandidateRdo || lardCovTimeCandidateRdo
            || lardStage3ShadowTimeCandidate || lardStage3SeqShadowTimeCandidate || lardStage3ZdShadowTimeCandidate || lardStage3LbTimeCandidate )
        {
          const auto lard2ndCandidateRdoEnd = std::chrono::steady_clock::now();
          const uint64_t ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lard2ndCandidateRdoEnd - lard2ndCandidateRdoStart ).count();
          if( lard2ndTimeCandidateRdo )
          {
            xLard2ndCountCandidateRdo( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                       cu.qp, cu.lwidth(), cu.lheight(), lard2ndDct2CostBin, ns, lard2ndWouldSkipCandidate );
          }
          if( lard14TimeLfnstRdo )
          {
            lard14LocalTiming.idxActual[lfnstIdx]++;
            lard14LocalTiming.idxTimeNs[lfnstIdx] += ns;
            xLard14CallerCountCandidateRdo( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                            cu.qp, cu.lwidth(), cu.lheight(), xLahtpModeGroupId( cu.intraDir[CH_L] ),
                                            xLardLfnstLatBucketId( lard2ndF.absLatDeg ), lfnstIdx,
                                            ns, lard2ndWouldSkipCandidate );
          }
          if( lard18TimeCandidateRdo )
          {
            const bool predictedMask0 = lardCovDecision.valid && lardCovDecision.maskPred == 0x1;
            xLard18ComplexityStore().recordCandidateRdo( m_pcEncCfg->m_LardLfnst18StatFile,
                                                          cu.qp, cu.lwidth(), cu.lheight(),
                                                          lfnstIdx, predictedMask0, ns );
          }
          if( lardCovTimeCandidateRdo )
          {
            lardCovDecision.actualRdoTimeNs[lfnstIdx] += ns;
          }
          if( lardStage3ShadowTimeCandidate )
          {
            xLardSkip21Stage3TimingStore().recordPrunedCandidate( m_pcEncCfg->m_LardLfnst21Stage3TimingFile,
                                                                   cu.qp, cu.lwidth(), cu.lheight(),
                                                                   lardSkip21Decision.stage3SelectedIdx, lfnstIdx,
                                                                   lardSkip21Decision.stage3DiffQ,
                                                                   lardSkip21Decision.stage3KeepScoreQ,
                                                                   ns );
          }
          if( lardStage3SeqShadowTimeCandidate )
          {
            xLardSkip21Stage3TimingStore().recordSeqOtherCandidate( m_pcEncCfg->m_LardLfnst21Stage3TimingFile,
                                                                     cu.qp, cu.lwidth(), cu.lheight(),
                                                                     lardSkip21Decision.stage3SeqBestIdx,
                                                                     lardSkip21Decision.stage3SeqOtherIdx,
                                                                     lardSkip21Decision.stage3DiffQ,
                                                                     lardSkip21Decision.stage3KeepScoreQ,
                                                                     lardSkip21Decision.stage3SeqSkipReason,
                                                                     lardSkip21Decision.stage3EvalNs,
                                                                     ns,
                                                                     lardSkip21Stage3Cost[0],
                                                                     lardSkip21Stage3Cost[lardSkip21Decision.stage3SeqBestIdx],
                                                                     singleCostTmp );
          }
          if( lardStage3ZdShadowTimeCandidate )
          {
            lardSkip21Stage3ZdCandidateNs[Clip3( 0, 2, lfnstIdx )] += ns;
          }
          if( lardStage3LbTimeCandidate )
          {
            const uint64_t beforeDistReadyNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lardStage3LbDistReadyTime - lard2ndCandidateRdoStart ).count();
            const uint64_t afterDistReadyNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lard2ndCandidateRdoEnd - lardStage3LbDistReadyTime ).count();
            const bool wrongTerminate = lardStage3LbWouldTerminate && !lardStage3LbTerminatedCandidate && singleCostTmp < lardStage3LbBestBefore;
            const uint64_t wouldTerminateTailNs = ( lardStage3LbWouldTerminate && !lardStage3LbTerminatedCandidate ) ? afterDistReadyNs : 0;
            xLardSkip21Stage3LbTimingStore().record( m_pcEncCfg->m_LardLfnst21Stage3LbTimingFile,
                                                      cu.qp, cu.lwidth(), cu.lheight(), lfnstIdx,
                                                      lardStage3LbBestIdxBefore,
                                                      LardSkip21Stage3LbTimingStore::distMarginBin( lardStage3LbDistLowerBound, lardStage3LbBestBefore ),
                                                      lardStage3LbWouldTerminate,
                                                      wrongTerminate,
                                                      ns, beforeDistReadyNs, afterDistReadyNs,
                                                      wouldTerminateTailNs, lardStage3LbCheckNs );
          }
        }
#endif
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        if( modeId == 0 && lfnstIdx >= 0 && lfnstIdx <= 2 && !cu.ispMode )
        {
          lard2ndLfnstCost[lfnstIdx] = singleCostTmp;
          lardSkip21Stage3Cost[lfnstIdx] = singleCostTmp;
          if( lardSkip21Decision.stage3SeqEnabled && lfnstIdx == lardSkip21Decision.stage3SeqBestIdx )
          {
            const int seqReason = xLardSkip21Stage3SeqShouldSkipOther( lardSkip21Decision, lardSkip21Stage3Cost[0], lardSkip21Stage3Cost[lfnstIdx] );
            lardSkip21Decision.stage3SeqSkipReason = seqReason;
            if( seqReason == 2 || seqReason == 3 )
            {
              lardSkip21Decision.stage3SeqShouldSkipOther = true;
            }
          }
          if( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 21
              && m_pcEncCfg->m_LardLfnst21Stage3Mode == 3
              && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
          {
            lardSkip21ZeroStats.valid = singleCostTmp < MAX_DOUBLE * 0.5;
            lardSkip21ZeroStats.j0 = singleCostTmp;
            lardSkip21ZeroStats.distCost0 = m_pcRdCost->calcRdCost( 0, singleDistTmpLuma );
            lardSkip21ZeroStats.baseCbf = TU::getCbfAtDepth( tu, COMP_Y, currDepth ) ? 1 : 0;
            lardSkip21ZeroStats.baseNnz = (int)xLahtpCountNonZeroCoeffs( tu, COMP_Y );
            lardSkip21ZeroStats.baseLast = std::max( 0, (int)tu.lastPos[COMP_Y] );
            lardSkip21ZeroStats.baseAbsLevelSum = (int)std::floor( xLahtpSumAbsCoeffs( tu, COMP_Y ) + 0.5 );
            lardSkip21ZeroStats.baseCoeffBits = (int)std::min<uint64_t>( singleTmpFracBits, 2147483647u );
            lardSkip21ZeroStats.width = (int)cu.lwidth();
            lardSkip21ZeroStats.height = (int)cu.lheight();
            lardSkip21ZeroStats.qp = cu.qp;

            const auto lardStage3ZdEvalStart = std::chrono::steady_clock::now();
            const bool highCostPass = xLardSkip21Stage3HighCostPass( m_pcEncCfg->m_LardLfnst21Stage3HighCostMode,
                                                                      lardSkip21ZeroStats.width, lardSkip21ZeroStats.height );
            const LardSkip21Stage3ZdProfileParams zdParams = xLardSkip21Stage3ZdProfileParams( m_pcEncCfg->m_LardLfnst21Stage3Profile );
            lardSkip21Stage3ZdWouldSkip = highCostPass && xLardSkip21Stage3ZdWouldSkip( lardSkip21ZeroStats, lardSkip21Decision, zdParams );
            const auto lardStage3ZdEvalEnd = std::chrono::steady_clock::now();
            lardSkip21Stage3ZdEvalNs = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lardStage3ZdEvalEnd - lardStage3ZdEvalStart ).count();
            lardSkip21Stage3ZdChecked = true;
            if( lardSkip21Stage3ZdWouldSkip && m_pcEncCfg->m_LardLfnst21Stage3Debug != 3 )
            {
              endLfnstIdx = 0;
            }
          }
          if( lardLfnstCovMode && singleCostTmp < MAX_DOUBLE * 0.5 )
          {
            lardCovRdoValid[lfnstIdx] = true;
            lardCovDist[lfnstIdx] = singleDistTmpLuma;
            lardCovFracBits[lfnstIdx] = singleTmpFracBits;
            lardCovDistCost[lfnstIdx] = m_pcRdCost->calcRdCost( 0, singleDistTmpLuma );
            lardCovRateCost[lfnstIdx] = m_pcRdCost->calcRdCost( singleTmpFracBits, 0 );
          }
        }
#endif

        if( lahtpLazyTwoStage && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          LahtpFeatures quantF = lahtpLazyF;
          if( xLahtpCheckQuantRoi( cu, tu, quantF ) )
          {
            endLfnstIdx = 0;
          }
        }

        if( lardLfnstCandGain && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          LahtpFeatures quantF = lardCandF;
          if( xLahtpCheckQuantRoi( cu, tu, quantF ) )
          {
            lardCandDecision.valid = true;
            lardCandDecision.mask  = 0x1;
            lardCandDecision.gain1 = -m_pcEncCfg->m_LardLfnstCandTau0;
            lardCandDecision.gain2 = -m_pcEncCfg->m_LardLfnstCandTau0;
          }
          else
          {
            lardCandDecision = xLardLfnstPredictCandidates( cu, tu, quantF );
          }
          if( lardCandDecision.valid && lardCandDecision.mask == 0x1 )
          {
            endLfnstIdx = 0;
          }
        }

        if( m_pcEncCfg && m_pcEncCfg->m_LardLfnstSkip == 12 && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          lardPaperDecision = xLardLfnstPaperGradDecision( cu, tu );
          if( lardPaperDecision.valid && lardPaperDecision.mask == 0x1 )
          {
            endLfnstIdx = 0;
          }
        }

#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        if( lardLfnst2ndResp && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          lard2ndDct2CostBin = xLard2ndCostBin( singleCostTmp );
          const double minDct2Cost = lardLfnstSkip11 ? m_pcEncCfg->m_LardLfnst11MinDct2Cost
                                                      : m_pcEncCfg->m_LardLfnst2ndMinDct2Cost;
          const bool lowCostReject = m_pcEncCfg && minDct2Cost >= 0.0 && singleCostTmp < minDct2Cost;
          if( lowCostReject )
          {
            xLard2ndCountLowCostReject( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr, cu.qp );
          }
          else
          {
            const bool lard14TimeFeature = lardLfnstSkip14 && lardLfnst2ndCount;
            const auto lard14FeatureStart = lard14TimeFeature ? std::chrono::steady_clock::now()
                                                              : std::chrono::steady_clock::time_point();
            lard2ndDecision = xLardLfnst2ndRespDecision( cu, tu, lard2ndF, lard2ndDct2CostBin );
            if( lard14TimeFeature )
            {
              const auto lard14FeatureEnd = std::chrono::steady_clock::now();
              const uint64_t ns = (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>( lard14FeatureEnd - lard14FeatureStart ).count();
              xLard14CallerCountFeature( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                          cu.qp, cu.lwidth(), cu.lheight(), xLahtpModeGroupId( cu.intraDir[CH_L] ),
                                          xLardLfnstLatBucketId( lard2ndF.absLatDeg ), ns );
            }
            if( lard2ndDecision.valid )
            {
              xLard2ndCountCandidateMask( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                          cu.qp, cu.lwidth(), cu.lheight(), lard2ndDecision.mask, startLfnstIdx, endLfnstIdx );
              xLard2ndCountCostDecision( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                                          cu.qp, lard2ndDct2CostBin, lard2ndDecision.mask, startLfnstIdx, endLfnstIdx );
            }
            if( lard2ndDecision.valid && lard2ndDecision.mask == 0x1 && !lardLfnst2ndMeasureOnly )
            {
              endLfnstIdx = 0;
            }
          }
        }
        const bool lard2ndAllowsPaperFallback = !lard2ndDecision.valid
                                             || ( m_pcEncCfg->m_LardLfnstTheoryTable && lard2ndDecision.mask == 0x7 );
        if( lardLfnstSkip13 && m_pcEncCfg->m_LardLfnst13Fusion == 1 && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode && lard2ndAllowsPaperFallback )
        {
          lardPaperDecision = xLardLfnstPaperGradDecision( cu, tu );
          if( lardPaperDecision.valid )
          {
            lard2ndDecision.valid = true;
            lard2ndDecision.mask  = lardPaperDecision.mask;
            lard2ndDecision.rawMask = lardPaperDecision.mask;
            if( lard2ndDecision.mask == 0x1 && !lardLfnst2ndMeasureOnly )
            {
              endLfnstIdx = 0;
            }
          }
        }
#endif
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
        if( lardLfnstSkip20 && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          lardSkip20Mask = m_pcEncCfg->m_Skip20ForceMask0 ? 0x1 : xLardSkip20DirectMask( cu, tu, m_pcTrQuant, m_pcEncCfg->m_LardLfnst20Profile );
          if( lardSkip20Mask == 0x1 )
          {
            endLfnstIdx = 0;
          }
        }
        if( lardLfnstCovMode && modeId == 0 && lfnstIdx == 0 && endLfnstIdx > 0 && !cu.ispMode )
        {
          lardCovDecision = xLardLfnstCovDecision( cu, tu );
          xLard18ComplexityStore().recordDecision(
            m_pcEncCfg ? m_pcEncCfg->m_LardLfnst18StatFile : nullptr,
            cu.qp, cu.lwidth(), cu.lheight(),
            lardCovDecision.eligible, lardCovDecision.tableFound,
            lardCovDecision.metadataGateReject, lardCovDecision.metadataGatePass,
            lardCovDecision.cheapGateReject, lardCovDecision.cheapGatePass,
            lardCovDecision.responsePredictorEntered,
            lardCovDecision.qpEarlyBypass, lardCovDecision.sizeEarlyBypass,
            lardCovDecision.roiEnergyGate, lardCovDecision.optimizedResponse,
            lardCovDecision.timeMetaGateNs, lardCovDecision.timeCheapGateNs,
            lardCovDecision.timeResponseFeatureNs, lardCovDecision.timePredictScoreNs );
          if( lardLfnstSkip18 && m_pcEncCfg && m_pcEncCfg->m_LardLfnst18RealSkip == 1
              && lardCovDecision.valid && lardCovDecision.maskPred == 0x1 )
          {
            xLard18ComplexityStore().recordPrune( m_pcEncCfg->m_LardLfnst18StatFile,
                                                  cu.qp, cu.lwidth(), cu.lheight() );
            endLfnstIdx = 0;
          }
          else if( lardLfnstSkip18 && m_pcEncCfg && m_pcEncCfg->m_LardLfnst18RealSkip == 2
                   && lardCovDecision.valid && lardCovDecision.maskPred == 0x1 )
          {
            xLard18ComplexityStore().recordShadowPrediction( m_pcEncCfg->m_LardLfnst18StatFile,
                                                             cu.qp, cu.lwidth(), cu.lheight() );
          }
        }
#endif

        if( lahtpTraceEnabled )
        {
          const uint32_t nonZero = xLahtpCountNonZeroCoeffs( tu, COMP_Y );
          const double   absSum  = xLahtpSumAbsCoeffs( tu, COMP_Y );
          xLahtpAppendTrace( cu, lahtpTraceF, cu.intraDir[CH_L], lfnstIdx, tu.mtsIdx[COMP_Y],
                             singleCostTmp, singleTmpFracBits, singleDistTmpLuma, numSig, nonZero, tu.lastPos[COMP_Y], absSum,
                             lfnstPrunedByCaller );
        }

        if (singleCostTmp < dSingleCost)
        {
          trGrpBestCost  = singleCostTmp;
          dSingleCost    = singleCostTmp;
          singleDistLuma = singleDistTmpLuma;
          singleFracBits = singleTmpFracBits;
          bestLfnstIdx   = lfnstIdx;
          bestMTS        = modeId;

          if (dSingleCost < bestCostForISP)
          {
            bestCostForISP = dSingleCost;
          }

          splitCbfLumaSum = splitCbfLuma;

          if (lfnstIdx == 0 && modeId == 0 && cu.ispMode == 0)
          {
            dct2Cost = singleCostTmp;

            if (!TU::getCbfAtDepth(tu, COMP_Y, currDepth))
            {
              if (rapidLFNST)
              {
                 endLfnstIdx = 0;   // break the loop but do not cpy best
              }

              EndMTS = 0;
            }
          }

          if (bestLfnstIdx != endLfnstIdx || bestMTS != EndMTS)
          {
            if (cu.ispMode)
            {
              saveCS.getRecoBuf(currArea.Y()).copyFrom(cs.getRecoBuf(currArea.Y()));

              for (uint32_t j = 0; j < cs.tus.size(); j++)
              {
                saveCS.tus[j]->copyComponentFrom(*cs.tus[j], COMP_Y);
              }
            }
            else
            {
              saveCS.getPredBuf(tu.Y()).copyFrom(cs.getPredBuf(tu.Y()));
              saveCS.getRecoBuf(tu.Y()).copyFrom(cs.getRecoBuf(tu.Y()));

              tmpTU->copyComponentFrom(tu, COMP_Y);
            }

            ctxBest = m_CABACEstimator->getCtx();
          }
      
        }
        else
        {
          if( rapidLFNST )
          {
            endLfnstIdx = lfnstIdx; // break the loop
          }
        }
        // VVenC adaptation: completed baseline for this intra candidate.
        // Native TS/MTS ordering and native eligibility remain unchanged.
        if (saldanhaRun.mode != saldanha::Runtime::OFF && modeId == 0 && lfnstIdx == 0
            && endLfnstIdx > 0 && singleCostTmp < MAX_DOUBLE * 0.5 && std::isfinite(singleCostTmp))
        {
          double nz = 0, absSum = 0;
          for (const TransformUnit* st : cs.tus)
          {
            if (!st->blocks[COMP_Y].valid()) continue;
            const auto cb = st->getCoeffs(COMP_Y);
            for (unsigned sy=0; sy<cb.height; ++sy)
              for (unsigned sx=0; sx<cb.width; ++sx)
              {
                const double c = double(cb.at(sx,sy));
                nz += c != 0; absSum += std::abs(c);
              }
          }
          saldanhaF = {{ double(cu.lwidth()), double(cu.lheight()), double(cu.lwidth()*cu.lheight()),
            double(cu.lwidth()) / cu.lheight(), double(cu.mtDepth), double(cu.mipFlag), double(cu.ispMode),
            singleCostTmp, double(singleDistTmpLuma), double(singleTmpFracBits),
            double(cu.intraDir[CH_L]), nz, absSum }};
          saldanhaSkip = saldanhaRun.decide(saldanhaF);
          saldanhaCaptured = true;
        }

      }
      if (m_pcEncCfg->m_LFNST && m_pcEncCfg->m_MTS == 2 && modeId && modeId != EndMTS)
      {
        NStopMTS = false;

        if (bestMTS || bestLfnstIdx)
        {
          if ((modeId > 1 && bestMTS == modeId) || modeId == 1)
          {
            NStopMTS = (dct2Cost / trGrpBestCost) < trGrpStopThreshold;
          }
        }
      }
    }

    if (saldanhaCaptured)
      saldanhaRun.finish(saldanhaF, saldanhaSkip, bestLfnstIdx > 0 ? 1 : 0,
                         cs.picture->poc, cu.qp, cu.lx(), cu.ly());
    cu.lfnstIdx = bestLfnstIdx;
#if VVENC_LARD_LFNST_2ND_RESP_ENABLE
    if( lardSkip21Stage3ZdChecked && m_pcEncCfg && m_pcEncCfg->m_LardLfnst21Stage3Mode == 3
        && m_pcEncCfg->m_LardLfnst21Stage3Debug == 3
        && m_pcEncCfg->m_LardLfnst21Stage3TimingFile[0] != '\0' )
    {
      const double bestNonzero = std::min( lardSkip21Stage3Cost[1], lardSkip21Stage3Cost[2] );
      const bool wrongSkip = lardSkip21Stage3ZdWouldSkip
                           && lardSkip21ZeroStats.j0 < MAX_DOUBLE * 0.5
                           && bestNonzero < lardSkip21ZeroStats.j0;
      xLardSkip21Stage3TimingStore().recordZdDecision( m_pcEncCfg->m_LardLfnst21Stage3TimingFile,
                                                        cu.qp, cu.lwidth(), cu.lheight(),
                                                        lardSkip21Stage3ZdWouldSkip, wrongSkip,
                                                        lardSkip21Stage3ZdCandidateNs[1],
                                                        lardSkip21Stage3ZdCandidateNs[2],
                                                        lardSkip21Stage3ZdEvalNs );
    }
    if( lardLfnstSkip14 && lardLfnst2ndCount
        && ( lard14LocalTiming.idxActual[0] || lard14LocalTiming.idxActual[1] || lard14LocalTiming.idxActual[2] ) )
    {
      xLard14CallerCountFinal( m_pcEncCfg ? m_pcEncCfg->m_LardLfnst2ndCountFile : nullptr,
                               cu.qp, bestLfnstIdx, lard14LocalTiming );
    }
    if( lardLfnst2ndBase && lard2ndDecision.valid )
    {
      if( lard14ShadowEarlyValid )
      {
        lard2ndDecision.earlyValid = true;
        lard2ndDecision.earlyGeom = lard14ShadowEarlyGeom;
        lard2ndDecision.earlyRoiFull = lard14ShadowEarlyRoiFull;
        lard2ndDecision.earlyRoiProxy = lard14ShadowEarlyProxy.skip;
        lard2ndDecision.earlySkip = lard14ShadowEarlyGeom || lard14ShadowEarlyRoiFull || lard14ShadowEarlyProxy.skip;
        lard2ndDecision.earlyMh = lard14ShadowEarlyMh;
        lard2ndDecision.earlyRoiEnergyQ = lard14ShadowEarlyProxy.roiEnergyQ;
        lard2ndDecision.earlyPredNz = lard14ShadowEarlyProxy.predNz;
        lard2ndDecision.earlyLfRatio = lard14ShadowEarlyProxy.lfRatio;
        lard2ndDecision.earlyCorrProxy = lard14ShadowEarlyProxy.corrProxy;
        lard2ndDecision.earlyMeanAbsQ = lard14ShadowEarlyProxy.meanAbsQ;
      }
      xLardLfnst2ndAppendFinalStats( cu, lard2ndDecision, bestLfnstIdx,
                                     lard2ndLfnstCost[0], lard2ndLfnstCost[1], lard2ndLfnstCost[2],
                                     lard2ndDct2CostBin );
    }
    if( lardLfnstCovMode && lardCovDecision.eligible )
    {
      for( int idx = 0; idx < 3; idx++ )
      {
        lardCovDecision.rdoValid[idx] = lardCovRdoValid[idx];
        lardCovDecision.actualDist[idx] = (uint64_t)lardCovDist[idx];
        lardCovDecision.actualFracBits[idx] = lardCovFracBits[idx];
        lardCovDecision.actualDistCost[idx] = lardCovDistCost[idx];
        lardCovDecision.actualRateCost[idx] = lardCovRateCost[idx];
      }
      xLardLfnstCovAppendLog( cu, lardCovDecision, bestLfnstIdx,
                              lard2ndLfnstCost[0], lard2ndLfnstCost[1], lard2ndLfnstCost[2] );
      xLardLfnstCovAppendTrace( cu, lardCovDecision );
    }
#endif
    if (dSingleCost != MAX_DOUBLE)
    {
      if (bestLfnstIdx != endLfnstIdx || bestMTS != EndMTS)
      {
        if (cu.ispMode)
        {
          const UnitArea& currArea = partitioner.currArea();
          cs.getRecoBuf(currArea.Y()).copyFrom(saveCS.getRecoBuf(currArea.Y()));

          if (saveCS.tus.size() != cs.tus.size())
          {
            partitioner.splitCurrArea(ispType, cs);

            do
            {
              partitioner.nextPart(cs);
              cs.addTU(CS::getArea(cs, partitioner.currArea(), partitioner.chType, partitioner.treeType),
                partitioner.chType, cs.cus[0]);
            } while (saveCS.tus.size() != cs.tus.size());

            partitioner.exitCurrSplit();
          }

          for (uint32_t j = 0; j < saveCS.tus.size(); j++)
          {
            cs.tus[j]->copyComponentFrom(*saveCS.tus[j], COMP_Y);
          }
        }
        else
        {
          cs.getRecoBuf(tu.Y()).copyFrom(saveCS.getRecoBuf(tu.Y()));

          tu.copyComponentFrom(*tmpTU, COMP_Y);
        }

        m_CABACEstimator->getCtx() = ctxBest;
      }

      // otherwise this would've happened in useSubStructure
      cs.picture->getRecoBuf(currArea.Y()).copyFrom(cs.getRecoBuf(currArea.Y()));
    }
  }
  else
  {
    if (cu.ispMode)
    {
      const PartSplit ispType = CU::getISPType(cu, COMP_Y);
      partitioner.splitCurrArea(ispType, cs);

      CUCtx      cuCtx;
      dSingleCost = xTestISP(cs, partitioner, bestCostForISP, ispType, splitCbfLumaSum, singleFracBits, singleDistLuma, cuCtx);
      partitioner.exitCurrSplit();
      bool storeCost = (numMode == 1) ? true : false;
      if ((m_pcEncCfg->m_ISP >= 2) && (numMode <= 1))
      {
        storeCost = true;
      }
      if (storeCost)
      {
        m_ispTestedModes[0].bestCost[cu.ispMode - 1] = dSingleCost;
      }
    }
    else
    {
      TransformUnit& tu =
        cs.addTU(CS::getArea(cs, currArea, partitioner.chType, partitioner.treeType), partitioner.chType, cs.cus[0]);
      tu.depth = currDepth;

      CHECK(!tu.Y().valid(), "Invalid TU");
      xIntraCodingTUBlock(tu, COMP_Y, false, singleDistLuma, &numSig, predBuf);
      //----- determine rate and r-d cost -----
      m_ispTestedModes[0].IspType = TU_NO_ISP;
      m_ispTestedModes[0].subTuCounter = -1;
      singleFracBits = xGetIntraFracBitsQT(cs, partitioner, true);
      dSingleCost = m_pcRdCost->calcRdCost(singleFracBits, singleDistLuma);
    }
  }

  if (cu.ispMode)
  { 
    for (auto& ptu : cs.tus)
    {
      if (currArea.Y().contains(ptu->Y()))
      {
        TU::setCbfAtDepth(*ptu, COMP_Y, currDepth, splitCbfLumaSum ? 1 : 0);
      }
    }
  }
  cs.dist     += singleDistLuma;
  cs.fracBits += singleFracBits;
  cs.cost      = dSingleCost;

  STAT_COUNT_CU_MODES( partitioner.chType == CH_L, g_cuCounters1D[CU_RD_TESTS][0][!cs.slice->isIntra() + cs.slice->depth] );
  STAT_COUNT_CU_MODES( partitioner.chType == CH_L && !cs.slice->isIntra(), g_cuCounters2D[CU_RD_TESTS][Log2( cs.area.lheight() )][Log2( cs.area.lwidth() )] );
}

ChromaCbfs IntraSearch::xIntraChromaCodingQT(CodingStructure& cs, Partitioner& partitioner)
{
  UnitArea    currArea      = partitioner.currArea();

  if( !currArea.Cb().valid() ) 
    return ChromaCbfs(false);

  TransformUnit& currTU     = *cs.getTU( currArea.chromaPos(), CH_C );
  const CodingUnit& cu  = *cs.getCU( currArea.chromaPos(), CH_C, TREE_D );
  ChromaCbfs cbfs(false);
  uint32_t   currDepth = partitioner.currTrDepth;
  const bool useTS = cs.picture->useTS;
  if (currDepth == currTU.depth)
  {
    if (!currArea.Cb().valid() || !currArea.Cr().valid())
    {
      return cbfs;
    }

    CodingStructure& saveCS = *m_pSaveCS[1];
    saveCS.pcv = cs.pcv;
    saveCS.picture = cs.picture;
    saveCS.area.repositionTo(cs.area);

    TransformUnit& tmpTU = saveCS.tus.empty() ? saveCS.addTU(currArea, partitioner.chType, nullptr) : *saveCS.tus.front();
    tmpTU.initData();
    tmpTU.UnitArea::operator=(currArea);
    const unsigned      numTBlocks = getNumberValidTBlocks(*cs.pcv);

    CompArea& cbArea = currTU.blocks[COMP_Cb];
    CompArea& crArea = currTU.blocks[COMP_Cr];
    double     bestCostCb = MAX_DOUBLE;
    double     bestCostCr = MAX_DOUBLE;
    Distortion bestDistCb = 0;
    Distortion bestDistCr = 0;

    TempCtx ctxStartTU(m_CtxCache);
    TempCtx ctxStart(m_CtxCache);
    TempCtx ctxBest(m_CtxCache);

    ctxStartTU = m_CABACEstimator->getCtx();
    ctxStart = m_CABACEstimator->getCtx();
    currTU.jointCbCr = 0;

    // Do predictions here to avoid repeating the "default0Save1Load2" stuff
    int  predMode = cu.bdpcmM[CH_C] ? BDPCM_IDX : CU::getFinalIntraMode(cu, CH_C);

    PelBuf piPredCb = cs.getPredBuf(COMP_Cb);
    PelBuf piPredCr = cs.getPredBuf(COMP_Cr);

    initIntraPatternChType(*currTU.cu, cbArea);
    initIntraPatternChType(*currTU.cu, crArea);

    if (CU::isLMCMode(predMode))
    {
      loadLMLumaRecPels(cu, cbArea);
      predIntraChromaLM(COMP_Cb, piPredCb, cu, cbArea, predMode);
      predIntraChromaLM(COMP_Cr, piPredCr, cu, crArea, predMode);
    }
    else
    {
      predIntraAng(COMP_Cb, piPredCb, cu);
      predIntraAng(COMP_Cr, piPredCr, cu);
    }

    // determination of chroma residuals including reshaping and cross-component prediction
    //----- get chroma residuals -----
    PelBuf resiCb = cs.getResiBuf(COMP_Cb);
    PelBuf resiCr = cs.getResiBuf(COMP_Cr);
    resiCb.subtract(cs.getOrgBuf(COMP_Cb), piPredCb);
    resiCr.subtract(cs.getOrgBuf(COMP_Cr), piPredCr);

    //----- get reshape parameter ----
    ReshapeData& reshapeData = cs.picture->reshapeData;
    bool doReshaping = (cs.picHeader->lmcsEnabled && cs.picHeader->lmcsChromaResidualScale && (cs.slice->isIntra() || reshapeData.getCTUFlag()) && (cbArea.width * cbArea.height > 4));
    if (doReshaping)
    {
      const Area area = currTU.Y().valid() ? currTU.Y() : Area(recalcPosition(currTU.chromaFormat, currTU.chType, CH_L, currTU.blocks[currTU.chType].pos()), recalcSize(currTU.chromaFormat, currTU.chType, CH_L, currTU.blocks[currTU.chType].size()));
      const CompArea& areaY = CompArea(COMP_Y, currTU.chromaFormat, area);
      currTU.chromaAdj = reshapeData.calculateChromaAdjVpduNei(currTU, areaY, currTU.cu->treeType);
    }

    //===== store original residual signals (std and crossCompPred) =====
    for( int k = 0; k < 5; k++ )
    {
      m_orgResiCb[k].compactResize( cbArea );
      m_orgResiCr[k].compactResize( crArea );
    }
    for (int k = 0; k < 1; k += 4)
    {
      m_orgResiCb[k].copyFrom(resiCb);
      m_orgResiCr[k].copyFrom(resiCr);

      if (doReshaping)
      {
        int cResScaleInv = currTU.chromaAdj;
        m_orgResiCb[k].scaleSignal(cResScaleInv, 1, cs.slice->clpRngs[COMP_Cb]);
        m_orgResiCr[k].scaleSignal(cResScaleInv, 1, cs.slice->clpRngs[COMP_Cr]);
      }
    }

    CUCtx cuCtx;
    cuCtx.isDQPCoded = true;
    cuCtx.isChromaQpAdjCoded = true;
    cuCtx.lfnstLastScanPos = false;

    CodingStructure& saveCScur = *m_pSaveCS[2];

    saveCScur.pcv = cs.pcv;
    saveCScur.picture = cs.picture;
    saveCScur.area.repositionTo(cs.area);

    TransformUnit& tmpTUcur = saveCScur.tus.empty() ? saveCScur.addTU(currArea, partitioner.chType, nullptr) : *saveCScur.tus.front();
    tmpTUcur.initData();
    tmpTUcur.UnitArea::operator=(currArea);

    TempCtx ctxBestTUL(m_CtxCache);

    const SPS& sps = *cs.sps;
    double     bestCostCbcur = MAX_DOUBLE;
    double     bestCostCrcur = MAX_DOUBLE;
    Distortion bestDistCbcur = 0;
    Distortion bestDistCrcur = 0;

    int  endLfnstIdx = (partitioner.isSepTree(cs) && partitioner.chType == CH_C && (partitioner.currArea().lwidth() < 8 || partitioner.currArea().lheight() < 8))
      || (partitioner.currArea().lwidth() > sps.getMaxTbSize() || partitioner.currArea().lheight() > sps.getMaxTbSize()) || !sps.LFNST ? 0 : 2;
    int  startLfnstIdx = 0;
    int  bestLfnstIdx = 0;
    bool testLFNST = sps.LFNST;

    // speedUps LFNST
    bool rapidLFNST = false;
    if (m_pcEncCfg->m_LFNST > 1)
    {
      rapidLFNST = true;
      if (m_pcEncCfg->m_LFNST > 2)
      {
        endLfnstIdx = endLfnstIdx ? 1 : 0;
      }
    }
    if( m_pcEncCfg && m_pcEncCfg->m_EarlyForceNoNonzeroLfnst )
    {
      endLfnstIdx = 0;
      testLFNST = false;
      rapidLFNST = false;
    }
    int ts_used = 0;
    bool testTS = false;
    if (partitioner.chType != CH_C)
    {
      startLfnstIdx = currTU.cu->lfnstIdx;
      endLfnstIdx = currTU.cu->lfnstIdx;
      bestLfnstIdx = currTU.cu->lfnstIdx;
      testLFNST  = false;
      rapidLFNST = false;
      ts_used = currTU.mtsIdx[COMP_Y];
    }
    if (cu.bdpcmM[CH_C])
    {
      endLfnstIdx = 0;
      testLFNST = false;
    }

    double dSingleCostAll = MAX_DOUBLE;
    double singleCostTmpAll = 0;

    for (int lfnstIdx = startLfnstIdx; lfnstIdx <= endLfnstIdx; lfnstIdx++)
    {
      if (rapidLFNST && lfnstIdx)
      {
        if ((lfnstIdx == 2) && (bestLfnstIdx == 0))
        {
          continue;
        }
      }

      currTU.cu->lfnstIdx = lfnstIdx;
      if (lfnstIdx)
      {
        m_CABACEstimator->getCtx() = ctxStartTU;
      }

      cuCtx.lfnstLastScanPos = false;
      cuCtx.violatesLfnstConstrained[CH_L] = false;
      cuCtx.violatesLfnstConstrained[CH_C] = false;

      for (uint32_t c = COMP_Cb; c < numTBlocks; c++)
      {
        const ComponentID compID = ComponentID(c);
        const CompArea& area = currTU.blocks[compID];
        double     dSingleCost = MAX_DOUBLE;
        Distortion singleDistCTmp = 0;
        double     singleCostTmp = 0;
        bool tsAllowed = useTS && TU::isTSAllowed(currTU, compID) && m_pcEncCfg->m_useChromaTS && !currTU.cu->lfnstIdx && !cu.bdpcmM[CH_C];
        if ((partitioner.chType == CH_L) && (!ts_used))
        {
          tsAllowed = false;
        }
        uint8_t nNumTransformCands = 1 + (tsAllowed ? 1 : 0); // DCT + TS = 2 tests       
        std::vector<TrMode> trModes;
        if (nNumTransformCands > 1)
        {
          trModes.push_back(TrMode(0, true));   // DCT2
          trModes.push_back(TrMode(1, true));   // TS
          testTS = true;
        }
        bool cbfDCT2 = true;
        const bool isLastMode = testLFNST || cs.sps->jointCbCr ||  tsAllowed ? false : true;
        int bestModeId = 0;
        ctxStart = m_CABACEstimator->getCtx();
        for (int modeId = 0; modeId < nNumTransformCands; modeId++)
        {
          if (doReshaping || lfnstIdx || modeId)
          {
            resiCb.copyFrom(m_orgResiCb[0]);
            resiCr.copyFrom(m_orgResiCr[0]);
          }
          if (modeId == 0)
          {
            if ( tsAllowed)
            {
              xPreCheckMTS(currTU, &trModes, m_pcEncCfg->m_MTSIntraMaxCand, 0, compID);
            }
          }

          currTU.mtsIdx[compID] = currTU.cu->bdpcmM[CH_C] ? MTS_SKIP : modeId;

          if (modeId)
          {
            if (!cbfDCT2 && trModes[modeId].first == MTS_SKIP)
            {
              break;
            }
            m_CABACEstimator->getCtx() = ctxStart;
          }
          singleDistCTmp = 0;
          if (tsAllowed)
          {
            xIntraCodingTUBlock(currTU, compID, false, singleDistCTmp, 0, 0, true);
            if ((modeId == 0) && (!trModes[modeId + 1].second))
            {
              nNumTransformCands = 1;
            }
          }
          else
        {
          xIntraCodingTUBlock(currTU, compID, false, singleDistCTmp);
        }
        if (((currTU.mtsIdx[compID] == MTS_SKIP && !currTU.cu->bdpcmM[CH_C])
          && !TU::getCbf(currTU, compID)))   // In order not to code TS flag when cbf is zero, the case for TS with
                                             // cbf being zero is forbidden.
        {
          singleCostTmp = MAX_DOUBLE;
        }
        else
        {
          uint64_t fracBitsTmp = xGetIntraFracBitsQTChroma(currTU, compID, &cuCtx);
          singleCostTmp = m_pcRdCost->calcRdCost(fracBitsTmp, singleDistCTmp);
        }

        if (singleCostTmp < dSingleCost)
        {
          dSingleCost = singleCostTmp;

          if (compID == COMP_Cb)
          {
            bestCostCb = singleCostTmp;
            bestDistCb = singleDistCTmp;
          }
          else
          {
            bestCostCr = singleCostTmp;
            bestDistCr = singleDistCTmp;
          }
          bestModeId = modeId;
          if (currTU.mtsIdx[compID] == MTS_DCT2_DCT2)
          {
            cbfDCT2 = TU::getCbfAtDepth(currTU, compID, currDepth);
          }
          if (!isLastMode)
          {
            saveCS.getRecoBuf(area).copyFrom(cs.getRecoBuf(area));
            tmpTU.copyComponentFrom(currTU, compID);
            ctxBest = m_CABACEstimator->getCtx();
          }
        }
        }
        if (testTS && ((c == COMP_Cb && bestModeId < (nNumTransformCands - 1)) ))
        {
          m_CABACEstimator->getCtx() = ctxBest;

          currTU.copyComponentFrom(tmpTU, COMP_Cb); // Cbf of Cb is needed to estimate cost for Cr Cbf
        }
      }

      singleCostTmpAll = bestCostCb + bestCostCr;

      bool rootCbfL = false;
      if (testLFNST)
      {
        for (uint32_t t = 0; t < getNumberValidTBlocks(*cs.pcv); t++)
        {
          rootCbfL |= bool(tmpTU.cbf[t]);
        }
        if (rapidLFNST && !rootCbfL)
        {
          endLfnstIdx = lfnstIdx; // end this
        }
      }

      if (testLFNST && lfnstIdx && !cuCtx.lfnstLastScanPos)
      {
        bool cbfAtZeroDepth = CU::isSepTree(*currTU.cu)
          ? rootCbfL : (cs.area.chromaFormat != CHROMA_400
            && std::min(tmpTU.blocks[1].width, tmpTU.blocks[1].height) < 4)
          ? TU::getCbfAtDepth(currTU, COMP_Y, currTU.depth) : rootCbfL;
        if (cbfAtZeroDepth)
        {
          singleCostTmpAll = MAX_DOUBLE;
        }
      }
      if ((testLFNST || testTS) && (singleCostTmpAll < dSingleCostAll))
      {
        bestLfnstIdx = lfnstIdx;
        if ((lfnstIdx != endLfnstIdx) || testTS)
        {
          dSingleCostAll = singleCostTmpAll;

          bestCostCbcur = bestCostCb;
          bestCostCrcur = bestCostCr;
          bestDistCbcur = bestDistCb;
          bestDistCrcur = bestDistCr;

          saveCScur.getRecoBuf(cbArea).copyFrom(saveCS.getRecoBuf(cbArea));
          saveCScur.getRecoBuf(crArea).copyFrom(saveCS.getRecoBuf(crArea));

          tmpTUcur.copyComponentFrom(tmpTU, COMP_Cb);
          tmpTUcur.copyComponentFrom(tmpTU, COMP_Cr);
        }
        ctxBestTUL = m_CABACEstimator->getCtx();
      }
    }
    if ((testLFNST && (bestLfnstIdx != endLfnstIdx)) || testTS)
    {
      bestCostCb = bestCostCbcur;
      bestCostCr = bestCostCrcur;
      bestDistCb = bestDistCbcur;
      bestDistCr = bestDistCrcur;
      currTU.cu->lfnstIdx = bestLfnstIdx;
      if (!cs.sps->jointCbCr)
      {
        cs.getRecoBuf(cbArea).copyFrom(saveCScur.getRecoBuf(cbArea));
        cs.getRecoBuf(crArea).copyFrom(saveCScur.getRecoBuf(crArea));

        currTU.copyComponentFrom(tmpTUcur, COMP_Cb);
        currTU.copyComponentFrom(tmpTUcur, COMP_Cr);

        m_CABACEstimator->getCtx() = ctxBestTUL;
      }
    }

    Distortion bestDistCbCr = bestDistCb + bestDistCr;

    if (cs.sps->jointCbCr)
    {
      if ((testLFNST && (bestLfnstIdx != endLfnstIdx)) || testTS)
      {
        saveCS.getRecoBuf(cbArea).copyFrom(saveCScur.getRecoBuf(cbArea));
        saveCS.getRecoBuf(crArea).copyFrom(saveCScur.getRecoBuf(crArea));

        tmpTU.copyComponentFrom(tmpTUcur, COMP_Cb);
        tmpTU.copyComponentFrom(tmpTUcur, COMP_Cr);
        m_CABACEstimator->getCtx() = ctxBestTUL;
        ctxBest = m_CABACEstimator->getCtx();
      }
      // Test using joint chroma residual coding
      double     bestCostCbCr = bestCostCb + bestCostCr;
      int        bestJointCbCr = 0;
      bool checkDCTOnly = m_pcEncCfg->m_useChromaTS && ((TU::getCbf(tmpTU, COMP_Cb) && tmpTU.mtsIdx[COMP_Cb] == MTS_DCT2_DCT2 && !TU::getCbf(tmpTU, COMP_Cr)) ||
        (TU::getCbf(tmpTU, COMP_Cr) && tmpTU.mtsIdx[COMP_Cr] == MTS_DCT2_DCT2 && !TU::getCbf(tmpTU, COMP_Cb)) ||
        (TU::getCbf(tmpTU, COMP_Cb) && tmpTU.mtsIdx[COMP_Cb] == MTS_DCT2_DCT2 && TU::getCbf(tmpTU, COMP_Cr) && tmpTU.mtsIdx[COMP_Cr] == MTS_DCT2_DCT2));
      bool checkTSOnly = m_pcEncCfg->m_useChromaTS && ((TU::getCbf(tmpTU, COMP_Cb) && tmpTU.mtsIdx[COMP_Cb] == MTS_SKIP && !TU::getCbf(tmpTU, COMP_Cr)) ||
        (TU::getCbf(tmpTU, COMP_Cr) && tmpTU.mtsIdx[COMP_Cr] == MTS_SKIP && !TU::getCbf(tmpTU, COMP_Cb)) ||
        (TU::getCbf(tmpTU, COMP_Cb) && tmpTU.mtsIdx[COMP_Cb] == MTS_SKIP && TU::getCbf(tmpTU, COMP_Cr) && tmpTU.mtsIdx[COMP_Cr] == MTS_SKIP));
      bool       lastIsBest = false;
      bool noLFNST1 = false;
      if (rapidLFNST && (startLfnstIdx != endLfnstIdx))
      {
        if (bestLfnstIdx == 2)
        {
          noLFNST1 = true;
        }
        else
        {
          endLfnstIdx = 1;
        }
      }

      for (int lfnstIdxj = startLfnstIdx; lfnstIdxj <= endLfnstIdx; lfnstIdxj++)
      {
        if (rapidLFNST && noLFNST1 && (lfnstIdxj == 1))
        {
          continue;
        }
        currTU.cu->lfnstIdx = lfnstIdxj;
        std::vector<int> jointCbfMasksToTest;
        if (TU::getCbf(tmpTU, COMP_Cb) || TU::getCbf(tmpTU, COMP_Cr))
        {
          jointCbfMasksToTest = m_pcTrQuant->selectICTCandidates(currTU, m_orgResiCb, m_orgResiCr);
        }
        for (int cbfMask : jointCbfMasksToTest)
        {
          currTU.jointCbCr = (uint8_t)cbfMask;
          ComponentID codeCompId = ((currTU.jointCbCr >> 1) ? COMP_Cb : COMP_Cr);
          ComponentID otherCompId = ((codeCompId == COMP_Cb) ? COMP_Cr : COMP_Cb);
          bool tsAllowed = useTS && TU::isTSAllowed(currTU, codeCompId) && (m_pcEncCfg->m_useChromaTS) && !currTU.cu->lfnstIdx && !cu.bdpcmM[CH_C];
          if ((partitioner.chType == CH_L)&& tsAllowed && (currTU.mtsIdx[COMP_Y] != MTS_SKIP))
          {
            tsAllowed = false;
          }
          if (!tsAllowed)
          {
            checkTSOnly = false;
          }
          uint8_t     numTransformCands = 1 + (tsAllowed && !(checkDCTOnly || checkTSOnly)? 1 : 0); // DCT + TS = 2 tests
          std::vector<TrMode> trModes;
          if (numTransformCands > 1)
          {
            trModes.push_back(TrMode(0, true)); // DCT2
            trModes.push_back(TrMode(1, true));//TS
          }
          else
          {
            currTU.mtsIdx[codeCompId] = checkTSOnly || currTU.cu->bdpcmM[CH_C] ? 1 : 0;
          }

          for (int modeId = 0; modeId < numTransformCands; modeId++)
          {
            Distortion distTmp = 0;
            currTU.mtsIdx[codeCompId] = currTU.cu->bdpcmM[CH_C] ? MTS_SKIP : MTS_DCT2_DCT2;
            if (numTransformCands > 1)
            {
              currTU.mtsIdx[codeCompId] = currTU.cu->bdpcmM[CH_C] ? MTS_SKIP : trModes[modeId].first;
            }
            currTU.mtsIdx[otherCompId] = MTS_DCT2_DCT2;

            m_CABACEstimator->getCtx() = ctxStartTU;

            resiCb.copyFrom(m_orgResiCb[cbfMask]);
            resiCr.copyFrom(m_orgResiCr[cbfMask]);
            if ((modeId == 0) && (numTransformCands > 1))
            {
              xPreCheckMTS(currTU, &trModes, m_pcEncCfg->m_MTSIntraMaxCand, 0, COMP_Cb);
              currTU.mtsIdx[codeCompId] = trModes[modeId].first;
              currTU.mtsIdx[(codeCompId == COMP_Cr) ? COMP_Cb : COMP_Cr] = MTS_DCT2_DCT2;
            }
            cuCtx.lfnstLastScanPos = false;
            cuCtx.violatesLfnstConstrained[CH_L] = false;
            cuCtx.violatesLfnstConstrained[CH_C] = false;
            if (numTransformCands > 1)
            {
              xIntraCodingTUBlock(currTU, COMP_Cb, false, distTmp, 0, 0, true);
              if ((modeId == 0) && !trModes[modeId + 1].second)
              {
                numTransformCands = 1;
              }
            }
            else
            {
              xIntraCodingTUBlock(currTU, COMP_Cb, false, distTmp, 0);
            }

            double costTmp = std::numeric_limits<double>::max();
            if (distTmp < MAX_DISTORTION)
            {
              uint64_t bits = xGetIntraFracBitsQTChroma(currTU, COMP_Cb, &cuCtx);
              costTmp = m_pcRdCost->calcRdCost(bits, distTmp);
            }
            else if (!currTU.mtsIdx[codeCompId])
            {
              numTransformCands = 1;
            }
            bool rootCbfL = false;
            for (uint32_t t = 0; t < getNumberValidTBlocks(*cs.pcv); t++)
            {
              rootCbfL |= bool(tmpTU.cbf[t]);
            }
            if (rapidLFNST && !rootCbfL)
            {
              endLfnstIdx = lfnstIdxj;
            }
            if (testLFNST && currTU.cu->lfnstIdx && !cuCtx.lfnstLastScanPos)
            {
              bool cbfAtZeroDepth = CU::isSepTree(*currTU.cu) ? rootCbfL
                : (cs.area.chromaFormat != CHROMA_400 && std::min(tmpTU.blocks[1].width, tmpTU.blocks[1].height) < 4)
                ? TU::getCbfAtDepth(currTU, COMP_Y, currTU.depth) : rootCbfL;
              if (cbfAtZeroDepth)
              {
                costTmp = MAX_DOUBLE;
              }
            }
            if (costTmp < bestCostCbCr)
            {
              bestCostCbCr = costTmp;
              bestDistCbCr = distTmp;
              bestJointCbCr = currTU.jointCbCr;

              // store data
              bestLfnstIdx = lfnstIdxj;
              if ((cbfMask != jointCbfMasksToTest.back() || (lfnstIdxj != endLfnstIdx)) || (modeId != (numTransformCands - 1)))
              {
                saveCS.getRecoBuf(cbArea).copyFrom(cs.getRecoBuf(cbArea));
                saveCS.getRecoBuf(crArea).copyFrom(cs.getRecoBuf(crArea));

                tmpTU.copyComponentFrom(currTU, COMP_Cb);
                tmpTU.copyComponentFrom(currTU, COMP_Cr);

                ctxBest = m_CABACEstimator->getCtx();
              }
              else
              {
                lastIsBest = true;
                cs.cus[0]->lfnstIdx = bestLfnstIdx;
              }
            }
          }
        }

        // Retrieve the best CU data (unless it was the very last one tested)
      }
      if (!lastIsBest)
      {
        cs.getRecoBuf(cbArea).copyFrom(saveCS.getRecoBuf(cbArea));
        cs.getRecoBuf(crArea).copyFrom(saveCS.getRecoBuf(crArea));

        cs.cus[0]->lfnstIdx = bestLfnstIdx;
        currTU.copyComponentFrom(tmpTU, COMP_Cb);
        currTU.copyComponentFrom(tmpTU, COMP_Cr);
        m_CABACEstimator->getCtx() = ctxBest;
      }
      currTU.jointCbCr = (TU::getCbf(currTU, COMP_Cb) || TU::getCbf(currTU, COMP_Cr)) ? bestJointCbCr : 0;
    } // jointCbCr

    cs.dist += bestDistCbCr;
    cuCtx.violatesLfnstConstrained[CH_L] = false;
    cuCtx.violatesLfnstConstrained[CH_C] = false;
    cuCtx.lfnstLastScanPos = false;
    cuCtx.violatesMtsCoeffConstraint = false;
    cuCtx.mtsLastScanPos = false;
    cbfs.cbf(COMP_Cb) = TU::getCbf(currTU, COMP_Cb);
    cbfs.cbf(COMP_Cr) = TU::getCbf(currTU, COMP_Cr);
  }
  else
  {
    unsigned   numValidTBlocks = getNumberValidTBlocks(*cs.pcv);
    ChromaCbfs SplitCbfs(false);

    if (partitioner.canSplit(TU_MAX_TR_SPLIT, cs))
    {
      partitioner.splitCurrArea(TU_MAX_TR_SPLIT, cs);
    }
    else if (currTU.cu->ispMode)
    {
      partitioner.splitCurrArea(m_ispTestedModes[0].IspType, cs);
    }
    else
      THROW("Implicit TU split not available");

    do
    {
      ChromaCbfs subCbfs = xIntraChromaCodingQT(cs, partitioner);

      for (uint32_t ch = COMP_Cb; ch < numValidTBlocks; ch++)
      {
        const ComponentID compID = ComponentID(ch);
        SplitCbfs.cbf(compID) |= subCbfs.cbf(compID);
      }
    } while (partitioner.nextPart(cs));

    partitioner.exitCurrSplit();

    /*if (lumaUsesISP && cs.dist == MAX_UINT) //ahenkel
    {
      return cbfs;
    }*/
    {
      cbfs.Cb |= SplitCbfs.Cb;
      cbfs.Cr |= SplitCbfs.Cr;

      if (1)   //(!lumaUsesISP)
      {
        for (auto& ptu : cs.tus)
        {
          if (currArea.Cb().contains(ptu->Cb()) || (!ptu->Cb().valid() && currArea.Y().contains(ptu->Y())))
          {
            TU::setCbfAtDepth(*ptu, COMP_Cb, currDepth, SplitCbfs.Cb);
            TU::setCbfAtDepth(*ptu, COMP_Cr, currDepth, SplitCbfs.Cr);
          }
        }
      }
    }
  }
  return cbfs;
}

uint64_t IntraSearch::xFracModeBitsIntraLuma(const CodingUnit& cu, const unsigned* mpmLst)
{
  m_CABACEstimator->resetBits();

  if (!cu.ciip)
  {
    m_CABACEstimator->intra_luma_pred_mode(cu, mpmLst);
  }

  return m_CABACEstimator->getEstFracBits();
}

template<typename T, size_t N, int M>
void IntraSearch::xReduceHadCandList(static_vector<T, N>& candModeList, static_vector<double, N>& candCostList, SortedPelUnitBufs<M>& sortedPelBuffer, int& numModesForFullRD, const double thresholdHadCost, const double* mipHadCost, const CodingUnit& cu, const bool fastMip)
{
  const int maxCandPerType = numModesForFullRD >> 1;
  static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM> tempRdModeList;
  static_vector<double, FAST_UDI_MAX_RDMODE_NUM> tempCandCostList;
  const double minCost = candCostList[0];
  bool keepOneMip = candModeList.size() > numModesForFullRD;
  const int maxNumConv = 3; 

  int numConv = 0;
  int numMip = 0;
  for (int idx = 0; idx < candModeList.size() - (keepOneMip?0:1); idx++)
  {
    bool addMode = false;
    const ModeInfo& orgMode = candModeList[idx];

    if (!orgMode.mipFlg)
    {
      addMode = (numConv < maxNumConv);
      numConv += addMode ? 1:0;
    }
    else
    {
      addMode = ( numMip < maxCandPerType || (candCostList[idx] < thresholdHadCost * minCost) || keepOneMip );
      keepOneMip = false;
      numMip += addMode ? 1:0;
    }
    if( addMode )
    {
      tempRdModeList.push_back(orgMode);
      tempCandCostList.push_back(candCostList[idx]);
    }
  }

  // sort Pel Buffer
  int i = -1;
  for( auto &m: tempRdModeList)
  {
    if( ! (m == candModeList.at( ++i )) )
    {
      for( int j = i; j < (int)candModeList.size()-1; )
      {
        if( m == candModeList.at( ++j ) )
        {
          sortedPelBuffer.swap( i, j);
          break;
        }
      }
    }
  }
  sortedPelBuffer.reduceTo( (int)tempRdModeList.size() );

  if ((cu.lwidth() > 8 && cu.lheight() > 8))
  {
    // Sort MIP candidates by Hadamard cost
    const int transpOff = getNumModesMip(cu.Y());
    static_vector<uint8_t, FAST_UDI_MAX_RDMODE_NUM> sortedMipModes(0);
    static_vector<double, FAST_UDI_MAX_RDMODE_NUM> sortedMipCost(0);
    for (uint8_t mode : { 0, 1, 2 })
    {
      uint8_t candMode = mode + uint8_t((mipHadCost[mode + transpOff] < mipHadCost[mode]) ? transpOff : 0);
      updateCandList(candMode, mipHadCost[candMode], sortedMipModes, sortedMipCost, 3);
    }

    // Append MIP mode to RD mode list
    const int modeListSize = int(tempRdModeList.size());
    for (int idx = 0; idx < 3; idx++)
    {
      const bool     isTransposed = (sortedMipModes[idx] >= transpOff ? true : false);
      const uint32_t mipIdx       = (isTransposed ? sortedMipModes[idx] - transpOff : sortedMipModes[idx]);
      const ModeInfo mipMode( true, isTransposed, 0, NOT_INTRA_SUBPARTITIONS, mipIdx );
      bool alreadyIncluded = false;
      for (int modeListIdx = 0; modeListIdx < modeListSize; modeListIdx++)
      {
        if (tempRdModeList[modeListIdx] == mipMode)
        {
          alreadyIncluded = true;
          break;
        }
      }

      if (!alreadyIncluded)
      {
        tempRdModeList.push_back(mipMode);
        tempCandCostList.push_back(0);
        if( fastMip ) break;
      }
    }
  }

  candModeList = tempRdModeList;
  candCostList = tempCandCostList;
  numModesForFullRD = int(candModeList.size());
}

void IntraSearch::xPreCheckMTS(TransformUnit &tu, std::vector<TrMode> *trModes, const int maxCand, PelUnitBuf *predBuf, const ComponentID& compID)
{
  if (compID == COMP_Y)
  {
    CodingStructure&  cs = *tu.cs;
    const CompArea& area = tu.blocks[compID];
    const ReshapeData& reshapeData = cs.picture->reshapeData;
    const CodingUnit& cu = *cs.getCU(area.pos(), CH_L,TREE_D);
    PelBuf piPred = cs.getPredBuf(area);
    PelBuf piResi = cs.getResiBuf(area);

    initIntraPatternChType(*tu.cu, area);
    if (predBuf)
    {
      piPred.copyFrom(predBuf->Y());
    }
    else if (CU::isMIP(cu, CH_L))
    {
      initIntraMip(cu);
      predIntraMip(piPred, cu);
    }
    else
    {
      predIntraAng(COMP_Y, piPred, cu);
    }

    //===== get residual signal =====
    if (cs.picHeader->lmcsEnabled && reshapeData.getCTUFlag())
    {
      piResi.subtract(cs.getRspOrgBuf(), piPred);
    }
    else
    {
      CPelBuf piOrg = cs.getOrgBuf(COMP_Y);
      piResi.subtract(piOrg, piPred);
    }
    m_pcTrQuant->checktransformsNxN(tu, trModes, m_pcEncCfg->m_MTSIntraMaxCand, compID);
  }
  else
  {
    ComponentID codeCompId = (tu.jointCbCr ? (tu.jointCbCr >> 1 ? COMP_Cb : COMP_Cr) : compID);
    m_pcTrQuant->checktransformsNxN(tu, trModes, m_pcEncCfg->m_MTSIntraMaxCand, codeCompId);
  }
}

double IntraSearch::xTestISP(CodingStructure& cs, Partitioner& subTuPartitioner, double bestCostForISP, PartSplit ispType, bool& splitcbf, uint64_t& singleFracBits, Distortion& singleDistLuma, CUCtx& cuCtx)
{
  int  subTuCounter = 0;
  bool earlySkipISP = false;
  bool splitCbfLuma = false;
  CodingUnit& cu = *cs.cus[0];

  Distortion singleDistTmpLumaSUM = 0;
  uint64_t   singleTmpFracBitsSUM = 0;
  double     singleCostTmpSUM = 0;
  cuCtx.isDQPCoded = true;
  cuCtx.isChromaQpAdjCoded = true;

  do
  {
    Distortion singleDistTmpLuma = 0;
    uint64_t   singleTmpFracBits = 0;
    double     singleCostTmp = 0;
    TransformUnit& tmpTUcur = ((cs.tus.size() < (subTuCounter + 1)))
      ? cs.addTU(CS::getArea(cs, subTuPartitioner.currArea(), subTuPartitioner.chType,
        subTuPartitioner.treeType),
        subTuPartitioner.chType, cs.cus[0])
      : *cs.tus[subTuCounter];
    tmpTUcur.depth = subTuPartitioner.currTrDepth;

    // Encode TU
    xIntraCodingTUBlock(tmpTUcur, COMP_Y, false, singleDistTmpLuma, 0);
    cuCtx.mtsLastScanPos = false;

    if (singleDistTmpLuma == MAX_INT)   // all zero CBF skip
    {
      earlySkipISP = true;
      singleCostTmpSUM = MAX_DOUBLE;
      break;
    }

    if (m_pcRdCost->calcRdCost(singleTmpFracBitsSUM, singleDistTmpLumaSUM + singleDistTmpLuma) > bestCostForISP)
    {
      earlySkipISP = true;
    }
    else
    {
      m_ispTestedModes[0].IspType = ispType;
      m_ispTestedModes[0].subTuCounter = subTuCounter;
      singleTmpFracBits = xGetIntraFracBitsQT(cs, subTuPartitioner, true, &cuCtx);
    }
    singleCostTmp = m_pcRdCost->calcRdCost(singleTmpFracBits, singleDistTmpLuma);

    singleCostTmpSUM     += singleCostTmp;
    singleDistTmpLumaSUM += singleDistTmpLuma;
    singleTmpFracBitsSUM += singleTmpFracBits;

    subTuCounter++;

    splitCbfLuma |= TU::getCbfAtDepth( *cs.getTU(subTuPartitioner.currArea().lumaPos(), subTuPartitioner.chType, subTuCounter - 1), 
                                       COMP_Y, subTuPartitioner.currTrDepth);
    int nSubPartitions = m_ispTestedModes[cu.lfnstIdx].numTotalParts[cu.ispMode - 1];
    bool doStop = (m_pcEncCfg->m_ISP != 1) || (subTuCounter < nSubPartitions);
    if (doStop)
    {
      if (singleCostTmpSUM > bestCostForISP)
      {
        earlySkipISP = true;
        break;
      }
      if (subTuCounter < nSubPartitions)
      {
        double threshold = nSubPartitions == 2 ? 0.95 : subTuCounter == 1 ? 0.83 : 0.91;
        if (singleCostTmpSUM > bestCostForISP * threshold)
        {
          earlySkipISP = true;
          break;
        }
      }
    }
  } while (subTuPartitioner.nextPart(cs));
  singleDistLuma = singleDistTmpLumaSUM;
  singleFracBits = singleTmpFracBitsSUM;

  splitcbf = splitCbfLuma;
  return earlySkipISP ? MAX_DOUBLE : singleCostTmpSUM;
}

int IntraSearch::xSpeedUpISP(int speed, bool& testISP, int mode, int& noISP, int& endISP, CodingUnit& cu, static_vector<ModeInfo, FAST_UDI_MAX_RDMODE_NUM>& RdModeList, const ModeInfo& bestPUMode, int bestISP, int bestLfnstIdx)
{
  if (speed)
  {
    if (mode >= 1)
    {
      if (m_ispTestedModes[0].splitIsFinished[1] && m_ispTestedModes[0].splitIsFinished[0])
      {
        testISP = false;
        endISP = 0;
      }
      else
      {
        if (m_pcEncCfg->m_ISP >= 2)
        {
          if (mode == 1) //best Hor||Ver
          {
            int bestDir = 0;
            for (int d = 0; d < 2; d++)
            {
              int d2 = d ? 0 : 1;
              if ((m_ispTestedModes[0].bestCost[d] <= m_ispTestedModes[0].bestCost[d2])
                && (m_ispTestedModes[0].bestCost[d] != MAX_DOUBLE))
              {
                bestDir = d + 1;
                m_ispTestedModes[0].splitIsFinished[d2] = true;
              }
            }
            m_ispTestedModes[0].bestModeSoFar = bestDir;
            if (m_ispTestedModes[0].bestModeSoFar <= 0)
            {
              m_ispTestedModes[0].splitIsFinished[1] = true;
              m_ispTestedModes[0].splitIsFinished[0] = true;
              testISP = false;
              endISP = 0;
            }
          }
          if (m_ispTestedModes[0].bestModeSoFar == 2)
          {
            noISP = 1;
          }
          else
          {
            endISP = 1;
          }
        }
      }
    }
    if (testISP)
    {
      if (mode == 2)
      {
        for (int d = 0; d < 2; d++)
        {
          int d2 = d ? 0 : 1;
          if (m_ispTestedModes[0].bestCost[d] == MAX_DOUBLE)
          {
            m_ispTestedModes[0].splitIsFinished[d] = true;
          }
          if ((m_ispTestedModes[0].bestCost[d2] < 1.3 * m_ispTestedModes[0].bestCost[d])
            && (int(m_ispTestedModes[0].bestSplitSoFar) != (d + 1)))
          {
            if (d)
            {
              endISP = 1;
            }
            else
            {
              noISP = 1;
            }
            m_ispTestedModes[0].splitIsFinished[d] = true;
          }
        }
      }
      else
      {
        if (m_ispTestedModes[0].splitIsFinished[0])
        {
          noISP = 1;
        }
        if (m_ispTestedModes[0].splitIsFinished[1])
        {
          endISP = 1;
        }
      }
    }
    if ((noISP == 1) && (endISP == 1))
    {
      endISP = 0;
    }
  }
  else
  {
    bool stopFound = false;
    if (m_pcEncCfg->m_ISP >= 3)
    {
      if (mode)
      {
        if ((bestISP == 0) || ((bestPUMode.modeId != RdModeList[mode - 1].modeId)
          && (bestPUMode.modeId != RdModeList[mode].modeId)))
        {
          stopFound = true;
        }
      }
    }
    if (cu.mipFlag || cu.multiRefIdx)
    {
      cu.mipFlag = false;
      cu.multiRefIdx = 0;
      if (!stopFound)
      {
        for (int k = 0; k < mode; k++)
        {
          if (cu.intraDir[CH_L] == RdModeList[k].modeId)
          {
            stopFound = true;
            break;
          }
        }
      }
    }
    if (stopFound)
    {
      testISP = false;
      endISP = 0;
      return 1;
    }
    if (!stopFound && (m_pcEncCfg->m_ISP >= 2) && (cu.intraDir[CH_L] == DC_IDX))
    {
      stopFound = true;
      endISP = 0;
      return 1;
    }
  }
  return 0;
}

void IntraSearch::xSpeedUpIntra(double bestcost, int& EndMode, int& speedIntra, CodingUnit& cu)
{
  int bestIdxbefore = m_ispTestedModes[0].bestIntraMode;
  if (m_ispTestedModes[0].isIntra)
  {
    if (bestIdxbefore == 1)//ISP
    {
      speedIntra = 14;
    }
    if (bestIdxbefore == 4)//MTS
    {
      speedIntra = 3;
    }
  }
  else if (!cu.cs->slice->isIntra())
  {
    if (bestcost != MAX_DOUBLE)
    {
      speedIntra = 10;
    }
  }
  if (m_ispTestedModes[0].bestBefore[0] == -1)
  {
    speedIntra |= 7;
    if (m_pcEncCfg->m_FastIntraTools == 2)
    {
      EndMode = 1;
    }
  }
  if (!cu.cs->slice->isIntra())
  {
    if ((m_ispTestedModes[0].bestBefore[1] == 1) || (m_ispTestedModes[0].bestBefore[2] == 1))
    {
      speedIntra |= 2;
    }
    if ((m_ispTestedModes[0].bestBefore[1] == 4) || (m_ispTestedModes[0].bestBefore[2] == 4))
    {
      speedIntra |= 3;
    }
    if ((m_ispTestedModes[0].bestBefore[1] == 2) || (m_ispTestedModes[0].bestBefore[2] == 2))
    {
      speedIntra |= 1;
    }
  }
}

} // namespace vvenc

//! \}

