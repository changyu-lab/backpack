#include "EncoderLib/EncCfg.h"
#include "EncoderLib/VtmRcCompat/Adapter.h"
#include "EncoderLib/VtmRcCompat/IntraCost.h"
#include "CommonLib/Picture.h"
#include <iostream>
#include <vector>
#include <memory>
#include <stdexcept>
using namespace vvenc;
static void require(bool ok,const char* what) { if(!ok) throw std::runtime_error(what); }
template<class F> static void rejects(F fn,const char* what) {
 bool rejected=false;try { fn(); } catch(const std::logic_error&) { rejected=true; }
 require(rejected,what);
}
int main() {
 try {
  VVEncCfg cfg;vvenc_config_default(&cfg); cfg.m_SourceWidth=cfg.m_PadSourceWidth=128; cfg.m_SourceHeight=cfg.m_PadSourceHeight=96;
  cfg.m_CTUSize=64;cfg.m_GOPSize=1;cfg.m_IntraPeriod=32;cfg.m_framesToBeEncoded=4;
  cfg.m_vtmRcTargetBitrate=30000;cfg.m_vtmRcKeepHierBits=0;cfg.m_vtmRcTrace[0]=0;
  cfg.m_FrameRate=30;cfg.m_FrameScale=1;cfg.m_internalBitDepth[0]=10;
  cfg.m_GOPList[0].m_POC=1;cfg.m_GOPList[0].m_numRefPics[0]=cfg.m_GOPList[0].m_numRefPics[1]=0;
  vtmrc::Adapter rc(cfg);
  rejects([&]{rc.decideCtu(0);},"decision before picture accepted");
  rejects([&]{rc.feedbackCtu(0,1,32,1,0,1);},"feedback without decision accepted");
  std::unique_ptr<SPS> sps(new SPS); sps->bitDepths.recon[CH_L]=10;sps->qpBDOffset[CH_L]=12;
  Picture pic;pic.poc=1;pic.create(CHROMA_420,Size(128,96),64,0,false);
  Slice* slice=new Slice;pic.slices.push_back(slice);slice->pic=&pic;slice->sps=sps.get();slice->sliceType=VVENC_P_SLICE;
  slice->nalUnitType=VVENC_NAL_UNIT_CODED_SLICE_TRAIL;slice->TLayer=0;
  rc.beginPicture(pic);
  auto decision=rc.decideCtu(0);
  rejects([&]{rc.decideCtu(1);},"second decision before feedback accepted");
  rejects([&]{rc.feedbackCtu(1,10,decision.qp,decision.lambda,0,100);},"out-of-order feedback accepted");
  rejects([&]{rc.finishPicture(1,10,100);},"unfinished picture accepted");
  const int before=rc.picture().getBitsLeft();
  rc.feedbackCtu(0,10,decision.qp,decision.lambda,0,100);
  require(rc.picture().getBitsLeft()==before-10,"feedback debit mismatch");
  rejects([&]{rc.feedbackCtu(0,10,decision.qp,decision.lambda,0,100);},"duplicate feedback accepted");
  for(int i=1;i<rc.picture().getNumberOfLCU();++i) {
   decision=rc.decideCtu(i);rc.feedbackCtu(i,10,decision.qp,decision.lambda,0,100);
  }
  rc.finishPicture(1,10,100);require(!rc.active(),"picture remains active");
  std::vector<Pel> constant(64,128);
  require(vtmrc::intraCost(CPelBuf(constant.data(),8,8,8))==0,"DC not removed in original intra cost");
  std::cout << "PASS: ordered adapter feedback guards and original intra DC removal\n";
  return 0;
 } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
