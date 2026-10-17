#include "Tpsm/Model.h"
#include <cmath>
#include <stdexcept>
#include <iostream>
using namespace vvenc::tpsm;
void require(bool b){if(!b)throw std::runtime_error("TPSM assertion failed");}
void near(double a,double b){require(std::abs(a-b)<1e-10);}
int main(){
 History h(4); std::vector<Moments> m(1, Moments{10,20,64});
 for(int i=0;i<4;++i){auto w=h.begin(i,m,false); near(w.temporal[0],i==0?0:i==1?.5:i==2?.75:.875);h.finish({Observation{50,100,64}});}
 auto w=h.begin(4,m,false);near(w.temporal[0],.9375);h.finish({Observation{0,0,0}});
 w=h.begin(5,m,false);near(w.temporal[0],0);h.finish({Observation{50,100,64}});
 History a(0);a.begin(0,m,false);a.finish({Observation{80,100,64}});
 auto changed=m;changed[0].variance+=5;w=a.begin(1,changed,false);require(w.chain[0]==4);a.finish({Observation{80,100,64}});
 changed[0].variance+=5.01;w=a.begin(2,changed,false);require(w.chain[0]==1);a.finish({Observation{80,100,64}});
 changed[0].mean+=41;w=a.begin(3,changed,false);require(!w.sceneReset);a.finish({Observation{80,100,64}});
 changed[0].mean+=41;changed[0].variance+=16;w=a.begin(4,changed,false);require(w.sceneReset);near(w.temporal[0],0);a.finish({Observation{80,100,64}});
 auto neutral=temporalImportance({0,4},{1,3},0);near(neutral[0],1);near(neutral[1],1);auto strong=temporalImportance({0,1},{1,1},4);near(strong[0],1./3);near(strong[1],5./3);
 auto v=normalizeImportance({1,3},{1,3});near(v[0],.4);near(v[1],1.2);
 near(spatialWeight(0,64,128),std::cos(3.14159265358979323846/4));
 auto d=paperDecision(20,1,1,10);near(d.lambda,10);require(d.qp==10);
 require(frameQpOffset(.7)==0);require(frameQpOffset(.8)==2);require(frameQpOffset(1.2)==2);
 History b(4);b.begin(0,m,false);b.finish({Observation{200,100,64}});w=b.begin(1,m,false);near(w.temporal[0],2);b.finish({Observation{1,0,64}});w=b.begin(2,m,false);near(w.temporal[0],0);b.finish({Observation{1,1,64}});
 History mixed(4);mixed.begin(0,m,false);mixed.finish({Observation{16,32,32}});auto mw=mixed.begin(1,m,false);near(mw.temporal[0],0);near(mw.kappa,.5);mixed.finish({Observation{1,1,64}});
 bool caught=false;try{b.finish({Observation{1,1,64}});}catch(const std::logic_error&){caught=true;}require(caught);
 std::cout<<"TPSM arithmetic/history checks passed\n";
}
