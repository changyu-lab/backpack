#pragma once
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <map>

// This audit is restricted to single-thread encoder jobs by the runner.
struct TransformAudit {
  struct Row { unsigned long long calls=0, ns=0; };
  std::map<std::array<int,5>,Row> rows;
  static const char* path() { static const char* p=std::getenv("LFNST_TRANSFORM_AUDIT"); return p; }
  ~TransformAudit() {
    if(!path()) return;
    FILE* f=std::fopen(path(),"w"); if(!f) return;
    std::fprintf(f,"qp,w,h,component,kind,calls,ns\n");
    for(const auto& v:rows) std::fprintf(f,"%d,%d,%d,%d,%d,%llu,%llu\n",v.first[0],v.first[1],v.first[2],v.first[3],v.first[4],v.second.calls,v.second.ns);
    std::fclose(f);
  }
};
static TransformAudit& transformAudit() { static TransformAudit a;return a; }
struct TransformAuditScope {
  using Clock=std::chrono::steady_clock;
  TransformAudit::Row* row=nullptr;
  Clock::time_point start;
  TransformAuditScope(int qp,int w,int h,int component,int kind,bool active=true) {
    if(active && TransformAudit::path()) {
      row=&transformAudit().rows[{{qp,w,h,component,kind}}];
      start=Clock::now();
    }
  }
  ~TransformAuditScope() {
    if(row) {
      const auto end=Clock::now();
      row->ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count();
      ++row->calls;
    }
  }
};
