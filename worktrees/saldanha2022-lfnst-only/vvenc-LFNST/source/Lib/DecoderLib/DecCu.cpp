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


/** \file     DecCu.cpp
    \brief    CU decoder class
*/

#include "DecCu.h"

#include "CommonLib/InterPrediction.h"
#include "CommonLib/IntraPrediction.h"
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"
#include "CommonLib/LoopFilter.h"
#include "CommonLib/Reshape.h"
#include "CommonLib/dtrace_buffer.h"

//! \ingroup DecoderLib
//! \{

namespace vvenc {

// ====================================================================================================================
// Constructor / destructor / create / destroy
// ====================================================================================================================

DecCu::DecCu()
{
}

DecCu::~DecCu()
{
  m_TmpBuffer.destroy();
  m_PredBuffer.destroy();
}

void DecCu::init( TrQuant* pcTrQuant, IntraPrediction* pcIntra, InterPrediction* pcInter, ChromaFormat chrFormat)
{
  m_pcTrQuant       = pcTrQuant;
  m_pcIntraPred     = pcIntra;
  m_pcInterPred     = pcInter;
  m_TmpBuffer.destroy();
  m_TmpBuffer.create( chrFormat, Area( 0,0, MAX_TB_SIZEY, MAX_TB_SIZEY ));
  m_PredBuffer.destroy();
  m_PredBuffer.create( chrFormat, Area( 0,0, MAX_CU_SIZE, MAX_CU_SIZE ));
    //***************************************** attached part **********************************************
#if internet && 0 //init
  // --- IEPR init (encoder-side deploy) ---
  //if( m_pcEncCfg && m_pcEncCfg->m_ieprEnabled )
  {
    m_iepr.reset( new IeprOnnx() );
    if( !m_iepr->init( "G:/00_KeyResearch/conv360/iepr_new.onnx" ) )
    {
      m_iepr.reset();
    }
  }
#endif
 //******************************************************************************************************

}

// ====================================================================================================================
// Protected member functions
// ====================================================================================================================

void DecCu::xIntraRecBlk( TransformUnit& tu, const ComponentID compID )
{
  if( !tu.blocks[ compID ].valid() )
  {
    return;
  }

        CodingStructure &cs     = *tu.cs;
  const CompArea& area          = tu.blocks[compID];
  const ChannelType chType      = toChannelType( compID );
  PelBuf piPred                 = tu.cu->ispMode && isLuma( compID ) ? cs.getPredBuf( area ) : m_PredBuffer.getCompactBuf( area );
  const CodingUnit& cu          = *tu.cu;
  const uint32_t uiChFinalMode  = CU::getFinalIntraMode( cu, chType );
  PelBuf pReco                  = cs.getRecoBuf( area );

  //===== init availability pattern =====
  CompArea areaPredReg(COMP_Y, tu.chromaFormat, area);
  bool predRegDiffFromTB = isLuma( compID ) && CU::isPredRegDiffFromTB( *tu.cu );
  bool firstTBInPredReg  = isLuma( compID ) && CU::isFirstTBInPredReg ( *tu.cu, area );

  if( tu.cu->ispMode && isLuma( compID ) )
  {
    if( predRegDiffFromTB )
    {
      if( firstTBInPredReg )
      {
        CU::adjustPredArea( areaPredReg );
        m_pcIntraPred->initIntraPatternChTypeISP( *tu.cu, areaPredReg, pReco );
      }
    }
    else
    {
      m_pcIntraPred->initIntraPatternChTypeISP( *tu.cu, area, pReco );
    }
  }
  else
  {
    m_pcIntraPred->initIntraPatternChType( *tu.cu, area );
  }

  //===== get prediction signal =====
  if( compID != COMP_Y && CU::isLMCMode( uiChFinalMode ) )
  {
    const CodingUnit& cu = *tu.cu;
    m_pcIntraPred->loadLMLumaRecPels( cu, area );
    m_pcIntraPred->predIntraChromaLM( compID, piPred, cu, area, uiChFinalMode );
  }
  else if( CU::isMIP( cu, chType ) )
  {
    m_pcIntraPred->initIntraMip( cu );
    m_pcIntraPred->predIntraMip( piPred, cu );
  }
  else
  {
    if (predRegDiffFromTB)
    {
      if (firstTBInPredReg)
      {
        PelBuf piPredReg = cs.getPredBuf(areaPredReg);
        m_pcIntraPred->predIntraAng(compID, piPredReg, cu);
      }
    }
    else
    {
      m_pcIntraPred->predIntraAng(compID, piPred, cu);
    }
  }
  //===== inverse transform =====
  const Slice& slice       = *cs.slice;
  ReshapeData& reshapeData = cs.picture->reshapeData;
  bool lmcsflag = slice.lmcsEnabled && (slice.isIntra() || (!slice.isIntra() && reshapeData.getCTUFlag()));
  if (lmcsflag && slice.picHeader->lmcsChromaResidualScale && (compID != COMP_Y) && (tu.cbf[COMP_Cb] || tu.cbf[COMP_Cr]))
  {
    const Area area = tu.Y().valid() ? tu.Y() : Area(recalcPosition(tu.chromaFormat, tu.chType, CH_L, tu.blocks[tu.chType].pos()), recalcSize(tu.chromaFormat, tu.chType, CH_L, tu.blocks[tu.chType].size()));
    const CompArea& areaY = CompArea(COMP_Y, tu.chromaFormat, area);
    tu.chromaAdj = reshapeData.calculateChromaAdjVpduNei(tu, areaY, TREE_D);
  }
  //===== inverse transform =====
  PelBuf piResi = cs.getResiBuf( area );

  const QpParam cQP( tu, compID );

  if( tu.jointCbCr && isChroma(compID) )
  {
    if( compID == COMP_Cb )
    {
      PelBuf resiCr = cs.getResiBuf( tu.blocks[ COMP_Cr ] );
      if( tu.jointCbCr >> 1 )
      {
        m_pcTrQuant->invTransformNxN( tu, COMP_Cb, piResi, cQP );
      }
      else
      {
        const QpParam qpCr( tu, COMP_Cr );
        m_pcTrQuant->invTransformNxN( tu, COMP_Cr, resiCr, qpCr );
      }
      m_pcTrQuant->invTransformICT( tu, piResi, resiCr );
    }
  }
  else
  if( TU::getCbf( tu, compID ) )
  {
    m_pcTrQuant->invTransformNxN( tu, compID, piResi, cQP );
  }
  else
  {
    piResi.fill( 0 );
  }

  //===== reconstruction =====
  lmcsflag &= (tu.blocks[compID].width*tu.blocks[compID].height > 4) && slice.picHeader->lmcsChromaResidualScale;
  if (lmcsflag && (TU::getCbf(tu, compID) || tu.jointCbCr) && isChroma(compID) )
  {
    piResi.scaleSignal(tu.chromaAdj, 0, tu.cu->cs->slice->clpRngs[compID]);
  }


  piPred.reconstruct( piPred, piResi, tu.cu->cs->slice->clpRngs[ compID ] );
  pReco.copyFrom( piPred );

  if( true/*isEncoder*/ )
  {
    cs.picture->getRecoBuf( area ).copyFrom( pReco );
  }
}

void DecCu::xReconIntraQT( CodingUnit &cu )
{
  const uint32_t numChType = getNumberValidChannels( cu.chromaFormat );

  for( uint32_t chType = CH_L; chType < numChType; chType++ )
  {
    if( cu.blocks[chType].valid() )
    {
      xIntraRecQT( cu, ChannelType( chType ) );
    }
  }
}

/** Function for deriving reconstructed PU/CU chroma samples with QTree structure
* \param pcRecoYuv pointer to reconstructed sample arrays
* \param pcPredYuv pointer to prediction sample arrays
* \param pcResiYuv pointer to residue sample arrays
* \param chType    texture channel type (luma/chroma)
* \param rTu       reference to transform data
*
\ This function derives reconstructed PU/CU chroma samples with QTree recursive structure
*/

void DecCu::xIntraRecQT(CodingUnit &cu, const ChannelType chType)
{
  for( auto &currTU : CU::traverseTUs( cu ) )
  {
    if( isLuma( chType ) )
    {
      xIntraRecBlk( currTU, COMP_Y );
    }
    else
    {
      const uint32_t numValidComp = getNumberValidComponents( cu.chromaFormat );

      for( uint32_t compID = COMP_Cb; compID < numValidComp; compID++ )
      {
        xIntraRecBlk( currTU, ComponentID( compID ) );
      }
    }
  }
}

//******************************************************* attached part ******************************************************************
#if internet && 0//函数dec
void DecCu::dec_pred_refine_iepr(CodingStructure& cs, CodingUnit &cu, bool& done)
{
    //CodingUnit &cu = *cs.getCU( partitioner.chType, partitioner.treeType );
    
    const int ri0 = cu.refIdx[REF_PIC_LIST_0];
    const int ri1 = cu.refIdx[REF_PIC_LIST_1];
    //if (ri0 < 0) std::cout << " return 1" << " interDir="<< int(cu.interDir) <<" ri0="<<ri0<<" ri1="<<ri1<< std::endl;  return; // 或者直接跳过 IEPR
    //if( cu.interDir != 3 || ri1 < 0 ) std::cout << " interDir="<< int(cu.interDir) <<" ri0="<<ri0<<" ri1="<<ri1 << std::endl; return; 

    // ---------- 1) 计算扩展区域并裁剪到图像边界 ----------
    const SizeType extM = cu.lumaSize().width / 2;

    const PelBuf picRecoY = cs.picture->getRecoBuf( COMP_Y );// 取当前 picture 的 luma 全图尺寸（用现成 PelBuf 拿 width/height 最稳）
    const int picW = picRecoY.width;
    const int picH = picRecoY.height;

    PosType ext_x = std::max(int(cu.lumaPos().x - extM), 0);
    PosType ext_y = std::max(int(cu.lumaPos().y - extM), 0);

    int ext_w = cu.lumaSize().width + extM;
    int ext_h = cu.lumaSize().height + extM;

    ext_w = std::min( ext_w, picW - ext_x );
    ext_h = std::min( ext_h, picH - ext_y );

    if (ext_w <= 0 || ext_h <= 0) { std::cout << " ext_w=" << ext_w << " ext_h=" << ext_h << std::endl; return; }

    const Size blkSize = Size(ext_w, ext_h);
    const Position pos = Position(ext_x, ext_y);

    CompArea ext_area(COMP_Y, cs.area.chromaFormat, pos, blkSize); // predArea（必须在图像内）
    PelBuf predYbuf = cs.getPredBuf(COMP_Y);


    // ---------- 2) 构造 predtmp（用 vector，避免泄漏） ----------补L型像素
    // 准备 predtmp(96x96) + 输出 predOut(96x96) 的连续缓存
    std::vector<Pel> predTmp( ext_w * ext_h, 0 );
    std::vector<Pel> predOut( ext_w * ext_h, 0 );

    // 用 PelBuf 包装连续内存（stride = width）
    PelBuf predOutBuf( predOut.data(), ext_w, ext_w, ext_h );

    const PelBuf recoPicY = cs.picture->getRecoBuf( COMP_Y );

    for (int j = 0; j < ext_h; j++)
    {
        for (int i = 0; i < ext_w; i++)
        {
            if( j < extM || i < extM )
              predTmp[j*ext_w + i] = recoPicY.at(ext_x + i, ext_y + j);   // L 形：用已重建邻域
            else
              predTmp[j*ext_w + i] = predYbuf.at(i - extM, j - extM);  // 其余：用原 prediction
           
            predOut[j*ext_w + i] = predTmp[j*ext_w + i]; // 初始化输出缓冲为“原 predtmp”（网络输出是 refinement 后的 pred）
            //std::cout <<predtmp[j * ext_w + i]<< " ";
        }
        //std::cout << std::endl;
    }
    //std::cout << std::endl;

    // ========== 3) 取 L0/L1 参考块（必须使用 cu.refIdx，而不是写死 0） ==========
    const Picture* refPic0 = cu.slice->getRefPic( REF_PIC_LIST_0, ri0 );
    const Picture* refPic1 = cu.slice->getRefPic( REF_PIC_LIST_1, ri1 );
    //if (!refPic0 || !refPic1) { std::cout << " !refPic0=" << int(!refPic0) << " !refPic1=" << int(!refPic1) << std::endl; return; }
    if (cu.interDir == 1) // ri0=0, ri1=-1
    {
        refPic1 = refPic0;
    }
    else if(cu.interDir == 2)
    {
        refPic0 = refPic1; // ri0=-1, ri1=0
    }
    else if (cu.interDir != 3)
    {
        std::cout << " doont know which ref, return " << " interDir="<< int(cu.interDir) <<" ri0="<<ri0<<" ri1="<<ri1<< std::endl;
        return;
    }

    // ---- MV 取整像素位移：用统一右移写法（避免尺度错） ----
    auto calcRefPos = [&]( RefPicList L, const Picture* refPic, int& refX, int& refY )
    {
      Mv mv = cu.mv[L][0];
      clipMv( mv, cu.lumaPos(), cu.lumaSize(), *cs.pcv );

      Mv mvInt = mv;
      mvInt.roundToPrecision( MV_PRECISION_INTERNAL, MV_PRECISION_INT ); // -> full-pel 取整像素位移（luma 不需要 chroma scale）

      // 以扩展块左上角对齐
      refX = cu.lumaPos().x + mvInt.hor - extM;
      refY = cu.lumaPos().y + mvInt.ver - extM;

      // 裁剪到参考图像边界：保证 refArea 在 refPic 内
      const CPelBuf refFull = refPic->getRecoBuf( COMP_Y );
      refX = std::min( std::max( refX, 0 ), int(refFull.width)  - ext_w );
      refY = std::min( std::max( refY, 0 ), int(refFull.height) - ext_h );
    };

    int refX0, refY0, refX1, refY1;
    calcRefPos( REF_PIC_LIST_0, refPic0, refX0, refY0 );
    calcRefPos( REF_PIC_LIST_1, refPic1, refX1, refY1 );

    CompArea refArea0( COMP_Y, cs.area.chromaFormat, Position(refX0, refY0), blkSize );
    CompArea refArea1( COMP_Y, cs.area.chromaFormat, Position(refX1, refY1), blkSize );

    CPelBuf refYbuf0 = refPic0->getRecoBuf( refArea0 );
    CPelBuf refYbuf1 = refPic1->getRecoBuf( refArea1 );

    // ========== 4) 调用 IEPR：注意 ClpRng 传 COMP_Y ==========
    try
    {
        m_iepr->apply( predTmp.data(), predOutBuf, refYbuf0, refYbuf0, cu.lumaPos().y, cu.slice->clpRngs[COMP_Y] );
    }
    catch( const Ort::Exception& e )
    {
        printf("[IEPR] ORT exception: %s\n", e.what() );
        return;
    }
    // 把 refined 的 bottom-right 64x64 写回 CU pred（只改 CU 区域）
    for( int y = 0; y < cu.lumaSize().height; y++ )
    {
        for( int x = 0; x < cu.lumaSize().width; x++ )
        {
            predYbuf.at( x, y ) = predOutBuf.at( x + extM, y + extM );
        }
    }
    done = true;
    //std::cout << " done=" << done << std::endl;
}
#endif
//*************************************************************************************************************************

void DecCu::xReconInter(CodingUnit &cu)
{
  CodingStructure &cs = *cu.cs;
  // inter prediction

  PelUnitBuf predBuf = m_PredBuffer.getCompactBuf( cu ); 
  const ReshapeData& reshapeData = cs.picture->reshapeData;
  if (cu.geo)
  {
    m_pcInterPred->motionCompensationGeo(cu, predBuf, m_geoMrgCtx);
    CU::spanGeoMotionInfo(cu, m_geoMrgCtx, cu.geoSplitDir, cu.geoMergeIdx0, cu.geoMergeIdx1);
  }
  else
  {
    CHECK(CU::isIBC(cu) && cu.ciip, "IBC and Ciip cannot be used together");
    CHECK(CU::isIBC(cu) && cu.affine, "IBC and Affine cannot be used together");
    CHECK(CU::isIBC(cu) && cu.geo, "IBC and geo cannot be used together");
    CHECK(CU::isIBC(cu) && cu.mmvdMergeFlag, "IBC and MMVD cannot be used together");
    const bool luma = cu.Y().valid();
    const bool chroma = isChromaEnabled(cu.chromaFormat) && cu.Cb().valid();
    if (luma && (chroma || !isChromaEnabled(cu.chromaFormat)))
    {
      cu.mvRefine = true;
      m_pcInterPred->motionCompensation(cu, predBuf);
      cu.mvRefine = false;
    }
    else
    {
      cu.mcControl = luma ? 0 : 4;
      cu.mcControl |= chroma ? 0 : 2;
      m_pcInterPred->motionCompensationIBC(cu, predBuf);
      cu.mcControl = 0;
    }
    if (cu.Y().valid())
    {
      bool isIbcSmallBlk = CU::isIBC(cu) && (cu.lwidth() * cu.lheight() <= 16);
      //CU::saveMotionInHMVP(cu, isIbcSmallBlk);
      if (!cu.affine && !cu.geo && !isIbcSmallBlk)
      {
        const MotionInfo& mi = cu.getMotionInfo();
        HPMVInfo hMi( mi, ( mi.interDir() == 3 ) ? cu.BcwIdx : BCW_DEFAULT, cu.imv == IMV_HPEL, CU::isIBC( cu ) );
        cs.addMiToLut(CU::isIBC(cu) ? cu.cs->motionLut.lutIbc : cu.cs->motionLut.lut, hMi);
      }
    }

    if (cu.ciip)
    {
      PelBuf ciipBuf = m_TmpBuffer.getCompactBuf( cu.Y() );

      m_pcIntraPred->initIntraPatternChType(cu, cu.Y());
      m_pcIntraPred->predIntraAng(COMP_Y, ciipBuf, cu);

      if( cs.picHeader->lmcsEnabled && reshapeData.getCTUFlag() )
      {
        predBuf.Y().rspSignal( reshapeData.getFwdLUT());
      }
      const int numCiipIntra = m_pcIntraPred->getNumIntraCiip( cu );
      predBuf.Y().weightCiip( ciipBuf, numCiipIntra);

      if (isChromaEnabled(cu.chromaFormat) && cu.chromaSize().width > 2)
      {
        PelBuf ciipBufC = m_TmpBuffer.getCompactBuf( cu.Cb() );
        m_pcIntraPred->initIntraPatternChType(cu, cu.Cb());
        m_pcIntraPred->predIntraAng(COMP_Cb, ciipBufC, cu);
        predBuf.Cb().weightCiip( ciipBufC, numCiipIntra);

        m_pcIntraPred->initIntraPatternChType(cu, cu.Cr());
        m_pcIntraPred->predIntraAng(COMP_Cr, ciipBufC, cu);
        predBuf.Cr().weightCiip( ciipBufC, numCiipIntra);
      }
    }
  }

  if (cs.slice->lmcsEnabled && reshapeData.getCTUFlag() && !cu.ciip && !CU::isIBC(cu) )
  {
    predBuf.Y().rspSignal(reshapeData.getFwdLUT());
  }

  // inter recon
  xDecodeInterTexture(cu);

  bool LumaOnly = ((predBuf.bufs.size() > 1) && (predBuf.bufs[1].stride != 0 && predBuf.bufs[2].stride != 0) ) ? false : true;
  if (cu.rootCbf)
  {
    if (LumaOnly)
    {
      cs.getResiBuf(cu.Y()).reconstruct(predBuf.Y(), cs.getResiBuf(cu.Y()), cs.slice->clpRngs[COMP_Y]);
      cs.getRecoBuf(cu.Y()).copyFrom(cs.getResiBuf(cu.Y()));
#if internet && 0
        bool enbale_iepr = false;
        enbale_iepr = cu.Y().width == BLOCKSIZE && cu.Y().height == BLOCKSIZE && cu.predMode == MODE_INTER
                    /*&& (zeroCost > cs.cost) && cu.rootCbf*/
                    &&(m_iepr && m_iepr->ready());

        std::cout << "dec poc="<< cs.picture->getPOC() <<" x="<<cu.lx()<<" y="<<cu.ly() << " interDir="<<int(cu.interDir) << " enbale_iepr=" << enbale_iepr <<" bool="<<(m_iepr && m_iepr->ready()) << std::endl;

        // --- IEPR insertion: refine prediction BEFORE residual ---
        if(enbale_iepr)
        {
            //std::cout << " poc="<< cs.picture->getPOC() <<" x="<<cu.lx()<<" y="<<cu.ly() << " interDir="<<int(cu.interDir) << " enbale_iepr=" << enbale_iepr << std::endl;
              
            bool full_done = false;
            dec_pred_refine_iepr( cs, cu, full_done);
            //cu.enc_use_iepr = 1;
              
            //std::cout << " aft=" << full_done << std::endl;

            /*if (iresi!= nullptr) {
                delete[] iresi;
                iresi = nullptr;
            }*/
        
        }
#endif

    }
    else
    {
      cs.getResiBuf(cu).reconstruct(predBuf, cs.getResiBuf(cu), cs.slice->clpRngs);
      cs.getRecoBuf(cu).copyFrom(cs.getResiBuf(cu));
    }
  }
  else
  {
    if (LumaOnly)
    {
      cs.getRecoBuf(cu.Y()).copyClip(predBuf.Y(), cs.slice->clpRngs[COMP_Y]);
    }
    else
    {
      cs.getRecoBuf(cu).copyClip(predBuf, cs.slice->clpRngs);
    }
  }
}

void DecCu::xDecodeInterTU( TransformUnit&  currTU, const ComponentID compID )
{
  if( !currTU.blocks[compID].valid() ) return;

  const CompArea& area = currTU.blocks[compID];

  CodingStructure& cs = *currTU.cs;

  //===== inverse transform =====
  PelBuf resiBuf  = cs.getResiBuf(area);

  const QpParam cQP(currTU, compID);

  if( currTU.jointCbCr && isChroma(compID) )
  {
    if( compID == COMP_Cb )
    {
      PelBuf resiCr = cs.getResiBuf( currTU.blocks[ COMP_Cr ] );
      if( currTU.jointCbCr >> 1 )
      {
        m_pcTrQuant->invTransformNxN( currTU, COMP_Cb, resiBuf, cQP );
      }
      else
      {
        const QpParam qpCr( currTU, COMP_Cr );
        m_pcTrQuant->invTransformNxN( currTU, COMP_Cr, resiCr, qpCr );
      }
      m_pcTrQuant->invTransformICT( currTU, resiBuf, resiCr );
    }
  }
  else
  if( TU::getCbf( currTU, compID ) )
  {
    m_pcTrQuant->invTransformNxN( currTU, compID, resiBuf, cQP );
  }
  else
  {
    resiBuf.fill( 0 );
  }

  const Slice& slice = *currTU.cu->slice;
  const ReshapeData& reshapeData = cs.picture->reshapeData;
  if( slice.lmcsEnabled && reshapeData.getCTUFlag() && isChroma(compID) && (TU::getCbf(currTU, compID) || currTU.jointCbCr)
   && slice.picHeader->lmcsChromaResidualScale && currTU.blocks[compID].width * currTU.blocks[compID].height > 4)
  {
    resiBuf.scaleSignal(currTU.chromaAdj, 0, slice.clpRngs[compID]);
  }
}

void DecCu::xDecodeInterTexture(CodingUnit &cu)
{
  if( !cu.rootCbf )
  {
    return;
  }

  const uint32_t uiNumVaildComp = getNumberValidComponents(cu.chromaFormat);
  ReshapeData& reshapeData = cu.cs->picture->reshapeData;
  const bool chromaAdj = cu.slice->lmcsEnabled && reshapeData.getCTUFlag() && cu.slice->picHeader->lmcsChromaResidualScale;
  for (uint32_t ch = 0; ch < uiNumVaildComp; ch++)
  {
    const ComponentID compID = ComponentID(ch);

    for( auto& currTU : CU::traverseTUs( cu ) )
    {
      if( chromaAdj && (compID == COMP_Y) && (currTU.cbf[COMP_Cb] || currTU.cbf[COMP_Cr]))
      {
        currTU.chromaAdj = reshapeData.calculateChromaAdjVpduNei(currTU, currTU.blocks[COMP_Y], TREE_D);
      }

      xDecodeInterTU( currTU, compID );
    }
  }
}

void DecCu::xDeriveCUMV( CodingUnit &cu )
{
  MergeCtx mrgCtx;

  if( cu.mergeFlag )
  {
    if (cu.mmvdMergeFlag || cu.mmvdSkip)
    {
      CHECK(cu.ciip == true, "invalid MHIntra");
      if (cu.cs->sps->SbtMvp)
      {
        Size bufSize = g_miScaling.scale(cu.lumaSize());
        mrgCtx.subPuMvpMiBuf = MotionBuf(m_subPuMiBuf, bufSize);
      }
      int   fPosBaseIdx = cu.mmvdMergeIdx / MMVD_MAX_REFINE_NUM;
      CU::getInterMergeCandidates(cu, mrgCtx, 1, fPosBaseIdx + 1);
      CU::getInterMMVDMergeCandidates(cu, mrgCtx, cu.mmvdMergeIdx);
      mrgCtx.setMmvdMergeCandiInfo(cu, cu.mmvdMergeIdx);
      CU::spanMotionInfo(cu, mrgCtx);
    }
    else
    {
      if (cu.geo)
      {
        CU::getGeoMergeCandidates(cu, m_geoMrgCtx);
      }
      else
      {
        if (cu.affine)
        {
          AffineMergeCtx affineMergeCtx;
          if (cu.cs->sps->SbtMvp)
          {
            Size bufSize          = g_miScaling.scale(cu.lumaSize());
            mrgCtx.subPuMvpMiBuf  = MotionBuf(m_subPuMiBuf, bufSize);
            affineMergeCtx.mrgCtx = &mrgCtx;
          }
          CU::getAffineMergeCand(cu, affineMergeCtx, cu.mergeIdx);
          cu.interDir       = affineMergeCtx.interDirNeighbours[cu.mergeIdx];
          cu.affineType = affineMergeCtx.affineType[cu.mergeIdx];
          cu.BcwIdx     = affineMergeCtx.BcwIdx[cu.mergeIdx];
          cu.mergeType      = affineMergeCtx.mergeType[cu.mergeIdx];

          if (cu.mergeType == MRG_TYPE_SUBPU_ATMVP)
          {
            cu.refIdx[0] = affineMergeCtx.mvFieldNeighbours[(cu.mergeIdx << 1) + 0][0].refIdx;
            cu.refIdx[1] = affineMergeCtx.mvFieldNeighbours[(cu.mergeIdx << 1) + 1][0].refIdx;
          }
          else
          {
            for (int i = 0; i < 2; ++i)
            {
              if (cu.cs->slice->numRefIdx[RefPicList(i)] > 0)
              {
                MvField *mvField = affineMergeCtx.mvFieldNeighbours[(cu.mergeIdx << 1) + i];
                cu.mvpIdx[i]     = 0;
                cu.mvpNum[i]     = 0;
                cu.mvd[i][0]     = Mv();
                CU::setAllAffineMvField(cu, mvField, RefPicList(i));
              }
            }
          }
        }
        else
        {
          if (CU::isIBC(cu))
          {
            CU::getIBCMergeCandidates(cu, mrgCtx, cu.mergeIdx);
          }
          else
          {
            CU::getInterMergeCandidates(cu, mrgCtx, 0, cu.mergeIdx);
          }
          mrgCtx.setMergeInfo(cu, cu.mergeIdx);
        }

        CU::spanMotionInfo(cu, mrgCtx);
      }
    }
  } 
  else
  {
    if (cu.affine)
    {
      for (uint32_t uiRefListIdx = 0; uiRefListIdx < 2; uiRefListIdx++)
      {
        RefPicList eRefList = RefPicList(uiRefListIdx);
        if (cu.cs->slice->numRefIdx[eRefList] > 0 && (cu.interDir & (1 << uiRefListIdx)))
        {
          AffineAMVPInfo affineAMVPInfo;
          CU::fillAffineMvpCand(cu, eRefList, cu.refIdx[eRefList], affineAMVPInfo);

          const unsigned mvp_idx = cu.mvpIdx[eRefList];

          cu.mvpNum[eRefList] = affineAMVPInfo.numCand;

          //    Mv mv[3];
          CHECK(cu.refIdx[eRefList] < 0, "Unexpected negative refIdx.");
          if (!true/*isEncoder*/)
          {
            cu.mvd[eRefList][0].changeAffinePrecAmvr2Internal(cu.imv);
            cu.mvd[eRefList][1].changeAffinePrecAmvr2Internal(cu.imv);
            if (cu.affineType == AFFINEMODEL_6PARAM)
            {
              cu.mvd[eRefList][2].changeAffinePrecAmvr2Internal(cu.imv);
            }
          }

          Mv mvLT = affineAMVPInfo.mvCandLT[mvp_idx] + cu.mvd[eRefList][0];
          Mv mvRT = affineAMVPInfo.mvCandRT[mvp_idx] + cu.mvd[eRefList][1];
          mvRT += cu.mvd[eRefList][0];

          Mv mvLB;
          if (cu.affineType == AFFINEMODEL_6PARAM)
          {
            mvLB = affineAMVPInfo.mvCandLB[mvp_idx] + cu.mvd[eRefList][2];
            mvLB += cu.mvd[eRefList][0];
          }
          CU::setAllAffineMv(cu, mvLT, mvRT, mvLB, eRefList, true);
        }
      }
    }
    else if (CU::isIBC(cu) && cu.interDir == 1)
    {
      AMVPInfo amvpInfo;
      CU::fillIBCMvpCand(cu, amvpInfo);
      cu.mvpNum[REF_PIC_LIST_0] = amvpInfo.numCand;
      Mv mvd = cu.mvd[REF_PIC_LIST_0][0];
      if (!true/*isEncoder*/)
      {
        mvd.changeIbcPrecAmvr2Internal(cu.imv);
      }
      if (cu.cs->sps->maxNumIBCMergeCand == 1)
      {
        CHECK(cu.mvpIdx[REF_PIC_LIST_0], "mvpIdx for IBC mode should be 0");
      }
      cu.mv[REF_PIC_LIST_0][0] = amvpInfo.mvCand[cu.mvpIdx[REF_PIC_LIST_0]] + mvd;
      cu.mv[REF_PIC_LIST_0][0].mvCliptoStorageBitDepth();
    }
    else
    {
      for ( uint32_t uiRefListIdx = 0; uiRefListIdx < 2; uiRefListIdx++ )
      {
        RefPicList eRefList = RefPicList( uiRefListIdx );
        if ((cu.cs->slice->numRefIdx[eRefList] > 0 || (eRefList == REF_PIC_LIST_0 && CU::isIBC(cu))) && (cu.interDir & (1 << uiRefListIdx)))
        {
          AMVPInfo amvpInfo;
          CU::fillMvpCand(cu, eRefList, cu.refIdx[eRefList], amvpInfo);
          cu.mvpNum [eRefList] = amvpInfo.numCand;
          if (!true/*isEncoder*/)
          {
            cu.mvd[eRefList][0].changeTransPrecAmvr2Internal(cu.imv);
          }
          cu.mv[eRefList][0] = amvpInfo.mvCand[cu.mvpIdx[eRefList]] + cu.mvd[eRefList][0];
          cu.mv[eRefList][0].mvCliptoStorageBitDepth();
        }
      }
    }
    CU::spanMotionInfo( cu, mrgCtx );
  }
  if (CU::isIBC(cu)) //only check
  {
    const int cuPelX = cu.Y().x;
    const int cuPelY = cu.Y().y;
    int roiWidth = cu.lwidth();
    int roiHeight = cu.lheight();
    const unsigned int  lcuWidth = cu.cs->slice->sps->CTUSize;
    int xPred = cu.mv[0][0].hor >> MV_FRACTIONAL_BITS_INTERNAL;
    int yPred = cu.mv[0][0].ver >> MV_FRACTIONAL_BITS_INTERNAL;
    CHECK(!m_pcInterPred->isLumaBvValidIBC(lcuWidth, cuPelX, cuPelY, roiWidth, roiHeight, xPred, yPred), "invalid block vector for IBC detected.");
  }
}

} // namespace vvenc

//! \}

