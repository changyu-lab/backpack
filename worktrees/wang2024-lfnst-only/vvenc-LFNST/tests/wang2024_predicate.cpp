#include "WangLfnst.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
using namespace vvenc::wang2024;
int main() {
 int32_t z[64]={};
 auto g=gradient(z,8,8,8);
 assert(g.grad1==0 && g.grad2==0);
 assert(!skip(g,1,22) && skip(g,2,22));
 int32_t r[12]={0,0,10,999, 0,0,30,999, 0,10,60,999};
 g=gradient(r,3,3,4); // last row 0,10,60; last column 10,30,60
 assert(g.grad2==50 && g.grad1==110);
 assert(!skip({100,0},1,22) && skip({100,0},2,22));
 assert(!skip({101,0},2,22));
 assert(!skip({150,150},1,27) && skip({150,150},2,27));
 const double step=qpStep(22);
 assert(std::abs(step-8.0)<1e-12);
 assert(std::abs(threshold(1,22)-85.265)<1e-9);
 assert(std::abs(threshold(2,22)-45.265)<1e-9);
 assert(skip({0,0},1,-20)); // clipped threshold zero, inclusive >=
 assert(!skip({100000,100000},0,22));
 int32_t wide[4]={0,std::numeric_limits<int32_t>::min(),0,std::numeric_limits<int32_t>::max()};
 g=gradient(wide,2,2,2);
 assert(g.grad2==4294967295ULL && g.grad1==6442450942ULL);
 int32_t roi[64]={};roi[1]=123456; // interior must not contaminate full borders
 g=gradient(roi,8,8,8);assert(g.grad1==0 && g.grad2==0);
 assert(std::abs(qpStep(17)-4.489848193)<1e-8);
 assert(std::abs(qpStep(47)-143.6751422)<1e-6);
 std::cout << "PASS Wang2024 predicate\n";
}
