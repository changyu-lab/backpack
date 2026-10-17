#include "Sibrc/Controller.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <set>
#include <map>
#include <sstream>
#include <stdexcept>
#include <vector>
using namespace vvenc::sibrc;
std::vector<std::string> csv(const std::string& line){std::vector<std::string> fields;std::string field;bool quote=false;for(std::size_t i=0;i<line.size();++i){char c=line[i];if(c=='"'){if(quote&&i+1<line.size()&&line[i+1]=='"'){field+=c;++i;}else quote=!quote;}else if(c==','&&!quote){fields.push_back(field);field.clear();}else if(c!='\r')field+=c;}if(quote)throw std::runtime_error("CSV quote");fields.push_back(field);return fields;}
struct Row {int ctu,qp;double a,b,area,bits,mse;};
bool close(double a,double b){return std::isfinite(a)&&std::isfinite(b)&&std::abs(a-b)<=1e-8*(1+std::max(std::abs(a),std::abs(b)));}
int main(int argc,char**argv){try{
 if(argc!=6&&!(argc==7&&std::string(argv[6])=="--all-groups"))throw std::runtime_error("usage: m4_replay C2/model.I C2/model.P C3/model.I C3/model.P merged.csv");
 Model a[2]={Model::load(argv[1]),Model::load(argv[2])},b[2]={Model::load(argv[3]),Model::load(argv[4])};
 for(int k=0;k<2;++k)if(a[k].schemaVersion!=2||b[k].schemaVersion!=2||a[k].featureSelector!=2||b[k].featureSelector!=3||a[k].pictureType!=(k?"P":"I")||b[k].pictureType!=a[k].pictureType)throw std::runtime_error("incompatible model schemas");
 std::ifstream input(argv[5]);std::string line;if(!std::getline(input,line))throw std::runtime_error("missing CSV");auto head=csv(line);std::map<std::string,int> columns;for(int i=0;i<int(head.size());++i)columns[head[i]]=i;
 std::map<std::string,std::vector<Row>> groups;std::map<std::string,int> kinds; std::map<std::string,std::vector<std::string>> metadata;
 while(std::getline(input,line)){if(line.empty())continue;auto f=csv(line);auto get=[&](const std::string& key)->std::string{auto it=columns.find(key);if(it==columns.end()||it->second>=int(f.size()))throw std::runtime_error("missing CSV column "+key);return f[it->second];};
  if(get("kind")!="I"&&get("kind")!="P")throw std::runtime_error("invalid picture kind"); int kind=get("kind")=="I"?0:1;std::string requested=columns.count("requested_qp")?get("requested_qp"):get("actual_qp");std::string key=get("source_sequence")+"/"+get("window_start")+"/"+get("poc")+"/"+get("kind")+"/"+requested;
  Row r;r.ctu=std::stoi(get("ctu"));r.qp=std::stoi(get("actual_qp"));r.a=std::stod(get("feature_C2"));r.b=std::stod(get("feature_C3"));r.area=std::stod(get(columns.count("sphere_area")?"sphere_area":"area"));r.bits=std::stod(get("bits"));r.mse=std::stod(get("weighted_mse"));
  bool valid=std::isfinite(r.bits)&&r.bits>0&&std::isfinite(r.mse)&&r.mse>0&&std::isfinite(r.area)&&r.area>0;
  for(const auto& feature:{"C0","C1","C2","C3","C4","plane","geo","satd"}){double v=std::stod(get(std::string("feature_")+feature));valid=valid&&std::isfinite(v)&&v>=0;}
  if(!valid)continue;groups[key].push_back(r);kinds[key]=kind;metadata[key]={get("source_sequence"),get("window_start"),get("poc"),get("kind"),requested};
 }
 std::set<std::string> selected;
 if(argc==7){for(const auto&g:groups)selected.insert(g.first);}else{
  std::set<std::string> sources;for(const auto&g:metadata)sources.insert(g.second[0]);
  for(const auto&source:sources){std::set<int> windows;for(const auto&g:metadata)if(g.second[0]==source)windows.insert(std::stoi(g.second[1]));for(int window:{*windows.begin(),*windows.rbegin()})for(const auto&kind:{"I","P"}){
   std::set<int> pocs;for(const auto&g:metadata)if(g.second[0]==source&&std::stoi(g.second[1])==window&&g.second[3]==kind)pocs.insert(std::stoi(g.second[2]));if(pocs.empty())continue;int poc=*pocs.begin();std::map<double,std::string> qps;
   for(const auto&g:metadata)if(g.second[0]==source&&std::stoi(g.second[1])==window&&g.second[3]==kind&&std::stoi(g.second[2])==poc)qps[std::stod(g.second[4])]=g.first;std::vector<std::string> qs;for(const auto&q:qps)qs.push_back(q.second);if(!qs.empty()){selected.insert(qs.front());selected.insert(qs[qs.size()/2]);selected.insert(qs.back());}
  }}
 }
 std::size_t samples=0,decisions=0,failures=0;double maxLog=0,maxFeature=0;
 for(auto& group:groups){if(!selected.count(group.first))continue;auto&rows=group.second;std::sort(rows.begin(),rows.end(),[](const Row&x,const Row&y){return x.ctu<y.ctu;});int kind=kinds[group.first];std::vector<double> x,y,area;double total=0;for(const auto&r:rows){x.push_back(r.a);y.push_back(r.b);area.push_back(r.area);total+=r.bits;++samples;
  double za=std::log(std::max(r.a/a[kind].informationScale,a[kind].informationFloor)),zb=std::log(std::max(r.b/b[kind].informationScale,b[kind].informationFloor));maxFeature=std::max(maxFeature,std::abs(za-zb));
  for(int qp=-12;qp<=63;++qp){auto pa=a[kind].predict(r.a,qp,r.area),pb=b[kind].predict(r.b,qp,r.area);double e=std::max(std::abs(std::log(pa.rate)-std::log(pb.rate)),std::abs(std::log(pa.distortion)-std::log(pb.distortion)));maxLog=std::max(maxLog,e);if(!std::isfinite(e)||e>1e-8)++failures;}}
  for(double factor:{.5,1.,2.,10.}){Controller ca(a[kind]),cb(b[kind]);int picture=rows.front().qp;ca.begin(x,area,picture);cb.begin(y,area,picture);double remaining=total*factor;
   for(std::size_t i=0;i<rows.size();++i){int qp=rows[i].qp;if(kind==0)qp=std::max(picture-2,std::min(picture+2,qp));double lambda=std::exp2((qp-12.)/3.);auto da=ca.decide(i,qp,lambda,std::max(0.,remaining)),db=cb.decide(i,qp,lambda,std::max(0.,remaining));++decisions;
    if(da.qp!=db.qp||da.offset!=db.offset||da.fallback!=db.fallback||!close(da.lambda,db.lambda)||!close(da.prediction.rate,db.prediction.rate)||!close(da.prediction.distortion,db.prediction.distortion)||!close(da.deltaRate,db.deltaRate)||!close(da.deltaDistortion,db.deltaDistortion)||!close(da.predictedRemainingBits,db.predictedRemainingBits))++failures;
    ca.feedback(rows[i].bits,rows[i].mse);cb.feedback(rows[i].bits,rows[i].mse);remaining-=rows[i].bits;
   }
  }
 }
 bool pass=samples&&failures==0&&maxFeature<=1e-10;std::cout<<std::setprecision(17)<<"{\"available_groups\":"<<groups.size()<<",\"replay_groups\":"<<selected.size()<<",\"scope\":\""<<(argc==7?"all_groups":"per_source_first_last_window_first_poc_each_kind_low_middle_high_requested_qp")<<"\",\"controller_replay_pass\":"<<(pass?"true":"false")<<",\"samples\":"<<samples<<",\"decisions\":"<<decisions<<",\"failures\":"<<failures<<",\"max_log_prediction_difference\":"<<maxLog<<",\"max_standardized_log_difference\":"<<maxFeature<<",\"selected_group_keys\":[";bool first=true;for(const auto&key:selected){if(!first)std::cout<<",";first=false;std::cout<<"\""<<key<<"\"";}std::cout<<"]}\n";return pass?0:1;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 2;}}


