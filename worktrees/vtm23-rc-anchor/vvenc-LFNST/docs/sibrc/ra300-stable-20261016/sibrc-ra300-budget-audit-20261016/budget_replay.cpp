#include <fstream>
#include <iostream>
#include <iomanip>
#ifdef VTM_REFERENCE
#include "EncoderLib/RateCtrl.h"
MsgLevel g_verbosity=SILENT;
using Seq=EncRCSeq;
#else
#include "VtmRcCompat/RateCtrl.h"
using namespace vvenc::vtmrc;
using Seq=VtmRcSeq;
#endif
int main(int argc,char**argv){
 if(argc!=3)return 2;
 std::ifstream in(argv[1]);std::ofstream out(argv[2]);
 int rate,frames,w,h,fps,count;in>>rate>>frames>>w>>h>>fps>>count;
 Fraction f;f.num=fps;f.den=1;Seq s;s.create(frames,rate,f,32,32,w,h,128,128,8,true,0);
 out<<"INIT "<<s.getTargetBits()<<' '<<s.getFramesLeft()<<' '<<s.getBitsLeft()<<' '<<s.getLeftAverageBits()<<'\n';
 for(int i=0;i<count;++i){int poc,bits;in>>poc>>bits;s.updateAfterPic(bits);out<<poc<<' '<<s.getFramesLeft()<<' '<<s.getBitsLeft()<<' ';if(s.getFramesLeft()>0)out<<s.getLeftAverageBits();else out<<"END";out<<'\n';}
 return !in||!out;
}
