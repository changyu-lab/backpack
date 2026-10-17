/* The copyright in this software is being made available under the BSD
 * License, included below. This software may be subject to other third party
 * and contributor rights, including patent rights, and no such rights are
 * granted under this license.
 *
 * Copyright (c) 2010-2023, ITU/ISO/IEC
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *  * Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright notice,
 *    this list of conditions and the following disclaimer in the documentation
 *    and/or other materials provided with the distribution.
 *  * Neither the name of the ITU/ISO/IEC nor the names of its contributors may
 *    be used to endorse or promote products derived from this software without
 *    specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
 * BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
 * THE POSSIBILITY OF SUCH DAMAGE.
 */

#pragma once
#ifndef VTMRC_DISTORTION_PRECISION_ADJUSTMENT
#define VTMRC_DISTORTION_PRECISION_ADJUSTMENT(x) 0
#endif
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdarg>
#include <stdexcept>
#ifndef VTMRC_CHECK
#define VTMRC_CHECK(c, message) do { if(c) throw std::runtime_error(message); } while(false)
#endif
namespace vvenc { namespace vtmrc {
static constexpr int MAX_GOP = 64;
struct Fraction
{
  int num = 0;
  int den = 1;

  int    getIntValRound() const { return (num + den / 2) / den; }
  double getFloatVal() const { return static_cast<double>(num) / den; }
};

inline bool operator==(const Fraction& a, const Fraction& b) { return a.num == b.num && a.den == b.den; }
inline bool operator!=(const Fraction& a, const Fraction& b) { return !(a == b); }

template <typename T> inline T Clip3 (const T minVal, const T maxVal, const T a) { return std::min<T> (std::max<T> (minVal, a) , maxVal); }
// Only these GOP fields are read by the unchanged RC arithmetic.
struct GOPEntry { int m_POC = -1; bool m_refPic = false; };
struct GeneralHrdParams {
 uint32_t bitRateScale = 0, cpbSizeScale = 0;
 uint32_t getBitRateScale() const { return bitRateScale; }
 uint32_t getCpbSizeScale() const { return cpbSizeScale; }
};
struct OlsHrdParams {
 uint32_t cpbSizeValueMinus1 = 0, bitRateValueMinus1 = 0;
 uint32_t getCpbSizeValueMinus1(int, int) const { return cpbSizeValueMinus1; }
 uint32_t getBitRateValueMinus1(int, int) const { return bitRateValueMinus1; }
};
enum MsgLevel { NOTICE, WARNING };
inline void msg(MsgLevel, const char* fmt, ...) { va_list args; va_start(args, fmt); vprintf(fmt,args); va_end(args); }
} }
