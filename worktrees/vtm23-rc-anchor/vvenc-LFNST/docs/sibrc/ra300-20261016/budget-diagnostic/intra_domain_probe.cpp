#include <iostream>
#include <iomanip>
#include <cmath>
#include <cfenv>
#include <cerrno>
#ifdef VTM_REFERENCE
#include "EncoderLib/RateCtrl.h"
MsgLevel g_verbosity=SILENT;
using Pic=EncRCPic;
#else
#include "VtmRcCompat/RateCtrl.h"
using namespace vvenc::vtmrc;
using Pic=VtmRcPic;
#endif
int main(){for(int bits:{10000,200,1,0,-6808,-3017,-5939,-2201,-6615}){
 Pic p;p.setTotalIntraCost(10000000.0);errno=0;std::feclearexcept(FE_ALL_EXCEPT);
 // Same official method; sanitizer records nonfinite-to-int conversion.
 int value=p.getRefineBitsForIntra(bits);
 std::cout<<bits<<' '<<value<<' '<<errno<<' '<<std::fetestexcept(FE_INVALID|FE_DIVBYZERO)<<'\n';
}}
