#include "Sibrc/Preanalysis.h"
#include <array>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace vvenc::sibrc;
static const char* fixture="sibrc-feature-statistics.tmp";
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
bool near(double a,double b){return std::abs(a-b)<1e-9;}
void writeStats(bool varying=false){std::ofstream out(fixture);out<<"SIBRC_STATS_V1 2\n";for(int j=0;j<2;++j){out<<j*90<<'\n';for(int b=0;b<1024;++b)out<<(varying?.2+.4*j:.8)<<' '<<(varying?b*.5+1+j:1)<<'\n';}}
void rejects(const char* text){std::ofstream out(fixture);out<<text;out.close();bool rejected=false;try{Statistics s(fixture);}catch(const std::runtime_error&){rejected=true;}check(rejected,"malformed statistics rejection");}
int main(){try{
 writeStats();Statistics white(fixture);std::array<double,1024> residual;
 for(int y=0;y<32;++y)for(int x=0;x<32;++x)residual[y*32+x]=(x+y)%2?1:-1;
 check(near(informationFromResidual(residual.data(),0,white),1),"checkerboard unit variance and white covariance");
 check(near(informationFromResidual(residual.data(),60,white),.5),"latitude support halves information");
 for(auto& x:residual)x*=2;
 check(near(informationFromResidual(residual.data(),0,white),4),"information scales with residual variance");
 residual.fill(7);check(informationFromResidual(residual.data(),0,white)==0,"constant residual has zero information");
 writeStats(true);Statistics varying(fixture);auto mid=varying.at(45,3,4);
 check(near(mid.rho2,.4)&&near(mid.gain,67),"linear latitude interpolation and row major bands");
 check(near(varying.at(0,3,4).gain,66.5)&&near(varying.at(90,3,4).gain,67.5),"latitude endpoints");
 check(std::isfinite(mid.rho2)&&std::isfinite(mid.gain),"finite interpolated statistics");
 {std::ofstream out(fixture,std::ios::app);out<<" trailing";}bool trailing=false;try{Statistics s(fixture);}catch(const std::runtime_error&){trailing=true;}check(trailing,"trailing statistics rejection");
 rejects("BAD 2");rejects("SIBRC_STATS_V1 1");rejects("SIBRC_STATS_V1 2 0 .8");rejects("SIBRC_STATS_V1 2 0 nan 1");rejects("SIBRC_STATS_V1 2 0 1 1");rejects("SIBRC_STATS_V1 2 0 .8 -1");
 std::remove(fixture);std::cout<<"SIBRC feature tests passed\n";return 0;
 }catch(const std::exception& e){std::remove(fixture);std::cerr<<e.what()<<'\n';return 1;}}

