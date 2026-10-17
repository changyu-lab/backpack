// Replay the first real IRAP using the original kernel and identical actual feedback.
#include <fstream>
#include <iomanip>
#include <stdexcept>
#include <cmath>
#include <iostream>
#ifdef VTM_REFERENCE
#include "EncoderLib/RateCtrl.h"
MsgLevel g_verbosity = SILENT;
using Kernel = RateCtrl;
#else
#include "VtmRcCompat/RateCtrl.h"
using namespace vvenc::vtmrc;
using Kernel = VtmRateCtrl;
#endif
int main(int argc,char** argv) {
 try {
  if(argc!=3) throw std::runtime_error("fixture output required");
  std::ifstream in(argv[1]);std::ofstream out(argv[2]);out<<std::setprecision(17);
  int rate=0,width=0,height=0,frames=0,ctu=0,fps=0;in>>rate>>width>>height>>frames>>ctu>>fps;
  if(!in || !out || rate<=0 || width<=0 || height<=0 || frames<=0 || ctu<=0 || fps<=0) throw std::runtime_error("invalid fixture header/output");
  GOPEntry entries[MAX_GOP];for(int i=0;i<8;++i){entries[i].m_POC=i+1;entries[i].m_refPic=true;}
  Fraction fraction;fraction.num=fps;fraction.den=1;
  Kernel rc;rc.init(frames,rate,fraction,8,-1,width,height,ctu,ctu,10,2,true,entries);
  rc.initRCGOP(1);rc.initRCPic(0);auto* pic=rc.getRCPic();double total=0;
  const int estimated=pic->getTargetBits();
  for(int k=0;k<pic->getNumberOfLCU();++k){double cost;in>>cost;if(!in || !std::isfinite(cost) || cost<0) throw std::runtime_error("invalid SATD data");pic->getLCU(k).m_costIntra=cost;total+=cost;}
  if(total<=0 || rc.getRCSeq()->getLeftAverageBits()<=0) throw std::runtime_error("invalid original intra numeric domain");
  pic->setTotalIntraCost(total);
  pic->setTargetBits(std::max(200,pic->getRefineBitsForIntra(rc.getRCSeq()->getLeftAverageBits())));
  pic->getLCUInitTargetBits();double lambda=pic->estimatePicLambda(rc.getPicList(),true);
  int qp=pic->estimatePicQP(lambda,rc.getPicList());qp=std::max(-12,std::min(63,qp));pic->setPicEstQP(qp);
  out<<"I "<<estimated<<' '<<pic->getTargetBits()<<' '<<qp<<' '<<pic->getBitsLeft()<<' '<<rc.getRCSeq()->getBitsLeft()<<'\n';
  out<<"D "<<lambda<<'\n';
  for(int k=0;k<pic->getNumberOfLCU();++k){
   double bpp=pic->getLCUTargetBpp(true);int cq=qp;double cl=pic->getLCUEstLambdaAndQP(bpp,qp,&cq);
   cq=std::max(-12,std::min(63,cq));
   out<<"I "<<k<<' '<<pic->getLCU(k).m_targetBits<<' '<<cq<<' '<<pic->getBitsLeft()<<'\n';out<<"D "<<cl<<'\n';
   int bits,actualQp;double actualLambda,skip,mse;in>>bits>>actualQp>>actualLambda>>skip>>mse;
   if(!in) throw std::runtime_error("truncated fixture");
   pic->getLCU(k).m_actualMSE=mse;pic->updateAfterCTU(k,bits,actualQp,actualLambda,skip,false);
   out<<"I "<<k<<' '<<pic->getBitsLeft()<<'\n';
   auto model=rc.getRCSeq()->getLCUPara(0,k);out<<"D "<<model.m_alpha<<' '<<model.m_beta<<'\n';
  }
  return !out;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
