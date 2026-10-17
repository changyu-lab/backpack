#include "VisualGaze.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <string>
namespace vvenc { namespace gaze {
namespace {
void require(bool v,const char* why) {if(!v)throw std::runtime_error(why);}
bool valid(double v) {return std::isfinite(v) && v>=0;}
void header(std::istream& in,const char* kind,const Geometry& g) {
  std::string tag;int version=0,w=0,h=0,c=0,b=0,n=0;
  require(bool(in>>tag>>version>>w>>h>>c>>b>>n),"VisualGaze malformed input header");
  require(tag==kind && version==1 && w==g.width && h==g.height && c==g.ctu && b==g.bitdepth && n==g.frames,
          "VisualGaze input geometry/version mismatch");
}
}
double latitude(int y,int height) {require(height>0 && y>=0 && y<height,"invalid latitude row");return std::sin((y+.5)*std::acos(-1.)/height);}
std::vector<double> stripLatitudes(const Geometry& g) {
  require(g.width>0 && g.height>0 && g.ctu>0,"invalid ERP geometry");
  std::vector<double> result(g.rows());
  for(int r=0;r<g.rows();++r) {
    const int end=std::min((r+1)*g.ctu,g.height);
    for(int y=r*g.ctu;y<end;++y) result[r]+=latitude(y,g.height);
    result[r]=result[r]/(end-r*g.ctu)*g.cols(); // Eq.11 sum of CTU latitude means.
  } return result;
}
double dependency(double f,double d1,double r1,double d2,double r2) {
  require(valid(f)&&valid(d1)&&valid(d2)&&valid(r1)&&valid(r2)&&d1<=1&&d2<=1&&r1<=1&&r2<=1,"invalid dependency inputs");
  const double phi=1/(1+f*(d1*r1+d2*r2));
  require(std::isfinite(phi)&&phi>0,"invalid dependency factor");return phi;
}
double sampleError(int original,int reconstructed,const int16_t* inverse) {
  const double d=original-(inverse?inverse[reconstructed]:reconstructed);return d*d;
}
Optimized optimize(double base,int qp,double phi,bool key,bool complex,int depth) {
  require(std::isfinite(base)&&base>0&&std::isfinite(phi)&&phi>0&&phi<=1,"invalid lambda optimization");
  if(phi==1 || (!key && complex)) return {base,base,qp,false};
  const double raw=key?base*phi:base/phi;
  const double scale=std::pow(2.,2*(depth-8));
  const int lo=std::max(-6*(depth-8),qp-2),hi=std::min(63,qp+2);
  // Use the VTM mapping (including its int(x+.5) convention). Clip lambda,
  // too, so an enormous f cannot leave an unclipped RDO multiplier behind.
  const double minLam=std::exp((lo-.49-13.7122)/4.2005)*scale;
  const double maxLam=std::exp((hi+.49-13.7122)/4.2005)*scale;
  const double applied=std::max(minLam,std::min(maxLam,raw));
  const int mapped=int(4.2005*std::log(applied/scale)+13.7122+.5);
  return {applied,raw,std::max(lo,std::min(hi,mapped)),applied!=raw};
}
StripBudget::StripBudget(int cols,const std::vector<double>& f,const std::vector<double>& li,const std::vector<double>& pixels):m_cols(cols),m_features(f),m_latitudes(li),m_pixels(pixels) {
  require(cols>0&&!f.empty()&&li.size()==(f.size()+cols-1)/cols,"invalid strip geometry");
  for(auto x:f) require(valid(x),"invalid strip feature");
  for(auto x:li) require(valid(x)&&x>0,"invalid strip latitude");
  if(m_pixels.empty())m_pixels.assign(f.size(),1);
  require(m_pixels.size()==f.size(),"invalid pixel weights");
  for(auto x:m_pixels)require(valid(x)&&x>0,"invalid pixel count");
  m_average=std::accumulate(li.begin(),li.end(),0.)/li.size();
}
int StripBudget::target(int ctu,int remaining) {
  require(!m_pending&&ctu==m_next&&ctu<int(m_features.size()),"unordered strip decision");
  const int end=std::min(int(m_features.size()),(ctu/m_cols+1)*m_cols);
  if(ctu%m_cols==0) {
    double all=std::accumulate(m_features.begin()+ctu,m_features.end(),0.);
    double strip=std::accumulate(m_features.begin()+ctu,m_features.begin()+end,0.);
    m_fallback=all==0;
    if(all==0) {all=std::accumulate(m_pixels.begin()+ctu,m_pixels.end(),0.);strip=std::accumulate(m_pixels.begin()+ctu,m_pixels.begin()+end,0.);}
    m_left=remaining*strip/all*m_latitudes.at(ctu/m_cols)/m_average;
    m_begin=ctu;m_end=end;m_initial=m_left;
  }
  double tail=std::accumulate(m_features.begin()+ctu,m_features.begin()+end,0.);
  double weight=m_features[ctu];
  if(tail==0) {tail=std::accumulate(m_pixels.begin()+ctu,m_pixels.begin()+end,0.);weight=m_pixels[ctu];m_fallback=true;}
  const double raw=m_left*weight/tail;
  require(std::isfinite(raw)&&raw<std::numeric_limits<int>::max(),"strip target overflow");
  m_pending=true;return raw<1?1:int(raw+.5);
}
void StripBudget::feedback(int bits) {require(m_pending&&bits>=0,"unordered strip feedback");m_left-=bits;m_pending=false;++m_next;}
Features::Features(std::istream& in,const Geometry& g) {
  header(in,"VGFEATURES",g);m_spatial.assign(g.frames,std::vector<double>(g.count(),-1));m_temporal=m_spatial;
  for(int k=0;k<g.frames*g.count();++k) {
    int p,c;double s,t;require(bool(in>>p>>c>>s>>t),"VisualGaze missing feature rows");
    require(p>=0&&p<g.frames&&c>=0&&c<g.count()&&valid(s)&&valid(t),"VisualGaze invalid feature row");
    require(m_spatial[p][c]<0,"VisualGaze duplicate feature row");m_spatial[p][c]=s;m_temporal[p][c]=t;
  } std::string extra;require(!(in>>extra),"VisualGaze excess feature rows");
}
const std::vector<double>& Features::at(int p,bool intra) const {return (intra?m_spatial:m_temporal).at(p);}
Gaze::Gaze(std::istream& in,const Geometry& g) {
  header(in,"VGGAZE",g);int observers=0;require(bool(in>>observers)&&observers==49,"VisualGaze requires 49 observers");
  m_key.assign(g.frames,std::vector<bool>(g.count(),false));
  std::vector<std::vector<bool>> seen(g.frames,std::vector<bool>(49,false));
  for(int k=0;k<g.frames*49;++k) {
    int p,o;double y,x;require(bool(in>>p>>o>>y>>x),"VisualGaze missing gaze rows");
    require(p>=0&&p<g.frames&&o>=0&&o<49&&valid(x)&&valid(y)&&x<=1&&y<=1,"VisualGaze invalid gaze row");
    require(!seen[p][o],"VisualGaze duplicate gaze row");seen[p][o]=true;
    const int px=x==1?0:std::min(g.width-1,int(x*g.width));
    const int py=std::min(g.height-1,int(y*g.height));
    m_key[p][(py/g.ctu)*g.cols()+px/g.ctu]=true;
  } std::string extra;require(!(in>>extra),"VisualGaze excess gaze rows");
}
} }
