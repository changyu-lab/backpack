#pragma once
#include <cstdint>

namespace vvenc {

struct LardLfnstCovEntry
{
  uint8_t latBin;
  uint8_t width;
  uint8_t height;
  uint8_t setIdx;
  uint8_t transpose;
  uint8_t sbSize;
  uint8_t kIn;
  uint8_t outN;
  float varX[48];
  float varY[2][16];
  float expRetainedEnergy[2];
  float expZeroEnergy[2];
};

const LardLfnstCovEntry* getLardLfnstCovEntry( int latBin, int width, int height, int setIdx, bool transpose );
int getLardLfnstCovTableSize();

} // namespace vvenc
