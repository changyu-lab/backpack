import json
from pathlib import Path
import tempfile
import unittest
from batch_strip import sequence_info,prefix_hash
from prepare import sha
from remote_ra import validate_input


class RemoteInput(unittest.TestCase):
    def test_only_matching_source_and_feature_identity_is_accepted(self):
        scratch=Path('build-gaze');scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            p=Path(folder);source=p/'Test_4x2_30fps_8bit_420_erp.yuv'
            source.write_bytes(bytes(12*32))
            info=sequence_info(source,17)
            inputs=p/'inputs';work=inputs/'Test';work.mkdir(parents=True)
            f=work/'features.txt';f.write_text('VGFEATURES 1 4 2 128 10 17\n')
            digest=prefix_hash(source,info['prefix_bytes'])
            meta=dict(geometry=[4,2,128,10,17],mu_m=1,mu_s=1,motion_search=4,
                      output_sha256=sha(f),input_sha256=digest)
            (work/'features.txt.json').write_text(json.dumps(meta))
            (work/'input.json').write_text(json.dumps(dict(source_prefix_sha256=digest)))
            self.assertEqual(validate_input(info,inputs)['source_prefix_sha256'],digest)
            source.write_bytes(bytes([1])+bytes(12*32-1))
            with self.assertRaisesRegex(ValueError,'remote input differs'):validate_input(info,inputs)
            source.write_bytes(bytes(12*32));f.write_text('changed')
            with self.assertRaisesRegex(ValueError,'feature hash mismatch'):validate_input(info,inputs)


if __name__=='__main__':unittest.main()
