#ifndef ZHAO2022_RC_H
#define ZHAO2022_RC_H
#include <string>
#include <vector>
// Offline features and online two-region allocator. No R-lambda model changes.
class Zhao2022RC
{
public:
  struct Feature { int poc, address, x, y, region, area; double ss, st, sst; };
  void load(const std::string& path, int width, int height, int ctu, int poc, double bits);
  double target(int address, double nativeBitsLeft);
  void update(int address, int actualBits);
  const Feature& feature(int address) const { return m_features.at(address); }
  unsigned fallbackCount() const { return m_fallbacks; }
private:
  std::vector<Feature> m_features;
  double m_budget[2] = {0,0}, m_ss[2] = {0,0}, m_area[2] = {0,0};
  int m_next = 0;
  unsigned m_fallbacks = 0;
};
#endif
