"""Run with JAVA_HOME set to the downloaded JDK; synthetic rows are tests only."""
import csv, json, os, pathlib, subprocess, sys, tempfile, unittest
import train

class WekaIntegration(unittest.TestCase):
    def test_real_weka_export(self):
        root=pathlib.Path(__file__).parent.resolve()
        home=pathlib.Path(os.environ['JAVA_HOME'])
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            tmp=pathlib.Path(tmp); source=tmp/'synthetic.csv'
            with source.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=train.FEATURES+['sequence','poc','qp','label']); w.writeheader()
                for sequence in ['synthetic_train','synthetic_validation']:
                    for i in range(240):
                        r={k:0 for k in train.FEATURES}; r.update(width=8,height=8,area=64,blockRatio=1,currCost=i/7,currDistortion=i/9,sequence=sequence,poc=0,qp=32,label=int(i>=120)); w.writerow(r)
            command=[sys.executable,str(root/'train.py'),'--input',str(source),'--train-sequences','synthetic_train','--validation-sequences','synthetic_validation','--output',str(tmp/'out'),'--java',str(home/'bin/java.exe'),'--javac',str(home/'bin/javac.exe'),'--weka',str(root/'deps/weka.jar'),'--extra-classpath',str(root/'deps/bounce.jar')]
            subprocess.run(command,check=True,stdout=subprocess.PIPE,text=True)
            manifest=json.loads((tmp/'out/manifest.json').read_text())
            self.assertGreater(manifest['node_count'],1)
            self.assertEqual(manifest['max_prediction_error'],0)
            self.assertTrue(json.loads((tmp/'out/equivalence.json').read_text())['passed'])
            self.assertEqual(manifest['validation_rows'],240)
            first=(tmp/'out/model.txt').read_bytes()
            subprocess.run(command,check=True,stdout=subprocess.PIPE,text=True)
            self.assertEqual(first,(tmp/'out/model.txt').read_bytes())

if __name__=='__main__': unittest.main()
