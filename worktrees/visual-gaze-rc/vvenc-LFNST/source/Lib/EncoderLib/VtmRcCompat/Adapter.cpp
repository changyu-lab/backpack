// VVenC call-site adapter; the numerical controller lives in RateCtrl.cpp.
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"
#include "EncoderLib/EncCfg.h"
#include "Adapter.h"
#include "IntraCost.h"
#include <cmath>
#include <iomanip>
#include <stdexcept>

namespace vvenc { namespace vtmrc {
Adapter::Adapter(const VVEncCfg& cfg) : m_cfg(cfg)
{
  if(cfg.m_visualGazeMode>0) m_gaze.reset(new gaze::Runtime(cfg));
  GOPEntry entries[MAX_GOP];
  for(int i=0;i<cfg.m_GOPSize;++i)
  {
    entries[i].m_POC=cfg.m_GOPList[i].m_POC;
    entries[i].m_refPic=false;
    for(int j=0;j<cfg.m_GOPSize;++j)
      for(int l=0;l<2;++l)
        for(int r=0;r<cfg.m_GOPList[j].m_numRefPics[l];++r)
        {
          int ref=cfg.m_GOPList[j].m_POC-cfg.m_GOPList[j].m_deltaRefPics[l][r];
          ref=((ref-1)%cfg.m_GOPSize+cfg.m_GOPSize)%cfg.m_GOPSize+1;
          if(ref==entries[i].m_POC) entries[i].m_refPic=true;
        }
  }
  Fraction fps; fps.num=cfg.m_FrameRate; fps.den=cfg.m_FrameScale;
  m_rc.init(cfg.m_framesToBeEncoded,cfg.m_vtmRcTargetBitrate,fps,cfg.m_GOPSize,
            cfg.m_IntraPeriod,cfg.m_PadSourceWidth,cfg.m_PadSourceHeight,cfg.m_CTUSize,
            cfg.m_CTUSize,cfg.m_internalBitDepth[0],cfg.m_vtmRcKeepHierBits,true,entries);
  if(cfg.m_vtmRcTrace[0])
  {
    m_trace.open(cfg.m_vtmRcTrace,std::ios::out|std::ios::trunc);
    if(!m_trace) throw std::runtime_error("Cannot open VTMRCTrace");
    m_trace << "event,poc,ctu,bits,qp,lambda,pic_target,pic_left,gop_left,seq_left,alpha,beta,valid_pix,skip_ratio,mse\n";
    m_trace << std::setprecision(17);
  }
}

void Adapter::beginPicture(Picture& pic)
{
  if(m_active || m_pending) throw std::logic_error("VTM23 next picture before previous feedback");
  auto* seq=m_rc.getRCSeq();
  if(seq->getFramesLeft()<=0) throw std::logic_error("VTM23 picture exceeds FramesToBeEncoded");
  if(!m_hasGop || m_rc.getRCGOP()->getPicLeft()==0)
  {
    if(m_hasGop) m_rc.destroyRCGOP();
    const int count=pic.poc==0 ? 1 : std::min(m_cfg.m_GOPSize,seq->getFramesLeft());
    m_rc.initRCGOP(count); m_hasGop=true;
  }
  Slice& slice=*pic.slices[0];
  m_poc=pic.poc; m_irap=slice.isIRAP(); m_intra=slice.isIntra();
  const int relativePoc=((pic.poc-1)%m_cfg.m_GOPSize+m_cfg.m_GOPSize)%m_cfg.m_GOPSize+1;
  int gopId=-1;
  for(int i=0;i<m_cfg.m_GOPSize;++i)
    if(m_cfg.m_GOPList[i].m_POC==relativePoc) { gopId=i; break; }
  if(gopId<0) throw std::logic_error("VTM23 picture has no configured GOP entry");
  const int level=m_irap ? 0 : seq->getGOPID2Level(gopId);
  if(level>=seq->getNumberOfLevel()) throw std::logic_error("VTM23 incompatible picture hierarchy");
  m_rc.initRCPic(level);
  auto& rcPic=picture();
  m_estimatedBits=rcPic.getTargetBits(); // VTM GOP uses this pre-refinement IRAP estimate.
  if(level==0)
  {
    const int shift=slice.sps->bitDepths[CH_L]-8;
    const int offset=shift>0 ? 1<<(shift-1) : 0;
    double total=0.0;
    const int cols=(m_cfg.m_PadSourceWidth+m_cfg.m_CTUSize-1)/m_cfg.m_CTUSize;
    for(int k=0;k<rcPic.getNumberOfLCU();++k)
    {
      int x=(k%cols)*m_cfg.m_CTUSize, y=(k/cols)*m_cfg.m_CTUSize;
      CompArea area(COMP_Y,pic.chromaFormat,Position(x,y),Size(std::min<int>(m_cfg.m_CTUSize,m_cfg.m_PadSourceWidth-x),std::min<int>(m_cfg.m_CTUSize,m_cfg.m_PadSourceHeight-y)));
      const int cost=intraCost(pic.getOrigBuf(area));
      rcPic.getLCU(k).m_costIntra=(cost+offset)>>shift;
      total+=rcPic.getLCU(k).m_costIntra;
    }
    if(total<=0) throw std::runtime_error("VTM23 RC unsupported zero intra SATD (upstream numerical domain)");
    rcPic.setTotalIntraCost(total);
    if(m_cfg.m_IntraPeriod!=1 && seq->getLeftAverageBits()<=0)
      throw std::runtime_error("VTM23 RC unsupported nonpositive remaining intra budget (upstream numerical domain)");
    if(m_cfg.m_IntraPeriod!=1)
      rcPic.setTargetBits(std::max(200,rcPic.getRefineBitsForIntra(seq->getLeftAverageBits())));
    rcPic.getLCUInitTargetBits();
  }
  m_picLambda=rcPic.estimatePicLambda(m_rc.getPicList(),m_irap);
  m_picQp=rcPic.estimatePicQP(m_picLambda,m_rc.getPicList());
  m_picQp=std::min(MAX_QP,std::max(-slice.sps->qpBDOffset[CH_L],m_picQp));
  rcPic.setPicEstQP(m_picQp);
  pic.picInitialQP=m_picQp; pic.picInitialLambda=m_picLambda;
  if(m_gaze) m_gaze->begin(pic);
  m_active=true; m_pending=false;
  trace("begin",-1,m_estimatedBits,m_picQp,m_picLambda);
}

Decision Adapter::decideCtu(int ctu)
{
  if(!m_active || m_pending || ctu!=picture().getLCUCoded())
    throw std::logic_error("VTM23 decision issued before ordered CTU feedback");
  auto& rcPic=picture();
  double bpp=rcPic.getLCUTargetBpp(m_irap);
  if(m_gaze)
  {
    const int target=m_gaze->target(ctu,rcPic.getBitsLeft());
    rcPic.getLCU(ctu).m_targetBits=target;
    bpp=double(target)/rcPic.getLCU(ctu).m_numberOfPixel;
  }
  int qp=m_picQp;
  double lambda=m_intra ? rcPic.getLCUEstLambdaAndQP(bpp,m_picQp,&qp) : rcPic.getLCUEstLambda(bpp);
  if(!m_intra) qp=rcPic.getLCUEstQP(lambda,m_picQp);
  qp=std::min(MAX_QP,std::max(-6*(m_cfg.m_internalBitDepth[0]-8),qp));
  if(m_gaze) {const auto applied=m_gaze->optimizeCtu(ctu,lambda,qp);lambda=applied.lambda;qp=applied.qp;}
  if(!std::isfinite(lambda)||lambda<=0) throw std::runtime_error("Non-finite VTM23 CTU lambda");
  m_pending=true;
  trace("decision",ctu,rcPic.getLCU(ctu).m_targetBits,qp,lambda);
  return {rcPic.getLCU(ctu).m_targetBits,qp,lambda};
}

void Adapter::feedbackCtu(int ctu,int bits,int qp,double lambda,double skipRatio,double distortion)
{
  if(!m_active || !m_pending || ctu!=picture().getLCUCoded())
    throw std::logic_error("VTM23 out-of-order CTU feedback");
  auto& rcPic=picture();
  rcPic.getLCU(ctu).m_actualMSE=distortion/rcPic.getLCU(ctu).m_numberOfPixel;
  rcPic.updateAfterCTU(ctu,bits,qp,lambda,skipRatio,!m_irap);
  if(m_gaze) m_gaze->feedback(ctu,bits);
  m_pending=false;
  trace("feedback",ctu,bits,qp,lambda);
}

void Adapter::finishPicture(int poc,int headerBits,int totalBits)
{
  if(!m_active || m_pending || poc!=m_poc || picture().getLCULeft()!=0)
    throw std::logic_error("VTM23 incomplete picture feedback");
  auto& rcPic=picture();
  double avgQP=rcPic.calAverageQP(),avgLambda=rcPic.calAverageLambda();
  if(avgLambda<0) avgLambda=m_picLambda;
  rcPic.updateAfterPicture(headerBits,totalBits,avgQP,avgLambda,m_irap);
  m_rc.getRCSeq()->updateAfterPic(totalBits);
  m_rc.getRCGOP()->updateAfterPicture(m_irap ? m_estimatedBits : totalBits);
  trace("picture",-1,totalBits,int(avgQP+0.5),avgLambda);
  rcPic.addToPictureLsit(m_rc.getPicList());
  if(m_gaze) m_gaze->finish();
  m_active=false;
  if(m_trace.is_open()) { m_trace.flush(); if(!m_trace) throw std::runtime_error("Cannot write VTMRCTrace"); }
}

void Adapter::trace(const char* event,int ctu,int bits,int qp,double lambda)
{
  if(!m_trace.is_open()) return;
  auto& rcPic=picture();
  auto* seq=m_rc.getRCSeq();
  const auto para=seq->getPicPara(rcPic.getFrameLevel());
  const auto model=ctu>=0 ? seq->getLCUPara(rcPic.getFrameLevel(),ctu) : para;
  const double mse=ctu>=0 ? rcPic.getLCU(ctu).m_actualMSE : rcPic.getPicMSE();
  m_trace << event << ',' << m_poc << ',' << ctu << ',' << bits << ',' << qp << ',' << lambda
          << ',' << rcPic.getTargetBits() << ',' << rcPic.getBitsLeft() << ',' << m_rc.getRCGOP()->getBitsLeft()
          << ',' << seq->getBitsLeft() << ',' << model.m_alpha << ',' << model.m_beta << ',' << model.m_validPix
          << ',' << model.m_skipRatio << ',' << mse << '\n';
}
} }
