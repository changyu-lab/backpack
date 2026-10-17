#pragma once

#include <map>
#include <string>
#include <tuple>
#include <vector>

class Rc360OracleReplay
{
public:
  struct Config
  {
    bool enabled = false;
    bool dumpEnabled = false;
    std::string dumpFile;
    std::string baseDumpFile;
    std::string mapFile;
    int perturbPoc = -1;
    int perturbCtu = -1;
    int perturbDqp = 0;
  };

  struct BaseEntry
  {
    int poc = -1;
    int ctu = -1;
    int baseQpLuma = 0;
    double baseLambda = 1.0;
    int baseQpChroma = 0;
    int actualBits = 0;
    double localYWsMse = 0.0;
    double localYMse = 0.0;
    int frameTargetBits = 0;
    int frameActualBits = 0;
  };

  void init(const Config& cfg);
  void clear();

  bool isEnabled() const { return m_cfg.enabled; }
  bool dumpEnabled() const { return m_cfg.dumpEnabled && !m_cfg.dumpFile.empty(); }
  const Config& config() const { return m_cfg; }

  bool loadBaseDump();
  bool loadMap();

  bool hasBaseEntry(int poc, int ctu) const;
  const BaseEntry* getBaseEntry(int poc, int ctu) const;
  int getMapDqp(int poc, int ctu) const;
  int getReplayDqp(int poc, int ctu) const;

private:
  using Key = std::pair<int, int>;

  static std::map<std::string, size_t> parseHeader(const std::string& line);
  static std::vector<std::string> splitCsvLine(const std::string& line);
  static int toInt(const std::vector<std::string>& fields,
                   const std::map<std::string, size_t>& header,
                   const std::string& name,
                   int fallback);
  static double toDouble(const std::vector<std::string>& fields,
                         const std::map<std::string, size_t>& header,
                         const std::string& name,
                         double fallback);

  Config m_cfg;
  std::map<Key, BaseEntry> m_base;
  std::map<Key, int> m_mapDqp;
};
