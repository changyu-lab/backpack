#include "Model.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <limits>
namespace vvenc { namespace tpsm {
namespace {const double pi=3.14159265358979323846;
bool positive(double x){return std::isfinite(x)&&x>0;}
Moments combine(const std::vector<Moments>& m){double n=0,s=0,ss=0;for(auto a:m){n+=a.pixels;s+=a.mean*a.pixels;ss+=(a.variance+a.mean*a.mean)*a.pixels;}return {s/n,std::max(0.,ss/n-(s/n)*(s/n)),n};}
}
double spatialWeight(int y,int h,int height){if(y<0||h<=0||height<=0||y+h>height)throw std::invalid_argument("Invalid TPSM geometry");return std::cos(pi*((y+.5*h)/height-.5));}
Decision paperDecision(double lambda,double spatial,double temporal,int depth){
 if(!positive(lambda)||!positive(spatial)||!std::isfinite(temporal)||temporal<0||depth<8||depth>16)throw std::invalid_argument("Invalid TPSM decision");
 double l=lambda/(spatial*(1+temporal));if(!positive(l))throw std::overflow_error("TPSM lambda overflow");
 double q=std::floor(4.5499*std::log(l)-.0956+.5);return {int(std::max(double(-6*(depth-8)),std::min(63.,q))),l};
}
int frameQpOffset(double k){if(!std::isfinite(k)||k<=.7)return 0;double x=10*std::abs(1-k),nearest=std::round(x);if(std::abs(x-nearest)<=8*std::numeric_limits<double>::epsilon()*std::max(1.,x))x=nearest;return int(std::min(75.,std::floor(x)));}
std::vector<double> normalizeImportance(const std::vector<double>& h,const std::vector<double>& a){
 if(h.size()!=a.size()||h.empty())throw std::invalid_argument("Invalid TPSM importance size");
 double sum=0,area=0;for(size_t i=0;i<h.size();++i){if(!positive(h[i])||!positive(a[i]))throw std::invalid_argument("Invalid TPSM importance");sum+=h[i]*a[i];area+=a[i];}
 if(!positive(sum)||!positive(area))throw std::overflow_error("TPSM importance overflow");auto v=h;for(auto& x:v)x/=sum/area;return v;
}
std::vector<double> temporalImportance(const std::vector<double>& temporal,const std::vector<double>& area,double strength){
 if(!std::isfinite(strength)||strength<0||strength>4)throw std::invalid_argument("TPSM strength must be in [0,4]");
 auto h=temporal;for(auto& v:h){if(!std::isfinite(v)||v<0)throw std::invalid_argument("Invalid TPSM temporal weight");v=1+strength*v;}
 return normalizeImportance(h,area);
}
History::History(int chain):m_chain(chain){if(chain!=0&&chain!=1&&chain!=4)throw std::invalid_argument("TPSM chain must be 0,1,4");}
Weights History::begin(int poc,const std::vector<Moments>& moments,bool intra){
 if(m_pending||poc!=m_lastPoc+1||moments.empty())throw std::logic_error("TPSM pictures must be completed in POC order");
 for(auto m:moments)if(!std::isfinite(m.mean)||!std::isfinite(m.variance)||m.variance<0||!positive(m.pixels))throw std::invalid_argument("Invalid TPSM moments");
 if(!m_previous.empty()&&moments.size()!=m_previous.size())throw std::invalid_argument("TPSM picture geometry changed");
 Weights w;w.temporal.assign(moments.size(),0);w.chain.assign(moments.size(),m_chain?m_chain:4);
 if(!m_previous.empty()){auto a=combine(m_previous),b=combine(moments);w.sceneReset=std::abs(a.mean-b.mean)>40&&std::abs(a.variance-b.variance)>15;}
 if(intra||w.sceneReset){m_beta.clear();m_kappa=0;}
 w.kappa=m_kappa;
 for(size_t r=0;r<moments.size();++r){
  if(!m_chain&&!m_previous.empty()&&std::abs(moments[r].variance-m_previous[r].variance)>5)w.chain[r]=1;
  double product=1;int count=0;for(auto& frame:m_beta){if(count++>=w.chain[r]||frame[r]<0)break;product*=frame[r];if(!std::isfinite(product)||!std::isfinite(w.temporal[r]+product))throw std::overflow_error("TPSM chain overflow");w.temporal[r]+=product;}
 }
 m_current=moments;m_pending=true;m_lastPoc=poc;return w;
}
void History::finish(const std::vector<Observation>& observations){
 if(!m_pending||observations.size()!=m_current.size())throw std::logic_error("TPSM incomplete/duplicate picture feedback");
 std::vector<double> beta(observations.size(),-1);double d=0,p=0;
 for(size_t i=0;i<observations.size();++i){auto o=observations[i];if(positive(o.pixels)&&positive(o.mcp)&&std::isfinite(o.reconstruction)&&o.reconstruction>=0){double b=o.reconstruction/o.mcp;if(std::isfinite(b)){if(o.pixels==m_current[i].pixels)beta[i]=b;d+=o.reconstruction;p+=o.mcp;}}}
 m_kappa=positive(p)&&std::isfinite(d/p)?d/p:0;m_beta.push_front(beta);if(m_beta.size()>4)m_beta.pop_back();m_previous=m_current;m_pending=false;
}
} }
