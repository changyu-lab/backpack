#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>

struct StageWrongRow {
  uint64_t eligible=0, reached=0, skips=0, wrong=0, nonzero=0;
};
struct StageWrongAudit {
  std::map<std::array<int,4>, StageWrongRow> rows;
  std::mutex mutex;
  static const char* path() {
    static const char* p = std::getenv("LFNST_STAGE_WRONG_AUDIT");
    return p;
  }
  void record(int qp, int w, int h, bool s1, bool s2, bool s3, int anchorIdx) {
    std::lock_guard<std::mutex> lock(mutex);
    for(int stage=0;stage<=3;++stage) {
      auto& r=rows[{{qp,w,h,stage}}];
      ++r.eligible;
      r.nonzero += anchorIdx>0;
      const bool reached=stage<=1 || (stage==2 ? !s1 : !s1 && !s2);
      const bool skip=stage==0 ? s1||s2||s3 : (stage==1 ? s1 : (stage==2 ? !s1&&s2 : !s1&&!s2&&s3));
      r.reached += reached;
      r.skips += skip;
      r.wrong += skip && anchorIdx>0;
    }
  }
  ~StageWrongAudit() {
    if(!path() || rows.empty()) return;
    FILE* f=std::fopen(path(),"w");
    if(!f) return;
    std::fprintf(f,"actual_qp,w,h,stage,eligible,reached,skip,wrong,anchor_nonzero,wrong_per_skip,wrong_per_eligible\n");
    for(const auto& kv:rows) {
      const auto& k=kv.first;const auto& r=kv.second;
      std::fprintf(f,"%d,%d,%d,%d,%llu,%llu,%llu,%llu,%llu,",k[0],k[1],k[2],k[3],
        (unsigned long long)r.eligible,(unsigned long long)r.reached,(unsigned long long)r.skips,
        (unsigned long long)r.wrong,(unsigned long long)r.nonzero);
      if(r.skips) std::fprintf(f,"%.12g",double(r.wrong)/r.skips);
      std::fprintf(f,",%.12g\n",double(r.wrong)/r.eligible);
    }
    std::fclose(f);
  }
};
static StageWrongAudit& stageWrongAudit() { static StageWrongAudit a;return a; }
