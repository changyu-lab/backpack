import hashlib, tempfile, unittest
from pathlib import Path
import numpy as np
import evaluate
class QualityHashTests(unittest.TestCase):
 def test_stream_hash_complete_frames_and_quality_unchanged(self):
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'src'; recon=Path(d)/'rec'; src=b''; rec=b''; expected_ps=[]; expected_ws=[]
   for n in range(3):
    y=np.arange(16,dtype=np.uint8).reshape(4,4)+n
    ry=y.astype(np.uint16)*4+np.arange(16,dtype=np.uint16).reshape(4,4)%3
    src+=y.tobytes()+bytes(range(n,n+8)); rec+=ry.astype('<u2').tobytes()+np.arange(n,n+8,dtype='<u2').tobytes()
    mse,wmse=evaluate.picture_mse(y,ry/4.)
    expected_ps.append(10*np.log10(255**2/mse)); expected_ws.append(10*np.log10(255**2/wmse))
   source.write_bytes(src); recon.write_bytes(rec)
   result=evaluate.quality(source,recon,4,4,2)
   self.assertEqual(result['source_prefix_sha256'],hashlib.sha256(src[:48]).hexdigest())
   self.assertEqual(result['reconstruction_prefix_sha256'],hashlib.sha256(rec[:96]).hexdigest())
   self.assertEqual(result['picture_y_psnr'],expected_ps[:2]); self.assertEqual(result['picture_y_wspsnr'],expected_ws[:2])
   self.assertEqual(result['mean_y_psnr'],float(np.mean(expected_ps[:2]))); self.assertEqual(result['mean_y_wspsnr'],float(np.mean(expected_ws[:2])))
   full=evaluate.quality(source,recon,4,4,3)
   self.assertEqual(full['source_prefix_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
   self.assertEqual(full['reconstruction_prefix_sha256'],hashlib.sha256(recon.read_bytes()).hexdigest())
if __name__=='__main__': unittest.main()
