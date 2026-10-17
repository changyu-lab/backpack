#include "Encoder.h"
#include "EncoderLib/EncCfg.h"
#include "CommonLib/Picture.h"
#include "CommonLib/UnitTools.h"
#include <cmath>
#include <iomanip>
#include <stdexcept>
namespace vvenc { namespace tpsm {
Encoder::Encoder(const VVEncCfg& cfg):m_cfg(cfg),m_history(cfg.m_tpsmChain){
 m_trace.open(cfg.m_tpsmTrace);if(!m_trace)throw std::runtime_error("Cannot open TPSMTrace");
 m_trace<<"poc,ctu,d,mcp,pixels,beta,kappa,wm,wt,importance,chain,scene_reset,bits,qp,lambda,sample_scale,cached_inter_cus,history_valid,strength\n"<<std::setprecision(17);
 if(cfg.m_tpsmAudit[0]){m_audit.open(cfg.m_tpsmAudit,std::ios::binary);if(!m_audit)throw std::runtime_error("Cannot open TPSMAudit");}
}
void Encoder::begin(Picture& pic){
 if(m_picture)throw std::logic_error("TPSM picture not completed");
 m_picture=&pic;m_completed=0;m_pixels.clear();
 auto o=pic.getOrigBuf(COMP_Y);int size=m_cfg.m_CTUSize,cols=(o.width+size-1)/size;
 m_scale=m_cfg.m_tpsmNormalize8Bit?std::exp2(pic.slices[0]->sps->bitDepths[CH_L]-8):1.;
 std::vector<Moments> moments;m_spatial.clear();
 for(int y=0;y<o.height;y+=size)for(int x=0;x<o.width;x+=size){
  int w=std::min<int>(size,o.width-x),h=std::min<int>(size,o.height-y);double sum=0,ss=0,n=w*h;
  for(int j=0;j<h;++j)for(int i=0;i<w;++i){double v=o.buf[(y+j)*o.stride+x+i]/m_scale;sum+=v;ss+=v*v;}
  moments.push_back({sum/n,std::max(0.,ss/n-(sum/n)*(sum/n)),n});m_spatial.push_back(spatialWeight(y,h,o.height));
 }
 (void)cols;m_weights=m_history.begin(pic.poc,moments,pic.slices[0]->isIntra());
 m_observations.assign(moments.size(),Observation{0,0,0});m_lastPoc=pic.poc;
}
int Encoder::frameOffset() const{return m_cfg.m_tpsmMode==1?frameQpOffset(m_weights.kappa):0;}
Decision Encoder::decide(int ctu,double lambda){if(!m_picture||ctu!=m_completed)throw std::logic_error("TPSM CTU order");return paperDecision(lambda,m_spatial.at(ctu),m_weights.temporal.at(ctu),m_cfg.m_internalBitDepth[0]);}
std::vector<double> Encoder::importance(const std::vector<double>& area)const{return temporalImportance(m_weights.temporal,area,m_cfg.m_tpsmStrength);}
void Encoder::capture(CodingUnit& cu){
 cu.tpsmD=cu.tpsmMcp=0;cu.tpsmPixels=0;cu.tpsmAuditToken=0;
 if(cu.chType!=CH_L||!CU::isInter(cu))return;
 const auto area=clipArea(cu.Y(),m_picture->cs->area.Y());if(!area.valid())return;
 auto o=m_picture->getOrigBuf(area);auto p=cu.cs->getPredBuf(area);auto c=cu.cs->getRecoBuf(area);
 std::vector<int16_t> triples;if(m_audit.is_open())triples.reserve(area.area()*3);
 for(int y=0;y<o.height;++y)for(int x=0;x<o.width;++x){int ov=o.buf[y*o.stride+x],pv=p.buf[y*p.stride+x],cv=c.buf[y*c.stride+x];double d=double(ov-cv),e=double(ov-pv);cu.tpsmD+=d*d;cu.tpsmMcp+=e*e;++cu.tpsmPixels;
  if(m_audit.is_open()){triples.push_back(int16_t(ov));triples.push_back(int16_t(pv));triples.push_back(int16_t(cv));}}
 if(m_audit.is_open()){cu.tpsmAuditToken=++m_token;m_pixels.emplace(m_token,std::move(triples));}
}
void Encoder::collect(int ctu,int bits,int qp,double lambda){
 if(!m_picture||ctu!=m_completed)throw std::logic_error("TPSM duplicate or unordered CTU feedback");
 auto& pic=*m_picture;auto o=pic.getOrigBuf(COMP_Y);int size=m_cfg.m_CTUSize,cols=(o.width+size-1)/size;
 UnitArea area(pic.chromaFormat,Area((ctu%cols)*size,(ctu/cols)*size,std::min<int>(size,o.width-(ctu%cols)*size),std::min<int>(size,o.height-(ctu/cols)*size)));
 auto& obs=m_observations.at(ctu);int cached=0;
 for(auto& cu:pic.cs->traverseCUs(area,CH_L)){
  cached+=cu.tpsmCachedPrediction&&cu.tpsmPixels>0;
  obs.reconstruction+=cu.tpsmD;obs.mcp+=cu.tpsmMcp;obs.pixels+=cu.tpsmPixels;
  if(m_audit.is_open()&&cu.tpsmPixels){auto it=m_pixels.find(cu.tpsmAuditToken);if(it==m_pixels.end())throw std::logic_error("TPSM selected predictor audit missing");
   auto visible=clipArea(cu.Y(),pic.cs->area.Y());int32_t header[6]={pic.poc,ctu,visible.x,visible.y,int32_t(visible.width),int32_t(visible.height)};
   m_audit.write(reinterpret_cast<const char*>(header),sizeof(header));m_audit.write(reinterpret_cast<const char*>(it->second.data()),it->second.size()*sizeof(int16_t));}
 }
 m_pixels.clear();
 // Trace SSE in raw internal sample units; ratios are invariant to scaling.
 m_trace<<pic.poc<<','<<ctu<<','<<obs.reconstruction<<','<<obs.mcp<<','<<obs.pixels<<','<<(obs.mcp>0&&obs.pixels==area.lumaSize().area()?obs.reconstruction/obs.mcp:-1)<<','<<m_weights.kappa<<','<<m_spatial[ctu]<<','<<m_weights.temporal[ctu]<<',';
 if(m_cfg.m_tpsmMode==2){ // normalized weights depend on integrated spherical area, not CTU-center geometry
  std::vector<double> areas(m_spatial.size(),0);for(size_t k=0;k<areas.size();++k){int y=int(k/cols)*size,w=std::min<int>(size,o.width-int(k%cols)*size);for(int yy=y;yy<std::min<int>(o.height,y+size);++yy)areas[k]+=w*std::cos(3.14159265358979323846*((yy+.5)/o.height-.5));}m_trace<<importance(areas)[ctu];
 }else m_trace<<1+m_weights.temporal[ctu];
 m_trace<<','<<m_weights.chain[ctu]<<','<<m_weights.sceneReset<<','<<bits<<','<<qp<<','<<lambda<<','<<m_scale<<','<<cached<<','<<(obs.mcp>0&&obs.pixels==area.lumaSize().area())<<','<<m_cfg.m_tpsmStrength<<'\n';
 if(!m_trace||(m_audit.is_open()&&!m_audit))throw std::runtime_error("TPSM trace/audit write failed");++m_completed;
}
void Encoder::finish(int poc){if(!m_picture||poc!=m_lastPoc||m_completed!=int(m_observations.size()))throw std::logic_error("TPSM incomplete picture");m_history.finish(m_observations);m_trace.flush();if(m_audit.is_open())m_audit.flush();m_picture=nullptr;}
} }
