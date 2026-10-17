#include "source/Lib/EncoderLib/Rc360OracleReplay.h"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

namespace
{
void require(bool condition, const char* message)
{
  if (!condition)
  {
    std::cerr << message << "\n";
    std::exit(1);
  }
}

std::string tmpPath(const char* name)
{
  return std::string(name);
}
}

int main()
{
  const std::string baseFile = tmpPath("rc360_oracle_base_test.csv");
  const std::string mapFile = tmpPath("rc360_oracle_map_test.csv");

  {
    std::ofstream out(baseFile.c_str());
    out << "poc,ctu,baseQpLuma,baseLambda,baseQpChroma,actualBits,localYWsMse,localYMse,frameTargetBits,frameActualBits\n";
    out << "2,10,34,512.5,33,1200,0.25,0.50,10000,9800\n";
    out << "2,11,35,768.0,34,900,0.30,0.60,10000,9800\n";
  }
  {
    std::ofstream out(mapFile.c_str());
    out << "poc,ctu,dqp\n";
    out << "2,10,-1\n";
    out << "2,11,+1\n";
  }

  Rc360OracleReplay replay;
  Rc360OracleReplay::Config cfg;
  cfg.enabled = true;
  cfg.baseDumpFile = baseFile;
  cfg.mapFile = mapFile;
  replay.init(cfg);

  require(replay.loadBaseDump(), "base dump load");
  require(replay.loadMap(), "map load");
  require(replay.hasBaseEntry(2, 10), "has base entry");
  require(!replay.hasBaseEntry(3, 10), "missing base entry");

  const Rc360OracleReplay::BaseEntry* entry = replay.getBaseEntry(2, 10);
  require(entry != nullptr, "get base entry");
  require(entry->baseQpLuma == 34, "base qp");
  require(std::fabs(entry->baseLambda - 512.5) < 1e-12, "base lambda");
  require(entry->baseQpChroma == 33, "base chroma qp");

  require(replay.getMapDqp(2, 10) == -1, "map dqp minus");
  require(replay.getMapDqp(2, 11) == 1, "map dqp plus");
  require(replay.getMapDqp(2, 12) == 0, "map dqp default");

  cfg.mapFile.clear();
  cfg.perturbPoc = 2;
  cfg.perturbCtu = 11;
  cfg.perturbDqp = -1;
  replay.init(cfg);
  require(replay.loadBaseDump(), "base reload");
  require(replay.getReplayDqp(2, 10) == 0, "perturb non target");
  require(replay.getReplayDqp(2, 11) == -1, "perturb target");
  require(replay.getReplayDqp(3, 11) == 0, "perturb wrong poc");

  std::remove(baseFile.c_str());
  std::remove(mapFile.c_str());
  return 0;
}
