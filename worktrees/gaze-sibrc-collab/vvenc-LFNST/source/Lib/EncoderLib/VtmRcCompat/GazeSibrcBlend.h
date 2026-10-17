#pragma once
#include <cmath>
#include <stdexcept>

namespace vvenc { namespace gaze {
// Convex target blend, applied once before the VTM lambda/QP estimate.
inline int blendTarget(int original, int strip, double alpha)
{
  if(original < 1 || strip < 1 || !std::isfinite(alpha) || alpha < 0 || alpha > 1)
    throw std::invalid_argument("Invalid gaze/SIBRC target blend");
  if(alpha == 0) return original;
  if(alpha == 1) return strip;
  return static_cast<int>(std::floor((1-alpha)*original + alpha*strip + 0.5));
}
} }
