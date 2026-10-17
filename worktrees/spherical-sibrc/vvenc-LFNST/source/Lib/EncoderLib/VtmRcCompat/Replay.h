#pragma once
#include <vector>
#include <string>
#include <fstream>
#include <cmath>
#include <stdexcept>
namespace vvenc { namespace vtmrc {
struct ReplayDecision {int qp; double lambda;};
// Experimental open-loop decision replay. It freezes requested decisions, not coding modes.
class Replay {
 std::vector<ReplayDecision> m_rows;
 std::size_t m_pos=0;
 int m_ctus,m_probePoc,m_probeCtu,m_offset,m_minQp;
public:
 Replay(const std::string& path,int frames,int ctus,int probePoc,int probeCtu,int offset,int minQp)
 :m_ctus(ctus),m_probePoc(probePoc),m_probeCtu(probeCtu),m_offset(offset),m_minQp(minQp){
  std::ifstream f(path);std::string magic;int n=0,k=0;
  if(!(f>>magic>>n>>k)||magic!="VTM_REPLAY_V1"||n!=frames||k!=ctus||n<=0||k<=0)throw std::runtime_error("Invalid VTM replay header");
  for(int p=0;p<n;++p)for(int c=-1;c<k;++c){int rp,rc,q;double l;
   if(!(f>>rp>>rc>>q>>l)||rp!=p||rc!=c||q<minQp||q>63||!std::isfinite(l)||l<=0)throw std::runtime_error("Invalid VTM replay decision/order");
   if(p==probePoc&&c==probeCtu&&(q+offset<minQp||q+offset>63))throw std::runtime_error("Probe exceeds legal QP");
   m_rows.push_back({q,l});
  }
  std::string extra;if(f>>extra)throw std::runtime_error("Trailing VTM replay data");
 }
 ReplayDecision next(int poc,int ctu){
  if(m_pos>=m_rows.size()||poc!=int(m_pos/(m_ctus+1))||ctu!=int(m_pos%(m_ctus+1))-1)throw std::logic_error("VTM replay out of order/exhausted");
  auto d=m_rows[m_pos++];if(poc==m_probePoc&&ctu==m_probeCtu){d.qp+=m_offset;d.lambda*=std::exp2(double(m_offset)/3.);}
  if(d.qp<m_minQp||!std::isfinite(d.lambda)||d.lambda<=0)throw std::runtime_error("Invalid perturbed VTM replay decision");
  return d;
 }
 void finish()const{if(m_pos!=m_rows.size())throw std::logic_error("Incomplete VTM replay");}
};
}}
