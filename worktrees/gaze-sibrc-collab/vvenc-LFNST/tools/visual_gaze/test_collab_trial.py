import csv
import gzip
import json
import math
import tempfile
import unittest
from pathlib import Path
import collab_trial as trial


class CollaborationTrial(unittest.TestCase):
    def test_clone_preserves_frozen_controller_and_inputs(self):
        old = ['old', '-c', 'frozen.cfg', '-i', 'source.yuv', '-f', '32',
               '-b', 'old.vvc', '-o', 'old.yuv', '--VTMRCTrace=old.csv',
               '--SIBRCModel=model.json', '--SIBRCStats=stats.json', '--SIBRCMode=4']
        cmd = trial.clone_command(old, 'new', 'out/R1', 'rec.yuv', 'features.txt', .25)
        self.assertEqual(old[0], 'old')
        for flag in ('--SIBRCModel=model.json', '--SIBRCStats=stats.json', '--SIBRCMode=4'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd.count('-o'), 1)
        self.assertEqual(cmd[cmd.index('-o')+1], 'rec.yuv')
        self.assertIn('--GazeSibrcAlpha=0.25', cmd)
        self.assertIn('--GazeSibrcTrace=out/R1.collab.csv', cmd)
        self.assertNotIn('old.yuv', cmd)

    def rows(self, alpha=.25):
        return [dict(poc=poc, ctu=ctu, alpha=alpha, original_target=100,
                     strip_target=140 if alpha else -1, mixed_target=110 if alpha else 100,
                     base_qp=30, qp=29, base_lambda=10, **{'lambda': 10*2**(-1/3)},
                     sibrc_offset=-1, sibrc_fallback=0, frame_before=200-20*ctu,
                     frame_after=180-20*ctu, bits=20) for poc in range(32) for ctu in range(2)]

    def trace(self, rows):
        path=Path(self.temp.name)/'trace.csv'
        with path.open('w', newline='') as f:
            writer=csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader(); writer.writerows(rows)
        return path

    def setUp(self): self.temp=tempfile.TemporaryDirectory()
    def tearDown(self): self.temp.cleanup()

    def test_trace_requires_both_controller_activity_and_complete_geometry(self):
        rows=self.rows()
        result=trial.check_trace(self.trace(rows), 256, 128, .25)
        self.assertEqual(result['mixed_active_ctus'], 64)
        self.assertEqual(result['sibrc_active_ctus'], 64)
        for mutate in ('debit', 'duplicate', 'blend', 'qp', 'lambda', 'positive', 'continuity'):
            bad=self.rows()
            if mutate=='debit':bad[0]['bits']=19
            elif mutate=='duplicate':bad[-1]=bad[0]
            elif mutate=='blend':bad[0]['mixed_target']=111
            elif mutate=='qp':bad[0]['qp']=28
            elif mutate=='lambda':bad[0]['lambda']=9
            elif mutate=='positive':bad[0]['base_lambda']=0
            else:bad[1]['frame_before']+=1;bad[1]['frame_after']+=1
            with self.assertRaises(ValueError, msg=mutate):
                trial.check_trace(self.trace(bad),256,128,.25)

    def test_inactivity_and_fallback_preserve_quality_eligibility_evidence(self):
        rows=self.rows()
        for row in rows:
            row.update(qp=30,sibrc_offset=0,sibrc_fallback=1,**{'lambda':10})
        result=trial.check_trace(self.trace(rows),256,128,.25)
        self.assertFalse(result['eligible'])
        self.assertIn('sibrc_inactive',result['ineligible_reasons'])
        self.assertEqual(result['sibrc_fallback_ctus'],64)

    def bundle(self, rows):
        root=Path(self.temp.name);paths={}
        allrows={'vtm':[],'sibrc':[],'gaze':[]}
        for row in rows:
            p,c=row['poc'],row['ctu']
            if c==0:allrows['vtm'].append(dict(event='begin',poc=p,ctu=-1,bits=200,qp=30,**{'lambda':10},pic_left=200))
            allrows['vtm'] += [dict(event='decision',poc=p,ctu=c,bits=row['mixed_target'],qp=row['base_qp'],
                                   **{'lambda':row['base_lambda']},pic_left=row['frame_before']),
                               dict(event='feedback',poc=p,ctu=c,bits=row['bits'],qp=row['qp'],
                                    **{'lambda':row['lambda']},pic_left=row['frame_after'])]
            if c==1:allrows['vtm'].append(dict(event='picture',poc=p,ctu=-1,bits=40,qp=30,**{'lambda':10},pic_left=160))
            allrows['sibrc'].append(dict(poc=p,ctu=c,qp=row['qp'],bits=row['bits'],base_qp=row['base_qp'],
                                         offset=row['sibrc_offset'],base_lambda=row['base_lambda'],
                                         **{'lambda':row['lambda']},actual_qp=row['qp'],fallback=row['sibrc_fallback'],pic_left=row['frame_after']))
            allrows['gaze'].append(dict(poc=p,ctu=c,target=row['strip_target'],bits=row['bits'],
                                        base_qp=row['base_qp'],qp=row['base_qp'],base_lambda=row['base_lambda'],
                                        **{'lambda':row['base_lambda']},strip_before=150-20*c,strip_after=130-20*c,
                                        zero_feature_fallback=0))
        for name,values in allrows.items():
            paths[name]=root/(name+'.csv')
            self.write_csv(paths[name],values)
        return paths,allrows

    def write_csv(self,path,rows):
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)

    def test_real_controller_traces_are_joined_and_corruption_fails(self):
        rows=self.rows();path=self.trace(rows);paths,values=self.bundle(rows)
        self.assertTrue(trial.check_trace(path,256,128,.25,paths)['feedback_join_verified'])
        for name,field in [('vtm','bits'),('sibrc','actual_qp'),('gaze','strip_after')]:
            paths,values=self.bundle(rows)
            index=2 if name=='vtm' else 0
            values[name][index][field]+=1
            self.write_csv(paths[name],values[name])
            with self.assertRaises(ValueError,msg=name):trial.check_trace(path,256,128,.25,paths)
        paths,values=self.bundle(rows);values['gaze'].append(values['gaze'][0]);self.write_csv(paths['gaze'],values['gaze'])
        with self.assertRaises(ValueError):trial.check_trace(path,256,128,.25,paths)

    def test_alpha_zero_requires_exact_bypass(self):
        rows=self.rows(0)
        self.assertEqual(trial.check_trace(self.trace(rows),256,128,0)['mixed_active_ctus'],0)
        rows[0]['mixed_target']=101
        with self.assertRaises(ValueError):trial.check_trace(self.trace(rows),256,128,0)

    def test_manifest_refuses_any_identity_change(self):
        path=Path(self.temp.name)/'manifest.json'
        original={'encoder':'abc','source':'def'}
        first=trial.immutable_manifest(path,original)
        self.assertEqual(first,trial.immutable_manifest(path,original))
        with self.assertRaises(ValueError):trial.immutable_manifest(path,dict(original,encoder='changed'))
        self.assertEqual(json.loads(path.read_text()),original)

    def test_gzip_checks_raw_digest_as_well_as_compressed_digest(self):
        path=Path(self.temp.name)/'trace.csv.gz'
        with gzip.open(path,'wb') as dest:dest.write(b'frozen trace')
        trace=dict(path=str(path),gzip_sha256=trial.sha(path),uncompressed_sha256='bad')
        with self.assertRaisesRegex(ValueError,'raw trace'):trial.verify_trace_artifact(trace)

    def test_trace_rejects_fractional_ctu_identity(self):
        rows=self.rows();rows[0]['ctu']=.5
        with self.assertRaises(ValueError):trial.check_trace(self.trace(rows),256,128,.25)

    def test_resume_checks_artifacts_and_identity(self):
        folder=Path(self.temp.name)/'DrivingInCity'/'alpha0.1';folder.mkdir(parents=True)
        prefix=folder/'R1';stream=prefix.with_suffix('.vvc');stream.write_bytes(b'stream')
        log=prefix.with_suffix('.log');log.write_text('frozen')
        row=dict(identity='id',stream_sha256=trial.sha(stream),artifacts={str(log):trial.sha(log)},traces=[])
        trial.save(prefix.with_suffix('.result.json'),row)
        from types import SimpleNamespace
        args=SimpleNamespace(output=Path(self.temp.name))
        case=dict(spec={},groups={'C4':[({'target_bps':100},None)]})
        with self.assertRaises(ValueError):trial.point(args,case,'DrivingInCity',1,.1,'id',None)

    def test_summary_keeps_both_alphas_and_both_baselines_with_all_sequences(self):
        refs=[(None,dict(actual_bps=100*2**i,**{'mean_y_'+m:30+i for m in trial.NATIVE.values()})) for i in range(4)]
        cases={name:dict(groups={'anchor':refs,'C4':refs}) for name in trial.SEQUENCES}
        points=[dict(sequence=n,alpha=a,point=i+1,actual_bps=q['actual_bps']*.95,
                     quality={m:q['mean_y_'+native] for m,native in trial.NATIVE.items()})
                for n in trial.SEQUENCES for a in trial.ALPHAS for i,(r,q) in enumerate(refs)]
        report=trial.summarize(cases,points,{})
        for alpha in trial.ALPHAS:
            self.assertEqual(len(report['average'][str(alpha)]),8)
            for value in report['average'][str(alpha)].values():self.assertAlmostEqual(value,-5,places=8)
        points[0]['activity']={'eligible':False,'ineligible_reasons':['sibrc_fallback']}
        report=trial.summarize(cases,points,{})
        self.assertEqual(len(report['average']['0.1']),8)
        self.assertEqual(report['ineligible_points'][0]['reasons'],['sibrc_fallback'])
        report=trial.summarize(cases,points[:-1],{})
        self.assertIsNone(report['average']['0.1'])
        self.assertIsNone(report['average']['0.25'])

    def test_clone_redirects_every_frozen_trace(self):
        command=['old','-b','old.vvc','--VTMRCTrace=old.vtm.csv','--SIBRCTrace=old.sibrc.csv']
        cmd=trial.clone_command(command,'exe','out/R1','rec')
        self.assertIn('--VTMRCTrace=out/R1.vtm.csv',cmd)
        self.assertIn('--SIBRCTrace=out/R1.sibrc.csv',cmd)


if __name__=='__main__':unittest.main()
