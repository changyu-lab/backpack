// Thin file adapter; S/CPP logic is compiled directly from unmodified 360Lib.
#include "Lib360/TSPSNRMetricCalc.h"
#include "Lib360/TCPPPSNRMetricCalc.h"
#include "CommonLib/Rom.h"
#include <fstream>
#include <iostream>
#include <iomanip>
#include <memory>
#include <vector>
#include <thread>
#include <mutex>
#include <atomic>
#include <algorithm>
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
 if(argc<8||argc>10)throw std::runtime_error("source8 recon10 width height frames sphere output.json [workers=1] [all|s-only]");
 int w=std::stoi(argv[3]),h=std::stoi(argv[4]),n=std::stoi(argv[5]);
 if(w<32||h<16||w%2||h%2||n<=0)throw std::runtime_error("invalid dimensions/frames");
 initROM();
 SVideoInfo vi{};vi.geoType=SVIDEO_EQUIRECT;vi.iFaceWidth=w;vi.iFaceHeight=h;vi.iNumFaces=1;
 vi.framePackStruct.chromaFormatIDC=ChromaFormat::_420;vi.framePackStruct.chromaSampleLocType=2;vi.framePackStruct.rows=vi.framePackStruct.cols=1;
 InputGeoParam gp{};gp.chromaFormat=ChromaFormat::_420;gp.nBitDepth=gp.nOutputBitDepth=10;gp.iInterp[0]=SI_LANCZOS3;gp.iInterp[1]=SI_LANCZOS2;
 BitDepths ref{},rec{};ref[ChannelType::LUMA]=ref[ChannelType::CHROMA]=8;rec[ChannelType::LUMA]=rec[ChannelType::CHROMA]=10;
 std::ifstream fa(argv[1],std::ios::binary),fb(argv[2],std::ios::binary);if(!fa||!fb)throw std::runtime_error("cannot open input");
 int workers=argc>=9?std::stoi(argv[8]):1;if(workers<1||workers>4)throw std::runtime_error("workers must be 1..4");workers=std::min(workers,n);
 bool cpp=argc<10||std::string(argv[9])=="all";if(argc==10&&!cpp&&std::string(argv[9])!="s-only")throw std::runtime_error("invalid metric mode");
 std::vector<double> sv(n),cv(n);std::mutex io,print;int next=0;std::atomic<int> done{0};std::exception_ptr failure;
 auto work=[&](){try {
  // Every worker owns its metric and geometry state; original per-picture sums stay serial.
  std::unique_ptr<TGeometry> geo(TGeometry::create(vi,&gp));
  TSPSNRMetric s;s.setSPSNREnabledFlag(true);s.setReferenceBitDepth(ref);s.setOutputBitDepth(rec);s.sphSampoints(argv[6]);s.initCFSPSNR(vi,vi,gp);s.createTable(geo.get());
  TCPPPSNRMetric c;c.setCPPPSNREnabledFlag(cpp);c.setReferenceBitDepth(ref);c.setOutputBitDepth(rec);if(cpp)c.initCPPPSNR(gp,w,h,vi,vi);
  PelStorage a,b;a.create(ChromaFormat::_420,Area(Position(),Size(w,h)));b.create(ChromaFormat::_420,Area(Position(),Size(w,h)));
  for(;;){int k;{std::lock_guard<std::mutex> lock(io);if(next>=n)return;k=next++;readPicture(fa,a,false);readPicture(fb,b,true);}
   s.xCalculateSPSNR(a,b);sv[k]=s.getSPSNR()[0];if(cpp){c.xCalculateCPPPSNR(&a,&b);cv[k]=c.getCPPPSNR()[0];}int completed=++done;
   if(k==0||completed%10==0){std::lock_guard<std::mutex> lock(print);std::cerr<<"PROGRESS "<<completed<<"/"<<n<<" POC "<<k<<" "<<sv[k]<<" "<<cv[k]<<std::endl;}
  }
 }catch(...){std::lock_guard<std::mutex> lock(io);if(!failure)failure=std::current_exception();next=n;}};
 std::vector<std::thread> threads;for(int t=0;t<workers;t++)threads.emplace_back(work);for(auto&t:threads)t.join();if(failure)std::rethrow_exception(failure);
 std::ofstream o;o.exceptions(std::ios::failbit|std::ios::badbit);o.open(argv[7]);o<<std::setprecision(17)<<"{\"picture_y_spsnr\":[";for(int k=0;k<n;k++)o<<(k?",":"")<<sv[k];o<<"]";if(cpp){o<<",\"picture_y_cpppsnr\":[";for(int k=0;k<n;k++)o<<(k?",":"")<<cv[k];o<<"]";}o<<"}";o.close();
 return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
