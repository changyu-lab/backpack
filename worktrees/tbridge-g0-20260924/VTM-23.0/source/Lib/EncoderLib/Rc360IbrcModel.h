/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 */

#pragma once

#include <array>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>

#ifndef IBRC360SplitSkipModel
#define IBRC360SplitSkipModel 0
#endif

#ifndef IBRC360ClosedLoopRateModel
#define IBRC360ClosedLoopRateModel 0
#endif

#ifndef IBRC360FrameMedianIeffModel
#define IBRC360FrameMedianIeffModel 0
#endif

#ifndef IBRC360RdDomainGuard
#define IBRC360RdDomainGuard 0
#endif

#ifndef IBRC360RdGuardIeffMin
#define IBRC360RdGuardIeffMin 1.028678
#endif

#ifndef IBRC360RdGuardIeffMax
#define IBRC360RdGuardIeffMax 1.573470
#endif

#ifndef IBRC360CtuIeffCalib
#define IBRC360CtuIeffCalib 0
#endif

#ifndef IBRC360CtuIeffFitMedian
#define IBRC360CtuIeffFitMedian 1.207007
#endif

#ifndef IBRC360CtuIeffCalibLogScaleLow
#define IBRC360CtuIeffCalibLogScaleLow 1.50
#endif

#ifndef IBRC360CtuIeffCalibLogScaleHigh
#define IBRC360CtuIeffCalibLogScaleHigh 1.00
#endif

#ifndef IBRC360RdMonotonicModel
#define IBRC360RdMonotonicModel 1
#endif

#ifndef IBRC360RdMinDistDlnDx
#define IBRC360RdMinDistDlnDx 0.020
#endif

#ifndef IBRC360RdMaxRateDlnDx
#define IBRC360RdMaxRateDlnDx -0.020
#endif

#ifndef IBRC360IeffVersion
#define IBRC360IeffVersion 2
#endif

#ifndef IBRC360OldIeffRateC0Offset
#define IBRC360OldIeffRateC0Offset 0.00
#endif

#ifndef IBRC360RateBiasResidualClip
#define IBRC360RateBiasResidualClip 1.25
#endif

struct Rc360IbrcPolyModel
{
  double c0 = 0.0;
  double c1 = 0.0;
  double c2 = 0.0;
  double c3 = 0.0;
  double c4 = 0.0;
  double c5 = 0.0;
};

using Rc360IbrcLogPoly = Rc360IbrcPolyModel;

struct Rc360IbrcModelState
{
  Rc360IbrcPolyModel rate;
  Rc360IbrcPolyModel dist;
};

struct Rc360IbrcSequenceModel
{
  const char* sequence = "";
  Rc360IbrcPolyModel rate;
  Rc360IbrcPolyModel dist;
  double ieffMedian = 1.0;
};

inline constexpr double RC360_IBRC_MODEL_IEFF_NORM_MIN = 0.35;
inline constexpr double RC360_IBRC_MODEL_IEFF_NORM_MAX = 2.85;
inline constexpr double RC360_IBRC_MODEL_BPP_MAX       = 4.0;

inline Rc360IbrcPolyModel RC360_IBRC_RATE_MODEL =
{
#if IBRC360IeffOnlyCtuRD
  10.9015, -6.62649, -2.72217, 0.433281, -0.356687, 0.548068
#else
  -0.9295665944, -1.4077610147, 2.5377401919, -0.5439235363, 0.0, 0.0
#endif
};

inline Rc360IbrcPolyModel RC360_IBRC_DIST_MODEL =
{
#if IBRC360IeffOnlyCtuRD
  5.50867, -0.272468, -0.32481, 0.0879897, 0.0553805, 0.046042
#else
  5.8068847576, -0.5425803632, -0.3006400785, 0.0838033987, 0.0414522760, 0.0831503006
#endif
};

inline double RC360_IBRC_MODEL_IEFF_MEDIAN =
#if IBRC360IeffOnlyCtuRD
  1.0;
#else
  1816.9280749340405;
#endif

inline bool RC360_IBRC_MODEL_INITIALIZED = false;
inline bool RC360_IBRC_EXTERNAL_MODEL_LOADED = false;

#if IBRC360SplitSkipModel
inline Rc360IbrcModelState RC360_IBRC_FRAME_MODEL =
{
  RC360_IBRC_RATE_MODEL,
  RC360_IBRC_DIST_MODEL
};
#if IBRC360ClosedLoopRateModel && IBRC360ClosedLoopRateTargetSplit && IBRC360ClosedLoopRateSegmentSplit
inline std::array<Rc360IbrcModelState, 10> RC360_IBRC_CTU_SKIP_MODELS =
{{
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }
}};
#elif IBRC360ClosedLoopRateModel && IBRC360ClosedLoopRateTargetSplit
inline std::array<Rc360IbrcModelState, 6> RC360_IBRC_CTU_SKIP_MODELS =
{{
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }
}};
#else
inline std::array<Rc360IbrcModelState, 3> RC360_IBRC_CTU_SKIP_MODELS =
{{
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL },
  { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }
}};
#endif
#endif

inline const Rc360IbrcSequenceModel RC360_IBRC_SEQUENCE_MODELS[] =
{
  {
    "AerialCity",
#if IBRC360IeffOnlyCtuRD
    { 10.9015, -6.62649, -2.72217, 0.433281, -0.356687, 0.548068 },
    { 5.50867, -0.272468, -0.32481, 0.0879897, 0.0553805, 0.046042 },
    1.0
#else
    { -0.9295665944, -1.4077610147, 2.5377401919, -0.5439235363, 0.0, 0.0 },
    { 5.8068847576, -0.5425803632, -0.3006400785, 0.0838033987, 0.0414522760, 0.0831503006 },
    1816.9280749340405
#endif
  },
  {
    "PoleVault_le",
    { 1.45066, -1.88987, 3.84421, -0.538847, -0.656533, 0.0454789 },
    { 5.8674, -0.237015, -0.239626, 0.0868055, 0.126785, 0.0412086 }
  },
  {
    "DrivingInCity",
    { 2.12343, -2.15922, 0.864782, -0.260397, 2.55749, 0.0918062 },
    { 5.77594, -0.152494, -0.843367, 0.218248, 0.123204, 0.0239336 }
  },
  {
    "DrivingInCountry",
    { 4.50287, -2.97044, 0.22764, -0.230845, -1.52596, 0.128046 },
    { 5.78802, -0.126233, -0.0820007, 0.0432069, 0.151312, 0.0252924 }
  }
};

static inline double rc360ClipPositive(double v, double lo, double hi)
{
  if (!std::isfinite(v))
  {
    return lo;
  }
  return std::max(lo, std::min(hi, v));
}

static inline double rc360IbrcCtuIeffCalibrated(double ieffNorm)
{
  const double ieff = rc360ClipPositive(ieffNorm, 1e-12, 1e12);
#if IBRC360CtuIeffCalib
  const double fitLo = std::log(rc360ClipPositive(double(IBRC360RdGuardIeffMin), 1e-12, 1e12));
  const double fitHi = std::log(rc360ClipPositive(double(IBRC360RdGuardIeffMax), 1e-12, 1e12));
  const double fitCenter = rc360ClipPositive(double(IBRC360CtuIeffFitMedian),
                                             double(IBRC360RdGuardIeffMin),
                                             double(IBRC360RdGuardIeffMax));
  const double zCenter = std::log(fitCenter);
  const double rawZ = std::log(ieff);
  const double lowSpan = std::max(1e-9, zCenter - fitLo);
  const double highSpan = std::max(1e-9, fitHi - zCenter);
  if (rawZ >= 0.0)
  {
    const double scale = std::max(1e-9, double(IBRC360CtuIeffCalibLogScaleHigh));
    return rc360ClipPositive(std::exp(zCenter + highSpan * std::tanh(rawZ / scale)),
                             double(IBRC360RdGuardIeffMin),
                             double(IBRC360RdGuardIeffMax));
  }
  const double scale = std::max(1e-9, double(IBRC360CtuIeffCalibLogScaleLow));
  return rc360ClipPositive(std::exp(zCenter + lowSpan * std::tanh(rawZ / scale)),
                           double(IBRC360RdGuardIeffMin),
                           double(IBRC360RdGuardIeffMax));
#else
  return ieff;
#endif
}

static inline double rc360IbrcPolyEvalFromXZ(const Rc360IbrcPolyModel& model,
                                             double x,
                                             double z)
{
  return model.c0
       + model.c1 * x
       + model.c2 * z
       + model.c3 * x * z
       + model.c4 * z * z
       + model.c5 * x * x;
}

static inline bool rc360IbrcParseModelCsvLine(const char* line,
                                              const std::string& requested,
                                              Rc360IbrcModelState& model,
                                              double& ieffMedian)
{
  if (line == nullptr || line[0] == '\0' || line[0] == '#')
  {
    return false;
  }

  char sequence[128] = { 0 };
  double median = 1.0;
  Rc360IbrcPolyModel rate;
  Rc360IbrcPolyModel dist;
  const int count = std::sscanf(line,
                                " %127[^,\r\n] , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf , %lf ",
                                sequence, &median,
                                &rate.c0, &rate.c1, &rate.c2, &rate.c3, &rate.c4, &rate.c5,
                                &dist.c0, &dist.c1, &dist.c2, &dist.c3, &dist.c4, &dist.c5);
  if (count != 14)
  {
    return false;
  }

  char* begin = sequence;
  while (*begin == ' ' || *begin == '\t')
  {
    begin++;
  }
  char* end = begin + std::strlen(begin);
  while (end > begin && (end[-1] == ' ' || end[-1] == '\t'))
  {
    *--end = '\0';
  }

  if (requested != begin)
  {
    return false;
  }

  model = { rate, dist };
  ieffMedian = rc360ClipPositive(median, 1e-9, 1e12);
  return true;
}

static inline bool rc360IbrcLoadExternalModel(const std::string& requested,
                                              Rc360IbrcModelState& model,
                                              double& ieffMedian)
{
  const char* fileName = std::getenv("RC360_IBRC_MODEL_CSV");
  if (fileName == nullptr || fileName[0] == '\0')
  {
    return false;
  }

  FILE* fp = std::fopen(fileName, "r");
  if (fp == nullptr)
  {
    std::printf("[RC360IBRC][ModelSelect] externalModelFile=%s openFailed=1\n", fileName);
    std::fflush(stdout);
    return false;
  }

  char line[2048];
  bool found = false;
  while (std::fgets(line, sizeof(line), fp) != nullptr)
  {
    if (rc360IbrcParseModelCsvLine(line, requested, model, ieffMedian))
    {
      found = true;
      break;
    }
  }
  std::fclose(fp);

  std::printf("[RC360IBRC][ModelSelect] externalModelFile=%s requested=%s found=%d\n",
              fileName, requested.c_str(), found ? 1 : 0);
  std::fflush(stdout);
  return found;
}

static inline void rc360IbrcInitModelFromEnv()
{
  if (RC360_IBRC_MODEL_INITIALIZED)
  {
    return;
  }
  RC360_IBRC_MODEL_INITIALIZED = true;

  const char* envSeq = std::getenv("RC360_IBRC_SEQUENCE");
  const std::string requested = envSeq ? std::string(envSeq) : std::string("AerialCity");
  const Rc360IbrcSequenceModel* selected = &RC360_IBRC_SEQUENCE_MODELS[0];
  for (const auto& model : RC360_IBRC_SEQUENCE_MODELS)
  {
    if (requested == model.sequence)
    {
      selected = &model;
      break;
    }
  }

  Rc360IbrcModelState selectedState = { selected->rate, selected->dist };
  double selectedIeffMedian = selected->ieffMedian;
  RC360_IBRC_EXTERNAL_MODEL_LOADED =
    rc360IbrcLoadExternalModel(requested, selectedState, selectedIeffMedian);

  RC360_IBRC_RATE_MODEL = selectedState.rate;
  RC360_IBRC_DIST_MODEL = selectedState.dist;
  RC360_IBRC_MODEL_IEFF_MEDIAN = selectedIeffMedian;
#if IBRC360IeffVersion == 2
  RC360_IBRC_RATE_MODEL.c0 += double(IBRC360OldIeffRateC0Offset);
#endif
#if IBRC360SplitSkipModel
  RC360_IBRC_FRAME_MODEL = { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL };
#if IBRC360ClosedLoopRateModel
  if (RC360_IBRC_EXTERNAL_MODEL_LOADED)
  {
    for (auto& model : RC360_IBRC_CTU_SKIP_MODELS)
    {
      model = { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL };
    }
  }
  else
  {
#if IBRC360ClosedLoopRateTargetSplit && IBRC360ClosedLoopRateSegmentSplit
  RC360_IBRC_CTU_SKIP_MODELS[0] =
  {
    { -3.6039984885779273, -0.680773119211342, 1.4440664197975157,
      -0.24535916018077394, 0.07329817957935462, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[1] =
  {
    { -3.353547740830068, -0.42990530123382836, 0.9518626122688464,
      -0.15266057295198837, 0.04233834654975302, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[2] =
  {
    { -8.245423025089554, -0.000100000000000, 0.15680294778016515,
      0.0, -0.06949557759062068, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[3] =
  {
    { -7.7335258970202405, -0.17562390600302238, 0.42284960530268834,
      -0.04689406261772898, -0.03672147724481481, 0.0032996595932576326 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[4] =
  {
    { -8.245423025089554, -0.000100000000000, 0.15680294778016515,
      0.0, -0.06949557759062068, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[5] =
  {
    { -7.7335258970202405, -0.17562390600302238, 0.42284960530268834,
      -0.04689406261772898, -0.03672147724481481, 0.0032996595932576326 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[6] =
  {
    { -6.986796817736144, -0.2162021826255595, 0.6208817990765432,
      -0.06251770652517429, -0.07053251703053841, 0.004198682015597592 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[7] =
  {
    { -6.206456972442555, -0.2754420710884136, 0.9834008926371687,
      -0.09921672204919059, -0.04458821351372736, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[8] =
  {
    { -6.150138281150291, -0.019193666794685225, 0.9387647102274393,
      -0.007313213790924083, -0.042344912249911666, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[9] =
  {
    { -5.588643882331123, -0.000100000000000, 1.0402222210852055,
      0.0, -0.06202619606271275, 0.0 },
    selected->dist
  };
#elif IBRC360ClosedLoopRateTargetSplit
  RC360_IBRC_CTU_SKIP_MODELS[0] =
  {
    { -3.6039984885779273, -0.680773119211342, 1.4440664197975157,
      -0.24535916018077394, 0.07329817957935462, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[1] =
  {
    { -3.353547740830068, -0.42990530123382836, 0.9518626122688464,
      -0.15266057295198837, 0.04233834654975302, 0.0 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[2] =
  {
    { -8.230497628430218, -0.03759290372525857, 0.1880826858720485,
      0.0, -0.05620107241967566, 0.0030050459403300656 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[3] =
  {
    { -8.230497628430218, -0.03759290372525857, 0.1880826858720485,
      0.0, -0.05620107241967566, 0.0030050459403300656 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[4] =
  {
    { -6.6487950621544325, -0.23129709945773713, 0.8003909934327258,
      -0.07588707880322283, -0.04950359273837086, 0.001650961906329769 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[5] =
  {
    { -5.8963202258028975, -0.00010000000000011456, 0.9760092142352061,
      0.0, -0.05171062631228301, 0.0 },
    selected->dist
  };
#else
  RC360_IBRC_CTU_SKIP_MODELS[0] =
  {
    { -3.62236968309577, -0.6597857755346445, 1.4263490925012388,
      -0.24734791508316137, 0.08107528344520643, -0.0027719169371483885 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[1] =
  {
    { -3.3663671973919773, -0.41181275406869366, 0.9417069225705316,
      -0.1561232525158969, 0.048777532715535636, -0.0028991369552492283 },
    selected->dist
  };
  RC360_IBRC_CTU_SKIP_MODELS[2] =
  {
    { -5.656819061942656, -0.49043953288269027, 1.1485736605728307,
      -0.17669832897404691, -0.08244327258199288, -0.0016486617089393845 },
    selected->dist
  };
#endif
  }
#else
  for (auto& model : RC360_IBRC_CTU_SKIP_MODELS)
  {
    model = { RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL };
  }
#endif
#endif
  std::printf("[RC360IBRC][ModelSelect] requested=%s selected=%s external=%d ieffMedian=%.9f rate=(%.9f,%.9f,%.9f,%.9f,%.9f,%.9f) distOrdMse=(%.9f,%.9f,%.9f,%.9f,%.9f,%.9f)\n",
              requested.c_str(), selected->sequence, RC360_IBRC_EXTERNAL_MODEL_LOADED ? 1 : 0,
              RC360_IBRC_MODEL_IEFF_MEDIAN,
              RC360_IBRC_RATE_MODEL.c0, RC360_IBRC_RATE_MODEL.c1, RC360_IBRC_RATE_MODEL.c2,
              RC360_IBRC_RATE_MODEL.c3, RC360_IBRC_RATE_MODEL.c4, RC360_IBRC_RATE_MODEL.c5,
              RC360_IBRC_DIST_MODEL.c0, RC360_IBRC_DIST_MODEL.c1, RC360_IBRC_DIST_MODEL.c2,
              RC360_IBRC_DIST_MODEL.c3, RC360_IBRC_DIST_MODEL.c4, RC360_IBRC_DIST_MODEL.c5);
  std::fflush(stdout);
}

static inline double rc360IbrcModelZFromIeff(double ieffNorm)
{
#if IBRC360FrameMedianIeffModel
  return std::log(rc360IbrcCtuIeffCalibrated(ieffNorm));
#else
  const double median = rc360ClipPositive(RC360_IBRC_MODEL_IEFF_MEDIAN, 1e-9, 1e9);
  return median > 1.0
       ? std::log(rc360ClipPositive(ieffNorm, 1e-9, 1e9) / median)
       : std::log(rc360ClipPositive(ieffNorm,
                                    RC360_IBRC_MODEL_IEFF_NORM_MIN,
                                    RC360_IBRC_MODEL_IEFF_NORM_MAX));
#endif
}

static inline double rc360IbrcLogPolyEval(const Rc360IbrcPolyModel& model,
                                          double qs,
                                          double ieffNorm)
{
  const double x = std::log(rc360ClipPositive(qs, 0.125, 512.0));
  const double z = rc360IbrcModelZFromIeff(ieffNorm);
  return rc360IbrcPolyEvalFromXZ(model, x, z);
}

static inline double rc360IbrcDlnDx(const Rc360IbrcPolyModel& model,
                                    double qs,
                                    double ieffNorm)
{
  const double x = std::log(rc360ClipPositive(qs, 0.125, 512.0));
  const double z = rc360IbrcModelZFromIeff(ieffNorm);
  return model.c1 + model.c3 * z + 2.0 * model.c5 * x;
}

static inline double rc360IbrcConstrainedDlnDx(const Rc360IbrcPolyModel& model,
                                              double qs,
                                              double ieffNorm,
                                              double slopeLimit,
                                              bool lowerBound)
{
  const double rawSlope = rc360IbrcDlnDx(model, qs, ieffNorm);
#if IBRC360RdMonotonicModel
  if (!std::isfinite(rawSlope))
  {
    return slopeLimit;
  }
  return lowerBound ? std::max(rawSlope, slopeLimit)
                    : std::min(rawSlope, slopeLimit);
#else
  return rawSlope;
#endif
}

static inline double rc360IbrcMonotonicLogDistEval(const Rc360IbrcPolyModel& model,
                                                  double qs,
                                                  double ieffNorm)
{
  const double x = std::log(rc360ClipPositive(qs, 0.125, 512.0));
  const double z = rc360IbrcModelZFromIeff(ieffNorm);
  const double rawSlope = model.c1 + model.c3 * z + 2.0 * model.c5 * x;
#if IBRC360RdMonotonicModel
  const double minSlope = std::max(0.0, double(IBRC360RdMinDistDlnDx));
  if (std::isfinite(rawSlope) && rawSlope < minSlope && std::abs(model.c5) > 1e-12)
  {
    const double anchorX = (minSlope - model.c1 - model.c3 * z) / (2.0 * model.c5);
    const double anchorLogD = rc360IbrcPolyEvalFromXZ(model, anchorX, z);
    return anchorLogD + minSlope * (x - anchorX);
  }
#endif
  return rc360IbrcPolyEvalFromXZ(model, x, z);
}

static inline double rc360IbrcRateBpp(const Rc360IbrcModelState& model, double qs, double ieffNorm)
{
  return rc360ClipPositive(std::exp(rc360IbrcLogPolyEval(model.rate, qs, ieffNorm)),
                           1e-12, RC360_IBRC_MODEL_BPP_MAX);
}

static inline double rc360IbrcRateBpp(double qs, double ieffNorm)
{
  return rc360IbrcRateBpp({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm);
}

static inline double rc360IbrcRateBits(const Rc360IbrcModelState& model, double qs, double ieffNorm, int numPixels)
{
  return std::max(1e-9, rc360IbrcRateBpp(model, qs, ieffNorm) * double(std::max(1, numPixels)));
}

static inline double rc360IbrcRateBits(double qs, double ieffNorm, int numPixels)
{
  return rc360IbrcRateBits({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm, numPixels);
}

static inline double rc360IbrcDistMse(const Rc360IbrcModelState& model, double qs, double ieffNorm)
{
  return rc360ClipPositive(std::exp(rc360IbrcMonotonicLogDistEval(model.dist, qs, ieffNorm)), 1e-12, 1e12);
}

static inline double rc360IbrcDistMse(double qs, double ieffNorm)
{
  return rc360IbrcDistMse({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm);
}

static inline double rc360IbrcLambdaFromQs(const Rc360IbrcModelState& model, double qs, double ieffNorm)
{
  const double x = std::log(rc360ClipPositive(qs, 0.125, 512.0));
  const double z = rc360IbrcModelZFromIeff(ieffNorm);
  const double bpp = rc360IbrcRateBpp(model, qs, ieffNorm);
  const double mse = rc360IbrcDistMse(model, qs, ieffNorm);
  (void)x;
  (void)z;
  const double dLnRateDx =
    rc360IbrcConstrainedDlnDx(model.rate, qs, ieffNorm, double(IBRC360RdMaxRateDlnDx), false);
  const double dLnDistDx =
    rc360IbrcConstrainedDlnDx(model.dist, qs, ieffNorm, double(IBRC360RdMinDistDlnDx), true);
  const double denom = bpp * dLnRateDx;
  if (!std::isfinite(denom) || std::abs(denom) < 1e-12)
  {
    return 1e12;
  }
  const double lambda = -mse * dLnDistDx / denom;
  return rc360ClipPositive(std::abs(lambda), 1e-12, 1e12);
}

static inline double rc360IbrcLambdaFromQs(double qs, double ieffNorm)
{
  return rc360IbrcLambdaFromQs({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm);
}

static inline double rc360IbrcDistDlnDx(const Rc360IbrcModelState& model, double qs, double ieffNorm)
{
  return rc360IbrcConstrainedDlnDx(model.dist, qs, ieffNorm, double(IBRC360RdMinDistDlnDx), true);
}

static inline double rc360IbrcRawDistDlnDx(const Rc360IbrcModelState& model, double qs, double ieffNorm)
{
  return rc360IbrcDlnDx(model.dist, qs, ieffNorm);
}

static inline double rc360IbrcRawDistDlnDx(double qs, double ieffNorm)
{
  return rc360IbrcRawDistDlnDx({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm);
}

static inline double rc360IbrcDistDlnDx(double qs, double ieffNorm)
{
  return rc360IbrcDistDlnDx({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, qs, ieffNorm);
}

static inline bool rc360IbrcCtuRdDomainValid(double qs, double ieffNorm, double* distDlnDxOut = nullptr)
{
  const double ieff = rc360ClipPositive(ieffNorm, 1e-12, 1e12);
  const double distDlnDx = rc360IbrcDistDlnDx(qs, ieff);
  if (distDlnDxOut != nullptr)
  {
    *distDlnDxOut = distDlnDx;
  }
  return ieff >= double(IBRC360RdGuardIeffMin)
      && ieff <= double(IBRC360RdGuardIeffMax)
      && std::isfinite(distDlnDx)
      && distDlnDx >= 0.0;
}

static inline double rc360IbrcQsFromLambda(const Rc360IbrcModelState& model, double lambda, double ieffNorm)
{
  const double target = rc360ClipPositive(lambda, 1e-12, 1e12);
  const double lo = std::log(0.125);
  const double hi = std::log(512.0);
  double bestX = lo;
  double bestErr = std::numeric_limits<double>::max();

  for (int i = 0; i <= 128; i++)
  {
    const double x = lo + (hi - lo) * double(i) / 128.0;
    const double q = std::exp(x);
    const double l = rc360IbrcLambdaFromQs(model, q, ieffNorm);
    const double err = std::abs(std::log(rc360ClipPositive(l, 1e-12, 1e12)) - std::log(target));
    if (err < bestErr)
    {
      bestErr = err;
      bestX = x;
    }
  }

  double a = std::max(lo, bestX - (hi - lo) / 128.0);
  double b = std::min(hi, bestX + (hi - lo) / 128.0);
  for (int iter = 0; iter < 32; iter++)
  {
    const double m1 = a + (b - a) / 3.0;
    const double m2 = b - (b - a) / 3.0;
    const double e1 = std::abs(std::log(rc360IbrcLambdaFromQs(model, std::exp(m1), ieffNorm)) - std::log(target));
    const double e2 = std::abs(std::log(rc360IbrcLambdaFromQs(model, std::exp(m2), ieffNorm)) - std::log(target));
    if (e1 < e2)
    {
      b = m2;
    }
    else
    {
      a = m1;
    }
  }
  return rc360ClipPositive(std::exp(0.5 * (a + b)), 0.125, 512.0);
}

static inline double rc360IbrcQsFromLambda(double lambda, double ieffNorm)
{
  return rc360IbrcQsFromLambda({ RC360_IBRC_RATE_MODEL, RC360_IBRC_DIST_MODEL }, lambda, ieffNorm);
}

#if IBRC360SplitSkipModel
static inline int rc360IbrcSkipClass(double skipRatio)
{
  const double r = rc360ClipPositive(skipRatio, 0.0, 1.0);
  if (r < 0.25) return 0;
  if (r < 0.75) return 1;
  return 2;
}

static inline Rc360IbrcModelState& rc360IbrcFrameModel()
{
  rc360IbrcInitModelFromEnv();
  return RC360_IBRC_FRAME_MODEL;
}

static inline Rc360IbrcModelState& rc360IbrcCtuSkipModel(int skipClass)
{
  rc360IbrcInitModelFromEnv();
  const int cls = std::max(0, std::min(int(RC360_IBRC_CTU_SKIP_MODELS.size()) - 1, skipClass));
  return RC360_IBRC_CTU_SKIP_MODELS[cls];
}

static inline int rc360IbrcClosedLoopRateClass(int skipClass, int targetClass, int temporalSegment)
{
#if IBRC360ClosedLoopRateModel && IBRC360ClosedLoopRateTargetSplit && IBRC360ClosedLoopRateSegmentSplit
  if (skipClass >= 2)
  {
    const int t = std::max(0, std::min(3, targetClass));
    const int s = std::max(0, std::min(1, temporalSegment));
    return 2 + t * 2 + s;
  }
#elif IBRC360ClosedLoopRateModel && IBRC360ClosedLoopRateTargetSplit
  if (skipClass >= 2)
  {
    return 2 + std::max(0, std::min(3, targetClass));
  }
#else
  (void)targetClass;
  (void)temporalSegment;
#endif
  return skipClass;
}

static inline double rc360IbrcClosedLoopRateBits(int skipClass, int targetClass, int temporalSegment,
                                                 double qs, double ieffNorm, int numPixels)
{
#if IBRC360ClosedLoopRateModel
  return rc360IbrcRateBits(rc360IbrcCtuSkipModel(rc360IbrcClosedLoopRateClass(skipClass, targetClass, temporalSegment)),
                           qs, ieffNorm, numPixels);
#else
  (void)skipClass;
  (void)targetClass;
  (void)temporalSegment;
  return rc360IbrcRateBits(qs, ieffNorm, numPixels);
#endif
}
#endif
