#include "Sibrc/Preanalysis.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
using namespace vvenc::sibrc;
void check(bool v,const char* m){if(!v)throw std::runtime_error(m);}
int main(){try{
 for(double r : {0.,.2-1e-12,.2,.2+1e-12,.5,.9,.999999,.9999999}) {
  check(std::abs(frequencyWeight(r,2)-4*frequencyWeight(r,3))<1e-12,"C2/C3 constant equivalence");
  check(frequencyWeight(r,0)==1,"C0 unit");
 }
 std::ofstream out("m4-stats.tmp");out<<"SIBRC_STATS_V1 2\n";
 for(int j=0;j<2;++j){out<<j*90<<'\n';for(int b=0;b<1024;++b)out<<".8 1\n";}out.close();
 Statistics stats("m4-stats.tmp");double a[1024];for(int y=0;y<32;++y)for(int x=0;x<32;++x)a[y*32+x]=(x+y)%2?1:-1;
 auto v=descriptorsFromResidual(a,60,stats);
 check(std::abs(v[0]-.5)<1e-9,"masked target energy");
 check(std::abs(v[1]-.4)<1e-9,"rho squared weighting");
 check(std::abs(v[4]-informationFromResidual(a,60,stats))<1e-12,"legacy C4 compatibility");
 check(std::abs(v[5]-1)<1e-9&&std::abs(v[6]-.5)<1e-9,"plane and geometry energy");
 check(v[7]>0,"SATD nonzero");
 for(int selector=0;selector<8;++selector){auto only=descriptorsFromResidual(a,60,stats,selector);check(only[selector]==v[selector],"single selector equals common collection");for(int j=0;j<8;++j)if(j!=selector)check(only[j]==0,"single selector avoids unused descriptors");}
 for(double latitude : {0.,14.5,37.5,84.,89.9}) {
  for(int k=0;k<1024;++k)a[k]=std::sin(k*.013)+std::cos(k*.071);
  auto d=descriptorsFromResidual(a,latitude,stats);
  double old=informationFromResidual(a,latitude,stats);
  check(d[4]==old,"bit-exact old C4 residual evaluation");
  check(std::abs(d[2]-4*d[3])<1e-10*(1+std::abs(d[2])),"aggregate C2/C3 equivalence");
  for(double x:d)check(std::isfinite(x)&&x>=0,"finite nonnegative descriptors");
 }
 bool invalid=false;try{frequencyWeight(.8,5);}catch(const std::invalid_argument&){invalid=true;}
 check(invalid,"invalid frequency selector rejected");
 check(frequencyWeight(.9999999,1)==.999999,"shared rho cap");
 for(double& x:a)x=7;v=descriptorsFromResidual(a,60,stats);
 for(int k=0;k<7;++k)check(v[k]==0,"constant zero variance");
 check(v[7]==7./8,"constant SATD retains DC with orthonormal 8x8 normalization");
 std::remove("m4-stats.tmp");std::cout<<"M4 feature tests passed\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
