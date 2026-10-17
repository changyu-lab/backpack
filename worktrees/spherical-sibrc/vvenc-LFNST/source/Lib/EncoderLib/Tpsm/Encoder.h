#pragma once
#include "Model.h"
#include <fstream>
#include <unordered_map>
#include <cstdint>
namespace vvenc {
struct Picture;struct VVEncCfg;struct CodingUnit;
namespace tpsm {
class Encoder {
 public:
 explicit Encoder(const VVEncCfg& cfg);
 void begin(Picture& picture);
 int frameOffset() const;
 Decision decide(int ctu,double frameLambda);
 void capture(CodingUnit& cu);
 void collect(int ctu,int bits,int qp,double lambda);
 void finish(int poc);
 std::vector<double> importance(const std::vector<double>& area) const;
 private:
 const VVEncCfg& m_cfg; History m_history; Weights m_weights;
 Picture* m_picture=nullptr;std::vector<Observation> m_observations;
 std::vector<double> m_spatial;std::ofstream m_trace,m_audit;
 std::unordered_map<uint64_t,std::vector<int16_t>> m_pixels;
 uint64_t m_token=0;int m_completed=0,m_lastPoc=-1;double m_scale=1;
};
} }
