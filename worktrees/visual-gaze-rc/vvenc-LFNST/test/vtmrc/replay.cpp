#include <fstream>
#include <iomanip>
#include <string>
#ifdef VTM_REFERENCE
#include "EncoderLib/RateCtrl.h"
MsgLevel g_verbosity = SILENT;
using Kernel = RateCtrl;
#else
#include "VtmRcCompat/RateCtrl.h"
using namespace vvenc::vtmrc;
using Kernel = VtmRateCtrl;
#endif
int main(int argc, char** argv) {
 std::ofstream out(argv[1]); out << std::setprecision(17) << std::unitbuf;
 for (int scenario=0; scenario<8; ++scenario) {
  const int gopSize=(scenario&1)?8:4;
  GOPEntry entries[MAX_GOP];
  int ra[8]={8,4,2,1,3,6,5,7};
  for(int i=0;i<gopSize;++i) { entries[i].m_POC=gopSize==8?ra[i]:i+1; entries[i].m_refPic=gopSize==4 || (i==0||i==1||i==2||i==5); }
  Kernel rc; Fraction rate; rate.num=30000; rate.den=1001;
  rc.init(2*gopSize,(scenario&2)?800:500000,rate,gopSize,32,130,98,64,64,10,2,true,entries);
  auto s=rc.getRCSeq();
  auto dumpSeq = [&]() {
   out << "I " << s->getAdaptiveBits();
   for(int i=0;i<gopSize;++i) out << ' ' << s->getBitRatio(i);
   out << '\n' << "D " << s->getLastLambda() << '\n';
  };
  dumpSeq();
  out << "I " << scenario << ' ' << s->getTargetBits() << ' ' << s->getAverageBits()  << '\n';
  for(int group=0;group<2;++group) {
   rc.initRCGOP(gopSize); auto g=rc.getRCGOP(); dumpSeq();
   out << "I " << scenario << ' ' << g->getTargetBits() << ' ' << g->getBitsLeft() << '\n';
   for(int frame=0;frame<gopSize;++frame) {
    bool intra=group==0 && frame==0;
    int level=intra?0:s->getGOPID2Level(frame); rc.initRCPic(level); auto p=rc.getRCPic();
    double cost=0;
    for(int c=0;c<p->getNumberOfLCU();++c) { p->getLCU(c).m_costIntra=1000+123*c; cost+=1000+123*c; }
    p->setTotalIntraCost(cost); p->getLCUInitTargetBits();
    double lam=p->estimatePicLambda(rc.getPicList(),intra); int qp=p->estimatePicQP(lam,rc.getPicList()); p->setPicEstQP(qp); p->setPicEstLambda(lam);
    out << "I " << scenario << ' ' << p->getTargetBits() << ' ' << qp << ' ' << p->getBitsLeft() << ' ' << p->getLowerBound() << '\n';
    out << "D " << lam << '\n';
    int bits=0;
    for(int c=0;c<p->getNumberOfLCU();++c) {
     double bpp=p->getLCUTargetBpp(intra); int cq; double cl;
     if(intra) cl=p->getLCUEstLambdaAndQP(bpp,qp,&cq); else { cl=p->getLCUEstLambda(bpp); cq=p->getLCUEstQP(cl,qp); }
     int cb=25+((scenario*19+frame*11+c*7)%91); bits+=cb; p->getLCU(c).m_actualMSE=10+c;
     p->updateAfterCTU(c,cb,cq,cl,0.1*c,(scenario&4)!=0 && (c&1)==0);
     out << "I " << c << ' ' << cq << ' ' << p->getLCU(c).m_numberOfPixel << ' ' << p->getLCU(c).m_targetBits << ' ' << p->getBitsLeft() << ' ' << p->getPixelsLeft() << '\n';
     out << "D " << bpp << ' ' << cl << '\n';
     auto& state=p->getLCU(c);
     out << "I " << state.m_actualBits << ' ' << state.m_QP << ' ' << state.m_targetBitsLeft << '\n';
     out << "D " << state.m_lambda << ' ' << state.m_actualSSE << ' ' << state.m_actualMSE << '\n';
     if(s->getUseLCUSeparateModel()) { auto a=s->getLCUPara(level,c); out << "I " << a.m_validPix << '\n'; out << "D " << a.m_alpha << ' ' << a.m_beta << ' ' << a.m_skipRatio << '\n'; }
    }
    double aq=p->calAverageQP(), al=p->calAverageLambda(); p->setPicMSE(12.5); p->updateAfterPicture(17,bits+17,aq,al,intra);
    s->updateAfterPic(bits+17); g->updateAfterPicture(bits+17);
    auto a=s->getPicPara(level); dumpSeq(); out << "I " << a.m_validPix << '\n';
    out << "I " << s->getFramesLeft() << ' ' << s->getBitsLeft() << ' ' << g->getPicLeft() << ' ' << g->getBitsLeft() << ' ' << p->getPicActualBits() << ' ' << p->getPicActualQP() << '\n';
    out << "D " << aq << ' ' << al << ' ' << a.m_alpha << ' ' << a.m_beta << ' ' << a.m_skipRatio << '\n';
    p->addToPictureLsit(rc.getPicList());
   }
   rc.destroyRCGOP();
  }
 }
 return !out;
}
