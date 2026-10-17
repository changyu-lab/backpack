#pragma once

#include "CommonLib/CommonDef.h"

#if RC360_FB_TC_IEFF

#include <algorithm>
#include <cmath>
#include <cstddef>

#include "CommonLib/b1_coeff_rho_n32.h"

namespace rc360_ieff
{

struct IeffCfg
{
  double beta     = 0.2;
  double eps      = 1e-12;
  double minCos   = 1e-6;
};

static inline double clampd(double x, double lo, double hi)
{
  return std::max(lo, std::min(hi, x));
}

using RhoSquareTableN16 = const double (*)[16];

static inline RhoSquareTableN16 selectRhoSquareTableN16(double stretch)
{
  if (stretch < 1.28)
  {
    return rc360_coeff::B1_COEFF_RHO_SQUARE_N16_S1_15;
  }
  else if (stretch < 1.705)
  {
    return rc360_coeff::B1_COEFF_RHO_SQUARE_N16_S1_41;
  }
  else if (stretch < 2.93)
  {
    return rc360_coeff::B1_COEFF_RHO_SQUARE_N16_S2_00;
  }
  else
  {
    return rc360_coeff::B1_COEFF_RHO_SQUARE_N16_S3_86;
  }
}

static inline double getRhoSquareN16(int u, int v, double stretch)
{
  u = std::max(0, std::min(15, u));
  v = std::max(0, std::min(15, v));

  RhoSquareTableN16 table = selectRhoSquareTableN16(stretch);
  const double rho2 = table[v][u];

  return clampd(rho2, 0.0, 0.999999);
}

static inline double computeIeffBlock16FromVar(double varResi, double cosPhi, const IeffCfg& cfg)
{
  if (varResi <= 0.0)
  {
    return 0.0;
  }

  varResi /= 256.0;
  cosPhi = clampd(std::fabs(cosPhi), cfg.minCos, 1.0);

  const double stretch  = 1.0 / cosPhi;
  const double betaSafe = clampd(cfg.beta, 1e-9, 0.999999);
  const int uMax = std::max(0, std::min(15, int(std::floor(15.0 * cosPhi + 1e-9))));

  double ieff = 0.0;

  for (int v = 0; v < 16; ++v)
  {
    for (int u = 0; u < 16; ++u)
    {
      if (u > uMax)
      {
        continue;
      }

      const double rho2 = getRhoSquareN16(u, v, stretch);

      if (rho2 <= betaSafe)
      {
        continue;
      }

      const double coeffEnergy  = varResi * rc360_coeff::DCT2_RURV_N16_RHO060[v][u];
      const double targetEnergy = cosPhi * coeffEnergy;
      const double denom        = betaSafe * std::max(1.0 - rho2, cfg.eps);
      const double gammaStar    = std::max(0.0, (rho2 - betaSafe) / denom);
      const double iHat         = 0.5 * std::log2(1.0 + gammaStar);

      ieff += targetEnergy * iHat;
    }
  }

  return ieff;
}

template<typename PelT>
static inline double calcResidualVariance16x16(
  const PelT* org,
  ptrdiff_t orgStride,
  const PelT* predOrRef,
  ptrdiff_t predOrRefStride)
{
  double mean = 0.0;
  double m2   = 0.0;
  int n       = 0;

  for (int y = 0; y < 16; ++y)
  {
    const PelT* orgRow = org + y * orgStride;
    const PelT* refRow = predOrRef + y * predOrRefStride;

    for (int x = 0; x < 16; ++x)
    {
      const double r = double(orgRow[x]) - double(refRow[x]);

      ++n;
      const double delta = r - mean;
      mean += delta / double(n);
      const double delta2 = r - mean;
      m2 += delta * delta2;
    }
  }

  return n > 0 ? m2 / double(n) : 0.0;
}

static inline double calcResidualVariance16x16(const int* residual, int residualStride)
{
  double mean = 0.0;
  double m2   = 0.0;
  int n       = 0;

  for (int y = 0; y < 16; ++y)
  {
    const int* row = residual + y * residualStride;

    for (int x = 0; x < 16; ++x)
    {
      const double r = double(row[x]);

      ++n;
      const double delta = r - mean;
      mean += delta / double(n);
      const double delta2 = r - mean;
      m2 += delta * delta2;
    }
  }

  return n > 0 ? m2 / double(n) : 0.0;
}

static inline double computeIeffBlock16FromResidual(
  const int* residual,
  int residualStride,
  double cosPhi,
  const IeffCfg& cfg)
{
  const double varResi = calcResidualVariance16x16(residual, residualStride);

  return computeIeffBlock16FromVar(varResi, cosPhi, cfg);
}

template<typename PelT>
static inline double computeIeffBlock16FromOrgAndPred(
  const PelT* org,
  ptrdiff_t orgStride,
  const PelT* predOrRef,
  ptrdiff_t predOrRefStride,
  double cosPhi,
  const IeffCfg& cfg)
{
  const double varResi = calcResidualVariance16x16(org, orgStride, predOrRef, predOrRefStride);

  return computeIeffBlock16FromVar(varResi, cosPhi, cfg);
}

static inline double cosPhiFromRowCenter(double rowCenter, int pictureHeight)
{
  if (pictureHeight <= 0)
  {
    return 1.0;
  }

  const double pi = 3.14159265358979323846;
  const double phi = (0.5 - rowCenter / double(pictureHeight)) * pi;

  return std::max(std::cos(phi), 1e-6);
}

template<typename PelT>
static inline double computeCtuIeffFromOrgAndPred(
  const PelT* orgCtu,
  ptrdiff_t orgStride,
  const PelT* predCtu,
  ptrdiff_t predStride,
  int ctuX,
  int ctuY,
  int ctuW,
  int ctuH,
  int picHeight,
  const IeffCfg& cfg)
{
  double sumIeff = 0.0;
  int blockCount = 0;

  for (int by = 0; by + 16 <= ctuH; by += 16)
  {
    for (int bx = 0; bx + 16 <= ctuW; bx += 16)
    {
      const PelT* orgPtr  = orgCtu  + by * orgStride  + bx;
      const PelT* predPtr = predCtu + by * predStride + bx;

      const double rowCenter = double(ctuY + by) + 8.0;
      const double cosPhi = cosPhiFromRowCenter(rowCenter, picHeight);

      sumIeff += computeIeffBlock16FromOrgAndPred(orgPtr, orgStride, predPtr, predStride, cosPhi, cfg);
      ++blockCount;
    }
  }

  return blockCount > 0 ? sumIeff / double(blockCount) : 0.0;
}

} // namespace rc360_ieff

#endif // RC360_FB_TC_IEFF
