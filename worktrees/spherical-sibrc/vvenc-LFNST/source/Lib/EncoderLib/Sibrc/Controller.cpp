#include "Controller.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <stdexcept>
namespace vvenc { namespace sibrc {
namespace {
const double ln2=std::log(2.);
int clipQP(int q) {return std::max(-12,std::min(63,q));}
bool finitePositive(double v) {return std::isfinite(v)&&v>0;}
bool preferred(int a,int b) {
 if(a==0||b==0) return a==0&&b!=0;
 return std::abs(a)!=std::abs(b)?std::abs(a)<std::abs(b):a>b;
}
void token(std::istream& s,const char* expected) {
 std::string v; if(!(s>>v)||v!=expected) throw std::runtime_error(std::string("Invalid SIBRC model token: ")+expected);
}
}
double ibWeight(double rho,double beta) {
 if(!std::isfinite(rho)||!std::isfinite(beta)||beta<=1||rho<=1/beta) return 0;
 rho=std::min(rho,1-1e-6);
 return std::max(0.,.5*std::log2((1-1/beta)/(1-rho)));
}
double scaleLambda(double lambda,int offset) {
 if(!finitePositive(lambda)) throw std::invalid_argument("Invalid baseline lambda");
 return lambda*std::exp2(double(offset)/3);
}
Model Model::load(const std::string& path) {
 std::ifstream s(path); if(!s) throw std::runtime_error("Cannot open SIBRC model: "+path);
 Model m; token(s,"SIBRC_MODEL_V1"); token(s,"picture_type");
 if(!(s>>m.pictureType)||(m.pictureType!="I"&&m.pictureType!="P")) throw std::runtime_error("Invalid picture type");
 token(s,"qp_mapping"); token(s,"exp2_qp_minus4_over6");
 token(s,"information_floor"); double floor; if(!(s>>floor)||floor!=1e-12) throw std::runtime_error("Invalid information floor");
 token(s,"rate_unit"); token(s,"ctu_bits"); token(s,"distortion_unit"); token(s,"spherical_weighted_mse");
 token(s,"rate"); for(auto& v:m.rate) if(!(s>>v)||!std::isfinite(v)) throw std::runtime_error("Invalid rate coefficient");
 token(s,"distortion"); for(auto& v:m.distortion) if(!(s>>v)||!std::isfinite(v)) throw std::runtime_error("Invalid distortion coefficient");
 std::string extra; if(s>>extra) throw std::runtime_error("Trailing SIBRC model data");
 return m;
}
Prediction Model::predict(double info,int qp,double area) const {
 Prediction p;
 if(!std::isfinite(info)||info<0||!finitePositive(area)) return p;
 const double x=(qp-4)*ln2/6,z=std::log(std::max(info,1e-12));
 const double f[6]={1,x,z,x*z,z*z,x*x}; double r=0,d=0;
 for(int i=0;i<6;++i) {r+=rate[i]*f[i];d+=distortion[i]*f[i];}
 p.rate=std::exp(r); p.distortion=std::exp(d)*area;
 return p;
}
Controller::Controller(const Model& m,int a,int b,bool repairBias):m_repairBias(repairBias),m_model(m),m_min(a),m_max(b) {
 if(a>0||b<0||a>b||a<-75||b>75) throw std::invalid_argument("Invalid SIBRC offset range");
}
void Controller::begin(const std::vector<double>& info,const std::vector<double>& area,int qp,const std::vector<double>& temporal) {
 if(info.size()!=area.size()) throw std::invalid_argument("SIBRC feature size mismatch");
 for(std::size_t i=0;i<info.size();++i)
  if(!std::isfinite(info[i])||info[i]<0||!finitePositive(area[i])) throw std::invalid_argument("Invalid SIBRC features");
 if(!temporal.empty()&&temporal.size()!=info.size()) throw std::invalid_argument("SIBRC temporal size mismatch");
 for(double v:temporal)if(!finitePositive(v))throw std::invalid_argument("Invalid SIBRC temporal weight");
 m_temporal=temporal.empty()?std::vector<double>(info.size(),1.):temporal;
 m_ieff=info;m_area=area;m_pictureQP=clipQP(qp);m_deltaR=m_deltaD=0;m_zeroR=m_zeroD=0;m_pending=false;
}
Decision Controller::decide(std::size_t ctu,int qp,double lambda,double budget) {
 if(m_pending) throw std::logic_error("SIBRC feedback missing");
 if(ctu>=m_ieff.size()) throw std::out_of_range("SIBRC CTU index");
 qp=clipQP(qp); scaleLambda(lambda,0);
 struct Action {int offset;Prediction p;};
 std::vector<std::vector<Action>> actions;
 bool valid=true;
 for(std::size_t i=ctu;i<m_ieff.size();++i) {
  int base=i==ctu?qp:m_pictureQP;
  auto prediction=[&](int q) {Prediction p=m_model.predict(m_ieff[i],q,m_area[i]);p.rate*=std::exp(m_deltaR);p.distortion*=std::exp(m_deltaD);return p;};
  Prediction p0=prediction(base);
  std::vector<Action> a; a.push_back({0,p0});
  if(!finitePositive(p0.rate)||!finitePositive(p0.distortion)) valid=false;
  for(int off=m_min;off<=m_max;++off) {
   if(off==0||base+off<-12||base+off>63) continue;
   Prediction p=prediction(base+off);
   if(finitePositive(p.rate)&&finitePositive(p.distortion)&&off*(p.rate-p0.rate)<0&&off*(p.distortion-p0.distortion)>0) a.push_back({off,p});
  }
  actions.push_back(a);
 }
 auto select=[&](double price,std::vector<Action>& selected) {
  selected.clear();double total=0;
  std::size_t index=ctu;
  for(const auto& a:actions) {
   const double weight=m_temporal[index++];
   Action best=a[0];double score=weight*best.p.distortion+price*best.p.rate;
   for(const auto& candidate:a) {
    double value=weight*candidate.p.distortion+price*candidate.p.rate;
    if(value<score||(value==score&&preferred(candidate.offset,best.offset))) {best=candidate;score=value;}
   }
   selected.push_back(best);total+=best.p.rate;
  }return total;
 };
 std::vector<Action> selected;
 double price=0,total=select(0,selected);
 bool fallback=!valid||!std::isfinite(budget)||budget<0;
 if(!fallback&&total>budget) {
  double minimum=0;for(const auto& a:actions) {double r=a[0].p.rate;for(const auto& v:a)r=std::min(r,v.p.rate);minimum+=r;}
  if(minimum>budget) fallback=true;
  else {
   double lo=0,hi=1;std::vector<Action> feasible;
   int k=0;while(select(hi,feasible)>budget&&k++<100) hi*=2;
   if(select(hi,feasible)>budget) fallback=true;
   else {
    selected=feasible;total=select(hi,selected);price=hi;
    for(int n=0;n<80;++n) {
     double mid=(lo+hi)/2;std::vector<Action> trial;double r=select(mid,trial);
     if(r<=budget) {hi=mid;selected=trial;total=r;price=mid;} else lo=mid;
    }
   }
  }
 }
 if(fallback) {selected.clear();total=0;for(const auto& a:actions) {selected.push_back(a[0]);total+=a[0].p.rate;}price=0;}
 m_last=Decision();m_last.offset=selected[0].offset;m_last.qp=qp+m_last.offset;
 m_last.lambda=scaleLambda(lambda,m_last.offset);m_last.prediction=selected[0].p;
 m_last.deltaRate=m_deltaR;m_last.deltaDistortion=m_deltaD;m_last.price=price;
 m_last.predictedRemainingBits=total;m_last.fallback=fallback;m_ctu=ctu;m_pending=true;
 return m_last;
}
void Controller::feedback(double bits,double mse) {
 if(!m_pending) throw std::logic_error("SIBRC feedback has no pending decision");
 auto update=[this](double actual,double predicted,double& delta,std::size_t& zeros) {
  if(!finitePositive(actual)||!finitePositive(predicted)) {++zeros;return;}
  // predicted already includes exp(delta): adding its residual converges to full raw bias.
  // Keep the historical extra decay only for the default reproduction path.
  double residual=std::log(actual)-std::log(predicted);
  delta=std::max(-std::log(4.),std::min(std::log(4.),(m_repairBias?delta:.9*delta)+.1*residual));
 };
 update(bits,m_last.prediction.rate,m_deltaR,m_zeroR);
 update(mse*m_area[m_ctu],m_last.prediction.distortion,m_deltaD,m_zeroD);
 m_pending=false;
}
}}


