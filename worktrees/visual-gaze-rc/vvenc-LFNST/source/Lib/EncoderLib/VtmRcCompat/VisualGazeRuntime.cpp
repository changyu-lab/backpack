#include "VisualGazeRuntime.h"
#include "EncoderLib/EncCfg.h"
#include "CommonLib/Picture.h"
#include "CommonLib/Slice.h"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <numeric>
#include <set>
#include <stdexcept>
namespace vvenc { namespace gaze {
Features Runtime::load(const char* path,const Geometry& g) {
  std::ifstream in(path);if(!in)throw std::runtime_error("Cannot open VisualGazeFeatures");return Features(in,g);
}
Runtime::Runtime(const VVEncCfg& cfg):m_cfg(cfg),
  m_geometry{cfg.m_SourceWidth,cfg.m_SourceHeight,int(cfg.m_CTUSize),cfg.m_internalBitDepth[0],cfg.m_framesToBeEncoded},
  m_features(load(cfg.m_visualGazeFeatures,m_geometry)) {
  if(cfg.m_visualGazeMode==3) {
    std::ifstream in(cfg.m_visualGazePoints);if(!in)throw std::runtime_error("Cannot open VisualGazePoints");
    m_gaze.reset(new Gaze(in,m_geometry));
  }
  if(cfg.m_visualGazeTrace[0]) {
    m_trace.open(cfg.m_visualGazeTrace);if(!m_trace)throw std::runtime_error("Cannot open VisualGazeTrace");
    m_trace<<"poc,ctu,target,feature,mean,key,complex,phi,base_lambda,raw_lambda,lambda,base_qp,qp,clipped,strip_before,strip_after,bits,mse,zero_feature_fallback,ref1,ref2\n"<<std::setprecision(17);
  }
}
void Runtime::begin(Picture& pic) {
  m_picture=&pic;const Slice& slice=*pic.slices[0];m_refs.clear();
  if(!slice.isIntra()) {
    if(slice.isInterP()) {
      for(int i=0;i<std::min(2,slice.numRefIdx[0]);++i)m_refs.push_back(slice.getRefPic(REF_PIC_LIST_0,i)->poc);
    } else {
      for(int l=0;l<2;++l) if(slice.numRefIdx[l]>0)m_refs.push_back(slice.getRefPic(RefPicList(l),0)->poc);
    }
  }
  // Picture objects remain owned by the encoder DPB. POC tags protect against
  // pooled-object reuse. Retain all still-referenced snapshots, not merely the
  // current list (a later RA picture can use a different reference).
  const std::set<int> required(m_refs.begin(),m_refs.end());
  for(auto it=m_cache.begin();it!=m_cache.end();) {
    auto* owner=it->second.owner;
    if(!required.count(it->first) && (owner->poc!=it->first || !owner->isReferenced))it=m_cache.erase(it);
    else ++it;
  }
  for(auto poc:m_refs) if(!m_cache.count(poc))throw std::runtime_error("VisualGaze missing reconstructed reference snapshot");
  m_currentFeatures=m_features.at(pic.poc,slice.isIntra());
  m_mean=std::accumulate(m_currentFeatures.begin(),m_currentFeatures.end(),0.)/m_currentFeatures.size();
  std::vector<double> pixels;
  for(int y=0;y<m_geometry.height;y+=m_geometry.ctu)for(int x=0;x<m_geometry.width;x+=m_geometry.ctu)
    pixels.push_back(double(std::min(m_geometry.ctu,m_geometry.height-y))*std::min(m_geometry.ctu,m_geometry.width-x));
  m_budget.reset(new StripBudget(m_geometry.cols(),m_currentFeatures,stripLatitudes(m_geometry),pixels));
  Snapshot current;current.owner=&pic;current.mse.assign(m_geometry.count(),0);current.samples.resize(m_geometry.count());
  const auto orig=pic.getOrigBuf(COMP_Y);
  for(int c=0;c<m_geometry.count();++c) {
    const int x=(c%m_geometry.cols())*m_geometry.ctu,y=(c/m_geometry.cols())*m_geometry.ctu;
    const int w=std::min(m_geometry.ctu,m_geometry.width-x),h=std::min(m_geometry.ctu,m_geometry.height-y);
    // Fixed 16x16 normalized positions allow partial-border CTU comparison.
    for(int sy=0;sy<16;++sy)for(int sx=0;sx<16;++sx)
      current.samples[c].push_back(orig.buf[(y+sy*h/16)*orig.stride+x+sx*w/16]);
  }
  m_cache[pic.poc]=std::move(current);
}
double Runtime::mse(int c,bool beforeInverse) const {
  const auto a=m_picture->getOrigBuf(COMP_Y);
  const auto b=m_picture->getRecoBuf(COMP_Y);
  const int x=(c%m_geometry.cols())*m_geometry.ctu,y=(c/m_geometry.cols())*m_geometry.ctu;
  const int w=std::min(m_geometry.ctu,m_geometry.width-x),h=std::min(m_geometry.ctu,m_geometry.height-y);
  const Slice& slice=*m_picture->slices[0];
  const Pel* inverse=beforeInverse && slice.sps->lumaReshapeEnable && slice.picHeader->lmcsEnabled ? m_picture->reshapeData.getInvLUT():nullptr;
  double sum=0;
  for(int j=y;j<y+h;++j)for(int i=x;i<x+w;++i)sum+=sampleError(a.buf[j*a.stride+i],b.buf[j*b.stride+i],inverse);
  const double peak=(1<<m_geometry.bitdepth)-1;return sum/(w*h*peak*peak);
}
double Runtime::correlation(int c,const Snapshot& other,int index) const {
  const auto& a=m_cache.at(m_picture->poc).samples[c];const auto& b=other.samples[index];
  double sa=0,sb=0,aa=0,bb=0,ab=0;
  for(size_t i=0;i<a.size();++i) {sa+=a[i];sb+=b[i];aa+=double(a[i])*a[i];bb+=double(b[i])*b[i];ab+=double(a[i])*b[i];}
  const double n=double(a.size()),va=aa-sa*sa/n,vb=bb-sb*sb/n,cov=ab-sa*sb/n;
  return va<=0||vb<=0?0:std::min(1.,std::max(0.,cov*cov/(va*vb)));
}
int Runtime::target(int c,int frameLeft) {m_target=m_budget->target(c,frameLeft);m_before=m_budget->left();return m_target;}
Optimized Runtime::optimizeCtu(int c,double lambda,int qp) {
  m_phi=1;m_key=m_gaze && m_gaze->key(m_picture->poc,c);m_complex=m_currentFeatures[c]>m_mean;
  if(m_cfg.m_visualGazeMode>=2) {
    double d[2]={0,0},r[2]={0,0};
    if(m_picture->slices[0]->isIntra()) {
      const auto& own=m_cache.at(m_picture->poc);
      const int neighbors[2]={c>=m_geometry.cols()?c-m_geometry.cols():-1,c%m_geometry.cols()?c-1:-1};
      for(int i=0;i<2;++i)if(neighbors[i]>=0) {d[i]=own.mse[neighbors[i]];r[i]=correlation(c,own,neighbors[i]);}
    } else {
      for(size_t i=0;i<m_refs.size();++i) {const auto& ref=m_cache.at(m_refs[i]);d[i]=ref.mse[c];r[i]=correlation(c,ref,c);}
    }
    m_phi=dependency(m_cfg.m_visualGazeStrength,d[0],r[0],d[1],r[1]);
  }
  const auto result=m_cfg.m_visualGazeMode==1?Optimized{lambda,lambda,qp,false}:optimize(lambda,qp,m_phi,m_key,m_complex,m_geometry.bitdepth);
  m_baseLambda=lambda;m_rawLambda=result.rawLambda;m_appliedLambda=result.lambda;m_baseQp=qp;m_appliedQp=result.qp;m_clipped=result.clipped;return result;
}
void Runtime::feedback(int c,int bits) {
  const double distortion=mse(c,true);m_cache.at(m_picture->poc).mse[c]=distortion;m_budget->feedback(bits);
  if(m_trace.is_open()) m_trace<<m_picture->poc<<','<<c<<','<<m_target<<','<<m_currentFeatures[c]<<','<<m_mean<<','<<m_key<<','<<m_complex<<','<<m_phi<<','<<m_baseLambda<<','<<m_rawLambda<<','<<m_appliedLambda<<','<<m_baseQp<<','<<m_appliedQp<<','<<m_clipped<<','<<m_before<<','<<m_budget->left()<<','<<bits<<','<<distortion<<','<<m_budget->fallback()<<','<<(m_refs.empty()?-1:m_refs[0])<<','<<(m_refs.size()<2?-1:m_refs[1])<<'\n';
}
void Runtime::finish() {
  // Refresh reference distortion after the entire picture's in-loop filters.
  for(int c=0;c<m_geometry.count();++c)m_cache.at(m_picture->poc).mse[c]=mse(c);
  if(m_trace.is_open()) {m_trace.flush();if(!m_trace)throw std::runtime_error("Cannot write VisualGazeTrace");}
  m_picture=nullptr;
}
} }
