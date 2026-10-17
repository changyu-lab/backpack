import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import assess_local as a
class CacheTest(unittest.TestCase):
 def test_changed_job_and_source_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);src=p/'raw';src.write_bytes(b'original');dec=p/'dec';dec.write_bytes(b'decoder')
   (p/'case.vvc').write_bytes(b'stream');(p/'case.yuv').write_bytes(b'rec');(p/'case.run.json').write_text('{}')
   job={'name':'case','frames':1,'target_bps':100,'raw_input':{'coded_prefix_sha256':a.sha(src)}}
   signature={'source_prefix_sha256':a.sha(src),'frames':1,'width':3840,'height':1920,'fps':30,'target_bps':100,'decoder_sha256':a.sha(dec),'trace_sha256':None,'run_record_sha256':a.sha(p/'case.run.json')}
   cached={'evaluation_signature':signature,'reconstruction_sha256':a.sha(p/'case.yuv'),'bitstream_sha256':a.sha(p/'case.vvc'),'decode_matches':True}
   (p/'case.quality.json').write_text(json.dumps(cached))
   with patch.object(a,'DATA',p),patch.object(a,'SOURCES',{'AerialCity':src}),patch.object(a,'DEC',dec):
    self.assertEqual(a.assess(job),cached)
    changed=dict(job,target_bps=200)
    with self.assertRaisesRegex(RuntimeError,'provenance differs'):a.assess(changed)
    (p/'case.quality.json').unlink()
    with self.assertRaisesRegex(RuntimeError,'encoder reconstruction size differs'):a.assess(job)
    (p/'case.quality.json').write_text(json.dumps(cached))
    src.write_bytes(b'mutated')
    with self.assertRaisesRegex(RuntimeError,'source changed'):a.assess(job)
if __name__=='__main__':unittest.main()
