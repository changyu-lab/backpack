#include "Sibrc/Controller.h"
#include "VtmRcCompat/RateCtrl.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
int main(){try{
 using namespace vvenc::vtmrc;
 GOPEntry entries[MAX_GOP];for(int k=0;k<4;++k){entries[k].m_POC=k+1;entries[k].m_refPic=true;}
 Fraction rate;rate.num=30;rate.den=1;VtmRateCtrl rc;
 rc.init(4,500000,rate,4,32,1024,128,64,64,10,2,true,entries);
 rc.initRCGOP(4);rc.initRCPic(0);auto pic=rc.getRCPic();double total=0;
 for(int k=0;k<pic->getNumberOfLCU();++k){pic->getLCU(k).m_costIntra=1000+123*k;total+=1000+123*k;}
 pic->setTotalIntraCost(total);pic->getLCUInitTargetBits();
 double lambda=pic->estimatePicLambda(rc.getPicList(),true);int qp=pic->estimatePicQP(lambda,rc.getPicList());
 pic->setPicEstQP(qp);pic->setPicEstLambda(lambda);
 vvenc::sibrc::Model model;model.pictureType="I";model.rate={{std::log(100.),-1,0,0,0,0}};model.distortion={{0,1,0,0,0,0}};
 vvenc::sibrc::Controller controller(model);controller.begin(std::vector<double>(pic->getNumberOfLCU(),1),std::vector<double>(pic->getNumberOfLCU(),1),qp);
 for(int k=0;k<pic->getNumberOfLCU();++k){
  int base;double bpp=pic->getLCUTargetBpp(true);double lam=pic->getLCUEstLambdaAndQP(bpp,qp,&base);
  if(base<qp-2||base>qp+2)throw std::runtime_error("real VTM baseline QP drifted out of picture bounds");
  auto d=controller.decide(k,base,lam,pic->getBitsLeft());
  if(d.qp<qp-2||d.qp>qp+2)throw std::runtime_error("applied intra QP breaks real VTM feedback contract");
  pic->getLCU(k).m_actualMSE=10;pic->updateAfterCTU(k,100,d.qp,d.lambda,0,false);
  controller.feedback(100,10);
 }
 std::cout<<"Real VTM + SIBRC intra feedback contract passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
