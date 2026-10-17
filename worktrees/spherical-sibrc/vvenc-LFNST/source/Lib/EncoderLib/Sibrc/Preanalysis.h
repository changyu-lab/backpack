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
double informationFromResidual(const double* residual,double latitude,const Statistics& stats);
struct Features { std::vector<double> information,area; };
Features analysePicture(const Picture& pic,int ctuSize,const Statistics* stats,std::ofstream* residualDump);
double weightedCtuMse(const Picture& pic,int ctu,int ctuSize);
} }

