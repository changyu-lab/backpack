from pathlib import Path
import hashlib, json, shutil

ROOT = Path('I:/vvenc-LFNST')
W = Path('C:/Users/hitxi/.codex/worktrees/saldanha2022-lfnst-only/vvenc-LFNST')
BASE = ROOT/'backups/S123AB_rebuild_20261004/src'
STAGE = ROOT/'.tmp/saldanha2022'
hashes = {}
for base in ('source','include'):
    for p in (BASE/base).rglob('*'):
        if not p.is_file(): continue
        rel = p.relative_to(BASE)
        data = p.read_bytes()
        hashes[rel.as_posix()] = hashlib.sha256(data).hexdigest()
        q = W/rel
        if not q.exists() or q.read_bytes() != data:
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(data)
docs = W/'docs/saldanha2022'
(docs/'baseline-source-sha256.json').write_text(json.dumps(hashes,indent=2))
shutil.copyfile(STAGE/'implementation-plan.md',docs/'implementation-plan.md')
for name in ('SaldanhaLfnst.h',):
    shutil.copyfile(STAGE/name,W/'source/Lib/EncoderLib'/name)
tests = W/'tools/saldanha2022'
tests.mkdir(parents=True,exist_ok=True)
shutil.copyfile(STAGE/'test_model.cpp',tests/'test_model.cpp')
p = W/'source/Lib/EncoderLib/IntraSearch.cpp'
s = p.read_text(encoding='utf-8-sig')
s = '#include "SaldanhaLfnst.h"\n' + s
needle = '  const UnitArea& currArea  = partitioner.currArea();'
# Restrict to luma function; another function can contain the same statement.
offset = s.index('void IntraSearch::xIntraCodingLumaQT(')
a,b=s[:offset],s[offset:]
b=b.replace(needle, '''  saldanha::Runtime& saldanhaRun = saldanha::runtime();
  CHECK(saldanhaRun.mode != saldanha::Runtime::OFF &&
        (m_pcEncCfg->m_LardLfnstSkip != 0 || m_pcEncCfg->m_EarlyForceNoNonzeroLfnst),
        "Saldanha requires project LFNST pruning disabled");
  saldanha::Features saldanhaF{};
  bool saldanhaCaptured = false, saldanhaSkip = false;
''' + needle,1)
needle = '''        if (lfnstIdx && modeId)
        {
          continue;
        }'''
assert b.count(needle)==1
b=b.replace(needle,needle,1)
needle = '''        cu.lfnstIdx                          = lfnstIdx;'''
b=b.replace(needle,'''
        if (modeId == 0 && lfnstIdx > 0 && saldanhaSkip && saldanhaRun.mode == saldanha::Runtime::ON)
        {
          saldanhaRun.suppress();
          continue;
        }
''' + needle,1)
needle='''        if( lahtpTraceEnabled )
        {
          const uint32_t nonZero = xLahtpCountNonZeroCoeffs( tu, COMP_Y );'''
assert b.count(needle)==1
insert='''        // VVenC adaptation: completed baseline for this intra candidate.
        // Native TS/MTS ordering and native eligibility remain unchanged.
        if (saldanhaRun.mode != saldanha::Runtime::OFF && modeId == 0 && lfnstIdx == 0
            && endLfnstIdx > 0 && singleCostTmp < MAX_DOUBLE * 0.5 && std::isfinite(singleCostTmp))
        {
          double nz = 0, absSum = 0;
          for (const TransformUnit* st : cs.tus)
          {
            if (!st->blocks[COMP_Y].valid()) continue;
            const auto cb = st->getCoeffs(COMP_Y);
            for (unsigned sy=0; sy<cb.height; ++sy)
              for (unsigned sx=0; sx<cb.width; ++sx)
              {
                const double c = double(cb.at(sx,sy));
                nz += c != 0; absSum += std::abs(c);
              }
          }
          saldanhaF = {{ double(cu.lwidth()), double(cu.lheight()), double(cu.lwidth()*cu.lheight()),
            double(cu.lwidth()) / cu.lheight(), double(cu.mtDepth), double(cu.mipFlag), double(cu.ispMode),
            singleCostTmp, double(singleDistTmpLuma), double(singleTmpFracBits),
            double(cu.intraDir[CH_L]), nz, absSum }};
          saldanhaSkip = saldanhaRun.decide(saldanhaF);
          saldanhaCaptured = true;
        }

'''
# Capture after native zero-CBF/rapidLFNST eligibility updates and best-state saving.
needle='''      }
      if (m_pcEncCfg->m_LFNST && m_pcEncCfg->m_MTS == 2 && modeId && modeId != EndMTS)'''
assert b.count(needle)==1
b=b.replace(needle,insert+needle,1)
needle='''    cu.lfnstIdx = bestLfnstIdx;'''
assert needle in b
b=b.replace(needle,'''    if (saldanhaCaptured)
      saldanhaRun.finish(saldanhaF, saldanhaSkip, bestLfnstIdx > 0 ? 1 : 0,
                         cs.picture->poc, cu.qp, cu.lx(), cu.ly());
''' + needle,1)
p.write_text(a+b,encoding='utf-8')
print('Imported baseline files:',len(hashes),'and installed LFNST-only hook')
