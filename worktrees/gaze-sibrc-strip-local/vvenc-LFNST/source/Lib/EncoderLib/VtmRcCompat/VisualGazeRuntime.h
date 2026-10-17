#pragma once
#include "VisualGaze.h"
#include "CommonLib/CommonDef.h"
#include <fstream>
#include <map>
#include <memory>
namespace vvenc {
struct Picture;
struct VVEncCfg;
namespace gaze {
// Snapshot owns original samples because reference Picture original buffers may
// already have been returned to the input pool. Never dereference those buffers.
struct Snapshot {
  Picture* owner=nullptr;
  std::vector<std::vector<Pel>> samples;
  std::vector<double> mse;
};
class Runtime {
  const VVEncCfg& m_cfg;
  Geometry m_geometry;
  Features m_features;
  std::unique_ptr<Gaze> m_gaze;
  std::unique_ptr<StripBudget> m_budget;
  std::map<int,Snapshot> m_cache;
  Picture* m_picture=nullptr;
  std::vector<int> m_refs;
  std::vector<double> m_currentFeatures;
  double m_mean=0,m_phi=1,m_before=0,m_baseLambda=0,m_rawLambda=0,m_appliedLambda=0;
  int m_baseQp=0,m_appliedQp=0,m_target=0;
  bool m_key=false,m_complex=false,m_clipped=false;
  std::ofstream m_trace;
  static Features load(const char* path,const Geometry& g);
  double mse(int ctu,bool beforeInverse=false) const;
  double correlation(int ctu,const Snapshot& other,int index) const;
public:
  explicit Runtime(const VVEncCfg& cfg);
  void begin(Picture& picture);
  int target(int ctu,int frameLeft);
  const StripBudget& stripBudget() const {return *m_budget;}
  Optimized optimizeCtu(int ctu,double lambda,int qp);
  void feedback(int ctu,int bits);
  void finish();
};
} }
