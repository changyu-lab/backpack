#include "Rc360OracleReplay.h"

#include <cstdlib>
#include <fstream>
#include <sstream>
#include <vector>

void Rc360OracleReplay::init(const Config& cfg)
{
  m_cfg = cfg;
  clear();
}

void Rc360OracleReplay::clear()
{
  m_base.clear();
  m_mapDqp.clear();
}

std::vector<std::string> Rc360OracleReplay::splitCsvLine(const std::string& line)
{
  std::vector<std::string> fields;
  std::string cur;
  bool quoted = false;
  for (size_t i = 0; i < line.size(); i++)
  {
    const char c = line[i];
    if (c == '"')
    {
      if (quoted && i + 1 < line.size() && line[i + 1] == '"')
      {
        cur.push_back('"');
        i++;
      }
      else
      {
        quoted = !quoted;
      }
    }
    else if (c == ',' && !quoted)
    {
      fields.push_back(cur);
      cur.clear();
    }
    else if (c != '\r')
    {
      cur.push_back(c);
    }
  }
  fields.push_back(cur);
  return fields;
}

std::map<std::string, size_t> Rc360OracleReplay::parseHeader(const std::string& line)
{
  std::map<std::string, size_t> header;
  const std::vector<std::string> fields = splitCsvLine(line);
  for (size_t i = 0; i < fields.size(); i++)
  {
    header[fields[i]] = i;
  }
  return header;
}

int Rc360OracleReplay::toInt(const std::vector<std::string>& fields,
                             const std::map<std::string, size_t>& header,
                             const std::string& name,
                             int fallback)
{
  const auto it = header.find(name);
  if (it == header.end() || it->second >= fields.size() || fields[it->second].empty())
  {
    return fallback;
  }
  return std::atoi(fields[it->second].c_str());
}

double Rc360OracleReplay::toDouble(const std::vector<std::string>& fields,
                                   const std::map<std::string, size_t>& header,
                                   const std::string& name,
                                   double fallback)
{
  const auto it = header.find(name);
  if (it == header.end() || it->second >= fields.size() || fields[it->second].empty())
  {
    return fallback;
  }
  return std::atof(fields[it->second].c_str());
}

bool Rc360OracleReplay::loadBaseDump()
{
  m_base.clear();
  if (m_cfg.baseDumpFile.empty())
  {
    return false;
  }

  std::ifstream in(m_cfg.baseDumpFile.c_str());
  if (!in.good())
  {
    return false;
  }

  std::string line;
  if (!std::getline(in, line))
  {
    return false;
  }
  const std::map<std::string, size_t> header = parseHeader(line);

  while (std::getline(in, line))
  {
    if (line.empty())
    {
      continue;
    }
    const std::vector<std::string> fields = splitCsvLine(line);
    BaseEntry entry;
    entry.poc = toInt(fields, header, "poc", -1);
    entry.ctu = toInt(fields, header, "ctu", -1);
    if (entry.poc < 0 || entry.ctu < 0)
    {
      continue;
    }
    entry.baseQpLuma = toInt(fields, header, "baseQpLuma", toInt(fields, header, "QP", 0));
    entry.baseLambda = toDouble(fields, header, "baseLambda", toDouble(fields, header, "lambda", 1.0));
    entry.baseQpChroma = toInt(fields, header, "baseQpChroma", entry.baseQpLuma);
    entry.actualBits = toInt(fields, header, "actualBits", 0);
    entry.localYWsMse = toDouble(fields, header, "localYWsMse", 0.0);
    entry.localYMse = toDouble(fields, header, "localYMse", 0.0);
    entry.frameTargetBits = toInt(fields, header, "frameTargetBits", toInt(fields, header, "picTargetBits", 0));
    entry.frameActualBits = toInt(fields, header, "frameActualBits", 0);
    m_base[{ entry.poc, entry.ctu }] = entry;
  }

  return !m_base.empty();
}

bool Rc360OracleReplay::loadMap()
{
  m_mapDqp.clear();
  if (m_cfg.mapFile.empty())
  {
    return false;
  }

  std::ifstream in(m_cfg.mapFile.c_str());
  if (!in.good())
  {
    return false;
  }

  std::string line;
  if (!std::getline(in, line))
  {
    return false;
  }
  const std::map<std::string, size_t> header = parseHeader(line);

  while (std::getline(in, line))
  {
    if (line.empty())
    {
      continue;
    }
    const std::vector<std::string> fields = splitCsvLine(line);
    const int poc = toInt(fields, header, "poc", -1);
    const int ctu = toInt(fields, header, "ctu", -1);
    const int dqp = toInt(fields, header, "dqp", 0);
    if (poc >= 0 && ctu >= 0 && dqp != 0)
    {
      m_mapDqp[{ poc, ctu }] = dqp;
    }
  }

  return !m_mapDqp.empty();
}

bool Rc360OracleReplay::hasBaseEntry(int poc, int ctu) const
{
  return m_base.find({ poc, ctu }) != m_base.end();
}

const Rc360OracleReplay::BaseEntry* Rc360OracleReplay::getBaseEntry(int poc, int ctu) const
{
  const auto it = m_base.find({ poc, ctu });
  return it == m_base.end() ? nullptr : &it->second;
}

int Rc360OracleReplay::getMapDqp(int poc, int ctu) const
{
  const auto it = m_mapDqp.find({ poc, ctu });
  return it == m_mapDqp.end() ? 0 : it->second;
}

int Rc360OracleReplay::getReplayDqp(int poc, int ctu) const
{
  if (!m_cfg.mapFile.empty())
  {
    return getMapDqp(poc, ctu);
  }
  return (poc == m_cfg.perturbPoc && ctu == m_cfg.perturbCtu) ? m_cfg.perturbDqp : 0;
}
