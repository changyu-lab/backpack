#pragma once

#include "CommonLib/CommonDef.h"

#if wref_bitallocation_frame

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

struct RC360GopFrameParams
{
  bool        enabled       = false;
  int         targetBitrate = 0;
  double      frameRate     = 30.0;
  int         smoothWindow  = 4;
  double      alphaF        = 1.0;
  double      betaF         = 1.0;
  double      eps           = 1e-6;
  double      etaMin        = 0.70;
  double      etaMax        = 1.30;
  int         frameWidth    = 0;
  int         frameHeight   = 0;
  std::string sequenceName;
  std::string frameStatsFile;
  std::string traceFile;
};

struct RC360FrameStat
{
  int    poc         = -1;
  double ieff        = 1.0;
  double wref        = 1.0;
  double wrefRawUnclipped = 1.0;
  double wrefRawClipped = 1.0;
  double wrefFinal = 1.0;
  bool   hasExternal = false;
};

struct RC360FrameAlloc
{
  int         poc         = -1;
  int         baseBits    = 0;
  int         targetBits  = 0;
  double      ieff        = 1.0;
  double      wref        = 1.0;
  double      wrefRawUnclipped = 1.0;
  double      wrefRawClipped = 1.0;
  double      wrefFinal = 1.0;
  double      pi          = 1.0;
  double      lower       = 0.0;
  double      upper       = 0.0;
  bool        isPFrame    = false;
  bool        modelValid  = false;
  double      qsModel     = 0.0;
  double      predBpp     = 0.0;
  double      predBits    = 0.0;
  double      predD       = 0.0;
  std::string modelName;
};

class RC360FrameRDModel
{
public:
  struct Coeff
  {
    const char* name = "";
    double ieffMedian = 1.0;
    double rate[6] = {};
    double dist[6] = {};
  };

  static const Coeff* matchSequence(const std::string& inputName)
  {
    const std::string lower = toLower(inputName);
    for (const Coeff& c : getModels())
    {
      if (lower.find(toLower(c.name)) != std::string::npos)
      {
        return &c;
      }
    }
    return nullptr;
  }

  static double predictBpp(const Coeff& c, double qs, double ieff, double eps)
  {
    return predict(c.rate, c.ieffMedian, qs, ieff, eps);
  }

  static double predictOrdinaryMse(const Coeff& c, double qs, double ieff, double eps)
  {
    return predict(c.dist, c.ieffMedian, qs, ieff, eps);
  }

private:
  static const std::vector<Coeff>& getModels()
  {
    static const std::vector<Coeff> models =
    {
      {
        "AerialCity",
        1286.23604078,
        { -0.456187, -1.478058, 5.467612, -1.028381, -0.846165, 0.009743 },
        {  5.399946, -0.351090, -0.272064, 0.090593, 0.128403, 0.062688 }
      },
      {
        "BranCastle2",
        5109.25746083,
        { 3.140655, -0.957085, 3.553101, -0.990462, -3.461940, -0.132175 },
        { 5.549105, -0.127271, 0.278329, -0.033418, -0.054403, 0.045205 }
      },
      {
        "DrivingInCity",
        3340.64952409,
        { 0.834651, -1.006339, 2.837957, -0.569112, -3.829339, -0.057515 },
        { 5.494319, -0.184835, 0.973342, -0.231463, -0.925104, 0.035922 }
      }
    };
    return models;
  }

  static std::string toLower(const std::string& s)
  {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) { return char(std::tolower(c)); });
    return out;
  }

  static double predict(const double c[6], double ieffMedian, double qs, double ieff, double eps)
  {
    if (qs <= 0.0 || ieff <= 0.0 || ieffMedian <= 0.0)
    {
      return -1.0;
    }

    const double lnQS = std::log(std::max(qs, eps));
    const double lnIeffNorm = std::log(std::max(ieff / ieffMedian, eps));
    const double lnY = c[0]
                     + c[1] * lnQS
                     + c[2] * lnIeffNorm
                     + c[3] * lnQS * lnIeffNorm
                     + c[4] * lnIeffNorm * lnIeffNorm
                     + c[5] * lnQS * lnQS;

    const double y = std::exp(lnY);
    return std::isfinite(y) && y > 0.0 ? y : -1.0;
  }
};

class RC360GopFrameCtrl
{
public:
  RC360GopFrameCtrl() = default;

  void init(const RC360GopFrameParams& params)
  {
    m_params = params;
    m_inited = true;
    m_totalActualBits = 0;
    m_totalTargetBits = 0;
    m_currentGopTargetBits = 0;
    m_currentGopAllocs.clear();
    m_allocByPoc.clear();
    m_frameStats.clear();
    m_model = RC360FrameRDModel::matchSequence(m_params.sequenceName);

    if (!m_params.frameStatsFile.empty())
    {
      loadFrameStatsCsv(m_params.frameStatsFile);
    }

    if (!m_params.traceFile.empty())
    {
      std::ofstream fp(m_params.traceFile.c_str(), std::ios::out);
      fp << "stage,poc,gop_target_bits,base_bits,target_bits,ieff,wref,pi,total_actual_bits,total_target_bits,delta_bits,"
            "sequence_model,is_p_frame,qs_model,pred_bpp,pred_bits,pred_d,model_valid,"
            "frame_wref_raw_unclipped,frame_wref_raw_clipped,frame_wref_final\n";
    }
  }

  bool isEnabled() const
  {
    return m_inited && m_params.enabled;
  }

  int getCurrentGopTargetBits() const
  {
    return m_currentGopTargetBits;
  }

  int getTargetBitsForPoc(int poc, int fallbackBits) const
  {
    const auto it = m_allocByPoc.find(poc);
    if (it == m_allocByPoc.end())
    {
      return std::max(1, fallbackBits);
    }
    return std::max(1, it->second.targetBits);
  }

  double getIeffForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it == m_frameStats.end() ? 1.0 : std::max(m_params.eps, it->second.ieff);
  }

  double getWrefForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it == m_frameStats.end() ? 1.0 : std::max(m_params.eps, it->second.wref);
  }

  bool hasExternalFrameStatForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it != m_frameStats.end() && it->second.hasExternal;
  }

  double getWrefRawUnclippedForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it == m_frameStats.end() ? 1.0 : std::max(m_params.eps, it->second.wrefRawUnclipped);
  }

  double getWrefRawClippedForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it == m_frameStats.end() ? 1.0 : std::max(m_params.eps, it->second.wrefRawClipped);
  }

  double getWrefFinalForPoc(int poc) const
  {
    const auto it = m_frameStats.find(poc);
    return it == m_frameStats.end() ? 1.0 : std::max(m_params.eps, it->second.wrefFinal);
  }

  int calcGopTargetBits(int numGopPics, int baseGopBits)
  {
    if (!isEnabled() || numGopPics <= 0 || m_params.targetBitrate <= 0 || m_params.frameRate <= 0.0)
    {
      m_currentGopTargetBits = std::max(1, baseGopBits);
      return m_currentGopTargetBits;
    }

    const double avgFrameBits = double(m_params.targetBitrate) / m_params.frameRate;
    const double deltaR = double(m_totalActualBits - m_totalTargetBits);
    const double sw = std::max(0, m_params.smoothWindow);
    const double nGop = double(numGopPics);

    double target = ((avgFrameBits * (nGop + sw) - deltaR) / std::max(1.0, nGop + sw)) * nGop;
    const double minBits = std::max(1.0, 0.25 * double(std::max(1, baseGopBits)));
    const double maxBits = std::max(minBits, 4.00 * double(std::max(1, baseGopBits)));
    target = clipDouble(target, minBits, maxBits);

    m_currentGopTargetBits = std::max(1, int(std::llround(target)));
    return m_currentGopTargetBits;
  }

  void allocateCurrentGop(const std::vector<int>& pocs, const std::vector<int>& baseBits, const std::vector<bool>& isPFrame)
  {
    m_currentGopAllocs.clear();
    m_allocByPoc.clear();

    if (!isEnabled() || pocs.empty() || pocs.size() != baseBits.size() || pocs.size() != isPFrame.size())
    {
      return;
    }

    const int n = int(pocs.size());
    int baseGopBits = 0;
    for (int b : baseBits)
    {
      baseGopBits += std::max(1, b);
    }

    const int gopTargetBits = calcGopTargetBits(n, baseGopBits);
    const double frameArea = double(std::max(1, m_params.frameWidth) * std::max(1, m_params.frameHeight));

    std::vector<double> weights(n, 0.0);
    std::vector<double> lower(n, 1.0);
    std::vector<double> upper(n, std::numeric_limits<double>::max());
    std::vector<RC360FrameAlloc> allocInfo(n);

    int fixedBits = 0;
    int activePFrames = 0;

    for (int i = 0; i < n; ++i)
    {
      RC360FrameAlloc a;
      a.poc = pocs[i];
      a.baseBits = std::max(1, baseBits[i]);
      a.targetBits = a.baseBits;
      a.ieff = getIeffForPoc(pocs[i]);
      a.wref = getWrefForPoc(pocs[i]);
      a.wrefRawUnclipped = getWrefRawUnclippedForPoc(pocs[i]);
      a.wrefRawClipped = getWrefRawClippedForPoc(pocs[i]);
      a.wrefFinal = getWrefFinalForPoc(pocs[i]);
      a.isPFrame = isPFrame[i];
      a.modelName = m_model ? m_model->name : "unmatched";
      a.lower = std::max(1.0, m_params.etaMin * double(a.baseBits));
      a.upper = std::max(a.lower, m_params.etaMax * double(a.baseBits));

      if (a.isPFrame && m_model != nullptr && hasExternalFrameStatForPoc(pocs[i]) && a.ieff > 0.0)
      {
        a.qsModel = findQsForBaseBits(*m_model, a.baseBits, a.ieff, frameArea);
        a.predBpp = RC360FrameRDModel::predictBpp(*m_model, a.qsModel, a.ieff, m_params.eps);
        a.predBits = a.predBpp > 0.0 ? a.predBpp * frameArea : -1.0;
        a.predD = RC360FrameRDModel::predictOrdinaryMse(*m_model, a.qsModel, a.ieff, m_params.eps);
        a.modelValid = a.qsModel > 0.0 && a.predBpp > 0.0 && a.predBits > 0.0 && a.predD > 0.0;

        if (a.modelValid)
        {
          a.pi = std::max(m_params.eps, a.predBits) * std::max(m_params.eps, a.predD);
          weights[i] = a.pi;
          lower[i] = a.lower;
          upper[i] = a.upper;
          activePFrames++;
        }
      }

      if (!a.modelValid)
      {
        fixedBits += a.baseBits;
      }

      allocInfo[i] = a;
    }

    if (activePFrames <= 0)
    {
      m_currentGopTargetBits = baseGopBits;
      for (int i = 0; i < n; ++i)
      {
        allocInfo[i].targetBits = allocInfo[i].baseBits;
        m_currentGopAllocs.push_back(allocInfo[i]);
        m_allocByPoc[allocInfo[i].poc] = allocInfo[i];
        trace("alloc", allocInfo[i]);
      }
      return;
    }

    const int pTargetBits = std::max(1, gopTargetBits - fixedBits);
    std::vector<double> activeWeights;
    std::vector<double> activeLower;
    std::vector<double> activeUpper;
    std::vector<int> activeIndex;

    for (int i = 0; i < n; ++i)
    {
      if (allocInfo[i].modelValid)
      {
        activeIndex.push_back(i);
        activeWeights.push_back(weights[i]);
        activeLower.push_back(lower[i]);
        activeUpper.push_back(upper[i]);
      }
    }

    std::vector<double> activeAlloc = waterFillClip(pTargetBits, activeWeights, activeLower, activeUpper);
    std::vector<int> intActiveAlloc = integerize(activeAlloc, pTargetBits, activeUpper);

    for (size_t k = 0; k < activeIndex.size(); ++k)
    {
      allocInfo[activeIndex[k]].targetBits = std::max(1, intActiveAlloc[k]);
    }

    int sumBits = 0;
    for (const RC360FrameAlloc& a : allocInfo)
    {
      sumBits += a.targetBits;
    }
    m_currentGopTargetBits = std::max(1, sumBits);

    for (int i = 0; i < n; ++i)
    {
      m_currentGopAllocs.push_back(allocInfo[i]);
      m_allocByPoc[allocInfo[i].poc] = allocInfo[i];
      trace("alloc", allocInfo[i]);
    }
  }

  void updateAfterPic(int poc, int actualBits)
  {
    if (!isEnabled())
    {
      return;
    }

    RC360FrameAlloc a;
    const auto it = m_allocByPoc.find(poc);
    if (it != m_allocByPoc.end())
    {
      a = it->second;
    }
    else
    {
      a.poc = poc;
      a.baseBits = actualBits;
      a.targetBits = actualBits;
      a.modelName = m_model ? m_model->name : "unmatched";
    }

    m_totalActualBits += std::max(0, actualBits);
    m_totalTargetBits += std::max(0, a.targetBits);
    trace("update", a);
  }

private:
  RC360GopFrameParams m_params;
  bool m_inited = false;
  const RC360FrameRDModel::Coeff* m_model = nullptr;

  int64_t m_totalActualBits = 0;
  int64_t m_totalTargetBits = 0;
  int m_currentGopTargetBits = 0;

  std::map<int, RC360FrameStat> m_frameStats;
  std::vector<RC360FrameAlloc> m_currentGopAllocs;
  std::map<int, RC360FrameAlloc> m_allocByPoc;

private:
  static double clipDouble(double x, double lo, double hi)
  {
    return std::min(std::max(x, lo), hi);
  }

  static double qpToQs(double qp)
  {
    return std::pow(2.0, (qp - 4.0) / 6.0);
  }

  double findQsForBaseBits(const RC360FrameRDModel::Coeff& model, int baseBits, double ieff, double frameArea) const
  {
    if (baseBits <= 0 || frameArea <= 0.0 || ieff <= 0.0)
    {
      return -1.0;
    }

    double bestQs = -1.0;
    double bestErr = std::numeric_limits<double>::max();
    for (int step = 0; step <= (50 - 17) * 4; ++step)
    {
      const double qp = 17.0 + double(step) * 0.25;
      const double qs = qpToQs(qp);
      const double bpp = RC360FrameRDModel::predictBpp(model, qs, ieff, m_params.eps);
      if (bpp <= 0.0)
      {
        continue;
      }

      const double predBits = bpp * frameArea;
      const double err = std::abs(std::log(std::max(predBits, m_params.eps)) - std::log(double(std::max(1, baseBits))));
      if (err < bestErr)
      {
        bestErr = err;
        bestQs = qs;
      }
    }
    return bestQs;
  }

  static std::vector<double> waterFillClip(int targetBits,
                                           const std::vector<double>& weights,
                                           const std::vector<double>& lower,
                                           const std::vector<double>& upper)
  {
    const int n = int(weights.size());
    std::vector<double> out(n, 0.0);
    std::vector<int> active(n, 1);
    double remaining = double(std::max(1, targetBits));

    for (int iter = 0; iter < n + 4; ++iter)
    {
      double weightSum = 0.0;
      for (int i = 0; i < n; ++i)
      {
        if (active[i])
        {
          weightSum += std::max(1e-12, weights[i]);
        }
      }
      if (weightSum <= 0.0)
      {
        break;
      }

      bool changed = false;
      for (int i = 0; i < n; ++i)
      {
        if (!active[i])
        {
          continue;
        }

        const double v = remaining * std::max(1e-12, weights[i]) / weightSum;
        if (v < lower[i])
        {
          out[i] = lower[i];
          active[i] = 0;
          remaining -= out[i];
          changed = true;
        }
        else if (v > upper[i])
        {
          out[i] = upper[i];
          active[i] = 0;
          remaining -= out[i];
          changed = true;
        }
      }

      if (!changed)
      {
        for (int i = 0; i < n; ++i)
        {
          if (active[i])
          {
            out[i] = remaining * std::max(1e-12, weights[i]) / weightSum;
          }
        }
        break;
      }

      remaining = std::max(1.0, remaining);
    }

    for (int i = 0; i < n; ++i)
    {
      if (out[i] <= 0.0 || !std::isfinite(out[i]))
      {
        out[i] = lower[i];
      }
    }

    return out;
  }

  static std::vector<int> integerize(const std::vector<double>& alloc, int targetBits, const std::vector<double>& upper)
  {
    const int n = int(alloc.size());
    std::vector<int> intAlloc(n, 1);
    int intSum = 0;
    for (int i = 0; i < n; ++i)
    {
      intAlloc[i] = std::max(1, int(std::floor(alloc[i])));
      intSum += intAlloc[i];
    }

    int residual = targetBits - intSum;
    if (residual > 0)
    {
      std::vector<int> order(n);
      std::iota(order.begin(), order.end(), 0);
      std::sort(order.begin(), order.end(), [&](int a, int b)
      {
        return (alloc[a] - std::floor(alloc[a])) > (alloc[b] - std::floor(alloc[b]));
      });

      for (int k = 0; k < residual && k < n; ++k)
      {
        const int idx = order[k];
        if (double(intAlloc[idx] + 1) <= upper[idx] + 0.5)
        {
          ++intAlloc[idx];
        }
      }
    }

    return intAlloc;
  }

  void loadFrameStatsCsv(const std::string& path)
  {
    std::ifstream fp(path.c_str(), std::ios::in);
    if (!fp.good())
    {
      return;
    }

    std::string line;
    bool firstLine = true;
    while (std::getline(fp, line))
    {
      if (line.empty())
      {
        continue;
      }

      if (firstLine)
      {
        firstLine = false;
        if (line.find("poc") != std::string::npos)
        {
          continue;
        }
      }

      std::replace(line.begin(), line.end(), ',', ' ');
      std::istringstream iss(line);

      RC360FrameStat s;
      if (!(iss >> s.poc >> s.ieff >> s.wref))
      {
        continue;
      }

      s.wrefRawUnclipped = s.wref;
      s.wrefRawClipped = s.wref;
      s.wrefFinal = s.wref;

      double extRawUnclipped = 1.0;
      double extRawClipped = 1.0;
      double extFinal = 1.0;
      if (iss >> extRawUnclipped >> extRawClipped >> extFinal)
      {
        s.wrefRawUnclipped = extRawUnclipped;
        s.wrefRawClipped = extRawClipped;
        s.wrefFinal = extFinal;
      }

      s.ieff = std::max(m_params.eps, s.ieff);
      s.wref = std::max(m_params.eps, s.wref);
      s.wrefRawUnclipped = std::max(m_params.eps, s.wrefRawUnclipped);
      s.wrefRawClipped = std::max(m_params.eps, s.wrefRawClipped);
      s.wrefFinal = std::max(m_params.eps, s.wrefFinal);
      s.hasExternal = true;
      m_frameStats[s.poc] = s;
    }
  }

  void trace(const char* stage, const RC360FrameAlloc& a)
  {
    if (m_params.traceFile.empty())
    {
      return;
    }

    std::ofstream fp(m_params.traceFile.c_str(), std::ios::app);
    fp << stage << ","
       << a.poc << ","
       << m_currentGopTargetBits << ","
       << a.baseBits << ","
       << a.targetBits << ","
       << std::setprecision(10) << a.ieff << ","
       << std::setprecision(10) << a.wref << ","
       << std::setprecision(10) << a.pi << ","
       << m_totalActualBits << ","
       << m_totalTargetBits << ","
       << (m_totalActualBits - m_totalTargetBits) << ","
       << a.modelName << ","
       << (a.isPFrame ? 1 : 0) << ","
       << std::setprecision(10) << a.qsModel << ","
       << std::setprecision(10) << a.predBpp << ","
       << std::setprecision(10) << a.predBits << ","
       << std::setprecision(10) << a.predD << ","
       << (a.modelValid ? 1 : 0) << ","
       << std::setprecision(10) << a.wrefRawUnclipped << ","
       << std::setprecision(10) << a.wrefRawClipped << ","
       << std::setprecision(10) << a.wrefFinal
       << "\n";
  }
};

#endif // wref_bitallocation_frame
