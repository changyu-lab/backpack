#include "Sibrc/Controller.h"
#include <cmath>
#include <algorithm>
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
 // VTM intra feedback assumes every previous QP stays in picture QP +/-2.
 Model intra=m;intra.pictureType="I";Controller intraLow(intra);
 intraLow.begin({1},{1},28);auto safe=intraLow.decide(0,26,1,1000);
 check(safe.qp>=26&&safe.qp<=30,"intra action must preserve VTM picture QP feedback interval");
 Controller intraHigh(intra);intraHigh.begin({1},{1},28);
 safe=intraHigh.decide(0,30,1,intra.predict(1,31,1).rate);
 check(safe.fallback&&safe.qp==30,"intra budget cannot authorize unsafe upper QP");
 Controller interSame(m);interSame.begin({1},{1},28);
 safe=interSame.decide(0,26,1,1000);check(safe.qp==24,"P actions retain existing range");
 Controller intraChain(intra);intraChain.begin(std::vector<double>(12,1),std::vector<double>(12,1),28);
 int previous=28;
 for(int k=0;k<12;++k){
  int lo=std::max(26,previous-1),hi=std::min(30,previous+1);
  check(lo<=hi,"VTM intra neighbour/picture intersection stays nonempty");
  safe=intraChain.decide(k,lo,1,1000);
  intraChain.feedback(safe.prediction.rate,safe.prediction.distortion);previous=safe.qp;
 }
 for(int pictureQP : {-12,63}){
  Controller endpoint(intra);endpoint.begin({1},{1},pictureQP);
  safe=endpoint.decide(0,pictureQP,1,1000);
  check(safe.qp>=-12&&safe.qp<=63&&std::abs(safe.qp-pictureQP)<=2,"intra legal QP endpoints");
 }
 bool baselineRejected=false;Controller rejectIntra(intra);rejectIntra.begin({1},{1},28);
 try{rejectIntra.decide(0,25,1,1000);}catch(const std::logic_error&){baselineRejected=true;}
 check(baselineRejected,"out-of-range intra baseline rejected explicitly");
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
 {std::ofstream out(file);out<<"SIBRC_MODEL_V2 picture_type P qp_mapping exp2_qp_minus4_over6 feature_selector 2 information_scale 4 information_floor 1e-12 rate_unit ctu_bits distortion_unit spherical_weighted_mse rate 1 -1 1 0 0 0 distortion 0 1 1 0 0 0";} Model normalized=Model::load(file); check(near(normalized.predict(4,4,2).rate,std::exp(1.)),"V2 normalized scale"); Model bounded=normalized; bounded.informationScale=1; Controller c2(normalized),c3(bounded); c2.begin({0,4,8},{1,2,3},28); c3.begin({0,1,2},{1,2,3},28); for(int k=0;k<3;++k){auto da=c2.decide(k,28,1,1000),db=c3.decide(k,28,1,1000); check(da.qp==db.qp&&da.offset==db.offset&&da.fallback==db.fallback&&near(da.lambda,db.lambda),"C2 C3 controller replay"); c2.feedback(da.prediction.rate,da.prediction.distortion/(k+1)); c3.feedback(db.prediction.rate,db.prediction.distortion/(k+1));} std::remove(file); std::cout<<"SIBRC controller tests passed\n"; return 0;
 } catch(const std::exception& e) {std::cerr<<e.what()<<"\n"; return 1;}
}
