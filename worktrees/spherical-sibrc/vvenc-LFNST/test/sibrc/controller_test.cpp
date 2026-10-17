#include "Sibrc/Controller.h"
#include <cmath>
#include <fstream>
#include <cstdio>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace vvenc::sibrc;
void check(bool ok,const char* text) { if(!ok) throw std::runtime_error(text); }
bool near(double a,double b) { return std::abs(a-b)<1e-9; }
int main() {
 try {
 check(near(ibWeight(.1,5),0),"IB inactive");
 check(near(ibWeight(.8,5),1),"IB activated");
 check(near(ibWeight(.5,5),.5*std::log2(1.6)),"IB discriminating point"); check(near(ibWeight(.9,5),1.5),"IB high relevance"); check(std::isfinite(ibWeight(1,5)),"IB boundary");
 check(near(scaleLambda(3,3),6),"lambda mapping");
 Model m; m.rate={{std::log(100.),-1,0,0,0,0}}; m.distortion={{0,1,0,0,0,0}};
 auto p=m.predict(1,4,2); check(near(p.rate,100)&&near(p.distortion,2),"model mapping");
 Model poly; poly.rate={{1,2,3,4,5,6}}; poly.distortion=poly.rate;
 double x=std::log(2.), z=std::log(3.);
 check(near(std::log(poly.predict(3,10,1).rate),1+2*x+3*z+4*x*z+5*z*z+6*x*x),"feature order");
 check(std::isfinite(m.predict(0,4,1).rate),"zero information");
 Controller c(m); c.begin({1,1},{1,1},4);
 auto d=c.decide(0,4,3,180); check(!d.fallback&&d.predictedRemainingBits<=180&&d.offset>=0,"feasible budget");
 c.feedback(d.prediction.rate*std::exp(2.),d.prediction.distortion*std::exp(2.));
 check(near(c.rateCorrection(),.2)&&near(c.distortionCorrection(),.2),"first residual");
 d=c.decide(1,4,3,1000);
 c.feedback(d.prediction.rate*std::exp(2.),d.prediction.distortion*std::exp(2.));
 check(near(c.rateCorrection(),.38),"corrected residual update");
 c.begin({1},{1},4); check(c.rateCorrection()==0,"picture reset");
 d=c.decide(0,4,3,1); check(d.fallback&&d.offset==0,"infeasible fallback");
 c.feedback(0,0); check(c.zeroRateSamples()==1&&c.zeroDistortionSamples()==1,"zero samples");
 bool duplicate=false; try { c.feedback(1,1); } catch(const std::logic_error&) {duplicate=true;} check(duplicate,"duplicate feedback");
 Model wrong=m; wrong.rate[1]=1; Controller invalid(wrong); invalid.begin({1},{1},4);
 d=invalid.decide(0,4,3,1000); check(d.offset==0,"invalid monotonic actions");
 Model flat; Controller ties(flat); ties.begin({1},{1},4); d=ties.decide(0,4,1,10); check(d.offset==0,"deterministic baseline tie");
 Controller clipped(m); clipped.begin({1},{1},63); d=clipped.decide(0,63,1,1000); check(d.qp<=63&&d.qp>=-12,"codec range");
 Controller residual(m); residual.begin({1,1},{3,3},4);
 d=residual.decide(0,4,1,1000);
 residual.feedback(d.prediction.rate*std::exp(5.),d.prediction.distortion*std::exp(5.)/3);
 check(near(residual.rateCorrection(),.5)&&near(residual.distortionCorrection(),.5),"residual initial half");
 d=residual.decide(1,4,1,1000);
 residual.feedback(d.prediction.rate*std::exp(2.),d.prediction.distortion*std::exp(2.)/3);
 check(near(residual.rateCorrection(),.65)&&near(residual.distortionCorrection(),.65),"chapter corrected prediction smoothing");
 Controller repaired(m,-2,2,true); std::vector<double> many(160,1.);
 repaired.begin(many,many,4);
 for(std::size_t i=0;i<many.size();++i) {
  d=repaired.decide(i,4,1,1e9);
  auto raw=m.predict(1,d.qp,1);
  repaired.feedback(raw.rate*std::exp(.8),raw.distortion*std::exp(.6));
 }
 check(std::abs(repaired.rateCorrection()-.8)<1e-6,"repaired rate full-bias convergence");
 check(std::abs(repaired.distortionCorrection()-.6)<1e-6,"repaired distortion full-bias convergence");
 repaired.begin({1},{1},4);check(repaired.rateCorrection()==0,"repair picture reset");
 Controller bounds(m); bounds.begin({1},{1},4); d=bounds.decide(0,4,1,1000);
 bounds.feedback(d.prediction.rate*std::exp(100.),d.prediction.distortion*std::exp(100.));
 check(near(bounds.rateCorrection(),std::log(4.)),"correction bound");
 for(double budget=160;budget<=230;budget+=5) {
  Controller budgeted(m);budgeted.begin({1,1},{1,2},4);
  d=budgeted.decide(0,4,1,budget);
  check(!d.fallback&&d.predictedRemainingBits<=budget,"budget grid feasibility");
  check(d.price>=0&&std::isfinite(d.price),"finite nonnegative price");
  budgeted.feedback(d.prediction.rate,d.prediction.distortion);
 }
 Model overflow=m;overflow.rate[0]=1000;Controller guard(overflow);guard.begin({1},{1},4);
 d=guard.decide(0,4,1,1000);check(d.fallback&&d.offset==0,"overflow baseline fallback");guard.feedback(1,1);
 bool mismatch=false;try {c.begin({1},{1,2},4);}catch(const std::invalid_argument&){mismatch=true;}check(mismatch,"feature lengths");
 const char* file="sibrc-model-test.tmp";
 {std::ofstream out(file);out<<"SIBRC_MODEL_V1 picture_type P qp_mapping exp2_qp_minus4_over6 information_floor 1e-12 rate_unit ctu_bits distortion_unit spherical_weighted_mse rate 1 -1 0 0 0 0 distortion 0 1 0 0 0 0";}
 Model loaded=Model::load(file);check(loaded.pictureType=="P"&&loaded.rate[0]==1,"strict model load");
 {std::ofstream out(file,std::ios::app);out<<" extra";}
 bool malformed=false;try {Model::load(file);}catch(const std::runtime_error&){malformed=true;}check(malformed,"trailing model rejection");
 {std::ofstream out(file);out<<"SIBRC_MODEL_V1 picture_type B";}
 malformed=false;try {Model::load(file);}catch(const std::runtime_error&){malformed=true;}check(malformed,"picture type rejection");std::remove(file);
 std::cout<<"SIBRC controller tests passed\n"; return 0;
 } catch(const std::exception& e) {std::cerr<<e.what()<<"\n"; return 1;}
}


