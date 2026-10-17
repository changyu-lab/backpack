import importlib.util
import pathlib
import unittest
import tempfile
import json
import contextlib
import io
import os

HERE = pathlib.Path(__file__).parent
REFERENCE_ROOT = pathlib.Path(os.environ.get('SALDANHA_REFERENCE_ROOT', 'I:/vvenc-LFNST/backups/S123AB_formal_20261005/runner'))
SPEC = importlib.util.spec_from_file_location('runner', HERE / 'run_matched.py')
r = importlib.util.module_from_spec(SPEC) if SPEC else None
if SPEC and pathlib.Path(SPEC.origin).exists():
    SPEC.loader.exec_module(r)

class RunnerTests(unittest.TestCase):
    def test_stats_validation(self):
        self.assertTrue(hasattr(r, 'validate_stats'), 'stats validation missing')
        with self.assertRaises(ValueError):
            r.validate_stats({'eligible': 3}, 'proposed')
        r.validate_stats({'eligible': 3, 'predicted_skip': 2, 'suppressed_candidates': 4}, 'proposed')

    def test_real_reference_dry_run(self):
        root = REFERENCE_ROOT
        with contextlib.nullcontext(HERE / 'test_fixture') as tmp:
            tmp.mkdir(exist_ok=True)
            seq = tmp/'Demo_16x16_30fps_8bit_420_erp.yuv'
            seq.write_bytes(bytes(16*16*3//2*32))
            asset = tmp/'asset'
            asset.write_text('test')
            argv = ['--encoder', str(asset), '--model', str(asset), '--seq-root', str(tmp),
                    '--output', str(tmp/'out'), '--sphere', str(asset), '--360convert', str(asset),
                    '--reference-runner-root', str(root), '--dry-run']
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(r.main(argv), 0)
            plan = json.loads((tmp/'out/plan.json').read_text())
            self.assertEqual(len(plan['cases']), 48)
            self.assertEqual([c['kind'] for c in plan['cases'][:4]], ['anchor','proposed','proposed','anchor'])
            for case in plan['cases']:
                cmd = case['command']
                self.assertEqual(cmd[cmd.index('--additional')+1], 'LFNST=1 LardLfnstSkip=0')
                self.assertEqual(case['frames'], {'AI':1,'RA':32,'LD':16}[case['config']])
                self.assertNotIn('SALDANHA_CSV', case['environment'])
            old = plan['cases'][0]
            asset.write_text('changed model')
            with contextlib.redirect_stdout(io.StringIO()):
                r.main(argv)
            new = json.loads((tmp/'out/plan.json').read_text())['cases'][0]
            self.assertFalse(r.provenance_matches(old, new))

    def test_arm_environment(self):
        self.assertTrue(hasattr(r, 'arm_environment'), 'arm environment implementation missing')
        for kind, mode in [('anchor', 'off'), ('proposed', 'on')]:
            env = r.arm_environment({'SALDANHA_CSV': 'bad', 'SALDANHA_MODE': 'bad'}, kind, 'model', 'stats', 'seq')
            self.assertNotIn('SALDANHA_CSV', env)
            self.assertEqual(env['SALDANHA_MODE'], mode)

    def test_resume_model_change_rejected(self):
        self.assertTrue(hasattr(r, 'provenance_matches'), 'resume provenance implementation missing')
        self.assertFalse(r.provenance_matches({'model_sha256': 'old'}, {'model_sha256': 'new'}))

    def test_incomplete_qps_no_bd(self):
        self.assertTrue(hasattr(r, 'summarize'), 'summary implementation missing')
        result = r.summarize([], [22, 27, 32, 37], 2, None)
        self.assertIsNone(result['bd_rate'])
        self.assertFalse(result['complete'])

    def test_real_reference_bd_and_timing(self):
        legacy, _ = r.load_reference(REFERENCE_ROOT)
        rows = []
        for i, qp in enumerate(r.QPS):
            for rep in (1, 2):
                for kind in ('anchor', 'proposed'):
                    rows.append({'QP':qp, 'repeat':rep, 'kind':kind,
                        'Seconds': 10 if kind == 'anchor' else 9,
                        'Kbps':1000/(i+1), **{f'360Lib13_6_{m}_Y':40-i*3 for m in ('WS','S','CPP')}})
        result = r.summarize(rows, r.QPS, 2, legacy)
        self.assertTrue(result['complete'])
        self.assertEqual(result['TSbest_pct'], 10)
        self.assertEqual(result['TSmedian_pct'], 10)
        for value in result['bd_rate'].values():
            self.assertAlmostEqual(value, 0)
        self.assertIsNone(r.summarize(rows[:-1], r.QPS, 2, legacy)['bd_rate'])

if __name__ == '__main__':
    unittest.main()
