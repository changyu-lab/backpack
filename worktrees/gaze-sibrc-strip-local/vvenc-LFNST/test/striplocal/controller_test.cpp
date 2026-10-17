#include "EncoderLib/Sibrc/Controller.h"
#include "EncoderLib/VtmRcCompat/VisualGaze.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace vvenc;
void check(bool v,const char* s){if(!v)throw std::runtime_error(s);}
template<class F> void rejects(F f){bool yes=false;try{f();}catch(const std::exception&){yes=true;}check(yes,"invalid range accepted");}
int main(){try{
 sibrc::Model m;m.rate={{8,-1,.2,0,0,0}};m.distortion={{0,1,.1,0,0,0}};
 sibrc::Controller a(m),b(m),legacy(m);
 a.begin({1,2,1e12,1e12},{1,1,1,1},30);b.begin({1,2},{1,1},30);legacy.begin({1,2},{1,1},30);
 auto x=a.decide(0,30,100,250,2),y=b.decide(0,30,100,250),z=legacy.decide(0,30,100,250,2);
 check(x.qp==y.qp&&x.lambda==y.lambda&&x.predictedRemainingBits==y.predictedRemainingBits,"next strip influenced current optimization");
 check(y.qp==z.qp&&y.lambda==z.lambda,"default end changed legacy");
 check(x.minimumRemainingBits>0&&x.maximumRemainingBits>=x.minimumRemainingBits,"missing feasible rate interval");
 a.feedback(100,10);b.feedback(100,10);legacy.feedback(100,10);
 double correction=a.rateCorrection();check(correction!=0,"feedback not retained");
 auto n=a.decide(2,30,100,1e9,4);check(n.deltaRate==correction,"strip boundary reset correction");a.feedback(100,10);
 rejects([&]{a.decide(3,30,100,250,3);});rejects([&]{a.decide(3,30,100,250,5);});
 sibrc::Controller low(m),negative(m);low.begin({1,2},{1,1},30);negative.begin({1,2},{1,1},30);
 auto l=low.decide(0,30,100,0,2);check(l.fallback&&l.fallbackReason==3&&l.offset==0,"unreachable budget not recorded");
 auto bad=negative.decide(0,30,100,-1,2);check(bad.fallback&&bad.fallbackReason==2,"negative budget reason missing");
 gaze::StripBudget ledger(2,{1,1,1,1},{1,1});
 check(ledger.target(0,400)==100,"row allocation changed");check(ledger.begin()==0&&ledger.end()==2&&ledger.initial()==200,"row identity missing");
 ledger.feedback(150);check(ledger.left()==50,"real bit debit missing");check(ledger.target(1,250)==50,"row remainder wrong");ledger.feedback(80);check(ledger.left()==-30,"row overspend hidden");
 check(ledger.target(2,170)==85&&ledger.initial()==170&&ledger.begin()==2&&ledger.end()==4,"next row failed to use actual frame remainder");ledger.feedback(20);
 check(ledger.target(3,150)==150,"last CTU remainder wrong");ledger.feedback(150);
 std::cout<<"strip-local contracts passed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
