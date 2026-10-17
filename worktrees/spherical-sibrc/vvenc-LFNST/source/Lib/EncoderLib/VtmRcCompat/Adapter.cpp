// VVenC call-site adapter; the numerical controller lives in RateCtrl.cpp.
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"
#include "EncoderLib/EncCfg.h"
#include "Adapter.h"
#include "IntraCost.h"
#include "../Tpsm/Encoder.h"
#include <cmath>
#include <iomanip>
#include <stdexcept>

namespace vvenc { namespace vtmrc {
Adapter::Adapter(const VVEncCfg& cfg) : m_cfg(cfg)
{
  const int ctus=((cfg.m_PadSourceWidth+cfg.m_CTUSize-1)/cfg.m_CTUSize)*((cfg.m_PadSourceHeight+cfg.m_CTUSize-1)/cfg.m_CTUSize);
  if(cfg.m_vtmDecisionReplay[0])m_replay.reset(new Replay(cfg.m_vtmDecisionReplay,cfg.m_framesToBeEncoded,ctus,cfg.m_vtmProbePOC,cfg.m_vtmProbeCTU,cfg.m_vtmProbeOffset,-6*(cfg.m_internalBitDepth[0]-8)));
  if(cfg.m_vtmDecisionRecord[0]){
    m_decisionRecord.open(cfg.m_vtmDecisionRecord);if(!m_decisionRecord)throw std::runtime_error("Cannot open VTMDecisionRecord");
    m_decisionRecord<<"VTM_REPLAY_V1 "<<cfg.m_framesToBeEncoded<<' '<<ctus<<'\n'<<std::setprecision(17);
  }
  if(cfg.m_sibrcMode>=2)m_sibStats.reset(new sibrc::Statistics(cfg.m_sibrcStats));
  if(cfg.m_sibrcMode==3){
    const std::string prefix=cfg.m_sibrcModel;
    auto intraModel=sibrc::Model::load(prefix+".I"),interModel=sibrc::Model::load(prefix+".P");
    if(intraModel.pictureType!="I"||interModel.pictureType!="P")throw std::runtime_error("SIBRC I/P model identity mismatch");
    m_sibIntra.reset(new sibrc::Controller(intraModel,cfg.m_sibrcMinOffset,cfg.m_sibrcMaxOffset,cfg.m_sibrcBiasRepair));
    m_sibInter.reset(new sibrc::Controller(interModel,cfg.m_sibrcMinOffset,cfg.m_sibrcMaxOffset,cfg.m_sibrcBiasRepair));
  }
  if(cfg.m_sibrcMode>=2){m_sibTrace.open(cfg.m_sibrcTrace);if(!m_sibTrace)throw std::runtime_error("Cannot open SIBRCTrace");
    m_sibTrace<<"poc,ctu,ieff,qp,bits,weighted_mse,area,kind,base_qp,offset,lambda,base_lambda,actual_qp,fallback,rate_bias,dist_bias,pic_left,price,predicted_remaining,predicted_bits,predicted_sse,zero_rate,zero_dist,latitude\n"<<std::setprecision(17);}
  if(cfg.m_sibrcMode==1){m_sibResidual.open(cfg.m_sibrcResidual,std::ios::binary);if(!m_sibResidual)throw std::runtime_error("Cannot open SIBRCResidual");}
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
  if(pic.tpsmController && m_cfg.m_tpsmMode==1){
    int q=std::min(MAX_QP,m_picQp+pic.tpsmController->frameOffset());
    m_picLambda*=std::exp2(double(q-m_picQp)/3.);m_picQp=q;
  }
  if(m_replay){
    if(!slice.isInterP()&&m_poc==m_cfg.m_vtmProbePOC)throw std::runtime_error("VTM probe must target inter picture");
    auto d=m_replay->next(m_poc,-1);m_picQp=d.qp;m_picLambda=d.lambda;
  }
  if(m_decisionRecord.is_open())m_decisionRecord<<m_poc<<" -1 "<<m_picQp<<' '<<m_picLambda<<'\n';
  rcPic.setPicEstQP(m_picQp);
  pic.picInitialQP=m_picQp; pic.picInitialLambda=m_picLambda;
  m_sibPicture=&pic;
  m_sibController=nullptr; // Intra bypass must never reuse a previous inter controller.
  if(m_cfg.m_sibrcMode>0){
    m_sibPicture=&pic;
    m_sibFeatures=sibrc::analysePicture(pic,m_cfg.m_CTUSize,m_sibStats.get(),m_cfg.m_sibrcMode==1?&m_sibResidual:nullptr);
    if(!m_replay&&m_cfg.m_sibrcMode==3&&!(m_intra&&m_cfg.m_sibrcIntraAnchor)){m_sibController=m_intra?m_sibIntra.get():m_sibInter.get();m_sibController->begin(m_sibFeatures.information,m_sibFeatures.area,m_picQp,pic.tpsmController?pic.tpsmController->importance(m_sibFeatures.area):std::vector<double>());}
  }
  m_active=true; m_pending=false;
  trace("begin",-1,m_estimatedBits,m_picQp,m_picLambda);
}

Decision Adapter::decideCtu(int ctu)
{
  if(!m_active || m_pending || ctu!=picture().getLCUCoded())
    throw std::logic_error("VTM23 decision issued before ordered CTU feedback");
  auto& rcPic=picture();
  const double bpp=rcPic.getLCUTargetBpp(m_irap);
  int qp=m_picQp;
  const double lambda=m_intra ? rcPic.getLCUEstLambdaAndQP(bpp,m_picQp,&qp) : rcPic.getLCUEstLambda(bpp);
  if(!m_intra) qp=rcPic.getLCUEstQP(lambda,m_picQp);
  qp=std::min(MAX_QP,std::max(-6*(m_cfg.m_internalBitDepth[0]-8),qp));
  if(!std::isfinite(lambda)||lambda<=0) throw std::runtime_error("Non-finite VTM23 CTU lambda");
  m_pending=true;
  trace("decision",ctu,rcPic.getLCU(ctu).m_targetBits,qp,lambda);
  m_sibBaseQp=m_sibAppliedQp=qp;m_sibBaseLambda=m_sibAppliedLambda=lambda;m_sibOffset=0;m_sibFallback=false;
  if(m_cfg.m_sibrcMode==2&&m_cfg.m_sibrcCalibrationQP>=0){m_sibAppliedQp=m_cfg.m_sibrcCalibrationQP;m_sibAppliedLambda=sibrc::scaleLambda(lambda,m_sibAppliedQp-qp);m_sibOffset=m_sibAppliedQp-qp;}
  if(m_sibController){auto d=m_sibController->decide(ctu,qp,lambda,rcPic.getBitsLeft());m_sibAppliedQp=d.qp;m_sibAppliedLambda=d.lambda;m_sibOffset=d.offset;m_sibFallback=d.fallback;}
  if(m_cfg.m_tpsmMode==1){auto d=m_sibPicture->tpsmController->decide(ctu,m_picLambda);m_sibAppliedQp=d.qp;m_sibAppliedLambda=d.lambda;}
  if(m_replay){auto d=m_replay->next(m_poc,ctu);m_sibAppliedQp=d.qp;m_sibAppliedLambda=d.lambda;}
  if(m_decisionRecord.is_open()){
    m_decisionRecord<<m_poc<<' '<<ctu<<' '<<m_sibAppliedQp<<' '<<m_sibAppliedLambda<<'\n';
    if(!m_decisionRecord)throw std::runtime_error("VTM decision record write failed");
  }
  return {rcPic.getLCU(ctu).m_targetBits,m_sibAppliedQp,m_sibAppliedLambda};
}

void Adapter::feedbackCtu(int ctu,int bits,int qp,double lambda,double skipRatio,double distortion)
{
  if(!m_active || !m_pending || ctu!=picture().getLCUCoded())
    throw std::logic_error("VTM23 out-of-order CTU feedback");
  auto& rcPic=picture();
  rcPic.getLCU(ctu).m_actualMSE=distortion/rcPic.getLCU(ctu).m_numberOfPixel;
  rcPic.updateAfterCTU(ctu,bits,qp,lambda,skipRatio,!m_irap);
  if(m_cfg.m_sibrcMode>=2){
    double wmse=sibrc::weightedCtuMse(*m_sibPicture,ctu,m_cfg.m_CTUSize);
    if(m_sibController)m_sibController->feedback(bits,wmse);
    m_sibTrace<<m_poc<<','<<ctu<<','<<m_sibFeatures.information[ctu]<<','<<m_sibAppliedQp<<','<<bits<<','<<wmse<<','<<m_sibFeatures.area[ctu]<<','<<(m_intra?'I':'P')<<','<<m_sibBaseQp<<','<<m_sibOffset<<','<<m_sibAppliedLambda<<','<<m_sibBaseLambda<<','<<qp<<','<<m_sibFallback<<','<<(m_sibController?m_sibController->rateCorrection():0)<<','<<(m_sibController?m_sibController->distortionCorrection():0)<<','<<rcPic.getBitsLeft();
    auto sd=m_sibController?m_sibController->lastDecision():sibrc::Decision();
    int cols=(m_cfg.m_PadSourceWidth+m_cfg.m_CTUSize-1)/m_cfg.m_CTUSize;
    double centreY=std::min<double>(m_cfg.m_PadSourceHeight,(ctu/cols+1)*m_cfg.m_CTUSize)+(ctu/cols)*m_cfg.m_CTUSize;
    double latitude=std::abs(90-90*centreY/m_cfg.m_PadSourceHeight);
    m_sibTrace<<','<<sd.price<<','<<sd.predictedRemainingBits<<','<<sd.prediction.rate<<','<<sd.prediction.distortion<<','<<(m_sibController?m_sibController->zeroRateSamples():0)<<','<<(m_sibController?m_sibController->zeroDistortionSamples():0)<<','<<latitude<<'\n';
    if(!m_sibTrace)throw std::runtime_error("Cannot write SIBRCTrace");
  }
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
  m_active=false;
  if(m_sibTrace.is_open())m_sibTrace.flush();
  if(m_replay&&m_poc==m_cfg.m_framesToBeEncoded-1)m_replay->finish();
  if(m_decisionRecord.is_open()){m_decisionRecord.flush();if(!m_decisionRecord)throw std::runtime_error("VTM decision record flush failed");}
  if(m_sibResidual.is_open())m_sibResidual.flush();
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
