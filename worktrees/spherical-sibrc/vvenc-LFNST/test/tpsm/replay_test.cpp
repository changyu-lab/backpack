#include "VtmRcCompat/Replay.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <cmath>
using namespace vvenc::vtmrc;
void check(bool x,const char* s){if(!x)throw std::runtime_error(s);}
int main(){try{
 const char* p="replay-test.txt";
 {std::ofstream f(p);f<<"VTM_REPLAY_V1 2 2\n0 -1 20 10\n0 0 21 11\n0 1 22 12\n1 -1 23 13\n1 0 24 14\n1 1 25 15\n";}
 Replay a(p,2,2,1,0,-1, -12);check(a.next(0,-1).qp==20,"picture replay");a.next(0,0);a.next(0,1);a.next(1,-1);auto x=a.next(1,0);check(x.qp==23&&std::abs(x.lambda-14*std::exp2(-1./3))<1e-12,"single probe");check(a.next(1,1).qp==25,"other CTU fixed");a.finish();
 bool bad=false;try{a.next(2,-1);}catch(const std::exception&){bad=true;}check(bad,"exhaustion");
 bad=false;try{Replay b(p,3,2,-1,-1,0,-12);}catch(const std::exception&){bad=true;}check(bad,"geometry/frame mismatch");
 bad=false;try{Replay b(p,2,2,-1,-1,0,-12);b.next(0,0);}catch(const std::exception&){bad=true;}check(bad,"call order");
 bad=false;try{Replay b(p,2,2,-1,-1,0,-12);b.finish();}catch(const std::exception&){bad=true;}check(bad,"incomplete replay");
 {std::ofstream f(p);f<<"VTM_REPLAY_V1 1 1\n0 -1 20 10\n0 0 21 -1\n";}
 bad=false;try{Replay b(p,1,1,-1,-1,0,-12);}catch(const std::exception&){bad=true;}check(bad,"nonpositive lambda");
 {std::ofstream f(p);f<<"VTM_REPLAY_V1 1 1\n0 -1 20 10\n0 0 21 1\nEXTRA\n";}
 bad=false;try{Replay b(p,1,1,-1,-1,0,-12);}catch(const std::exception&){bad=true;}check(bad,"trailing data");
 {std::ofstream f(p);f<<"VTM_REPLAY_V1 1 1\n0 -1 20 10\n0 0 63 1\n";}
 bad=false;try{Replay b(p,1,1,0,0,1,-12);}catch(const std::exception&){bad=true;}check(bad,"probe clipping rejected");
 std::remove(p);std::cout<<"replay tests passed\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
