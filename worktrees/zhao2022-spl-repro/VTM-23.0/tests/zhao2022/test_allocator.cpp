#include "Zhao2022RC.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
static void require(bool v) { if (!v) throw std::runtime_error("assertion failed"); }
static void near(double a,double b) { require(std::abs(a-b)<1e-8); }
int main() {
  const char *path="zhao_test.csv";
  { std::ofstream f(path); f<<"# zhao2022 width=96 height=64 ctu=64 poc=7\npoc,ctu_addr,x,y,SS,ST,SST,region\n7,0,0,0,1,0,1,0\n7,1,64,0,3,0,3,1\n"; }
  Zhao2022RC rc; rc.load(path,96,64,64,7,400);
  near(rc.target(0,400),100); rc.update(0,150); near(rc.target(1,250),250);
  bool failed=false; try { rc.update(0,1); } catch(const std::exception&) {failed=true;} require(failed);
  failed=false; try { rc.load(path,96,64,64,8,400); } catch(const std::exception&) {failed=true;} require(failed);
  { std::ofstream f(path); f<<"# zhao2022 width=96 height=64 ctu=64 poc=7\npoc,ctu_addr,x,y,SS,ST,SST,region\n7,0,0,0,0,0,0,0\n7,1,64,0,0,0,0,0\n"; }
  rc.load(path,96,64,64,7,300); near(rc.target(0,300),200); rc.update(0,290); near(rc.target(1,10),10);
  { std::ofstream f(path); f<<"# zhao2022 width=128 height=64 ctu=64 poc=7\npoc,ctu_addr,x,y,SS,ST,SST,region\n7,0,0,0,1,0,1,0\n7,1,64,0,3,0,1,0\n"; }
  rc.load(path,128,64,64,7,400); near(rc.target(0,400),100); rc.update(0,180); near(rc.target(1,220),220);
  failed=false; try { rc.load(path,96,64,64,7,400); } catch(const std::exception&) {failed=true;} require(failed);
  { std::ofstream f(path); f<<"# zhao2022 width=128 height=64 ctu=64 poc=7\npoc,ctu_addr,x,y,SS,ST,SST,region\n7,0,0,0,1e308,0,1,0\n7,1,64,0,0,0,1,0\n"; }
  rc.load(path,128,64,64,7,400); near(rc.target(0,400),400);
  const char* invalid[] = {
    "7,0,0,0,nan,0,1,0\n7,1,64,0,3,0,1,0\n",
    "7,0,0,0,-1,0,1,0\n7,1,64,0,3,0,1,0\n",
    "7,0,0,0,1,0,1,2\n7,1,64,0,3,0,1,0\n",
    "7,0,0,0,1,0,1,0\n7,0,64,0,3,0,1,0\n",
    "7,0,0,0,1,0,1,0\n",
    "7,0,0,0,1,0,1,0\n7,1,64,0,3,0,1,0\n7,2,128,0,1,0,1,0\n",
    "7,0,1,0,1,0,1,0\n7,1,64,0,3,0,1,0\n"
  };
  for (const auto row : invalid) {
    { std::ofstream f(path); f<<"# zhao2022 width=128 height=64 ctu=64 poc=7\npoc,ctu_addr,x,y,SS,ST,SST,region\n"<<row; }
    failed=false; try { rc.load(path,128,64,64,7,400); } catch(const std::exception&) {failed=true;} require(failed);
  }
  std::remove(path); std::cout<<"Zhao2022 allocator/geometry/POC tests passed\n";
}
