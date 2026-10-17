#include "EncoderLib/VtmRcCompat/VisualGaze.h"
#include <cmath>
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace vvenc::gaze;
void check(bool v,const char* s) { if(!v) throw std::runtime_error(s); }
template<class F> void rejects(F f) { bool yes=false; try { f(); } catch(const std::exception&) {yes=true;} check(yes,"invalid input accepted"); }
int main() { try {
  Geometry g{128,130,64,10,2};
  check(std::abs(latitude(0,130)-latitude(129,130))<1e-12,"latitude symmetry");
  check(latitude(64,130)>.999,"equator");
  auto li=stripLatitudes(g);check(li.size()==3 && li[1]>li[0] && li[2]>0,"partial CTU latitude");
  StripBudget b(2,{1,1,1,1},{1,3});
  check(b.target(0,800)==100,"literal latitude allocation");
  rejects([&]{b.target(1,800);});b.feedback(120);
  check(b.target(1,680)==80,"strip feedback");b.feedback(90);
  check(b.target(2,590)==443,"new strip uses frame remaining");b.feedback(400);
  check(b.target(3,190)==485,"same strip retains own budget");b.feedback(500);
  rejects([&]{b.feedback(1);});
  auto key=optimize(100,33,.5,true,false,10);check(key.rawLambda==50 && key.qp>=31 && key.qp<=35,"key Eq16");
  auto low=optimize(100,33,.5,false,false,10);check(low.rawLambda==200,"low complexity Eq16");
  auto high=optimize(100,33,.5,false,true,10);check(high.lambda==100 && high.qp==33,"high complexity identity");
  auto identity=optimize(100,33,1,true,false,10);check(identity.lambda==100 && identity.qp==33,"f=0 identity");
  StripBudget flat(2,{0,0,0,0},{1,1},{64,32,64,32});
  check(flat.target(0,600)==200,"zero-feature pixel fallback");flat.feedback(50);
  check(flat.target(1,550)==250,"zero-feature remaining pixels");
  rejects([&]{optimize(100,33,0,true,false,10);});
  short inverse[64]={0};inverse[50]=100;
  check(sampleError(100,50,inverse)==0,"LMCS original-domain dependency");
  check(sampleError(100,50,nullptr)==2500,"unmapped sample error");
  check(std::abs(dependency(2,.1,.5,.2,1)-1./1.5)<1e-12,"dependency Eq30");
  std::istringstream features("VGFEATURES 1 128 130 64 10 2\n0 0 1 2\n0 1 2 3\n0 2 3 4\n0 3 4 5\n0 4 5 6\n0 5 6 7\n1 0 1 2\n1 1 2 3\n1 2 3 4\n1 3 4 5\n1 4 5 6\n1 5 6 7\n");
  Features f(features,g);check(f.at(1,false).at(5)==7,"features POC selection");
  std::istringstream bad("VGFEATURES 1 128 130 64 10 2\n0 0 1 2\n"); rejects([&]{Features missing(bad,g);});
  std::ostringstream gaze;gaze<<"VGGAZE 1 128 130 64 10 2 49\n";
  for(int p=0;p<2;++p)for(int o=0;o<49;++o) gaze<<p<<' '<<o<<" 0.5 1\n";
  std::istringstream paths(gaze.str());Gaze points(paths,g);
  check(points.key(0,2) && !points.key(0,3),"longitude wraps at x=1");
  std::cout<<"PASS visual gaze formulas, ordered budgets, strict inputs\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;} }
