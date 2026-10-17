// Wang et al., IEEE SPL 31 (2024), 366-370. DOI 10.1109/LSP.2024.3350989.
// Equations (1)-(4); QPstep uses the standard 2^((codingQP-4)/6) mapping.
#ifndef VVENC_WANG_LFNST_H
#define VVENC_WANG_LFNST_H
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
namespace vvenc { namespace wang2024 {
struct Gradients { uint64_t grad1, grad2; };
template<class T> inline Gradients gradient(const T* c, int w, int h, int stride) {
 Gradients g={0,0};
 if (!c || w<1 || h<1 || stride<w) return g;
 for(int i=1;i<h;++i) {
  const int64_t d=int64_t(c[i*stride+w-1])-int64_t(c[(i-1)*stride+w-1]);
  g.grad2+=uint64_t(d<0 ? -d : d);
 }
 g.grad1=g.grad2;
 for(int j=1;j<w;++j) {
  const int64_t d=int64_t(c[(h-1)*stride+j])-int64_t(c[(h-1)*stride+j-1]);
  g.grad1+=uint64_t(d<0 ? -d : d);
 }
 return g;
}
inline double qpStep(int qp) { return std::pow(2.0,(double(qp)-4.0)/6.0); }
inline double threshold(int idx,int qp) {
 // Cache the operational QP range; do not evaluate pow per transform candidate.
 static const std::array<double,176> steps=[](){
  std::array<double,176> a={};for(int i=0;i<176;++i)a[i]=qpStep(i-48);return a;
 }();
 const double step=qp>=-48 && qp<128 ? steps[qp+48] : qpStep(qp);
 return std::max(0.0,12.83*step-(idx==1 ? 17.375 : 57.375));
}
inline bool skip(Gradients g,int idx,int qp) {
 return (idx==1 || idx==2) &&
        (double(g.grad2)>=threshold(idx,qp) || (idx==2 && g.grad1<=100));
}
enum Mode { Off, Shadow, On };
inline Mode mode() {
 static const Mode m=[](){
  const char* s=std::getenv("WANG_LFNST_MODE");
  if(!s || !*s || !std::strcmp(s,"off")) return Off;
  if(!std::strcmp(s,"shadow")) return Shadow;
  if(!std::strcmp(s,"on")) return On;
  throw std::runtime_error("WANG_LFNST_MODE must be off, shadow, or on");
 }();return m;
}
struct Audit {
 std::string path;
 std::atomic<uint64_t> considered[2],wouldSkip[2],skipped[2],isp[2],mip[2],largeNonzero[2];
 Audit() {
  const char* p=std::getenv("WANG_LFNST_AUDIT");if(p)path=p;
  for(int i=0;i<2;++i){considered[i]=0;wouldSkip[i]=0;skipped[i]=0;isp[i]=0;mip[i]=0;largeNonzero[i]=0;}
 }
 ~Audit() {
  if(path.empty())return;
  FILE* f=std::fopen(path.c_str(),"w");if(!f)return;
  std::fprintf(f,"{\"mode\":\"%s\",\"kernels\":[",mode()==On?"on":"shadow");
  for(int i=0;i<2;++i)std::fprintf(f,
   "%s{\"index\":%d,\"considered\":%llu,\"would_skip\":%llu,\"skipped\":%llu,\"isp_considered\":%llu,\"mip_considered\":%llu,\"large_border_nonzero\":%llu}",
   i?",":"",i+1,(unsigned long long)considered[i].load(),(unsigned long long)wouldSkip[i].load(),
   (unsigned long long)skipped[i].load(),(unsigned long long)isp[i].load(),(unsigned long long)mip[i].load(),(unsigned long long)largeNonzero[i].load());
  std::fprintf(f,"]}\n");std::fclose(f);
 }
};
inline void record(int idx,bool reject,bool isIsp,bool isMip,Gradients g,int w,int h) {
 static Audit a;
 if(a.path.empty())return;
 const int i=idx-1;
 a.considered[i].fetch_add(1,std::memory_order_relaxed);
 if(reject)a.wouldSkip[i].fetch_add(1,std::memory_order_relaxed);
 if(reject && mode()==On)a.skipped[i].fetch_add(1,std::memory_order_relaxed);
 if(isIsp)a.isp[i].fetch_add(1,std::memory_order_relaxed);
 if(isMip)a.mip[i].fetch_add(1,std::memory_order_relaxed);
 if(w>=16 && h>=16 && w<=32 && h<=32 && g.grad1>0)a.largeNonzero[i].fetch_add(1,std::memory_order_relaxed);
}
} }
#endif
