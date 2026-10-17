#pragma once
#include <array>
#include <vector>
#include <string>
#include <fstream>
namespace vvenc { struct Picture; namespace sibrc {
struct BandStats { double rho2=0, gain=0; };
class Statistics {
public:
  explicit Statistics(const std::string& path);
  BandStats at(double absoluteDegrees,int u,int v) const;
private:
  std::vector<double> angles;
  std::vector<std::array<BandStats,1024>> nodes;
};
double frequencyWeight(double rhoSquared,int selector);
std::array<double,8> descriptorsFromResidual(const double* residual,double latitude,const Statistics& stats,int onlySelector=-1);
double informationFromResidual(const double* residual,double latitude,const Statistics& stats);
struct Features { std::vector<double> information,area; std::vector<std::array<double,8>> descriptors; };
Features analysePicture(const Picture& pic,int ctuSize,const Statistics* stats,std::ofstream* residualDump,int selector=4,bool collectAll=false);
double weightedCtuMse(const Picture& pic,int ctu,int ctuSize);
} }

