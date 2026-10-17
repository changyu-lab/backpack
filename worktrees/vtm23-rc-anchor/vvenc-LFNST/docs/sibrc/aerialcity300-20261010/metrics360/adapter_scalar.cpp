// Thin file adapter; S/CPP logic is compiled directly from unmodified 360Lib.
#include "Lib360/TSPSNRMetricCalc.h"
#include "Lib360/TCPPPSNRMetricCalc.h"
#include "CommonLib/Rom.h"
#include <fstream>
#include <iostream>
#include <iomanip>
#include <memory>
#include <vector>
static void readPicture(std::ifstream& f, PelStorage& pic, bool ten) {
 for (auto& b:pic.bufs) {
  std::vector<unsigned char> raw(size_t(b.width)*b.height*(ten?2:1));
  f.read(reinterpret_cast<char*>(raw.data()),raw.size());
  if(!f)throw std::runtime_error("truncated input");
  size_t i=0;
  for(int y=0;y<b.height;y++)for(int x=0;x<b.width;x++) {
   int n=raw[i++];if(ten)n+=int(raw[i++])<<8;
   if(n>(ten?1023:255))throw std::runtime_error("invalid sample");b.bufAt(x,y)[0]=n;
  }
 }
}
int main(int argc,char**argv) {try {
 if(argc!=8)throw std::runtime_error("source8 recon10 width height frames sphere output.json");
 int w=std::stoi(argv[3]),h=std::stoi(argv[4]),n=std::stoi(argv[5]);
 if(w<32||h<16||w%2||h%2||n<=0)throw std::runtime_error("invalid dimensions/frames");
 initROM();
 SVideoInfo vi{};vi.geoType=SVIDEO_EQUIRECT;vi.iFaceWidth=w;vi.iFaceHeight=h;vi.iNumFaces=1;
 vi.framePackStruct.chromaFormatIDC=ChromaFormat::_420;vi.framePackStruct.chromaSampleLocType=2;vi.framePackStruct.rows=vi.framePackStruct.cols=1;
 InputGeoParam gp{};gp.chromaFormat=ChromaFormat::_420;gp.nBitDepth=gp.nOutputBitDepth=10;gp.iInterp[0]=SI_LANCZOS3;gp.iInterp[1]=SI_LANCZOS2;
 BitDepths ref{},rec{};ref[ChannelType::LUMA]=ref[ChannelType::CHROMA]=8;rec[ChannelType::LUMA]=rec[ChannelType::CHROMA]=10;
 std::unique_ptr<TGeometry> geo(TGeometry::create(vi,&gp));
 TSPSNRMetric s;s.setSPSNREnabledFlag(true);s.setReferenceBitDepth(ref);s.setOutputBitDepth(rec);s.sphSampoints(argv[6]);s.createTable(geo.get());
 TCPPPSNRMetric c;c.setCPPPSNREnabledFlag(true);c.setReferenceBitDepth(ref);c.setOutputBitDepth(rec);c.initCPPPSNR(gp,w,h,vi,vi);
 PelStorage a,b;a.create(ChromaFormat::_420,Area(Position(),Size(w,h)));b.create(ChromaFormat::_420,Area(Position(),Size(w,h)));
 std::ifstream fa(argv[1],std::ios::binary),fb(argv[2],std::ios::binary);if(!fa||!fb)throw std::runtime_error("cannot open input");
 std::vector<double> sv,cv;
 for(int k=0;k<n;k++){readPicture(fa,a,false);readPicture(fb,b,true);s.xCalculateSPSNR(a,b);c.xCalculateCPPPSNR(&a,&b);sv.push_back(s.getSPSNR()[0]);cv.push_back(c.getCPPPSNR()[0]);if(k%50==0)std::cerr<<"METRIC "<<k<<" "<<sv.back()<<" "<<cv.back()<<std::endl;}
 std::ofstream o(argv[7]);o<<std::setprecision(17)<<"{\"picture_y_spsnr\":[";for(int k=0;k<n;k++)o<<(k?",":"")<<sv[k];o<<"],\"picture_y_cpppsnr\":[";for(int k=0;k<n;k++)o<<(k?",":"")<<cv[k];o<<"]}";
 return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
