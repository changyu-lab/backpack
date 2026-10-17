#pragma once
#include <string>
#include <vector>
#include <array>
#include <memory>
#include <unordered_map>

#include "CommonLib/Unit.h"
#include "CommonLib/CommonDef.h"

#include <onnxruntime_cxx_api.h>
#if __has_include(<onnxruntime/core/session/onnxruntime_cxx_api.h>)
  #include <onnxruntime/core/session/onnxruntime_cxx_api.h>
  #include <onnxruntime/core/session/onnxruntime_c_api.h>
#elif __has_include(<onnxruntime_cxx_api.h>)
  #include <onnxruntime_cxx_api.h>
  #include <onnxruntime_c_api.h>
#else
  #error "ONNX Runtime headers not found"
#endif

namespace vvenc {

class IeprOnnx
{
public:
  IeprOnnx() = default;

  bool initBucket( const std::string& modelPath );
  bool init( const std::string& modelPath );
  bool ready() const { return m_ready; }

  // predY: in/out (修正后写回)
  // refY : inf
  //void apply( Pel* predtmp, PelBuf& predOut, const CPelBuf& refY0, const CPelBuf& refY1,int posy_val, const ClpRng& clpRng );
  
  void apply(Pel* pred,const CPelBuf& ref0,const CPelBuf& ref1,PelBuf& predOut,const float* mv0, const float* mv1,const float* y0,const float* h,const float* qp,const ClpRng& clpRng);
  void applyRD(Pel* pred,const CPelBuf& ref0,const CPelBuf& ref1,PelBuf& predOut,const float* mv0, const float* mv1,const float* y0,const float* h,const float* qp,const ClpRng& clpRng);
  
  bool initref( const std::string& modelPath );
  void applyRef(Pel* pred,const CPelBuf& ref0,const CPelBuf& ref1,PelBuf& predOut,const float* mv0, const float* mv1,const float* y0,const float* h,const float* qp,const ClpRng& clpRng);

  bool initLISTRN( const std::string& modelPath );
  void applyLISTRN(Pel* pred,const CPelBuf& ref0,const CPelBuf& ref1,PelBuf& predOut,const float* mv0, const float* mv1,const float* y0,const float* h,const float* qp,const ClpRng& clpRng);

  void buildLatitudeImportancePriorCached(std::vector<float>& wPrior,int blk_h,float pos_y,float frame_h,int down_x);

private:
  bool m_ready = false;

  Ort::Env     m_env{ ORT_LOGGING_LEVEL_WARNING, "iepr" };
  Ort::SessionOptions m_sessOpt;
  std::unique_ptr<Ort::Session> m_sess;
  Ort::MemoryInfo m_memInfo = Ort::MemoryInfo::CreateCpu( OrtArenaAllocator, OrtMemTypeDefault );
  
  static constexpr int kNumBuckets = 4;
  std::unique_ptr<Ort::Session> m_sessBuckets[kNumBuckets];

  std::vector<std::string> m_inNameStr, m_outNameStr;
  std::vector<const char*> m_inNames, m_outNames;
  std::vector<float> m_inTensor;
  std::vector<float> m_outTensor;  
  float m_posyTensor;              // 单独存储 posy 标量（形状 [1]）
  float m_mvTensor[2]; 
  float m_hTensor;
  float m_qpTensor;
  
  bool   m_dumpEnable = true;   // 需要时你可以改成从配置/环境变量读取
int    m_dumpMax    = 20;     // 只dump前20个块
int    m_dumpCount  = 0;
std::string m_dumpRoot = "iepr_dump"; // 相对路径：运行目录下

std::vector<float> m_wPriorTensor;

struct WPriorCacheKey
{
    int blk_h;
    int pos_y_i;
    int frame_h_i;
    int down_x;

    bool operator==(const WPriorCacheKey& other) const
    {
        return blk_h == other.blk_h &&
               pos_y_i == other.pos_y_i &&
               frame_h_i == other.frame_h_i &&
               down_x == other.down_x;
    }
};

struct WPriorCacheKeyHash
{
    std::size_t operator()(const WPriorCacheKey& k) const
    {
        std::size_t h1 = std::hash<int>{}(k.blk_h);
        std::size_t h2 = std::hash<int>{}(k.pos_y_i);
        std::size_t h3 = std::hash<int>{}(k.frame_h_i);
        std::size_t h4 = std::hash<int>{}(k.down_x);

        return (((h1 * 1315423911u) ^ h2) * 1315423911u ^ h3) * 1315423911u ^ h4;
    }
};

std::unordered_map<WPriorCacheKey, std::vector<float>, WPriorCacheKeyHash> m_wPriorCache;


};

} // namespace vvenc
