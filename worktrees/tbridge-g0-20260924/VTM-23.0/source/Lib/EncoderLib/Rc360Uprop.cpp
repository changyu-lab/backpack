/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 */

#include "Rc360Uprop.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>

void Rc360Uprop::init(const Config& cfg)
{
  m_cfg = cfg;
  clear();
}

void Rc360Uprop::clear()
{
  m_framesByPoc.clear();
  m_analyzedWindows.clear();
  m_histSum = 0.0;
  m_histCount = 0;
}

bool Rc360Uprop::hasPicture(int poc) const
{
  return m_framesByPoc.find(poc) != m_framesByPoc.end();
}

double Rc360Uprop::getCtuNorm(int poc, int ctuRsAddr) const
{
  auto it = m_framesByPoc.find(poc);
  if (it == m_framesByPoc.end())
  {
    return 1.0;
  }
  const CoreFrameResult& frame = it->second;
  if (ctuRsAddr < 0 || ctuRsAddr >= int(frame.ctus.size()))
  {
    return 1.0;
  }
  return frame.ctus[ctuRsAddr].norm;
}

double Rc360Uprop::getCtuScale(int poc, int ctuRsAddr) const
{
  if (!ctuEnabled())
  {
    return 1.0;
  }
  return std::pow(std::max(1e-9, getCtuNorm(poc, ctuRsAddr)), std::max(0.0, m_cfg.beta));
}

double Rc360Uprop::getFrameMeanRaw(int poc) const
{
  auto it = m_framesByPoc.find(poc);
  if (it == m_framesByPoc.end())
  {
    return 1.0;
  }
  return it->second.meanRaw;
}

double Rc360Uprop::getFramePi(int poc) const
{
  if (!frameEnabled())
  {
    return 1.0;
  }
  const double current = std::max(1e-9, getFrameMeanRaw(poc));
  const double hist = m_histCount > 0 ? std::max(1e-9, getHistoricalFrameMeanRaw()) : current;
  return std::pow(current / hist, std::max(0.0, m_cfg.alpha));
}

double Rc360Uprop::getHistoricalFrameMeanRaw() const
{
  return m_histCount > 0 ? m_histSum / double(m_histCount) : 1.0;
}

void Rc360Uprop::commitPicture(int poc)
{
  auto it = m_framesByPoc.find(poc);
  if (it == m_framesByPoc.end())
  {
    return;
  }
  const double meanRaw = std::max(1e-9, it->second.meanRaw);
  m_histSum += meanRaw;
  m_histCount++;
}

bool Rc360Uprop::beginWindow(int startPoc, int endPoc)
{
  if (!m_cfg.enabled || endPoc < startPoc)
  {
    return false;
  }
  return m_analyzedWindows.insert({ startPoc, endPoc }).second;
}

int Rc360Uprop::windowStartForPoc(int poc, int gopSize)
{
  const int safeGopSize = std::max(1, gopSize);
  return poc <= 0 ? 0 : (poc / safeGopSize) * safeGopSize;
}

std::vector<int> Rc360Uprop::selectLegalReferenceFramesForTest(const std::vector<int>& framePocs,
                                                               int futureFrameIdx,
                                                               const std::vector<int>& legalRefPocs)
{
  std::vector<int> result;
  if (futureFrameIdx < 0 || futureFrameIdx >= int(framePocs.size()))
  {
    return result;
  }
  for (int frameIdx = 0; frameIdx < futureFrameIdx; frameIdx++)
  {
    if (std::find(legalRefPocs.begin(), legalRefPocs.end(), framePocs[frameIdx]) != legalRefPocs.end())
    {
      result.push_back(frameIdx);
    }
  }
  return result;
}

double Rc360Uprop::clipDouble(double v, double lo, double hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

double Rc360Uprop::median(std::vector<double> values, double fallback)
{
  if (values.empty())
  {
    return fallback;
  }
  std::sort(values.begin(), values.end());
  const size_t n = values.size();
  if ((n & 1) != 0)
  {
    return values[n / 2];
  }
  return 0.5 * (values[n / 2 - 1] + values[n / 2]);
}

double Rc360Uprop::dependencyDelta(double interCost, double intraCost, double tauLow, double tauHigh)
{
  if (tauHigh <= tauLow)
  {
    return 0.0;
  }
  const double q = interCost / (std::max(0.0, intraCost) + 1e-9);
  return clipDouble((tauHigh - q) / (tauHigh - tauLow + 1e-9), 0.0, 1.0);
}

double Rc360Uprop::sphericalU0(int yCenter, int picH)
{
  const double pi = 3.14159265358979323846;
  const double v = (double(yCenter) + 0.5) / double(std::max(1, picH));
  const double phi = (0.5 - v) * pi;
  return clipDouble(std::cos(std::fabs(phi)), 1e-6, 1.0);
}

Rc360Uprop::CoreResult Rc360Uprop::solveCoreForTest(const std::vector<CoreFrameInput>& frames,
                                                    const std::vector<CoreEdge>& edges,
                                                    const Config& cfg)
{
  CoreResult out;
  out.frames.resize(frames.size());
  for (size_t i = 0; i < frames.size(); i++)
  {
    out.frames[i].poc = frames[i].poc;
    out.frames[i].ctus.resize(frames[i].u0.size());
    for (size_t ctu = 0; ctu < frames[i].u0.size(); ctu++)
    {
      const double u0 = std::max(1e-9, frames[i].u0[ctu]);
      out.frames[i].ctus[ctu].u0 = u0;
      out.frames[i].ctus[ctu].raw = u0;
      out.frames[i].ctus[ctu].norm = 1.0;
    }
  }

  for (int frameIdx = int(out.frames.size()) - 1; frameIdx >= 0; frameIdx--)
  {
    for (const CoreEdge& edge: edges)
    {
      if (edge.fromFrame != frameIdx || edge.weight <= 0.0)
      {
        continue;
      }
      if (edge.toFrame < 0 || edge.toFrame >= int(out.frames.size()) || edge.fromCtu < 0 || edge.toCtu < 0)
      {
        continue;
      }
      CoreFrameResult& fromFrame = out.frames[edge.fromFrame];
      const CoreFrameResult& toFrame = out.frames[edge.toFrame];
      if (edge.fromCtu >= int(fromFrame.ctus.size()) || edge.toCtu >= int(toFrame.ctus.size()))
      {
        continue;
      }
      const std::vector<int>& legalRefPocs = frames[edge.toFrame].legalRefPocs;
      if (std::find(legalRefPocs.begin(), legalRefPocs.end(), frames[edge.fromFrame].poc) == legalRefPocs.end())
      {
        continue;
      }
      fromFrame.ctus[edge.fromCtu].raw += edge.weight * toFrame.ctus[edge.toCtu].raw;
      fromFrame.edgeCount++;
    }
  }

  const double normMin = std::max(1e-6, cfg.normMin);
  const double normMax = std::max(normMin, cfg.normMax);
  for (CoreFrameResult& frame: out.frames)
  {
    for (CoreCtuResult& ctu: frame.ctus)
    {
      if (cfg.ctuSignalMode == 1)
      {
        ctu.raw = ctu.u0;
      }
      else if (cfg.ctuSignalMode == 2)
      {
        ctu.raw = std::max(1e-9, ctu.raw - ctu.u0);
      }
    }

    std::vector<double> rawValues;
    rawValues.reserve(frame.ctus.size());
    double sumRaw = 0.0;
    for (const CoreCtuResult& ctu: frame.ctus)
    {
      rawValues.push_back(ctu.raw);
      sumRaw += ctu.raw;
    }
    frame.meanRaw = !frame.ctus.empty() ? sumRaw / double(frame.ctus.size()) : 1.0;
    frame.medianRaw = std::max(1e-9, median(rawValues, frame.meanRaw));
    frame.minNorm = normMax;
    frame.maxNorm = normMin;
    for (CoreCtuResult& ctu: frame.ctus)
    {
      ctu.norm = clipDouble((ctu.raw + 1e-9) / (frame.medianRaw + 1e-9), normMin, normMax);
      frame.minNorm = std::min(frame.minNorm, ctu.norm);
      frame.maxNorm = std::max(frame.maxNorm, ctu.norm);
    }
    if (frame.ctus.empty())
    {
      frame.minNorm = 1.0;
      frame.maxNorm = 1.0;
    }
  }
  return out;
}

uint64_t Rc360Uprop::sadPartial(const CPelBuf& a, const CPelBuf& b, int w, int h)
{
  uint64_t sum = 0;
  for (int y = 0; y < h; y++)
  {
    const Pel* pa = a.bufAt(0, y);
    const Pel* pb = b.bufAt(0, y);
    for (int x = 0; x < w; x++)
    {
      sum += uint64_t(std::abs(int(pa[x]) - int(pb[x])));
    }
  }
  return sum;
}

uint64_t Rc360Uprop::sadDiff(const CPelBuf& org, const CPelBuf& ref)
{
  uint64_t sum = 0;
  const int w = std::min(org.width, ref.width);
  const int h = std::min(org.height, ref.height);
  for (int y = 0; y < h; y += 4)
  {
    for (int x = 0; x < w; x += 4)
    {
      const int bw = std::min(4, w - x);
      const int bh = std::min(4, h - y);
      const CPelBuf a(org.bufAt(x, y), org.stride, bw, bh);
      const CPelBuf b(ref.bufAt(x, y), ref.stride, bw, bh);
      sum += sadPartial(a, b, bw, bh);
    }
  }
  return sum;
}

uint64_t Rc360Uprop::simpleIntraCost(const CPelBuf& org)
{
  uint64_t sumPix = 0;
  const int n = std::max(1, int(org.width) * int(org.height));
  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);
    for (int x = 0; x < org.width; x++)
    {
      sumPix += uint64_t(p[x]);
    }
  }
  const int mean = int((sumPix + n / 2) / n);
  uint64_t sum = 0;
  for (int y = 0; y < org.height; y++)
  {
    const Pel* p = org.bufAt(0, y);
    for (int x = 0; x < org.width; x++)
    {
      sum += uint64_t(std::abs(int(p[x]) - mean));
    }
  }
  return sum;
}

Rc360Uprop::SearchResult Rc360Uprop::searchPreviousFrames(const std::vector<AnalysisFrame>& frames,
                                                         int futureFrameIdx,
                                                         int x,
                                                         int y,
                                                         int width,
                                                         int height,
                                                         double intraCost) const
{
  SearchResult best;
  best.interCost = std::numeric_limits<double>::max();
  const AnalysisFrame& current = frames[futureFrameIdx];
  const CPelBuf curOrg(current.luma.bufAt(x, y), current.luma.stride, width, height);
  const int step = std::max(1, m_cfg.searchStep);
  const std::vector<int> framePocs = [&frames]()
  {
    std::vector<int> pocs;
    pocs.reserve(frames.size());
    for (const AnalysisFrame& frame: frames)
    {
      pocs.push_back(frame.poc);
    }
    return pocs;
  }();
  const std::vector<int> legalFrames =
    selectLegalReferenceFramesForTest(framePocs, futureFrameIdx, current.legalRefPocs);

  for (int refFrameIdx: legalFrames)
  {
    const AnalysisFrame& refFrame = frames[refFrameIdx];
    const int refW = refFrame.luma.width;
    const int refH = refFrame.luma.height;
    const int minRx = std::max(0, x - m_cfg.searchRange);
    const int maxRx = std::min(refW - width, x + m_cfg.searchRange);
    const int minRy = std::max(0, y - m_cfg.searchRange);
    const int maxRy = std::min(refH - height, y + m_cfg.searchRange);
    if (maxRx < minRx || maxRy < minRy)
    {
      continue;
    }
    for (int ry = minRy; ry <= maxRy; ry += step)
    {
      for (int rx = minRx; rx <= maxRx; rx += step)
      {
        const CPelBuf refOrg(refFrame.luma.bufAt(rx, ry), refFrame.luma.stride, width, height);
        const double cost = double(sadDiff(curOrg, refOrg));
        if (cost < best.interCost)
        {
          best.frameIdx = refFrameIdx;
          best.rx = rx;
          best.ry = ry;
          best.interCost = cost;
        }
      }
    }
  }
  if (best.frameIdx >= 0)
  {
    best.delta = dependencyDelta(best.interCost, intraCost, m_cfg.tauLow, m_cfg.tauHigh);
  }
  return best;
}

void Rc360Uprop::addOverlapEdgesForReferenceArea(const AnalysisFrame& refFrame,
                                                 int refFrameIdx,
                                                 int toFrameIdx,
                                                 int toCtu,
                                                 int rx,
                                                 int ry,
                                                 int w,
                                                 int h,
                                                 double delta,
                                                 std::vector<CoreEdge>& edges) const
{
  if (delta <= 0.0)
  {
    return;
  }
  const int picW = refFrame.luma.width;
  const int picH = refFrame.luma.height;
  const int ctuW = std::max(1, refFrame.ctuWidth);
  const int ctuH = std::max(1, refFrame.ctuHeight);
  const int widthInCtus = (picW + ctuW - 1) / ctuW;
  const int heightInCtus = (picH + ctuH - 1) / ctuH;
  const int x1 = rx;
  const int y1 = ry;
  const int x2 = std::min(picW, rx + w);
  const int y2 = std::min(picH, ry + h);
  if (x2 <= x1 || y2 <= y1)
  {
    return;
  }
  const int ctuX0 = x1 / ctuW;
  const int ctuY0 = y1 / ctuH;
  const int ctuX1 = (x2 - 1) / ctuW;
  const int ctuY1 = (y2 - 1) / ctuH;
  const double refArea = double((x2 - x1) * (y2 - y1));
  for (int cy = ctuY0; cy <= ctuY1; cy++)
  {
    for (int cx = ctuX0; cx <= ctuX1; cx++)
    {
      if (cx < 0 || cy < 0 || cx >= widthInCtus || cy >= heightInCtus)
      {
        continue;
      }
      const int bx1 = cx * ctuW;
      const int by1 = cy * ctuH;
      const int bx2 = std::min(picW, bx1 + ctuW);
      const int by2 = std::min(picH, by1 + ctuH);
      const int ox1 = std::max(x1, bx1);
      const int oy1 = std::max(y1, by1);
      const int ox2 = std::min(x2, bx2);
      const int oy2 = std::min(y2, by2);
      if (ox2 <= ox1 || oy2 <= oy1)
      {
        continue;
      }
      const double overlap = double((ox2 - ox1) * (oy2 - oy1)) / std::max(1.0, refArea);
      edges.push_back({ refFrameIdx, cy * widthInCtus + cx, toFrameIdx, toCtu, overlap * delta });
    }
  }
}

void Rc360Uprop::analyzeWindow(int startPoc, int endPoc, const std::vector<AnalysisFrame>& inputFrames)
{
  if (!beginWindow(startPoc, endPoc))
  {
    if (m_cfg.verbose)
    {
      std::printf("[RC360Uprop][WindowCacheHit] startPOC=%d endPOC=%d\n", startPoc, endPoc);
      std::fflush(stdout);
    }
    return;
  }

  std::vector<AnalysisFrame> frames;
  for (const AnalysisFrame& frame: inputFrames)
  {
    if (frame.poc >= startPoc && frame.poc <= endPoc && frame.luma.buf != nullptr
        && frame.ctuWidth > 0 && frame.ctuHeight > 0)
    {
      frames.push_back(frame);
    }
  }
  std::sort(frames.begin(), frames.end(), [](const AnalysisFrame& a, const AnalysisFrame& b) { return a.poc < b.poc; });
  frames.erase(std::unique(frames.begin(), frames.end(),
                           [](const AnalysisFrame& a, const AnalysisFrame& b) { return a.poc == b.poc; }),
               frames.end());
  if (frames.empty())
  {
    return;
  }

  std::vector<CoreFrameInput> coreFrames;
  coreFrames.reserve(frames.size());
  std::vector<CoreEdge> edges;

  for (size_t frameIdx = 0; frameIdx < frames.size(); frameIdx++)
  {
    const AnalysisFrame& analysisFrame = frames[frameIdx];
    const int picH = analysisFrame.luma.height;
    const int picW = analysisFrame.luma.width;
    const int ctuW = analysisFrame.ctuWidth;
    const int ctuH = analysisFrame.ctuHeight;
    const int widthInCtus = (picW + ctuW - 1) / ctuW;
    const int heightInCtus = (picH + ctuH - 1) / ctuH;
    const int numCtus = widthInCtus * heightInCtus;
    CoreFrameInput frame;
    frame.poc = analysisFrame.poc;
    frame.legalRefPocs = analysisFrame.legalRefPocs;
    frame.u0.resize(numCtus, 1.0);
    for (int ctu = 0; ctu < numCtus; ctu++)
    {
      const int ctuX = ctu % widthInCtus;
      const int ctuY = ctu / widthInCtus;
      const int x = ctuX * ctuW;
      const int y = ctuY * ctuH;
      (void)x;
      const int h = std::min(ctuH, picH - y);
      frame.u0[ctu] = sphericalU0(y + h / 2, picH);
    }
    coreFrames.push_back(frame);
  }

  for (int futureFrameIdx = 1; futureFrameIdx < int(frames.size()); futureFrameIdx++)
  {
    const AnalysisFrame& current = frames[futureFrameIdx];
    const int picW = current.luma.width;
    const int picH = current.luma.height;
    const int ctuW = current.ctuWidth;
    const int ctuH = current.ctuHeight;
    const int widthInCtus = (picW + ctuW - 1) / ctuW;
    const int heightInCtus = (picH + ctuH - 1) / ctuH;
    const int numCtus = widthInCtus * heightInCtus;
    for (int ctu = 0; ctu < numCtus; ctu++)
    {
      const int ctuX = ctu % widthInCtus;
      const int ctuY = ctu / widthInCtus;
      const int x = ctuX * ctuW;
      const int y = ctuY * ctuH;
      const int w = std::min(ctuW, picW - x);
      const int h = std::min(ctuH, picH - y);
      if (w <= 0 || h <= 0)
      {
        continue;
      }
      const CPelBuf curArea(current.luma.bufAt(x, y), current.luma.stride, w, h);
      const double intraCost = double(simpleIntraCost(curArea));
      const SearchResult best = searchPreviousFrames(frames, futureFrameIdx, x, y, w, h, intraCost);
      if (best.frameIdx >= 0 && best.delta > 0.0)
      {
        addOverlapEdgesForReferenceArea(frames[best.frameIdx], best.frameIdx, futureFrameIdx, ctu,
                                        best.rx, best.ry, w, h, best.delta, edges);
      }
    }
  }

  const CoreResult result = solveCoreForTest(coreFrames, edges, m_cfg);
  for (const CoreFrameResult& frame: result.frames)
  {
    m_framesByPoc[frame.poc] = frame;
    if (m_cfg.verbose)
    {
      std::printf("[RC360Uprop][Stats] windowStart=%d windowEnd=%d POC=%d ctus=%d signalMode=%d meanRaw=%.9f medianRaw=%.9f minNorm=%.9f maxNorm=%.9f edges=%d histMeanRaw=%.9f histCount=%d\n",
                  startPoc, endPoc, frame.poc, int(frame.ctus.size()),
                  m_cfg.ctuSignalMode,
                  frame.meanRaw, frame.medianRaw, frame.minNorm, frame.maxNorm,
                  frame.edgeCount, getHistoricalFrameMeanRaw(), m_histCount);
    }
  }
  if (m_cfg.verbose)
  {
    std::fflush(stdout);
  }
}
