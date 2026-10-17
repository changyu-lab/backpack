// Paper equations and strict offline inputs; independent of the VTM RC kernel.
#pragma once
#include <istream>
#include <vector>
#include <cstdint>
namespace vvenc { namespace gaze {
struct Geometry { int width,height,ctu,bitdepth,frames;
  int cols() const {return (width+ctu-1)/ctu;}
  int rows() const {return (height+ctu-1)/ctu;}
  int count() const {return cols()*rows();}
};
double latitude(int y,int height);
std::vector<double> stripLatitudes(const Geometry& g);
double dependency(double strength,double d1,double r1,double d2,double r2);
double sampleError(int original,int reconstructed,const int16_t* inverse);
struct Optimized { double lambda,rawLambda; int qp; bool clipped; };
Optimized optimize(double lambda,int qp,double phi,bool key,bool complex,int bitdepth);
class StripBudget {
  int m_cols,m_next=0; bool m_pending=false;
  std::vector<double> m_features,m_latitudes,m_pixels;
  double m_left=0,m_average=0; bool m_fallback=false;
public:
  StripBudget(int cols,const std::vector<double>& features,const std::vector<double>& latitudes,const std::vector<double>& pixels={});
  int target(int ctu,int frameLeft);
  void feedback(int bits);
  double left() const {return m_left;}
  bool fallback() const {return m_fallback;}
};
class Features {
  std::vector<std::vector<double>> m_spatial,m_temporal;
public:
  Features(std::istream& input,const Geometry& geometry);
  const std::vector<double>& at(int poc,bool intra) const;
};
class Gaze {
  std::vector<std::vector<bool>> m_key;
public:
  Gaze(std::istream& input,const Geometry& geometry);
  bool key(int poc,int ctu) const {return m_key.at(poc).at(ctu);}
};
} }
