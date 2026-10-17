#include "Preanalysis.h"
#include "Controller.h"
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <cstdlib>
namespace vvenc { namespace sibrc {
static constexpr double pi=3.14159265358979323846;
static int ablationMode(){static int m=[](){const char* p=std::getenv("SIBRC_M4_ABLATION");if(!p)return 0;int v=std::atoi(p);if(v!=0&&v!=5&&v!=6)throw std::invalid_argument("Invalid ablation");return v;}();return m;}
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
double frequencyWeight(double r,int selector) {
 if(selector<0||selector>4)throw std::invalid_argument("Invalid M4 frequency selector");
 if(!std::isfinite(r)||r<0)return 0;
 r=std::min(r,1-1e-6);
 const double t=ibWeight(r,5);
 switch(selector){case 0:return 1;case 1:return r;case 2:return std::max(0.,5*r-1);case 3:return -std::expm1(-2*t*std::log(2.));default:return t;}
}
// 8x8 separable orthonormal Walsh-Hadamard L1, summed then divided by block area.
// DC is retained; a constant residual c has SATD density abs(c)/8.
static double residualSatd(const double* residual) {
 double sum=0;
 for(int oy=0;oy<32;oy+=8)for(int ox=0;ox<32;ox+=8){double a[8][8];
  for(int y=0;y<8;++y)for(int x=0;x<8;++x)a[y][x]=residual[(oy+y)*32+ox+x];
  for(int step=1;step<8;step*=2){
   for(int y=0;y<8;++y)for(int x=0;x<8;x+=2*step)for(int k=0;k<step;++k){double p=a[y][x+k],q=a[y][x+k+step];a[y][x+k]=p+q;a[y][x+k+step]=p-q;}
   for(int x=0;x<8;++x)for(int y=0;y<8;y+=2*step)for(int k=0;k<step;++k){double p=a[y+k][x],q=a[y+k+step][x];a[y+k][x]=p+q;a[y+k+step][x]=p-q;}
  }
  for(int y=0;y<8;++y)for(int x=0;x<8;++x)sum+=std::abs(a[y][x])/8;
 }
 return sum/1024;
}
std::array<double,8> descriptorsFromResidual(const double* residual,double latitude,const Statistics& stats,int onlySelector) {
 if(onlySelector< -1||onlySelector>7)throw std::invalid_argument("Invalid M4 descriptor selector");
 std::array<double,8> result{};if(onlySelector<0||onlySelector==7)result[7]=residualSatd(residual);if(onlySelector==7)return result;
 double mean=0,var=0,hcov=0,vcov=0;for(int i=0;i<1024;++i)mean+=residual[i];mean/=1024;
 for(int y=0;y<32;++y)for(int x=0;x<32;++x){double d=residual[y*32+x]-mean;var+=d*d;if(x<31)hcov+=d*(residual[y*32+x+1]-mean);if(y<31)vcov+=d*(residual[(y+1)*32+x]-mean);}
 var/=1024;if(onlySelector<0||onlySelector==5)result[5]=var;if(onlySelector<0||onlySelector==6)result[6]=var*std::cos(latitude*pi/180);if(var<=1e-12||onlySelector>=5)return result;
 int rh=int(std::floor(std::max(0.0,std::min(.99,hcov/(32*31)/var))*100+.5));
 int rv=int(std::floor(std::max(0.0,std::min(.99,vcov/(32*31)/var))*100+.5));
 const auto& diag=covarianceDiagonals();int support=std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));
 for(int v=0;v<32;++v)for(int u=0;u<support;++u){auto b=stats.at(latitude,u,v);double energy=var*diag[rh][u]*diag[rv][v]/1024*b.gain;for(int j=onlySelector<0?0:onlySelector;j<(onlySelector<0?5:onlySelector+1);++j)result[j]+=energy*frequencyWeight(b.rho2,j);}
 return result;
}
double informationFromResidual(const double* residual,double latitude,const Statistics& stats) {
 double mean=0,var=0,hcov=0,vcov=0;for(int i=0;i<1024;++i)mean+=residual[i];mean/=1024;
 for(int y=0;y<32;++y)for(int x=0;x<32;++x){double d=residual[y*32+x]-mean;var+=d*d;if(x<31)hcov+=d*(residual[y*32+x+1]-mean);if(y<31)vcov+=d*(residual[(y+1)*32+x]-mean);}
 var/=1024;
 if(ablationMode()==5){double total=0;int support=std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));for(int v=0;v<32;++v)for(int u=0;u<support;++u)total+=ibWeight(stats.at(latitude,u,v).rho2,5);return total;}
 if(var<=1e-12)return 0;
 int rh=int(std::floor(std::max(0.0,std::min(.99,hcov/(32*31)/var))*100+.5));
 int rv=int(std::floor(std::max(0.0,std::min(.99,vcov/(32*31)/var))*100+.5));
 const auto& diag=covarianceDiagonals();double total=0;int support=ablationMode()==6?32:std::max(1,int(std::floor(32*std::cos(latitude*pi/180)+.5)));
 for(int v=0;v<32;++v)for(int u=0;u<support;++u){auto s=stats.at(latitude,u,v);total+=var*diag[rh][u]*diag[rv][v]/1024*s.gain*ibWeight(s.rho2,5);}
 return total;
}
} }

