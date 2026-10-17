import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).parent

def rows():
    result=[]
    for poc in range(32):
        for ctu in range(6):
            begin=ctu//3*3;before=300-(ctu-begin)*10
            result.append(dict(poc=poc,ctu=ctu,strip_begin=begin,strip_end=begin+3,strip_target=300,strip_before=before,strip_after=before-10,frame_before=10000-ctu*10,frame_after=9990-ctu*10,bits=10,minimum_bits=20,maximum_bits=400,predicted_remaining=100,fallback_reason=0,base_qp=30,qp=31,base_lambda=10,offset=1,fallback=0,**{'lambda':10*2**(1/3)}))
    return result

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert (HERE/'strip_local_trial.py').exists(),'strip-local runner is missing'
        spec=importlib.util.spec_from_file_location('strip_local_trial',HERE/'strip_local_trial.py')
        cls.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.mod)
    def check(self,data):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'trace.csv'
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=data[0]);w.writeheader();w.writerows(data)
            return self.mod.check_strip_trace(p,384,256)
    def test_valid(self):
        r=self.check(rows());self.assertEqual(r['ctus'],192);self.assertEqual(r['strips'],64);self.assertTrue(r['eligible']);self.assertEqual(r['strip_target_actual_deviation_bits']['mean'],-270)
    def test_corrupt(self):
        for col,val in [('ctu',.5),('strip_end',4),('strip_after',1),('strip_before',310),('strip_target',310),('frame_before',9999),('lambda',99),('qp',32),('minimum_bits','nan')]:
            data=rows();data[1][col]=val
            with self.subTest(col=col),self.assertRaises(ValueError):self.check(data)
        for data in (rows()[:-1],rows()+[rows()[0]]):
            with self.assertRaises(ValueError):self.check(data)
    def test_fallback_retained(self):
        data=rows()
        for i in range(3):data[i].update(strip_target=-1,strip_before=-1-i*10,strip_after=-11-i*10,fallback_reason=2,fallback=1)
        data[2].update(fallback_reason=1,minimum_bits='nan',maximum_bits='nan',predicted_remaining='nan')
        r=self.check(data);self.assertTrue(r['eligible']);self.assertEqual(r['fallback_reason_counts']['2'],2);self.assertEqual(r['fallback_reason_counts']['1'],1)
    def test_clone(self):
        old=['old','-i','frozen.yuv','-b','old.vvc','-o','oldrec','--SIBRCMode=3','--VisualGazeMode=0','--GazeSibrcAlpha=.1','--GazeSibrcTrace=frozen.csv','--GazeSibrcStripTrace=frozen-strip.csv','--VTMRCTrace=frozen-vtm.csv','--SIBRCResidual=frozen-residual.bin','--SummaryOutFilename=frozen-summary.txt']
        cmd=self.mod.method_command(old,'new',Path('owned/R1'),Path('scratch/rec'),Path('features'))
        self.assertEqual(cmd[cmd.index('-o')+1],str(Path('scratch/rec')));self.assertIn('--GazeSibrcStripLocal=1',cmd);self.assertIn('--GazeSibrcAlpha=1',cmd);self.assertIn('--GazeSibrcStripTrace='+str(Path('owned/R1'))+'.strip.csv',cmd);self.assertEqual(len([v for v in cmd if v.startswith('--GazeSibrcAlpha=')]),1);self.assertNotIn('--VisualGazeMode=0',cmd);self.assertFalse(any('frozen' in v for v in cmd if 'Trace=' in v));self.assertEqual(old[0],'old');self.assertFalse(any('frozen' in v for v in cmd if 'Residual=' in v or 'Filename=' in v))
    def test_output_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';out.mkdir();(out/'manifest.json').write_text('{}')
            with self.assertRaises(ValueError):self.mod.prepare_output(out,root/'scratch',[root/'frozen'])
            with self.assertRaises(ValueError):self.mod.prepare_output(root/'frozen'/'child',root/'scratch',[root/'frozen'])
    def test_partial_summary(self):
        r=self.mod.summarize({'groups':{}},[],{'R1':'failed'});self.assertIsNone(r['comparisons']);self.assertIsNone(r['seconds_sum']);self.assertFalse(r['timing_comparable']);self.assertEqual(r['expected_points'],4)

class FormulaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('strip_local_trial',HERE/'strip_local_trial.py');cls.mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.mod)
    def test_row_formula_and_ctu_initial_target(self):
        data=rows();features={(p,c):1 for p in range(32) for c in range(6)}
        for r in data:
            r['strip_target']=5000 if r['ctu']<3 else 9970
            r['strip_before']=r['strip_target']-(r['ctu']%3)*10
        self.mod.verify_row_formula(data,features,384,256)
        data[0]['strip_target']+=1
        with self.assertRaises(ValueError):self.mod.verify_row_formula(data,features,384,256)
    def test_correction_survives_every_ctu_and_row_boundary(self):
        data=rows();sib={}
        for r in data:
            r.update(rate_correction_before=0 if r['ctu']==0 else 1,dist_correction_before=0 if r['ctu']==0 else 2)
            sib[(r['poc'],r['ctu'])]=dict(rate_bias=1,dist_bias=2)
        self.mod.verify_corrections(data,sib)
        data[3]['rate_correction_before']=0
        with self.assertRaises(ValueError):self.mod.verify_corrections(data,sib)
    def test_complete_companion_feedback_join(self):
        data=rows();companions={key:[] for key in ('collab','gaze','sibrc','vtm')}
        for r in data:
            r['strip_target']=5000 if r['ctu']<3 else 9970;r['strip_before']=r['strip_target']-r['ctu']%3*10;r['strip_after']=r['strip_before']-10
            r.update(rate_correction_before=0 if r['ctu']==0 else 1,dist_correction_before=0 if r['ctu']==0 else 2)
            target=max(1,int(r['strip_before']/(3-r['ctu']%3)+.5));common=dict(poc=r['poc'],ctu=r['ctu'],bits=10)
            companions['collab'].append(dict(common,alpha=1,original_target=100,strip_target=target,mixed_target=target,base_qp=30,qp=31,base_lambda=10,**{'lambda':r['lambda']},sibrc_offset=1,sibrc_fallback=0,frame_before=r['frame_before'],frame_after=r['frame_after']))
            companions['gaze'].append(dict(common,target=target,feature=1,base_qp=30,qp=30,base_lambda=10,**{'lambda':10},strip_before=r['strip_before'],strip_after=r['strip_after'],zero_feature_fallback=0))
            companions['sibrc'].append(dict(common,kind='I' if r['poc']==0 else 'P',qp=31,base_qp=30,offset=1,base_lambda=10,**{'lambda':r['lambda']},actual_qp=31,fallback=0,pic_left=r['frame_after'],rate_bias=1,dist_bias=2))
            companions['vtm'].extend([dict(common,event='decision',bits=target,qp=30,**{'lambda':10},pic_left=r['frame_before']),dict(common,event='feedback',qp=31,**{'lambda':r['lambda']},pic_left=r['frame_after'])])
        for poc in range(32):
            for event in ('begin','picture'):companions['vtm'].append(dict(poc=poc,ctu=-1,event=event,bits=0,qp=30,**{'lambda':10},pic_left=0))
        with tempfile.TemporaryDirectory() as temp:
            paths={}
            for key,records in dict(companions,strip=data).items():
                path=Path(temp)/(key+'.csv');paths[key]=path
                with path.open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=records[0]);writer.writeheader();writer.writerows(records)
            result=self.mod.check_strip_trace(paths['strip'],384,256,paths)
            self.assertTrue(result['feedback_join_verified']);self.assertTrue(result['row_formula_verified']);self.assertTrue(result['correction_continuity_verified'])
    def test_historical_native_schema_supported(self):
        mq=dict(quality_mean_db=dict(psnr=30,ws_psnr=30,s_psnr_nn=30),frames=[dict(psnr=30,ws_psnr=30,s_psnr_nn=30) for _ in range(32)])
        nq={'picture_y_spsnr':[30]*32,'picture_y_cpppsnr':[30]*32}
        self.assertEqual(self.mod.quality_crosscheck(mq,nq)['cpp_psnr'],30)
    def test_native_per_frame_mismatch_rejected(self):
        mq=dict(quality_mean_db=dict(psnr=30,ws_psnr=30,s_psnr_nn=30),frames=[dict(psnr=30,ws_psnr=30,s_psnr_nn=30) for _ in range(32)])
        nq={'picture_y_'+m:[30]*32 for m in ('psnr','wspsnr','spsnr','cpppsnr')}
        self.assertEqual(self.mod.quality_crosscheck(mq,nq)['cpp_psnr'],30)
        nq['picture_y_wspsnr'][31]=31
        with self.assertRaises(ValueError):self.mod.quality_crosscheck(mq,nq)

if __name__=='__main__':unittest.main()
