#include "SaldanhaLfnst.h"
#include <sstream>
#include <iostream>
#include <algorithm>
int main(int argc,char**argv)
{
  if(argc!=3) return 2;
  saldanha::Model model(argv[1]);
  std::ifstream in(argv[2]); std::string line; std::getline(in,line);
  unsigned count=0;
  while(std::getline(in,line))
  {
    std::replace(line.begin(),line.end(),',',' ');
    std::istringstream row(line); saldanha::Features f{};
    for(double& x:f) if(!(row>>x)) return 3;
    double p0,p1; if(!(row>>p0>>p1)) return 4;
    if(model.skip(f)!=(p0>=p1)) { std::cerr<<"Mismatch row "<<count<<'\n'; return 1; }
    ++count;
  }
  if(!count) return 5;
  std::cout<<"PASS C++ exported inference: "<<count<<" rows\n";
}
