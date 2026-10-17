#include "Zhao2022RC.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <limits>
namespace {
void check(bool bad, const std::string& why) { if (bad) throw std::runtime_error("ZhaoRC: " + why); }
std::string line(std::istream& in) { std::string s; std::getline(in,s); if(!s.empty() && s.back()=='\r') s.pop_back(); return s; }
int integer(const std::string& s) { size_t n=0; int v=std::stoi(s,&n); check(n!=s.size(),"invalid integer"); return v; }
double number(const std::string& s) { size_t n=0; double v=std::stod(s,&n); check(n!=s.size() || !std::isfinite(v) || v<0,"feature must be finite and nonnegative"); return v; }
}
void Zhao2022RC::load(const std::string& path,int width,int height,int ctu,int poc,double bits)
{
  check(width<=0 || height<=0 || ctu<=0,"invalid encoder geometry");
  std::ifstream in(path); check(!in,"cannot open " + path);
  std::ostringstream expected; expected<<"# zhao2022 width="<<width<<" height="<<height<<" ctu="<<ctu<<" poc="<<poc;
  check(line(in)!=expected.str(),"metadata mismatch in " + path);
  check(line(in)!="poc,ctu_addr,x,y,SS,ST,SST,region","CSV schema mismatch in " + path);
  m_features.clear(); m_next=0; m_fallbacks=0;
  for(int r=0;r<2;++r) m_budget[r]=m_ss[r]=m_area[r]=0;
  const int columns=(width+ctu-1)/ctu, rows=(height+ctu-1)/ctu;
  const int count=columns*rows;
  double sst[2]={0,0};
  for(int i=0;i<count;++i) {
    check(!in.good(),"missing CTU row in " + path);
    std::string row=line(in); std::istringstream csv(row); std::vector<std::string> fields; std::string field;
    while(std::getline(csv,field,',')) fields.push_back(field);
    check(fields.size()!=8 || row.empty() || row.back()==',',"expected eight CSV fields in " + path);
    Feature f; f.poc=integer(fields[0]); f.address=integer(fields[1]); f.x=integer(fields[2]); f.y=integer(fields[3]);
    f.ss=number(fields[4]); f.st=number(fields[5]); f.sst=number(fields[6]); f.region=integer(fields[7]);
    check(f.poc!=poc || f.address!=i || f.x!=(i%columns)*ctu || f.y!=(i/columns)*ctu,"POC/raster CTU mismatch in " + path);
    check(f.region<0 || f.region>1,"region must be zero or one");
    f.area=std::min(ctu,width-f.x)*std::min(ctu,height-f.y);
    m_features.push_back(f); sst[f.region]+=f.sst; m_ss[f.region]+=f.ss; m_area[f.region]+=f.area;
    check(!std::isfinite(sst[f.region]) || !std::isfinite(m_ss[f.region]),"feature sum overflow");
  }
  check(in.peek()!=std::char_traits<char>::eof(),"extra CTU rows in " + path);
  const double total=sst[0]+sst[1]; check(!std::isfinite(total),"SST sum overflow");
  for(int r=0;r<2;++r) m_budget[r]=std::max(0.0,bits)*(total>0 ? sst[r]/total : m_area[r]/(m_area[0]+m_area[1]));
  if(total==0) ++m_fallbacks;
}
double Zhao2022RC::target(int address,double nativeBitsLeft)
{
  check(address!=m_next,"CTUs must be coded once in raster order");
  const Feature& f=m_features.at(address);
  // Drop exhausted regions, clamp overspent regions, and reconcile against VTM's
  // actual remaining payload. The native counter itself is never changed here.
  for(int r=0;r<2;++r) m_budget[r]=m_area[r]>0 ? std::max(0.0,m_budget[r]) : 0;
  const double total=m_budget[0]+m_budget[1], available=std::max(0.0,nativeBitsLeft);
  if(total>0) { for(int r=0;r<2;++r) m_budget[r]=available*m_budget[r]/total; }
  else { ++m_fallbacks; for(int r=0;r<2;++r) m_budget[r]=available*m_area[r]/(m_area[0]+m_area[1]); }
  if(m_ss[f.region]>0) return m_budget[f.region]*(f.ss/m_ss[f.region]);
  ++m_fallbacks; return m_budget[f.region]*(f.area/m_area[f.region]);
}
void Zhao2022RC::update(int address,int actualBits)
{
  check(address!=m_next || actualBits<0,"duplicate/out-of-order CTU update or negative actual bits");
  const Feature& f=m_features.at(address);
  m_budget[f.region]-=actualBits;
  m_ss[f.region]=std::max(0.0,m_ss[f.region]-f.ss);
  m_area[f.region]-=f.area; ++m_next;
}
