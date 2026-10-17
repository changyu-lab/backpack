#include "Sibrc/Controller.h"
#include <cmath>
#include <stdexcept>
#include <iostream>
using namespace vvenc::sibrc;
void require(bool b){if(!b)throw std::runtime_error("temporal assertion failed");}
int main(){
 Model m;m.rate={{8,-1,0,0,0,0}};m.distortion={{-2,1,0,0,0,0}};
 Controller a(m),b(m),c(m);a.begin({1,1},{1,1},30);b.begin({1,1},{1,1},30,{1,1});c.begin({1,1},{1,1},30,{4,1});
 double budget=m.predict(1,30,1).rate*2;
 auto x=a.decide(0,30,10,budget),y=b.decide(0,30,10,budget),z=c.decide(0,30,10,budget);
 require(x.qp==y.qp&&x.lambda==y.lambda&&x.prediction.distortion==y.prediction.distortion);
 require(std::abs(z.prediction.distortion-m.predict(1,z.qp,1).distortion)<1e-10);
 require(z.offset<x.offset);require(z.predictedRemainingBits<=budget);
 a.feedback(x.prediction.rate,x.prediction.distortion);b.feedback(y.prediction.rate,y.prediction.distortion);c.feedback(z.prediction.rate,z.prediction.distortion);
 require(a.distortionCorrection()==0&&b.distortionCorrection()==0&&c.distortionCorrection()==0);
 bool bad=false;try{a.begin({1},{1},30,{0});}catch(const std::invalid_argument&){bad=true;}require(bad);
 std::cout<<"SIBRC temporal scoring checks passed\n";
}
