/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 */

#include "Rc360PaperTI.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>

namespace
{
double rc360PaperTiQuantile(std::vector<double> values, double q, double fallback)
{
  if (values.empty())
  {
    return fallback;
  }
  std::sort(values.begin(), values.end());
  const double pos = std::max(0.0, std::min(1.0, q)) * double(values.size() - 1);
  const int lo = int(std::floor(pos));
  const int hi = int(std::ceil(pos));
  const double frac = pos - double(lo);
  return values[lo] * (1.0 - frac) + values[hi] * frac;
}

double rc360PaperTiMean(const std::vector<double>& values)
{
  if (values.empty())
  {
    return 0.0;
  }
  double sum = 0.0;
  for (double v: values)
  {
    sum += v;
  }
  return sum / double(values.size());
}

double rc360PaperTiClip(double v, double lo, double hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

int rc360PaperTiRoundDqp(double v)
{
  return int(std::floor(v + (v >= 0.0 ? 0.5 : -0.5)));
}
}

void Rc360PaperTI::init(const Config& cfg)
{
  m_cfg = cfg;
  clear();
}

void Rc360PaperTI::clear()
{
  m_framesByPoc.clear();
  m_analyzedWindows.clear();
}

bool Rc360PaperTI::hasPicture(int poc) const
{
  return m_framesByPoc.find(poc) != m_framesByPoc.end();
}

double Rc360PaperTI::getFrameImportance(int poc) const
{
  if (!frameEnabled())
  {
    return 1.0;
  }
  auto it = m_framesByPoc.find(poc);
  return it != m_framesByPoc.end() ? it->second.frameImportance : 1.0;
}

double Rc360PaperTI::getFrameLambdaRatio(int poc) const
{
  if (!frameEnabled())
  {
    return 1.0;
  }
  auto it = m_framesByPoc.find(poc);
  return it != m_framesByPoc.end() ? it->second.frameLambdaRatio : 1.0;
}

double Rc360PaperTI::getCtuImportance(int poc, int ctuRsAddr) const
{
  if (!ctuEnabled())
  {
    return 1.0;
  }
  auto it = m_framesByPoc.find(poc);
  if (it == m_framesByPoc.end() || ctuRsAddr < 0 || ctuRsAddr >= int(it->second.ctus.size()))
  {
    return 1.0;
  }
  return it->second.ctus[ctuRsAddr].importance;
}

int Rc360PaperTI::getCtuDqp(int poc, int ctuRsAddr) const
{
  if (!ctuEnabled())
  {
    return 0;
  }
  auto it = m_framesByPoc.find(poc);
  if (it == m_framesByPoc.end() || ctuRsAddr < 0 || ctuRsAddr >= int(it->second.ctus.size()))
  {
    return 0;
  }
  return it->second.ctus[ctuRsAddr].dqp;
}

bool Rc360PaperTI::beginWindow(int startPoc, int endPoc)
{
  if (!m_cfg.enabled || endPoc < startPoc)
  {
    return false;
  }
  return m_analyzedWindows.insert({ startPoc, endPoc }).second;
}

void Rc360PaperTI::storeCoreResult(int startPoc, int endPoc, const CoreResult& result)
{
  (void)startPoc;
  (void)endPoc;
  for (const CoreFrameResult& frame: result.frames)
  {
    m_framesByPoc[frame.poc] = frame;
  }
}

int Rc360PaperTI::windowStartForPoc(int poc, int gopSize)
{
  const int safeGopSize = std::max(1, gopSize);
  return poc <= 0 ? 0 : (poc / safeGopSize) * safeGopSize;
}

double Rc360PaperTI::clipDouble(double v, double lo, double hi)
{
  return v < lo ? lo : (v > hi ? hi : v);
}

double Rc360PaperTI::median(std::vector<double> values, double fallback)
{
  if (values.empty())
  {
    return fallback;
  }
  std::sort(values.begin(), values.end());
  const size_t n = values.size();
  return (n & 1) != 0 ? values[n / 2] : 0.5 * (values[n / 2 - 1] + values[n / 2]);
}

double Rc360PaperTI::dependencyDelta(double predComplexity, double intraComplexity)
{
  if (intraComplexity <= 0.0)
  {
    return 0.0;
  }
  return clipDouble(1.0 - predComplexity / (intraComplexity + 1e-9), 0.0, 1.0);
}

Rc360PaperTI::CoreResult Rc360PaperTI::solveCoreForTest(const std::vector<CoreFrameInput>& frames,
                                                        const std::vector<CoreEdge>& edges,
                                                        const Config& cfg)
{
  CoreResult out;
  out.frames.resize(frames.size());
  for (size_t frameIdx = 0; frameIdx < frames.size(); frameIdx++)
  {
    out.frames[frameIdx].poc = frames[frameIdx].poc;
    out.frames[frameIdx].ctus.resize(frames[frameIdx].ctuComplexity.size());
    for (size_t ctu = 0; ctu < frames[frameIdx].ctuComplexity.size(); ctu++)
    {
      out.frames[frameIdx].ctus[ctu].complexity = std::max(1e-9, frames[frameIdx].ctuComplexity[ctu]);
      out.frames[frameIdx].ctus[ctu].tau = 1.0;
      out.frames[frameIdx].ctus[ctu].importance = 1.0;
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
      const std::vector<int>& legalRefs = frames[edge.toFrame].legalRefPocs;
      if (std::find(legalRefs.begin(), legalRefs.end(), frames[edge.fromFrame].poc) == legalRefs.end())
      {
        continue;
      }
      fromFrame.ctus[edge.fromCtu].tau += edge.weight * toFrame.ctus[edge.toCtu].tau;
      fromFrame.edgeCount++;
    }
  }

  std::vector<double> frameRawValues;
  frameRawValues.reserve(out.frames.size());
  for (CoreFrameResult& frame: out.frames)
  {
    std::vector<double> complexities;
    complexities.reserve(frame.ctus.size());
    for (const CoreCtuResult& ctu: frame.ctus)
    {
      complexities.push_back(ctu.complexity);
    }
    const double medianComplexity = std::max(1e-9, median(complexities, 1.0));

    std::vector<double> rawCtuValues;
    rawCtuValues.reserve(frame.ctus.size());
    double sumRaw = 0.0;
    for (CoreCtuResult& ctu: frame.ctus)
    {
      const double raw = ctu.tau * ctu.complexity / medianComplexity;
      rawCtuValues.push_back(raw);
      sumRaw += raw;
    }
    frame.rawFrameImportance = !rawCtuValues.empty() ? sumRaw / double(rawCtuValues.size()) : 1.0;
    frame.medianCtuImportance = std::max(1e-9, median(rawCtuValues, frame.rawFrameImportance));

    const double ctuMin = std::max(1e-9, cfg.ctuNormMin);
    const double ctuMax = std::max(ctuMin, cfg.ctuNormMax);
    frame.minCtuImportance = ctuMax;
    frame.maxCtuImportance = ctuMin;
    for (size_t ctuIdx = 0; ctuIdx < frame.ctus.size(); ctuIdx++)
    {
      const double norm = clipDouble(rawCtuValues[ctuIdx] / frame.medianCtuImportance, ctuMin, ctuMax);
      frame.ctus[ctuIdx].importance = norm;
      frame.minCtuImportance = std::min(frame.minCtuImportance, norm);
      frame.maxCtuImportance = std::max(frame.maxCtuImportance, norm);
    }
    if (frame.ctus.empty())
    {
      frame.minCtuImportance = 1.0;
      frame.maxCtuImportance = 1.0;
    }
    frameRawValues.push_back(frame.rawFrameImportance);
  }

  std::vector<double> frameScores = frameRawValues;
  if (cfg.frameSignalMode == 1 && frameScores.size() >= 2)
  {
    const double n = double(frameScores.size());
    double sumX = 0.0;
    double sumY = 0.0;
    double sumXX = 0.0;
    double sumXY = 0.0;
    for (size_t i = 0; i < frameScores.size(); i++)
    {
      const double x = double(frameScores.size() - 1 - i);
      const double y = std::log(std::max(1e-9, frameRawValues[i]));
      sumX += x;
      sumY += y;
      sumXX += x * x;
      sumXY += x * y;
    }
    const double denom = n * sumXX - sumX * sumX;
    const double slope = std::abs(denom) > 1e-12 ? (n * sumXY - sumX * sumY) / denom : 0.0;
    const double intercept = (sumY - slope * sumX) / n;
    for (size_t i = 0; i < frameScores.size(); i++)
    {
      const double x = double(frameScores.size() - 1 - i);
      const double residual = std::log(std::max(1e-9, frameRawValues[i])) - (intercept + slope * x);
      frameScores[i] = std::exp(residual);
    }
  }

  const double medianFrameRaw = std::max(1e-9, median(frameScores, 1.0));
  const double frameMin = std::max(1e-9, cfg.frameNormMin);
  const double frameMax = std::max(frameMin, cfg.frameNormMax);
  for (size_t frameIdx = 0; frameIdx < out.frames.size(); frameIdx++)
  {
    out.frames[frameIdx].frameImportance = clipDouble(frameScores[frameIdx] / medianFrameRaw, frameMin, frameMax);
  }

  const double frameLambdaMin = std::max(1e-9, cfg.frameLambdaMin);
  const double frameLambdaMax = std::max(frameLambdaMin, cfg.frameLambdaMax);
  std::vector<double> rawFrameLambdaRatios(out.frames.size(), 1.0);
  std::vector<int> activeFrameIdx;
  for (size_t frameIdx = 0; frameIdx < out.frames.size(); frameIdx++)
  {
    rawFrameLambdaRatios[frameIdx] =
      rc360PaperTiClip(1.0 / std::max(1e-9, out.frames[frameIdx].frameImportance), frameLambdaMin, frameLambdaMax);
    if (out.frames[frameIdx].poc > 0)
    {
      activeFrameIdx.push_back(int(frameIdx));
    }
  }
  double logScale = 0.0;
  if (cfg.frameLogNeutral && !activeFrameIdx.empty())
  {
    double lo = -8.0;
    double hi = 8.0;
    for (int iter = 0; iter < 80; iter++)
    {
      const double mid = 0.5 * (lo + hi);
      double sumLog = 0.0;
      for (int frameIdx: activeFrameIdx)
      {
        const double ratio =
          rc360PaperTiClip(rawFrameLambdaRatios[frameIdx] * std::exp(mid), frameLambdaMin, frameLambdaMax);
        sumLog += std::log(std::max(1e-12, ratio));
      }
      if (sumLog > 0.0)
      {
        hi = mid;
      }
      else
      {
        lo = mid;
      }
    }
    logScale = 0.5 * (lo + hi);
  }
  for (size_t frameIdx = 0; frameIdx < out.frames.size(); frameIdx++)
  {
    out.frames[frameIdx].frameLambdaRatio =
      rc360PaperTiClip(rawFrameLambdaRatios[frameIdx] * std::exp(logScale), frameLambdaMin, frameLambdaMax);
  }

  const int maxAbsDqp = std::max(0, cfg.ctuDqpDeltaMax);
  constexpr double invLog2 = 1.4426950408889634;
  for (CoreFrameResult& frame: out.frames)
  {
    std::vector<double> dqpFloats;
    dqpFloats.reserve(frame.ctus.size());
    for (const CoreCtuResult& ctu: frame.ctus)
    {
      dqpFloats.push_back(3.0 * std::log(1.0 / std::max(1e-9, ctu.importance)) * invLog2);
    }
    const double dqpOffset = cfg.ctuRateNeutral ? rc360PaperTiMean(dqpFloats) : 0.0;
    std::vector<double> ctuTValues;
    std::vector<double> neutralDqpFloats;
    ctuTValues.reserve(frame.ctus.size());
    neutralDqpFloats.reserve(frame.ctus.size());
    for (int& h: frame.dqpHist)
    {
      h = 0;
    }
    frame.dqpClipCount = 0;
    double lambdaRatioSum = 0.0;
    frame.predBitsDeltaSum = 0.0;
    for (CoreCtuResult& ctu: frame.ctus)
    {
      ctu.dqpFloat = 3.0 * std::log(1.0 / std::max(1e-9, ctu.importance)) * invLog2;
      ctu.neutralDqpFloat = ctu.dqpFloat - dqpOffset;
      const int roundedDqp = rc360PaperTiRoundDqp(ctu.neutralDqpFloat);
      if (roundedDqp < -maxAbsDqp || roundedDqp > maxAbsDqp)
      {
        frame.dqpClipCount++;
      }
      ctu.dqp = Clip3(-maxAbsDqp, maxAbsDqp, roundedDqp);
      ctuTValues.push_back(ctu.importance);
      neutralDqpFloats.push_back(ctu.neutralDqpFloat);
      const int histDqp = Clip3(-2, 2, ctu.dqp);
      frame.dqpHist[histDqp + 2]++;
      const double lambdaRatio = std::pow(2.0, double(ctu.dqp) / 3.0);
      lambdaRatioSum += lambdaRatio;
      frame.predBitsDeltaSum += 1.0 / std::max(1e-9, lambdaRatio) - 1.0;
    }
    frame.ctuTP10 = rc360PaperTiQuantile(ctuTValues, 0.10, 1.0);
    frame.ctuTP50 = rc360PaperTiQuantile(ctuTValues, 0.50, 1.0);
    frame.ctuTP90 = rc360PaperTiQuantile(ctuTValues, 0.90, 1.0);
    frame.ctuDqpFloatP10 = rc360PaperTiQuantile(neutralDqpFloats, 0.10, 0.0);
    frame.ctuDqpFloatP50 = rc360PaperTiQuantile(neutralDqpFloats, 0.50, 0.0);
    frame.ctuDqpFloatP90 = rc360PaperTiQuantile(neutralDqpFloats, 0.90, 0.0);
    frame.meanCtuLambdaRatio = !frame.ctus.empty() ? lambdaRatioSum / double(frame.ctus.size()) : 1.0;
  }
  return out;
}

uint64_t Rc360PaperTI::satdDiffArea(const CPelBuf& org, int ox, int oy,
                                    const CPelBuf& pred, int px, int py,
                                    int w, int h)
{
  uint64_t sum = 0;
  const int blockW = (w / 4) * 4;
  const int blockH = (h / 4) * 4;
  for (int y = 0; y < blockH; y += 4)
  {
    for (int x = 0; x < blockW; x += 4)
    {
      int d[4][4];
      int m[4][4];
      for (int yy = 0; yy < 4; yy++)
      {
        const Pel* pOrg = org.bufAt(ox + x, oy + y + yy);
        const Pel* pPred = pred.bufAt(px + x, py + y + yy);
        for (int xx = 0; xx < 4; xx++)
        {
          d[yy][xx] = int(pOrg[xx]) - int(pPred[xx]);
        }
        const int s0 = d[yy][0] + d[yy][3];
        const int s1 = d[yy][1] + d[yy][2];
        const int s2 = d[yy][1] - d[yy][2];
        const int s3 = d[yy][0] - d[yy][3];
        m[yy][0] = s0 + s1;
        m[yy][1] = s3 + s2;
        m[yy][2] = s0 - s1;
        m[yy][3] = s3 - s2;
      }
      for (int xx = 0; xx < 4; xx++)
      {
        const int s0 = m[0][xx] + m[3][xx];
        const int s1 = m[1][xx] + m[2][xx];
        const int s2 = m[1][xx] - m[2][xx];
        const int s3 = m[0][xx] - m[3][xx];
        sum += std::abs(s0 + s1);
        sum += std::abs(s3 + s2);
        sum += std::abs(s0 - s1);
        sum += std::abs(s3 - s2);
      }
    }
  }
  return (sum + 1) >> 1;
}

uint64_t Rc360PaperTI::satdIntraArea(const CPelBuf& org, int x, int y, int w, int h)
{
  uint64_t sumSamples = 0;
  const int sampleCount = std::max(1, w * h);
  for (int yy = 0; yy < h; yy++)
  {
    const Pel* row = org.bufAt(x, y + yy);
    for (int xx = 0; xx < w; xx++)
    {
      sumSamples += uint64_t(row[xx]);
    }
  }
  const int mean = int((sumSamples + sampleCount / 2) / sampleCount);
  uint64_t sum = 0;
  const int blockW = (w / 4) * 4;
  const int blockH = (h / 4) * 4;
  for (int yy = 0; yy < blockH; yy += 4)
  {
    for (int xx = 0; xx < blockW; xx += 4)
    {
      int d[4][4];
      int m[4][4];
      for (int r = 0; r < 4; r++)
      {
        const Pel* row = org.bufAt(x + xx, y + yy + r);
        for (int c = 0; c < 4; c++)
        {
          d[r][c] = int(row[c]) - mean;
        }
        const int s0 = d[r][0] + d[r][3];
        const int s1 = d[r][1] + d[r][2];
        const int s2 = d[r][1] - d[r][2];
        const int s3 = d[r][0] - d[r][3];
        m[r][0] = s0 + s1;
        m[r][1] = s3 + s2;
        m[r][2] = s0 - s1;
        m[r][3] = s3 - s2;
      }
      for (int c = 0; c < 4; c++)
      {
        const int s0 = m[0][c] + m[3][c];
        const int s1 = m[1][c] + m[2][c];
        const int s2 = m[1][c] - m[2][c];
        const int s3 = m[0][c] - m[3][c];
        sum += std::abs(s0 + s1);
        sum += std::abs(s3 + s2);
        sum += std::abs(s0 - s1);
        sum += std::abs(s3 - s2);
      }
    }
  }
  return (sum + 1) >> 1;
}

Rc360PaperTI::SearchResult Rc360PaperTI::searchPreviousFrames(const std::vector<AnalysisFrame>& frames,
                                                              int futureFrameIdx,
                                                              int x,
                                                              int y,
                                                              int width,
                                                              int height,
                                                              double intraComplexity) const
{
  SearchResult best;
  best.predComplexity = std::numeric_limits<double>::max();
  if (futureFrameIdx < 0 || futureFrameIdx >= int(frames.size()) || intraComplexity <= 0.0)
  {
    return best;
  }
  const AnalysisFrame& future = frames[futureFrameIdx];
  const int range = std::max(0, m_cfg.searchRange);
  const int step = std::max(1, m_cfg.searchStep);
  for (int refFrameIdx = 0; refFrameIdx < futureFrameIdx; refFrameIdx++)
  {
    const AnalysisFrame& ref = frames[refFrameIdx];
    if (std::find(future.legalRefPocs.begin(), future.legalRefPocs.end(), ref.poc) == future.legalRefPocs.end())
    {
      continue;
    }
    const int refWidth = int(ref.luma.width);
    const int refHeight = int(ref.luma.height);
    const int maxX = std::max(0, refWidth - width);
    const int maxY = std::max(0, refHeight - height);
    for (int dy = -range; dy <= range; dy += step)
    {
      const int ry = Clip3(0, maxY, y + dy);
      for (int dx = -range; dx <= range; dx += step)
      {
        const int rx = Clip3(0, maxX, x + dx);
        const double pred = double(satdDiffArea(future.luma, x, y, ref.luma, rx, ry, width, height));
        if (pred < best.predComplexity)
        {
          best.frameIdx = refFrameIdx;
          best.rx = rx;
          best.ry = ry;
          best.predComplexity = pred;
        }
      }
    }
  }
  return best;
}

void Rc360PaperTI::analyzeWindow(int startPoc, int endPoc, const std::vector<AnalysisFrame>& inputFrames)
{
  if (!m_cfg.enabled)
  {
    return;
  }
  if (!beginWindow(startPoc, endPoc))
  {
    if (m_cfg.verbose)
    {
      std::printf("[RC360PaperTI][WindowCacheHit] startPOC=%d endPOC=%d\n", startPoc, endPoc);
      std::fflush(stdout);
    }
    return;
  }

  std::vector<AnalysisFrame> frames = inputFrames;
  std::sort(frames.begin(), frames.end(), [](const AnalysisFrame& a, const AnalysisFrame& b) { return a.poc < b.poc; });
  std::vector<CoreFrameInput> coreFrames(frames.size());
  std::vector<CoreEdge> edges;

  for (size_t frameIdx = 0; frameIdx < frames.size(); frameIdx++)
  {
    const AnalysisFrame& frame = frames[frameIdx];
    const int frameWidth = int(frame.luma.width);
    const int frameHeight = int(frame.luma.height);
    const int widthInCtus = (frameWidth + frame.ctuWidth - 1) / frame.ctuWidth;
    const int heightInCtus = (frameHeight + frame.ctuHeight - 1) / frame.ctuHeight;
    const int ctuCount = widthInCtus * heightInCtus;
    coreFrames[frameIdx].poc = frame.poc;
    coreFrames[frameIdx].legalRefPocs = frame.legalRefPocs;
    coreFrames[frameIdx].ctuComplexity.assign(ctuCount, 1e-9);

    const int blockSize = std::max(4, m_cfg.blockSize);
    for (int ctuY = 0; ctuY < heightInCtus; ctuY++)
    {
      for (int ctuX = 0; ctuX < widthInCtus; ctuX++)
      {
        const int ctu = ctuY * widthInCtus + ctuX;
        const int ctuX0 = ctuX * frame.ctuWidth;
        const int ctuY0 = ctuY * frame.ctuHeight;
        const int ctuW = std::min(frame.ctuWidth, frameWidth - ctuX0);
        const int ctuH = std::min(frame.ctuHeight, frameHeight - ctuY0);
        double ctuComplexity = 0.0;
        for (int by = 0; by < ctuH; by += blockSize)
        {
          for (int bx = 0; bx < ctuW; bx += blockSize)
          {
            const int x = ctuX0 + bx;
            const int y = ctuY0 + by;
            const int bw = std::min(blockSize, frameWidth - x);
            const int bh = std::min(blockSize, frameHeight - y);
            if (bw < 4 || bh < 4)
            {
              continue;
            }
            const double intra = std::max(1.0, double(satdIntraArea(frame.luma, x, y, bw, bh)));
            ctuComplexity += intra;
            if (frameIdx == 0)
            {
              continue;
            }
            const SearchResult search = searchPreviousFrames(frames, int(frameIdx), x, y, bw, bh, intra);
            if (search.frameIdx < 0 || !std::isfinite(search.predComplexity))
            {
              continue;
            }
            const double delta = dependencyDelta(search.predComplexity, intra);
            if (delta <= 0.0)
            {
              continue;
            }
            const AnalysisFrame& refFrame = frames[search.frameIdx];
            const int refFrameWidth = int(refFrame.luma.width);
            const int refFrameHeight = int(refFrame.luma.height);
            const int refWidthInCtus = (refFrameWidth + refFrame.ctuWidth - 1) / refFrame.ctuWidth;
            const int refHeightInCtus = (refFrameHeight + refFrame.ctuHeight - 1) / refFrame.ctuHeight;
            const int refCtuX = Clip3(0, refWidthInCtus - 1, search.rx / refFrame.ctuWidth);
            const int refCtuY = Clip3(0, refHeightInCtus - 1, search.ry / refFrame.ctuHeight);
            const int refCtu = refCtuY * refWidthInCtus + refCtuX;
            const double areaWeight = double(std::max(1, bw * bh)) / double(std::max(1, ctuW * ctuH));
            edges.push_back({ search.frameIdx, refCtu, int(frameIdx), ctu, delta * areaWeight });
          }
        }
        coreFrames[frameIdx].ctuComplexity[ctu] = std::max(1e-9, ctuComplexity);
      }
    }
  }

  const CoreResult result = solveCoreForTest(coreFrames, edges, m_cfg);
  storeCoreResult(startPoc, endPoc, result);

  if (m_cfg.verbose)
  {
    for (const CoreFrameResult& frame: result.frames)
    {
      std::printf("[RC360PaperTI][Stats] windowStart=%d windowEnd=%d POC=%d ctus=%d rawFrameT=%.9f frameT=%.9f frameLambdaRatio=%.9f medianCtuT=%.9f minCtuT=%.9f maxCtuT=%.9f edges=%d blockSize=%d searchRange=%d searchStep=%d frameSignalMode=%d frameLogNeutral=%d ctuRateNeutral=%d ctuDqpMax=%d ctuTP10=%.9f ctuTP50=%.9f ctuTP90=%.9f dqpFloatP10=%.9f dqpFloatP50=%.9f dqpFloatP90=%.9f dqpHistM2=%d dqpHistM1=%d dqpHist0=%d dqpHistP1=%d dqpHistP2=%d dqpClipCount=%d meanCtuLambdaRatio=%.9f predBitsDeltaSum=%.9f\n",
                  startPoc, endPoc, frame.poc, int(frame.ctus.size()), frame.rawFrameImportance,
                  frame.frameImportance, frame.frameLambdaRatio, frame.medianCtuImportance, frame.minCtuImportance,
                  frame.maxCtuImportance, frame.edgeCount, std::max(4, m_cfg.blockSize),
                  std::max(0, m_cfg.searchRange), std::max(1, m_cfg.searchStep),
                  m_cfg.frameSignalMode, m_cfg.frameLogNeutral ? 1 : 0, m_cfg.ctuRateNeutral ? 1 : 0,
                  std::max(0, m_cfg.ctuDqpDeltaMax), frame.ctuTP10, frame.ctuTP50, frame.ctuTP90,
                  frame.ctuDqpFloatP10, frame.ctuDqpFloatP50, frame.ctuDqpFloatP90,
                  frame.dqpHist[0], frame.dqpHist[1], frame.dqpHist[2], frame.dqpHist[3], frame.dqpHist[4],
                  frame.dqpClipCount, frame.meanCtuLambdaRatio, frame.predBitsDeltaSum);
    }
    std::fflush(stdout);
  }
}
