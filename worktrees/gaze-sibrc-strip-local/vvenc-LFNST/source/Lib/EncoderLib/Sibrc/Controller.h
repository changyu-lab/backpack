#pragma once
#include <array>
#include <cstddef>
#include <string>
#include <vector>
namespace vvenc { namespace sibrc {
struct Prediction { double rate=0, distortion=0; };
struct Model {
 std::array<double,6> rate{{0,0,0,0,0,0}}, distortion{{0,0,0,0,0,0}};
 std::string pictureType="P";
 int schemaVersion=1,featureSelector=4;
 double informationScale=1,informationFloor=1e-12;
 static Model load(const std::string& path);
 Prediction predict(double ieff,int qp,double sphereArea) const;
};
struct Decision {
 int qp=0,offset=0; double lambda=0,deltaRate=0,deltaDistortion=0,price=0,predictedRemainingBits=0;
 Prediction prediction; bool fallback=false;
 double minimumRemainingBits=0,maximumRemainingBits=0;
 int fallbackReason=0; // 0:none,1:prediction,2:budget,3:below minimum,4:price search
};
double ibWeight(double rhoSquared,double beta);
double scaleLambda(double baseLambda,int offset);
class Controller {
public:
 explicit Controller(const Model& model,int minOffset=-2,int maxOffset=2);
 void begin(const std::vector<double>& ieff,const std::vector<double>& sphereArea,int pictureQP);
 Decision decide(std::size_t ctu,int baseQP,double baseLambda,double remainingBits,std::size_t end=0);
 void feedback(double bits,double weightedMse);
 double rateCorrection() const { return m_deltaR; }
 double distortionCorrection() const { return m_deltaD; }
 std::size_t zeroRateSamples() const { return m_zeroR; }
 std::size_t zeroDistortionSamples() const { return m_zeroD; }
 const Decision& lastDecision() const {return m_last;}
private:
 Model m_model; int m_min,m_max,m_pictureQP=0;
 std::vector<double> m_ieff,m_area;
 double m_deltaR=0,m_deltaD=0;
 std::size_t m_zeroR=0,m_zeroD=0,m_ctu=0; bool m_pending=false;
 Decision m_last;
};
}}
