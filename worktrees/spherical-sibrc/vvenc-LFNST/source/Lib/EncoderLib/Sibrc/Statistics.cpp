#include "Preanalysis.h"
#include "Controller.h"
#include <cmath>
#include <algorithm>
#include <stdexcept>
namespace vvenc { namespace sibrc {
static constexpr double pi=3.14159265358979323846;
Statistics::Statistics(const std::string& path) {
 std::ifstream f(path);std::string magic;int n=0;f>>magic>>n;
 if(magic!="SIBRC_STATS_V1" || n<2 || n>100)throw std::runtime_error("invalid SIBRC statistics header");
 for(int j=0;j<n;++j){double a;f>>a;if(!f||!std::isfinite(a)||a<0||a>90||(j&&a<=angles.back()))throw std::runtime_error("invalid SIBRC latitude grid");angles.push_back(a);nodes.emplace_back();
 for(auto& b:nodes.back()){f>>b.rho2>>b.gain;if(!f||!std::isfinite(b.rho2)||!std::isfinite(b.gain)||b.rho2<0||b.rho2>=1||b.gain<0||b.gain>1000)throw std::runtime_error("invalid SIBRC band statistics");}}
 std::string extra;if(f>>extra)throw std::runtime_error("trailing SIBRC statistics data");
}
BandStats Statistics::at(double a,int u,int v) const {
 const int b=v*32+u;if(a<=angles.front())return nodes.front()[b];if(a>=angles.back())return nodes.back()[b];
 auto hi=std::upper_bound(angles.begin(),angles.end(),a);int j=int(hi-angles.begin());double t=(a-angles[j-1])/(angles[j]-angles[j-1]);
 return {nodes[j-1][b].rho2*(1-t)+nodes[j][b].rho2*t,nodes[j-1][b].gain*(1-t)+nodes[j][b].gain*t};
}
// Quantized stationary covariance diagonals under orthonormal DCT; energy normalized by block area.
static const std::array<std::array<double,32>,100>& covarianceDiagonals() {
 static const auto table=[](){std::array<std::array<double,32>,100> result{};double basis[32][32];
 for(int u=0;u<32;++u)for(int x=0;x<32;++x)basis[u][x]=std::sqrt((u?2.0:1.0)/32)*std::cos(pi*(x+.5)*u/32);
 for(int r=0;r<100;++r)for(int u=0;u<32;++u){double d=0;for(int x=0;x<32;++x)for(int y=0;y<32;++y)d+=basis[u][x]*basis[u][y]*std::pow(r*.01,std::abs(x-y));result[r][u]=std::max(0.0,d);}return result;}();return table;
}
double informationFromResidual(const double* residual,double latitude,const Statistics& stats) {
 double mean=0,var=0,hcov=0,vcov=0;for(int i=0;i<1024;++i)mean+=residual[i];mean/=1024;
 for(int y=0;y<32;++y)for(int x=0;x<32;++x){double d=residual[y*32+x]-mean;var+=d*d;if(x<31)hcov+=d*(residual[y*32+x+1]-mean);if(y<31)vcov+=d*(residual[(y+1)*32+x]-mean);}
 var/=1024;if(var<=1e-12)return 0;
 int rh=int(std::floor(std::max(0.0,std::min(.99,hcov/(32*31)/var))*100+.5));
 int rv=int(std::floor(std::max(0.0,std::min(.99,vcov/(32*31)/var))*100+.5));
 const auto& diag=covarianceDiagonals();double total=0;int support=std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));
 for(int v=0;v<32;++v)for(int u=0;u<support;++u){auto s=stats.at(latitude,u,v);total+=var*diag[rh][u]*diag[rv][v]/1024*s.gain*ibWeight(s.rho2,5);}
 return total;
}
} }

