#pragma once
#include <vector>
#include <deque>
namespace vvenc { namespace tpsm {
struct Moments { double mean,variance,pixels; };
struct Observation { double reconstruction,mcp,pixels; };
struct Weights { std::vector<double> temporal; std::vector<int> chain; bool sceneReset=false; double kappa=0; };
struct Decision { int qp; double lambda; };
std::vector<double> temporalImportance(const std::vector<double>& temporal,const std::vector<double>& area,double strength);
double spatialWeight(int y,int visibleHeight,int frameHeight);
Decision paperDecision(double frameLambda,double spatial,double temporal,int bitDepth);
int frameQpOffset(double kappa);
std::vector<double> normalizeImportance(const std::vector<double>& importance,const std::vector<double>& area);
class History {
 public:
 explicit History(int chain);
 Weights begin(int poc,const std::vector<Moments>& moments,bool intra);
 void finish(const std::vector<Observation>& observations);
 private:
 int m_chain,m_lastPoc=-1;bool m_pending=false;
 double m_kappa=0;
 std::vector<Moments> m_previous,m_current;
 std::deque<std::vector<double>> m_beta;
};
} }
