// Explicit local spherical sampling proxy; see calibration metadata for its statistical definition.
#include "Preanalysis.h"
#include "Controller.h"
#include "CommonLib/Picture.h"
#include "CommonLib/Slice.h"
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <limits>
namespace vvenc { namespace sibrc {
static constexpr double pi=3.14159265358979323846;
Features analysePicture(const Picture& pic,int ctuSize,const Statistics* stats,std::ofstream* dump,int selector,bool collectAll) {
 if(selector<0||selector>7)throw std::invalid_argument("Invalid SIBRCFeature");
 auto orig=pic.getOrigBuf(COMP_Y);const int w=orig.width,h=orig.height,cols=(w+ctuSize-1)/ctuSize,rows=(h+ctuSize-1)/ctuSize;
 Features f;f.information.assign(cols*rows,0);f.area.assign(cols*rows,0);if(collectAll||selector!=4)f.descriptors.resize(cols*rows);std::vector<int> counts(cols*rows,0);
 const Slice& slice=*pic.slices[0];const Picture* ref=!slice.isIntra()&&slice.numRefIdx[0]>0?slice.getRefPic(REF_PIC_LIST_0,0):nullptr;
 CPelBuf rec;if(ref)rec=ref->getRecoBuf(COMP_Y);const double norm=std::pow(2.0,slice.sps->bitDepths[CH_L]-8);
 for(int y=0;y<h;y+=32)for(int x=0;x<w;x+=32){int k=(y/ctuSize)*cols+x/ctuSize;int dx=0,dy=0;double best=std::numeric_limits<double>::infinity();
 if(ref){auto sad=[&](int ax,int ay){double sum=0;for(int by=0;by<32;by+=4)for(int bx=0;bx<32;bx+=4){int ox=std::min(w-1,x+bx),oy=std::min(h-1,y+by);int rx=std::max(0,std::min<int>(rec.width-1,ox+ax)),ry=std::max(0,std::min<int>(rec.height-1,oy+ay));sum+=std::abs(orig.buf[oy*orig.stride+ox]-rec.buf[ry*rec.stride+rx]);}return sum;};
 for(int ay=-8;ay<=8;ay+=4)for(int ax=-8;ax<=8;ax+=4){double s=sad(ax,ay);if(s<best){best=s;dx=ax;dy=ay;}}
 int centreX=dx,centreY=dy;for(int ay=centreY-2;ay<=centreY+2;++ay)for(int ax=centreX-2;ax<=centreX+2;++ax){if(std::abs(ax)>8||std::abs(ay)>8)continue;double s=sad(ax,ay);if(s<best){best=s;dx=ax;dy=ay;}}}
 double residual[1024];for(int by=0;by<32;++by)for(int bx=0;bx<32;++bx){int ox=std::min(w-1,x+bx),oy=std::min(h-1,y+by);double p=128*norm;if(ref){int rx=std::max(0,std::min<int>(rec.width-1,ox+dx)),ry=std::max(0,std::min<int>(rec.height-1,oy+dy));p=rec.buf[ry*rec.stride+rx];}residual[by*32+bx]=(orig.buf[oy*orig.stride+ox]-p)/norm;}
 const double latitude=std::abs(90-180*(std::min<double>(h-1,y+15.5)+.5)/h);
 if(stats){if(collectAll||selector!=4){auto d=descriptorsFromResidual(residual,latitude,*stats,collectAll?-1:selector);for(int j=0;j<8;++j)f.descriptors[k][j]+=d[j];f.information[k]+=selector==4?informationFromResidual(residual,latitude,*stats):d[selector];}else f.information[k]+=informationFromResidual(residual,latitude,*stats);}
 ++counts[k];
 if(dump&&((y/32)*((w+31)/32)+x/32)%16==0)dump->write(reinterpret_cast<const char*>(residual),sizeof(residual));
 }
 for(int k=0;k<cols*rows;++k){if(counts[k]){f.information[k]/=counts[k];if(!f.descriptors.empty())for(auto& v:f.descriptors[k])v/=counts[k];}int x=(k%cols)*ctuSize,y=(k/cols)*ctuSize;for(int yy=y;yy<std::min(h,y+ctuSize);++yy)f.area[k]+=std::cos(pi*((yy+.5)/h-.5))*std::min(ctuSize,w-x);}
 if(dump&&!(*dump))throw std::runtime_error("SIBRC residual dump write failed");return f;
}
double weightedCtuMse(const Picture& pic,int ctu,int size) {
 auto o=pic.getOrigBuf(COMP_Y);auto r=pic.getRecoBuf(COMP_Y);int cols=(o.width+size-1)/size,x=(ctu%cols)*size,y=(ctu/cols)*size;double sse=0,area=0;double norm=std::pow(2.0,pic.slices[0]->sps->bitDepths[CH_L]-8);
 for(int yy=y;yy<std::min<int>(o.height,y+size);++yy){double weight=std::cos(pi*((yy+.5)/o.height-.5));for(int xx=x;xx<std::min<int>(o.width,x+size);++xx){double d=(o.buf[yy*o.stride+xx]-r.buf[yy*r.stride+xx])/norm;sse+=weight*d*d;area+=weight;}}
 return area>0?sse/area:0;
}
} }

