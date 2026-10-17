#include "CommonLib/IeprOnnx.h"
#include <cmath>
#include <cstring>
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <filesystem>
#include <cmath>
#include <stdexcept>
#include <algorithm>

#define CP_UTF8_here                   65001       // UTF-8 translation

extern int cntNum;

extern int down_x;

// Minimal .npy writer for float32, little-endian, C-order
static bool write_npy_f32(const std::string& path,
                          const float* data,
                          size_t count,
                          const std::vector<int64_t>& shape)
{
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;

    // magic + version
    const unsigned char magic[] = {0x93,'N','U','M','P','Y'};
    std::fwrite(magic, 1, 6, f);
    unsigned char ver[2] = {1, 0};
    std::fwrite(ver, 1, 2, f);

    // build header dict
    std::ostringstream oss;
    oss << "{'descr': '<f4', 'fortran_order': False, 'shape': (";
    for (size_t i = 0; i < shape.size(); ++i) {
        oss << shape[i];
        if (i + 1 < shape.size()) oss << ", ";
    }
    if (shape.size() == 1) oss << ","; // python tuple 1 elem needs trailing comma
    oss << "), }";

    std::string header = oss.str();
    // pad header so that magic(6)+ver(2)+hlen(2)+header is aligned to 16 bytes
    // NPY v1.0 uses uint16 header length
    size_t header_len = header.size() + 1; // include '\n'
    size_t preamble = 6 + 2 + 2;
    size_t pad = 16 - ((preamble + header_len) % 16);
    if (pad == 16) pad = 0;
    header.append(pad, ' ');
    header.push_back('\n');

    uint16_t hlen = static_cast<uint16_t>(header.size());
    std::fwrite(&hlen, 2, 1, f);
    std::fwrite(header.data(), 1, header.size(), f);

    // write data
    std::fwrite(data, sizeof(float), count, f);
    std::fclose(f);
    return true;
}

#if defined(_WIN32)
  #include <direct.h>   // _mkdir
  #define MKDIR(path) _mkdir(path)
#else
  #include <sys/stat.h>
  #define MKDIR(path) mkdir(path, 0755)
#endif

static void ensure_dir_recursive(const std::string& dir)
{
    if (dir.empty()) return;

    // 把 '\' 统一成 '/'
    std::string path = dir;
    for (auto& c : path) if (c == '\\') c = '/';

    std::string cur;
    cur.reserve(path.size());

    for (size_t i = 0; i < path.size(); ++i)
    {
        cur.push_back(path[i]);

        // 遇到分隔符就尝试创建
        if (path[i] == '/')
        {
            if (cur.size() > 1) MKDIR(cur.c_str()); // 忽略已存在错误
        }
    }
    // 创建最终目录
    MKDIR(cur.c_str());
}

#ifdef _WIN32
static std::wstring utf8_to_wstring(const std::string& s)
{
  if (s.empty()) return L"";

  int len = ::MultiByteToWideChar(CP_UTF8_here, 0, s.c_str(), -1, nullptr, 0);
  if (len <= 0) return L"";

  std::vector<wchar_t> buf(len); // len 包含结尾 '\0'
  ::MultiByteToWideChar(CP_UTF8_here, 0, s.c_str(), -1, buf.data(), len);

  return std::wstring(buf.data()); // buf 已含 '\0'
}

#endif

static inline int bucket_id_from_y0(float y0, int blk_h, float frame_h, float eps_cos = 0.20f)
{
    // y_center = y0 + H/2 + 0.5
    const float y_center = y0 + 0.5f + 0.5f * float(blk_h);
    const float phi = float(PI) * 0.5f - float(PI) * (y_center / frame_h);
    float abs_cos = std::abs(std::cos(phi));
    abs_cos = max(abs_cos, eps_cos);

    if (abs_cos < 0.3f) return 0;
    if (abs_cos < 0.6f) return 1;
    if (abs_cos < 0.9f) return 2;
    return 3;
}

// 从单个路径自动生成 bucket0~3 路径：
// 兼容三种写法：
//  1) "...bucket0....onnx" -> 替换 0 为 i
//  2) "...{bucket}....onnx" -> 替换 {bucket}
//  3) "xxx.onnx" -> 插入 "_bucket{i}" 在 .onnx 前
static inline std::string make_bucket_path(const std::string& modelPath, int i)
{
    std::string p = modelPath;

    // case 1: contains "{bucket}"
    const std::string key = "{bucket}";
    auto pos = p.find(key);
    if (pos != std::string::npos) {
        p.replace(pos, key.size(), std::to_string(i));
        return p;
    }

    // case 2: contains "bucket0"
    const std::string b0 = "bucket0";
    pos = p.find(b0);
    if (pos != std::string::npos) {
        p.replace(pos, b0.size(), "bucket" + std::to_string(i));
        return p;
    }

    // case 3: insert before ".onnx"
    pos = p.rfind(".onnx");
    if (pos != std::string::npos) {
        p.insert(pos, "_bucket" + std::to_string(i));
        return p;
    }

    // fallback
    return p + "_bucket" + std::to_string(i) + ".onnx";
}

namespace vvenc {

bool IeprOnnx::initBucket(const std::string& modelPath)
{
    m_sessOpt.SetIntraOpNumThreads(1);
    m_sessOpt.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

    try
    {
        Ort::AllocatorWithDefaultOptions alloc;

        // 0) 清理旧 session
        for (int i = 0; i < kNumBuckets; ++i) m_sessBuckets[i].reset();
        m_sess.reset(); // 如你仍保留单模型兼容，可不删，但这里清掉避免误用

        // 1) 加载 per-bucket sessions
        for (int i = 0; i < kNumBuckets; ++i)
        {
            const std::string path_i = make_bucket_path(modelPath, i);
            std::wstring wpath = utf8_to_wstring(path_i);
            m_sessBuckets[i] = std::make_unique<Ort::Session>(m_env, wpath.c_str(), m_sessOpt);

            if (!m_sessBuckets[i]) {
                printf("[IEPR] bucket %d session is null after construction.\n", i);
                m_ready = false;
                return false;
            }
            printf("[IEPR] loaded bucket %d: %s\n", i, path_i.c_str());
        }

        // 2) 读取输入/输出 names：用 bucket0 作为基准
        Ort::Session* sess0 = m_sessBuckets[0].get();
        size_t nIn  = sess0->GetInputCount();
        size_t nOut = sess0->GetOutputCount();

        printf("[IEPR] Model input count = %zu\n", nIn);

        m_inNames.resize(nIn);
        m_inNameStr.resize(nIn);
        for (size_t i = 0; i < nIn; i++)
        {
            auto name = sess0->GetInputNameAllocated(i, alloc);
            m_inNameStr[i] = name.get();
            m_inNames[i] = m_inNameStr[i].c_str();
        }

        m_outNames.resize(nOut);
        m_outNameStr.resize(nOut);
        for (size_t i = 0; i < nOut; i++)
        {
            auto name = sess0->GetOutputNameAllocated(i, alloc);
            m_outNameStr[i] = name.get();
            m_outNames[i] = m_outNameStr[i].c_str();
        }

        // （可选）检查 bucket1~3 的输入输出名是否一致（强烈建议调试阶段打开）
        for (int b = 1; b < kNumBuckets; ++b) {
            Ort::Session* sb = m_sessBuckets[b].get();
            if (!sb) continue;

            if (sb->GetInputCount() != nIn || sb->GetOutputCount() != nOut) {
                printf("[IEPR] bucket %d IO count mismatch!\n", b);
            }
        }

        m_inTensor.clear();
        m_outTensor.clear();

        printf("[IEPR] nIn=%zu nOut=%zu\n", nIn, nOut);
        for (size_t i = 0; i < nIn; i++)  printf("[IEPR] in[%zu]=%s\n", i, m_inNames[i]);
        for (size_t i = 0; i < nOut; i++) printf("[IEPR] out[%zu]=%s\n", i, m_outNames[i]);

        m_ready = true;
        return true;
    }
    catch (const Ort::Exception& e)
    {
        printf("[IEPR] ORT exception in init: %s\n", e.what());
        for (int i = 0; i < kNumBuckets; ++i) m_sessBuckets[i].reset();
        m_sess.reset();
        m_ready = false;
        return false;
    }
}

bool IeprOnnx::init( const std::string& modelPath )
{
  m_ready = false;
  m_sess.reset();

  try
  {
    m_sessOpt.SetIntraOpNumThreads( 1 );
    m_sessOpt.SetGraphOptimizationLevel( GraphOptimizationLevel::ORT_ENABLE_ALL );

#ifdef _WIN32
    const std::wstring wpath = utf8_to_wstring( modelPath );
    m_sess = std::make_unique<Ort::Session>( m_env, wpath.c_str(), m_sessOpt );
#else
    m_sess = std::make_unique<Ort::Session>( m_env, modelPath.c_str(), m_sessOpt );
#endif

    Ort::AllocatorWithDefaultOptions alloc;

    // Input names
    const size_t nIn = m_sess->GetInputCount();
    m_inNameStr.resize( nIn );
    m_inNames.resize( nIn );
    for( size_t i = 0; i < nIn; i++ )
    {
      auto nm = m_sess->GetInputNameAllocated( i, alloc );
      m_inNameStr[i] = nm.get();
      m_inNames[i]   = m_inNameStr[i].c_str();
    }

    // Output names
    const size_t nOut = m_sess->GetOutputCount();
    m_outNameStr.resize( nOut );
    m_outNames.resize( nOut );
    for( size_t i = 0; i < nOut; i++ )
    {
      auto nm = m_sess->GetOutputNameAllocated( i, alloc );
      m_outNameStr[i] = nm.get();
      m_outNames[i]   = m_outNameStr[i].c_str();
    }

    // Hard check: 3-input model expected
    if( nIn != 5 )
    {
      std::printf( "[IEPR] init failed: expected 3 inputs, got %zu\n", nIn );
      return false;
    }

    m_ready = true;

    std::printf("[IEPR] init ok. inputs:\n");
    /*for( size_t i=0;i<nIn;i++ )  std::printf("  in[%zu]=%s\n", i, m_inNames[i]);
    for( size_t i=0;i<nOut;i++ ) std::printf("  out[%zu]=%s\n", i, m_outNames[i]);*/

    return true;
  }
  catch( const Ort::Exception& e )
  {
    std::printf( "[IEPR] ORT exception in init: %s\n", e.what() );
    m_ready = false;
    m_sess.reset();
    return false;
  }
}

float calculateSSIM(const Pel* pred, const CPelBuf& ref, int H, int W, float clpRngMax) 
{
    const float K1 = 0.01f;
    const float K2 = 0.03f;
    const float C1 = (K1 * clpRngMax) * (K1 * clpRngMax);
    const float C2 = (K2 * clpRngMax) * (K2 * clpRngMax);
    const float inv = 1.0f / clpRngMax;

    // 计算均值、方差、协方差
    float mu_p = 0.0f, mu_r = 0.0f;
    float mu_p_sq = 0.0f, mu_r_sq = 0.0f, mu_pr = 0.0f;
    int pixel_count = H * W;

    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            int idx = y * W + x;
            float p = static_cast<float>(pred[idx]) * inv;
            float r = static_cast<float>(ref.at(x, y)) * inv;

            mu_p += p;
            mu_r += r;
            mu_p_sq += p * p;
            mu_r_sq += r * r;
            mu_pr += p * r;
        }
    }

    mu_p /= pixel_count;
    mu_r /= pixel_count;
    mu_p_sq /= pixel_count;
    mu_r_sq /= pixel_count;
    mu_pr /= pixel_count;

    float sigma_p_sq = mu_p_sq - (mu_p * mu_p);
    float sigma_r_sq = mu_r_sq - (mu_r * mu_r);
    float sigma_pr = mu_pr - (mu_p * mu_r);

    // 计算SSIM
    float numerator = (2 * mu_p * mu_r + C1) * (2 * sigma_pr + C2);
    float denominator = (mu_p * mu_p + mu_r * mu_r + C1) * (sigma_p_sq + sigma_r_sq + C2);
        
    return denominator == 0.0f ? 1.0f : (numerator / denominator);
}

    // 修改后的apply函数：满足2个核心要求
void IeprOnnx::apply(
    Pel* pred,                // 输入1：pred [1,1,H,W]
    const CPelBuf& ref0,      // 辅助：用于计算SSIM0（原始refY0）
    const CPelBuf& ref1,      // 辅助：用于计算SSIM1（原始refY1）
    PelBuf& predOut,          // 输出：修正后的pred
    const float* mv0,          // 输入2：mv [1,2]
    const float* mv1,          // 输入2：mv [1,2]
    const float* y0,          // 输入3：y0 [1]
    const float* h,           // 输入4：h [1]
    const float* qp,          // 输入3：y0 [1]
    const ClpRng& clpRng      // 辅助：像素裁剪范围
) {
    if (!m_ready) { 
        std::cout << " return 7" << std::endl; 
        return; 
    }
  
    float clpRngMax = static_cast<float>((1 << clpRng.bd) - 1); // 像素最大值
    const float inv = 1.0f / clpRngMax; 

    int blk_w = ref0.width;
    int blk_h = ref0.height;
    const int hw = blk_w * blk_h;

    // ========== 步骤1：计算SSIM0和SSIM1，选择最优ref ==========
    float ssim0 = calculateSSIM(pred, ref0, blk_h, blk_w, clpRngMax);
    float ssim1 = calculateSSIM(pred, ref1, blk_h, blk_w, clpRngMax);
    const CPelBuf& selected_ref = (ssim0 > ssim1) ? ref0 : ref1; // 取SSIM较大者对应的ref
    const float* selected_mv  = (ssim0 > ssim1) ? mv0 : mv1;

    //std::cout << "  apply: "<< " ssim0=" << ssim0 << " ssim1=" << ssim1 << " mvh=" << selected_mv[0] << " mvv=" << selected_mv[1] << " y0=" << *y0 << " h=" << *h << " clpRngMax="<<clpRngMax<<std::endl;
    // ========== 步骤2：调整输入缓冲区大小（适配新的5个输入参数） ==========
    // 包含：pred[hw] + selected_ref[hw] + mv[2] + y0[1] + h[1]
    m_inTensor.resize(static_cast<size_t>(hw) * 2); 

    float* base = m_inTensor.data();

    // 拷贝mv数据（[1,2]维度）
    m_mvTensor[0] = selected_mv[0];
    m_mvTensor[1] = selected_mv[1];

    // 拷贝y0和h数据（[1]维度）
    m_posyTensor = *y0;
    m_hTensor = *h;
    m_qpTensor = *qp;

    // ========== 步骤3：填充pred和最优ref的像素数据（[1,1,H,W]维度） ==========
    for (int y = 0; y < blk_h; y++) {
        for (int x = 0; x < blk_w; x++) {
            const int idx = y * blk_w + x;
            // 填充pred数据（归一化）
            base[0 * hw + idx] = static_cast<float>(pred[idx]) * inv;
            // 填充选中的ref数据（归一化）
            base[1 * hw + idx] = static_cast<float>(selected_ref.at(x, y)) * inv;
        }
    }

    // ========== 步骤4：定义各输入张量的维度 ==========
    int64_t inShp_4d[4] = {1, 1, blk_h, blk_w}; // pred/ref [1,1,H,W]
    int64_t inShp_2d[2] = {1, 2};                       // mv [1,2]
    int64_t inShp_1d[1] = {1};                          // y0/h [1]

    // ========== 步骤5：构造5个输入Ort::Value（与m_inNames顺序一致） ==========
    std::vector<Ort::Value> inVals;
    inVals.reserve(m_inNames.size());

    for (size_t i = 0; i < m_inNames.size(); i++) {
        const std::string& nm = m_inNameStr[i];
        float* ptr = nullptr;
        int64_t* shp = nullptr;
        size_t shp_dim = 0;
        size_t elem_count = 0;

        // 匹配新的5个输入参数
        if (nm == "pred") { 
            ptr = base + 0 * hw; 
            shp = inShp_4d; 
            shp_dim = 4;
            elem_count = hw;
        }
        else if (nm == "ref") { 
            ptr = base + 1 * hw; 
            shp = inShp_4d; 
            shp_dim = 4;
            elem_count = hw;
        }
        else if (nm == "mv") {
            ptr = m_mvTensor;
            shp = inShp_2d;
            shp_dim = 2;
            elem_count = 2;
        }/**/
       /* else if (nm == "qp") {
            ptr = m_qpTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }*/
        else if (nm == "y0") {
            ptr = &m_posyTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }
        else if (nm == "frame_h") {
            ptr = &m_hTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }/**/
        else {
            printf("[IEPR] unexpected input name: %s\n", nm.c_str());
            return;
        }

        inVals.emplace_back(
            Ort::Value::CreateTensor<float>(
                m_memInfo, ptr, elem_count, shp, shp_dim
            )
        );
    }


    // ========== per-bucket：选择 session ==========
    const int bid = bucket_id_from_y0(m_posyTensor, blk_h, m_hTensor, 0.20f);
    Ort::Session* sess = (bid >= 0 && bid < kNumBuckets) ? m_sessBuckets[bid].get() : nullptr;
    if (!sess) {
        printf("[IEPR] bucket session missing: bid=%d\n", bid);
        return;
    }

    // ========== 步骤6：运行ONNX模型（带异常捕获） ==========
    std::vector<Ort::Value> outVals;
    try {
        outVals = sess->Run(
            Ort::RunOptions{ nullptr },
            m_inNames.data(), inVals.data(), inVals.size(),
            m_outNames.data(), m_outNames.size()
        );
    }
    catch (const Ort::Exception& e) {
        printf("[IEPR] ORT Run failed (bucket=%d): %s\n", bid, e.what());
        // 不建议这里直接 m_ready=false（否则某个桶坏了全关）
        return;
    }

    // ===== DUMP: ORT output (float) =====
    //if (m_dumpEnable && m_dumpCount < m_dumpMax) {
    //    std::ostringstream ddir;
    //    ddir << m_dumpRoot << "/case_" << std::setw(4) << std::setfill('0') << m_dumpCount;
    //    const std::string dir = ddir.str();
    //    float* out = outVals[0].GetTensorMutableData<float>();
    //    write_npy_f32(dir + "/out_enc.npy", out, (size_t)hw, {1,1,blk_h,blk_w});
    //    // dump encoder-side postprocess result too (Pel) if you want (optional)
    //    // 这里略：如果需要我可以给一个 Pel->u16 的 .npy dump
    //    m_dumpCount++;
    //}


    // ========== 步骤7：写回修正后的predOut ==========
    float* out = outVals[0].GetTensorMutableData<float>();
    int sumdiff = 0;
    for (int y = 0; y < blk_h; y++) {
        for (int x = 0; x < blk_w; x++) {
            const int idx = y * blk_w + x;
            const float v = out[idx] * clpRngMax;
            const int iv = static_cast<int>(std::lround(v));
            predOut.at(x, y) = static_cast<Pel>(ClipPel(iv, clpRng));
            sumdiff += abs(static_cast<int>(predOut.at(x, y)) - static_cast<int>(pred[idx]));
        }
    }
    //float ssim = calculateSSIM(pred, predOut, blk_h, blk_w, clpRngMax);
    //std::cout << "   in-out sumdiff=" << sumdiff ;//<< std::endl
}

void IeprOnnx::applyRD(
    Pel* pred,                // 输入1：pred [1,1,H,W]
    const CPelBuf& ref0,      // 辅助：用于计算SSIM0（原始refY0）
    const CPelBuf& ref1,      // 辅助：用于计算SSIM1（原始refY1）
    PelBuf& predOut,          // 输出：修正后的pred
    const float* mv0,          // 输入2：mv [1,2]
    const float* mv1,          // 输入2：mv [1,2]
    const float* y0,          // 输入3：y0 [1]
    const float* h,           // 输入4：h [1]
    const float* qp,          // 输入3：y0 [1]
    const ClpRng& clpRng      // 辅助：像素裁剪范围
) {
    if (!m_ready) { 
        std::cout << " return 7" << std::endl; 
        return; 
    }
  
    float clpRngMax = static_cast<float>((1 << clpRng.bd) - 1); // 像素最大值
    const float inv = 1.0f / clpRngMax; 

    int blk_w = ref0.width;
    int blk_h = ref0.height;
    const int hw = blk_w * blk_h;

    // ========== 步骤1：计算SSIM0和SSIM1，选择最优ref ==========
    float ssim0 = calculateSSIM(pred, ref0, blk_h, blk_w, clpRngMax);
    float ssim1 = calculateSSIM(pred, ref1, blk_h, blk_w, clpRngMax);
    const CPelBuf& selected_ref = (ssim0 > ssim1) ? ref0 : ref1; // 取SSIM较大者对应的ref
    const float* selected_mv  = (ssim0 > ssim1) ? mv0 : mv1;

    //std::cout << "  before: w=" << blk_w << " h=" << blk_h << " inv=" << inv << " ssim0=" << ssim0 << " ssim1=" << ssim1 << " mvh=" << selected_mv[0] << " mvv=" << selected_mv[1] << " y0=" << *y0 << " h=" << *h << std::endl;
    // ========== 步骤2：调整输入缓冲区大小（适配新的5个输入参数） ==========
    // 包含：pred[hw] + selected_ref[hw] + mv[2] + y0[1] + h[1]
    m_inTensor.resize(static_cast<size_t>(hw * 2)); 

    float* base = m_inTensor.data();

    // 拷贝mv数据（[1,2]维度）
    m_mvTensor[0] = selected_mv[0];
    m_mvTensor[1] = selected_mv[1];

    // 拷贝y0和h数据（[1]维度）
    m_posyTensor = *y0;
    m_hTensor = *h;
    m_qpTensor = *qp;

    // ========== 步骤3：填充pred和最优ref的像素数据（[1,1,H,W]维度） ==========
    for (int y = 0; y < blk_h; y++) {
        for (int x = 0; x < blk_w; x++) {
            const int idx = y * blk_w + x;
            // 填充pred数据（归一化）
            base[0 * hw + idx] = static_cast<float>(pred[idx]) * inv;
            // 填充选中的ref数据（归一化）
            base[1 * hw + idx] = static_cast<float>(selected_ref.at(x, y)) * inv;
        }
    }

    // ========== 步骤4：定义各输入张量的维度 ==========
    int64_t inShp_4d[4] = {1, 1, blk_h, blk_w}; // pred/ref [1,1,H,W]
    int64_t inShp_2d[2] = {1, 2};                       // mv [1,2]
    int64_t inShp_1d[1] = {1};                          // y0/h [1]

    // ========== 步骤5：构造5个输入Ort::Value（与m_inNames顺序一致） ==========
    std::vector<Ort::Value> inVals;
    inVals.reserve(m_inNames.size());

    for (size_t i = 0; i < m_inNames.size(); i++) {
        const std::string& nm = m_inNameStr[i];
        float* ptr = nullptr;
        int64_t* shp = nullptr;
        size_t shp_dim = 0;
        size_t elem_count = 0;

        // 匹配新的5个输入参数
        if (nm == "pred") { 
            ptr = base + 0 * hw; 
            shp = inShp_4d; 
            shp_dim = 4;
            elem_count = hw;
        }
        else if (nm == "ref0") { 
            ptr = base + 1 * hw; 
            shp = inShp_4d; 
            shp_dim = 4;
            elem_count = hw;
        }
        else if (nm == "mv") {
            ptr = m_mvTensor;
            shp = inShp_2d;
            shp_dim = 2;
            elem_count = 2;
        }
        /*else if (nm == "qp") {
            ptr = &m_qpTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }*/
        else if (nm == "y0") {
            ptr = &m_posyTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }
        else if (nm == "frame_h") {
            ptr = &m_hTensor;
            shp = inShp_1d;
            shp_dim = 1;
            elem_count = 1;
        }/**/
        else {
            printf("[IEPR] unexpected input name: %s\n", nm.c_str());
            return;
        }

        inVals.emplace_back(
            Ort::Value::CreateTensor<float>(
                m_memInfo, ptr, elem_count, shp, shp_dim
            )
        );
    }

    // ========== 步骤6：运行ONNX模型（带异常捕获） ==========
    std::vector<Ort::Value> outVals;
    try {
        outVals = m_sess->Run(
            Ort::RunOptions{ nullptr },
            m_inNames.data(), inVals.data(), inVals.size(),
            m_outNames.data(), m_outNames.size()
        );
    }
    catch (const Ort::Exception& e) {
        printf("[IEPR] ORT Run failed: %s\n", e.what());
        m_ready = false; // 失败后禁用，避免重复崩溃
        return;
    }

    // ========== 步骤7：写回修正后的predOut ==========
    float* out = outVals[0].GetTensorMutableData<float>();
    int sumdiff = 0;
    for (int y = 0; y < blk_h; y++) {
        for (int x = 0; x < blk_w; x++) {
            const int idx = y * blk_w + x;
            const float v = out[idx] * clpRngMax;
            const int iv = static_cast<int>(std::lround(v));
            predOut.at(x, y) = static_cast<Pel>(ClipPel(iv, clpRng));
            sumdiff += abs(static_cast<int>(predOut.at(x, y)) - static_cast<int>(pred[idx]));
        }
    }
}

//=================================================================== ref ==========================================
#include <cmath>
#include <algorithm>
#include <stdexcept>

static void buildLatitudeImportancePriorRaw(
    std::vector<float>& wPrior,
    int blk_h,
    float pos_y,
    float frame_h,
    int down_x
)
{
    if (down_x <= 0)
    {
        throw std::runtime_error("down_x must be positive");
    }
    if (blk_h % down_x != 0)
    {
        throw std::runtime_error("blk_h must be divisible by down_x");
    }
    if (frame_h <= 0.0f)
    {
        throw std::runtime_error("frame_h must be positive");
    }

    const int feat_h = blk_h / down_x;
    std::vector<float> wFull(blk_h, 0.0f);

    for (int r = 0; r < blk_h; ++r)
    {
        const float global_y = pos_y + static_cast<float>(r);
        const float theta = static_cast<float>(PI) * ((global_y + 0.5f) / frame_h - 0.5f);
        const float w = std::cos(theta);
        wFull[r] = (std::max)(0.0f, (std::min)(1.0f, w));
    }

    wPrior.assign(feat_h, 0.0f);
    for (int i = 0; i < feat_h; ++i)
    {
        float sum = 0.0f;
        for (int k = 0; k < down_x; ++k)
        {
            sum += wFull[i * down_x + k];
        }
        wPrior[i] = sum / static_cast<float>(down_x);
    }
}

void IeprOnnx::buildLatitudeImportancePriorCached(
    std::vector<float>& wPrior,
    int blk_h,
    float pos_y,
    float frame_h,
    int down_x
)
{
    // 这里把 float 坐标转成 int 做 key
    // 因为你的 pos_y / frame_h 本身就是像素坐标/高度，理论上应为整数
    const int pos_y_i = static_cast<int>(std::lround(pos_y));
    const int frame_h_i = static_cast<int>(std::lround(frame_h));

    WPriorCacheKey key{ blk_h, pos_y_i, frame_h_i, down_x };

    auto it = m_wPriorCache.find(key);
    if (it != m_wPriorCache.end())
    {
        wPrior = it->second;
        return;
    }

    buildLatitudeImportancePriorRaw(wPrior, blk_h, pos_y, frame_h, down_x);
    m_wPriorCache.emplace(key, wPrior);
}


bool IeprOnnx::initref(const std::string& modelPath)
{
    m_ready = false;

    try
    {
        std::wstring wpath = utf8_to_wstring(modelPath);
        m_sess.reset(new Ort::Session(m_env, wpath.c_str(), m_sessOpt));
    }
    catch (const Ort::Exception& e)
    {
        printf("[IEPR] init failed when creating session: %s\n", e.what());
        return false;
    }

    if (!m_sess)
    {
        printf("[IEPR] init failed: session is null\n");
        return false;
    }

    Ort::AllocatorWithDefaultOptions alloc;

    m_inNameStr.clear();
    m_outNameStr.clear();
    m_inNames.clear();
    m_outNames.clear();

    const size_t numInputs  = m_sess->GetInputCount();
    const size_t numOutputs = m_sess->GetOutputCount();

    if (numInputs != 1)
    {
        printf("[IEPR] init failed: expected 1 input, got %zu\n", numInputs);
        return false;
    }
    if (numOutputs != 1)
    {
        printf("[IEPR] init failed: expected 1 output, got %zu\n", numOutputs);
        return false;
    }

    // 读取输入名
    for (size_t i = 0; i < numInputs; ++i)
    {
#if ORT_API_VERSION >= 13
        Ort::AllocatedStringPtr namePtr = m_sess->GetInputNameAllocated(i, alloc);
        m_inNameStr.emplace_back(namePtr.get());
#else
        char* name = m_sess->GetInputName(i, alloc);
        m_inNameStr.emplace_back(name);
        alloc.Free(name);
#endif
    }

    // 读取输出名
    for (size_t i = 0; i < numOutputs; ++i)
    {
#if ORT_API_VERSION >= 13
        Ort::AllocatedStringPtr namePtr = m_sess->GetOutputNameAllocated(i, alloc);
        m_outNameStr.emplace_back(namePtr.get());
#else
        char* name = m_sess->GetOutputName(i, alloc);
        m_outNameStr.emplace_back(name);
        alloc.Free(name);
#endif
    }

    // 构造 const char* 指针数组
    for (auto& s : m_inNameStr)  { m_inNames.push_back(s.c_str()); }
    for (auto& s : m_outNameStr) { m_outNames.push_back(s.c_str()); }

    // 检查名字是否符合导出模型
    if (m_inNameStr[0] != "input")
    {
        printf("[IEPR] warning: input name is '%s', expected 'input'\n", m_inNameStr[0].c_str());
    }
    if (m_outNameStr[0] != "output")
    {
        printf("[IEPR] warning: output name is '%s', expected 'output'\n", m_outNameStr[0].c_str());
    }

    // 打印 shape 信息（便于确认）
    try
    {
        auto inTypeInfo = m_sess->GetInputTypeInfo(0).GetTensorTypeAndShapeInfo();
        auto inShape = inTypeInfo.GetShape();

        auto outTypeInfo = m_sess->GetOutputTypeInfo(0).GetTensorTypeAndShapeInfo();
        auto outShape = outTypeInfo.GetShape();

        printf("[IEPR] ONNX input[0] name=%s shape=[", m_inNameStr[0].c_str());
        for (size_t i = 0; i < inShape.size(); ++i)
        {
            printf("%lld%s", (long long)inShape[i], (i + 1 < inShape.size()) ? "," : "");
        }
        printf("]\n");

        printf("[IEPR] ONNX output[0] name=%s shape=[", m_outNameStr[0].c_str());
        for (size_t i = 0; i < outShape.size(); ++i)
        {
            printf("%lld%s", (long long)outShape[i], (i + 1 < outShape.size()) ? "," : "");
        }
        printf("]\n");
    }
    catch (const Ort::Exception& e)
    {
        printf("[IEPR] warning: failed to query IO shapes: %s\n", e.what());
    }

    m_ready = true;
    return true;
}

void IeprOnnx::applyRef(
    Pel* pred,                // 输入1：pred [1,1,H,W]
    const CPelBuf& ref0,      // 辅助：用于计算SSIM0（原始refY0）
    const CPelBuf& ref1,      // 辅助：用于计算SSIM1（原始refY1）
    PelBuf& predOut,          // 输出：修正后的pred
    const float* mv0,          // 输入2：mv [1,2]
    const float* mv1,          // 输入2：mv [1,2]
    const float* y0,          // 输入3：y0 [1]
    const float* h,           // 输入4：h [1]
    const float* qp,          // 输入3：y0 [1]
    const ClpRng& clpRng      // 辅助：像素裁剪范围
) {
    if (!m_ready) { 
        std::cout << "[IEPR] session not ready\n";
        return; 
    }
  
    float clpRngMax = static_cast<float>((1 << clpRng.bd) - 1); // 像素最大值
    const float inv = 1.0f / (clpRngMax+1.0f); 

    int blk_w = ref0.width;
    int blk_h = ref0.height;
    const int hw = blk_w * blk_h;

    // ------------------------------------------------------------
    // 2) 构造 ONNX 单输入张量 input:[1,3,H,W]
    //    与当前训练脚本保持一致:
    //      C[0] = ref0
    //      C[1] = pred
    //      C[2] = ref1
    // ------------------------------------------------------------
    const size_t elemCount = static_cast<size_t>(3) * hw;
    m_inTensor.resize(elemCount);
    float* base = m_inTensor.data();

    float* ch0 = base + 0 * hw;  // ref
    float* ch1 = base + 1 * hw;  // pred
    float* ch2 = base + 2 * hw;  // ref

    for (int y = 0; y < blk_h; ++y) {
        for (int x = 0; x < blk_w; ++x) {
            const int idx = y * blk_w + x;

            const float p = static_cast<float>(pred[idx]) * inv - 0.5f;
            const float r0 = static_cast<float>(ref0.at(x, y)) * inv - 0.5f;
            const float r1 = static_cast<float>(ref1.at(x, y)) * inv - 0.5f;

            ch0[idx] = r0;
            ch1[idx] = p;
            ch2[idx] = r1;
        }
    }

    // ------------------------------------------------------------
    // 3) 创建单输入 tensor
    // ------------------------------------------------------------
    const int64_t inShape[4] = { 1, 3, blk_h, blk_w };

    std::vector<Ort::Value> inVals;
    inVals.reserve(1);
    inVals.emplace_back(
        Ort::Value::CreateTensor<float>(
            m_memInfo,
            base,
            elemCount,
            inShape,
            4
        )
    );

   // ------------------------------------------------------------
    // 4) 输入输出名字
    //    导出的 ONNX 中默认是:
    //      input  = "input"
    //      output = "output"
    // ------------------------------------------------------------
    static const char* kInputNames[]  = { "input" };
    static const char* kOutputNames[] = { "output" };

    // 如果你 init() 时已经从 session 里读到了真实名字，
    // 也可以改成用 m_inNames/m_outNames，但前提是模型确实只有一个输入输出。
    std::vector<Ort::Value> outVals;
    try {
        outVals = m_sess->Run(
            Ort::RunOptions{ nullptr },
            kInputNames,
            inVals.data(),
            1,
            kOutputNames,
            1
        );
    }
    catch (const Ort::Exception& e) {
        printf("[IEPR] ORT Run failed: %s\n", e.what());
        m_ready = false;
        return;
    }

    if (outVals.empty() || !outVals[0].IsTensor()) {
        printf("[IEPR] invalid ONNX output.\n");
        return;
    }

    // ========== 步骤7：写回修正后的predOut ==========
    float* out = outVals[0].GetTensorMutableData<float>();
    int sumdiff = 0;
    for (int y = 0; y < blk_h; y++) {
        for (int x = 0; x < blk_w; x++) {
            const int idx = y * blk_w + x;
            const float v = (out[idx] + 0.5 )* (clpRngMax + 1);
            const int iv = static_cast<int>(std::lround(v));
            predOut.at(x, y) = static_cast<Pel>(ClipPel(iv, clpRng));
            sumdiff += abs(static_cast<int>(predOut.at(x, y)) - static_cast<int>(pred[idx]));
        }
    }
}

bool IeprOnnx::initLISTRN(const std::string& modelPath)
{
    m_ready = false;

    try
    {
        std::wstring wpath = utf8_to_wstring(modelPath);
        m_sess.reset(new Ort::Session(m_env, wpath.c_str(), m_sessOpt));
    }
    catch (const Ort::Exception& e)
    {
        printf("[IEPR] init failed when creating session: %s\n", e.what());
        return false;
    }

    if (!m_sess)
    {
        printf("[IEPR] init failed: session is null\n");
        return false;
    }

    Ort::AllocatorWithDefaultOptions alloc;

    m_inNameStr.clear();
    m_outNameStr.clear();
    m_inNames.clear();
    m_outNames.clear();

    const size_t numInputs  = m_sess->GetInputCount();
    const size_t numOutputs = m_sess->GetOutputCount();

    // 现在模型应当有 3 个输入: input, pos_y, frame_h
    if (numInputs != 2)
    {
        printf("[IEPR] init failed: expected 3 inputs, got %zu\n", numInputs);
        return false;
    }
    if (numOutputs != 1)
    {
        printf("[IEPR] init failed: expected 1 output, got %zu\n", numOutputs);
        return false;
    }

    // 读取输入名
    for (size_t i = 0; i < numInputs; ++i)
    {
#if ORT_API_VERSION >= 13
        Ort::AllocatedStringPtr namePtr = m_sess->GetInputNameAllocated(i, alloc);
        m_inNameStr.emplace_back(namePtr.get());
#else
        char* name = m_sess->GetInputName(i, alloc);
        m_inNameStr.emplace_back(name);
        alloc.Free(name);
#endif
    }

    // 读取输出名
    for (size_t i = 0; i < numOutputs; ++i)
    {
#if ORT_API_VERSION >= 13
        Ort::AllocatedStringPtr namePtr = m_sess->GetOutputNameAllocated(i, alloc);
        m_outNameStr.emplace_back(namePtr.get());
#else
        char* name = m_sess->GetOutputName(i, alloc);
        m_outNameStr.emplace_back(name);
        alloc.Free(name);
#endif
    }

    // 构造 const char* 指针数组
    for (auto& s : m_inNameStr)  { m_inNames.push_back(s.c_str()); }
    for (auto& s : m_outNameStr) { m_outNames.push_back(s.c_str()); }

    // 记录输入名位置，避免依赖导出顺序
    int idxInput  = -1;
    int idxWPrior  = -1;

    for (int i = 0; i < static_cast<int>(m_inNameStr.size()); ++i)
    {
        if (m_inNameStr[i] == "input")   idxInput  = i;
        if (m_inNameStr[i] == "w_prior")   idxWPrior   = i;
    }

    if (idxInput < 0 || idxWPrior  < 0 )
    {
        printf("[IEPR] init failed: required inputs {input, pos_y, frame_h} not all found.\n");
        for (size_t i = 0; i < m_inNameStr.size(); ++i)
        {
            printf("[IEPR] found input[%zu] = %s\n", i, m_inNameStr[i].c_str());
        }
        return false;
    }

    if (m_outNameStr[0] != "output")
    {
        printf("[IEPR] warning: output name is '%s', expected 'output'\n", m_outNameStr[0].c_str());
    }

    // 打印所有输入输出 shape 信息
    try
    {
        for (size_t i = 0; i < numInputs; ++i)
        {
            auto inTypeInfo = m_sess->GetInputTypeInfo(i).GetTensorTypeAndShapeInfo();
            auto inShape = inTypeInfo.GetShape();

            printf("[IEPR] ONNX input[%zu] name=%s shape=[", i, m_inNameStr[i].c_str());
            for (size_t k = 0; k < inShape.size(); ++k)
            {
                printf("%lld%s", (long long)inShape[k], (k + 1 < inShape.size()) ? "," : "");
            }
            printf("]\n");
        }

        for (size_t i = 0; i < numOutputs; ++i)
        {
            auto outTypeInfo = m_sess->GetOutputTypeInfo(i).GetTensorTypeAndShapeInfo();
            auto outShape = outTypeInfo.GetShape();

            printf("[IEPR] ONNX output[%zu] name=%s shape=[", i, m_outNameStr[i].c_str());
            for (size_t k = 0; k < outShape.size(); ++k)
            {
                printf("%lld%s", (long long)outShape[k], (k + 1 < outShape.size()) ? "," : "");
            }
            printf("]\n");
        }
    }
    catch (const Ort::Exception& e)
    {
        printf("[IEPR] warning: failed to query IO shapes: %s\n", e.what());
    }

    m_ready = true;
    return true;
}

void IeprOnnx::applyLISTRN(
    Pel* pred,                // 输入1：pred [1,1,H,W]
    const CPelBuf& ref0,      // 辅助：用于计算SSIM0（原始refY0）
    const CPelBuf& ref1,      // 辅助：用于计算SSIM1（原始refY1）
    PelBuf& predOut,          // 输出：修正后的pred
    const float* mv0,          // 输入2：mv [1,2]
    const float* mv1,          // 输入2：mv [1,2]
    const float* y0,          // 输入3：y0 [1]
    const float* h,           // 输入4：h [1]
    const float* qp,          // 输入3：y0 [1]
    const ClpRng& clpRng      // 辅助：像素裁剪范围
)
{
    if (!m_ready || !m_sess) {
        std::cout << "[IEPR] session not ready\n";
        return;
    }

    const int blk_w = ref0.width;
    const int blk_h = ref0.height;
    const int hw    = blk_w * blk_h;

    // 与训练侧一致: x / (2^bitdepth) - 0.5
    const float denom = static_cast<float>(1 << clpRng.bd);  // 8bit->256, 10bit->1024
    const float inv   = 1.0f / denom;

    // ------------------------------------------------------------
    // 1) 构造主输入张量 input:[1,3,H,W]
    //    C[0] = ref0
    //    C[1] = pred
    //    C[2] = ref1
    // ------------------------------------------------------------
   /* const size_t elemCount = static_cast<size_t>(3) * hw;
    m_inTensor.resize(elemCount);
    float* base = m_inTensor.data();

    float* ch0 = base + 0 * hw;
    float* ch1 = base + 1 * hw;
    float* ch2 = base + 2 * hw;

    for (int yy = 0; yy < blk_h; ++yy) {
        for (int xx = 0; xx < blk_w; ++xx) {
            const int idx = yy * blk_w + xx;

            const float p  = static_cast<float>(pred[idx])       * inv - 0.5f;
            const float r0 = static_cast<float>(ref0.at(xx, yy)) * inv - 0.5f;
            const float r1 = static_cast<float>(ref1.at(xx, yy)) * inv - 0.5f;

            ch0[idx] = r0;
            ch1[idx] = p;
            ch2[idx] = r1;
        }
    }*/
    //-------------------------------------
    const size_t elemCount = static_cast<size_t>(1) * hw;
    m_inTensor.resize(elemCount);
    float* base = m_inTensor.data();

    float* ch0 = base + 0 * hw;
    for (int yy = 0; yy < blk_h; ++yy) {
        for (int xx = 0; xx < blk_w; ++xx) {
            const int idx = yy * blk_w + xx;

            const float p  = static_cast<float>(pred[idx])       * inv - 0.5f;

            ch0[idx] = p;

        }
    }

    // -----------------------------
    // 2) 构造 w_prior
    // -----------------------------
    const float posY   = (y0 != nullptr) ? *y0 : 0.0f;
    const float frameH = (h  != nullptr) ? *h  : 1.0f;

    // 你当前模型建议使用 down_x=2；如果类里有配置，可替换成成员变量
    //const int down_x = 2;

    if (blk_h % down_x != 0) {
        printf("[IEPR] blk_h=%d is not divisible by down_x=%d\n", blk_h, down_x);
        return;
    }

    const int feat_h = blk_h / down_x;
    m_wPriorTensor.clear();
    try {
        buildLatitudeImportancePriorCached(m_wPriorTensor, blk_h, posY, frameH, down_x);
    }
    catch (const std::exception& e) {
        printf("[IEPR] buildLatitudeImportancePriorCached failed: %s\n", e.what());
        return;
    }

    //// ------------------------------------------------------------
    //// 2) 构造 pos_y / frame_h 输入
    //// ------------------------------------------------------------
    //m_posyTensor = (y0 != nullptr) ? *y0 : 0.0f;
    //m_hTensor    = (h  != nullptr) ? *h  : 1.0f;

    //const int64_t inShape4d[4] = {1, 3, blk_h, blk_w};
    //const int64_t inShape1d[1] = {1};

    // ------------------------------------------------------------
    // 3) 按实际输入名顺序构造 Ort::Value
    // ------------------------------------------------------------
    const int64_t inShape4d[4] = {1, 1, blk_h, blk_w}; //--------------
    const int64_t wShape4d[4]  = {1, 1, feat_h, 1};

    std::vector<Ort::Value> inVals;
    inVals.reserve(m_inNames.size());

    for (size_t i = 0; i < m_inNames.size(); ++i)
    {
        const std::string& nm = m_inNameStr[i];

        if (nm == "input")
        {
            inVals.emplace_back(
                Ort::Value::CreateTensor<float>(
                    m_memInfo,
                    base,
                    elemCount,
                    inShape4d,
                    4
                )
            );
        }
        else if (nm == "w_prior")
        {
            inVals.emplace_back(
                Ort::Value::CreateTensor<float>(
                    m_memInfo,
                    m_wPriorTensor.data(),
                    m_wPriorTensor.size(),
                    wShape4d,
                    4
                )
            );
        }
        else
        {
            printf("[IEPR] unexpected input name: %s\n", nm.c_str());
            return;
        }
    }

    // ------------------------------------------------------------
    // 4) 运行 ONNX
    // ------------------------------------------------------------
    std::vector<Ort::Value> outVals;
    try {
        outVals = m_sess->Run(
            Ort::RunOptions{nullptr},
            m_inNames.data(),
            inVals.data(),
            inVals.size(),
            m_outNames.data(),
            m_outNames.size()
        );
    }
    catch (const Ort::Exception& e) {
        printf("[IEPR] ORT Run failed: %s\n", e.what());
        m_ready = false;
        return;
    }

    if (outVals.empty() || !outVals[0].IsTensor()) {
        printf("[IEPR] invalid ONNX output.\n");
        return;
    }

    // ------------------------------------------------------------
    // 5) 写回输出 output:[1,1,H,W]
    //    与训练侧逆变换一致: (out + 0.5) * (2^bitdepth)
    // ------------------------------------------------------------
    float* out = outVals[0].GetTensorMutableData<float>();

    int sumdiff = 0;
    for (int yy = 0; yy < blk_h; ++yy) {
        for (int xx = 0; xx < blk_w; ++xx) {
            const int idx = yy * blk_w + xx;

            const float v = (out[idx] + 0.5f) * denom;
            const int iv = static_cast<int>(std::lround(v));

            predOut.at(xx, yy) = static_cast<Pel>(ClipPel(iv, clpRng));
            sumdiff += std::abs(
                static_cast<int>(predOut.at(xx, yy)) -
                static_cast<int>(pred[idx])
            );
        }
    }

    // 可选调试
    // std::cout << "[IEPR] sumdiff=" << sumdiff
    //           << " pos_y=" << m_posyTensor
    //           << " frame_h=" << m_hTensor << std::endl;
}


} // namespace vvenc
