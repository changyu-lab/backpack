#ifndef VVENC_SALDANHA_LFNST_H
#define VVENC_SALDANHA_LFNST_H

#include <array>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace saldanha {
using Features = std::array<double, 13>;

class Model
{
  struct Node { int feature, left, right; double threshold, weight, p0, p1; };
  std::vector<Node> nodes;
  void visit(int id, int depth, std::vector<int>& seen) const
  {
    if (id < 0 || id >= int(nodes.size()) || seen[id] || depth > 8)
      throw std::runtime_error("Invalid Saldanha tree topology/depth");
    seen[id] = 1;
    const Node& n = nodes[id];
    if (n.feature >= 0) { visit(n.left, depth+1, seen); visit(n.right, depth+1, seen); }
  }
public:
  explicit Model(const std::string& path)
  {
    std::ifstream in(path);
    std::string magic;
    int count = 0, features = 0;
    if (!(in >> magic >> features >> count) || magic != "LFNST_REPTREE_V1" || features != 13 || count < 1 || count > 511)
      throw std::runtime_error("Invalid/missing Saldanha model: " + path);
    for (int i=0; i<count; ++i)
    {
      int id;
      Node n;
      if (!(in >> id >> n.feature >> n.threshold >> n.left >> n.right >> n.weight >> n.p0 >> n.p1)
          || id != i || n.feature < -1 || n.feature >= 13 || !std::isfinite(n.threshold)
          || !std::isfinite(n.weight) || n.weight < 0 || n.weight > 1
          || !std::isfinite(n.p0) || !std::isfinite(n.p1) || n.p0 < 0 || n.p1 < 0
          || std::abs(n.p0+n.p1-1.0) > 1e-9
          || (n.feature == -1 && (n.left != -1 || n.right != -1)))
        throw std::runtime_error("Invalid Saldanha model node");
      nodes.push_back(n);
    }
    std::string extra;
    if (in >> extra) throw std::runtime_error("Unexpected Saldanha model trailing data");
    std::vector<int> seen(count, 0);
    visit(0, 0, seen);
    for (int v : seen) if (!v) throw std::runtime_error("Unreachable Saldanha model node");
  }
  bool skip(const Features& f) const
  {
    for (double x : f) if (!std::isfinite(x)) return false;
    int id = 0;
    while (nodes[id].feature >= 0)
    {
      const Node& n = nodes[id];
      id = f[n.feature] < n.threshold ? n.left : n.right;
    }
    return nodes[id].p0 >= nodes[id].p1;
  }
};

inline std::string env(const char* name)
{
  const char* value = std::getenv(name);
  return value ? value : "";
}

class Runtime
{
public:
  enum Mode { OFF, COLLECT, SHADOW, ON };
  const Mode mode;
private:
  std::unique_ptr<Model> model;
  std::ofstream csv;
  std::ofstream statsOut;
  const std::string sequence;
  const std::string stats;
  std::mutex mutex;
  uint64_t sample = 0, written = 0;
  uint64_t stride = 1, maxRows = 200000;
  std::atomic<uint64_t> eligible{0}, predicted{0}, suppressed{0}, labeled{0}, wrong{0};
  static Mode getMode()
  {
    const std::string s = env("SALDANHA_MODE");
    if (s.empty() || s == "off") return OFF;
    if (s == "collect") return COLLECT;
    if (s == "shadow") return SHADOW;
    if (s == "on") return ON;
    throw std::runtime_error("SALDANHA_MODE must be off/collect/shadow/on");
  }
public:
  Runtime() : mode(getMode()), sequence(env("SALDANHA_SEQUENCE")), stats(env("SALDANHA_STATS"))
  {
    if (mode == OFF) return;
    if (!stats.empty())
    {
      statsOut.open(stats, std::ios::trunc);
      if (!statsOut) throw std::runtime_error("Cannot open SALDANHA_STATS");
    }
    if (mode == ON || mode == SHADOW) model.reset(new Model(env("SALDANHA_MODEL")));
    const std::string strideText = env("SALDANHA_STRIDE"), maxText = env("SALDANHA_MAX_ROWS");
    if (!strideText.empty()) stride = std::stoull(strideText);
    if (!maxText.empty()) maxRows = std::stoull(maxText);
    if (!stride || !maxRows) throw std::runtime_error("Saldanha sampling limits must be positive");
    const std::string path = env("SALDANHA_CSV");
    if (mode == COLLECT && path.empty()) throw std::runtime_error("collect requires SALDANHA_CSV");
    if (!path.empty())
    {
      if (sequence.empty() || sequence.find_first_of(",\r\n\"") != std::string::npos)
        throw std::runtime_error("Invalid SALDANHA_SEQUENCE for CSV");
      csv.open(path, std::ios::trunc);
      if (!csv) throw std::runtime_error("Cannot open SALDANHA_CSV");
      csv << "sequence,poc,qp,x,y,width,height,area,blockRatio,MTTD,mipFlag,ispMode,currCost,currDistortion,currFracBits,currIntraMode,numNonZeroCoeffs,absSumCoeffs,label,predicted_skip\n";
      csv << std::setprecision(17);
    }
  }
  bool decide(const Features& f)
  {
    ++eligible;
    const bool s = model && model->skip(f);
    if (s) ++predicted;
    return s;
  }
  void suppress() { ++suppressed; }
  void finish(const Features& f, bool pred, int label, int poc, int qp, int x, int y)
  {
    if (mode != ON)
    {
      ++labeled;
      if (pred && label == 1) ++wrong;
    }
    if (!csv.is_open()) return;
    std::lock_guard<std::mutex> guard(mutex);
    if ((sample++ % stride) || written >= maxRows) return;
    csv << sequence << ',' << poc << ',' << qp << ',' << x << ',' << y;
    for (double v : f) csv << ',' << v;
    csv << ',' << (mode == ON ? -1 : label) << ',' << int(pred) << '\n';
    ++written;
    if ((written % 1024) == 0) csv.flush();
    if (!csv) throw std::runtime_error("Saldanha CSV write failed");
  }
  ~Runtime()
  {
    if (csv.is_open()) { csv.flush(); if (!csv) { std::fputs("Saldanha CSV final flush failed\n", stderr); std::_Exit(EXIT_FAILURE); } }
    if (mode == OFF || stats.empty()) return;
    statsOut << "{\"eligible\":" << eligible << ",\"predicted_skip\":" << predicted
        << ",\"suppressed_candidates\":" << suppressed << ",\"labeled\":" << labeled
        << ",\"wrong_skip\":" << wrong << ",\"csv_rows\":" << written << "}\n";
    statsOut.flush();
    if (!statsOut)
    {
      std::fputs("Saldanha statistics write failed\n", stderr);
      std::_Exit(EXIT_FAILURE);
    }
  }
};

inline Runtime& runtime() { static Runtime r; return r; }
}
#endif
