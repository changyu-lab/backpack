// VVenC adapter for the mechanically extracted VTM23 controller.
#pragma once
#include "RateCtrl.h"
#include <fstream>
#include <string>
#include <memory>
#include "VisualGazeRuntime.h"

namespace vvenc {
struct Picture;
struct VVEncCfg;
namespace vtmrc {
struct Decision { int targetBits; int qp; double lambda; };
class Adapter
{
public:
  explicit Adapter(const VVEncCfg& cfg);
  void beginPicture(Picture& pic);
  Decision decideCtu(int ctu);
  void feedbackCtu(int ctu, int bits, int qp, double lambda, double skipRatio, double distortion);
  void finishPicture(int poc, int headerBits, int totalBits);
  VtmRcPic& picture() { return *m_rc.getRCPic(); }
  bool active() const { return m_active; }
private:
  const VVEncCfg& m_cfg;
  VtmRateCtrl m_rc;
  std::ofstream m_trace;
  bool m_active = false, m_pending = false, m_hasGop = false;
  bool m_irap = false, m_intra = false;
  int m_poc = -1, m_estimatedBits = 0, m_picQp = 0;
  double m_picLambda = 0.0;
  std::unique_ptr<gaze::Runtime> m_gaze;
  void trace(const char* event, int ctu, int bits, int qp, double lambda);
};
} }
