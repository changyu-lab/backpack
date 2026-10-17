import csv, os, subprocess, tempfile, unittest
from pathlib import Path

SERIAL = ['--Threads=0','--MaxParallelFrames=0','--IFP=0','--TileParallelCtuEnc=0',
          '--Tiles=1x1','--WaveFrontSynchro=0','--WppBitEqual=0',
          '--HrdParametersPresent=0','--SEIBufferingPeriod=0','--PerceptQPA=0','--BIM=0','--MCTF=0','--LookAhead=0','--STA=0']

class ClosedLoop(unittest.TestCase):
    def test_serial_feedback_and_closed_budget(self):
        exe=os.environ['VVENC_VTMRC_EXE']
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); clip=p/'clip.yuv'; trace=p/'rc.csv'
            frame=bytes((x*17+y*13)%256 for y in range(96) for x in range(128))+bytes([128])*(128*96//2)
            clip.write_bytes(frame*9)
            args=[exe,'--preset','faster','-s','128x96','-fr','30','-f','9','-i',str(clip),'-b',str(p/'out.vvc'),
                  '--GOPSize=8','--PicReordering=0','--POC0IDR=1','--DecodingRefreshType=0','--IntraPeriod=32','--VTMTargetBitrate=30000','--VTMRCTrace='+str(trace)]+SERIAL
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            self.assertEqual(result.returncode,0,result.stdout[-4000:])
            with trace.open() as stream:
                rows=list(csv.DictReader(stream))
            pictures=[r for r in rows if r['event']=='picture']
            self.assertEqual(len(pictures),9)
            pending=None; last=-1; remaining={}
            for r in rows:
                if r['event']=='decision':
                    self.assertIsNone(pending)
                    key=(int(r['poc']),int(r['ctu']))
                    self.assertEqual(key[1], last+1)
                    pending=key; remaining[key]=int(r['pic_left'])
                elif r['event']=='feedback':
                    key=(int(r['poc']),int(r['ctu']))
                    self.assertEqual(pending,key)
                    self.assertEqual(int(r['pic_left']),remaining[key]-int(r['bits']))
                    pending=None; last=key[1]
                elif r['event']=='picture':
                    self.assertIsNone(pending); last=-1
            self.assertIsNone(pending)

    def test_ra_tail_and_numerical_domain(self):
        exe=os.environ['VVENC_VTMRC_EXE']
        for gop,frames,rate,constant,success,reason in [(16,19,60000,False,True,''),(32,35,60000,False,True,''),(8,1,30000,True,False,'zero intra SATD'),(8,1,1,False,False,'nonpositive remaining intra budget')]:
            with self.subTest(gop=gop,rate=rate,constant=constant), tempfile.TemporaryDirectory() as folder:
                p=Path(folder);clip=p/'clip.yuv';trace=p/'rc.csv'
                y=bytes([128])*(128*96) if constant else bytes((x*17+y*13)%256 for y in range(96) for x in range(128))
                clip.write_bytes((y+bytes([128])*(128*96//2))*frames)
                args=[exe,'--preset','faster','-s','128x96','-fr','30','-f',str(frames),'-i',str(clip),'-b',str(p/'out.vvc'),'--GOPSize='+str(gop),'--PicReordering='+str(int(gop>8)),'--POC0IDR=1','--DecodingRefreshType='+str(int(gop>8)),'--IntraPeriod=32','--VTMTargetBitrate='+str(rate),'--VTMRCTrace='+str(trace)]+SERIAL
                result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                if success:
                    self.assertEqual(result.returncode,0,result.stdout[-4000:])
                    with trace.open() as stream: rows=list(csv.DictReader(stream))
                    self.assertEqual(len([r for r in rows if r['event']=='picture']),frames)
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn(reason,result.stdout)

class Configuration(unittest.TestCase):
    def test_conflicting_modes_are_rejected(self):
        exe=os.environ['VVENC_VTMRC_EXE']
        for change,reason in [('--PerceptQPA=1','QPA'),('--Threads=1','Threads=0'),
                              ('--WaveFrontSynchro=1','WaveFrontSynchro=0'),
                              ('--MaxParallelFrames=2','MaxParallelFrames=0'),
                              ('--TileParallelCtuEnc=1','TileParallelCtuEnc=0'),
                              ('--LookAhead=1','LookAhead=0'),('--BIM=1','BIM'),('--IFPLines=2','IFPLines=0'),('--TileColumnWidthArray=1','tile widths/heights'),
                              ('--TargetBitrate=30000','native RC')]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                p=Path(folder); clip=p/'input.yuv'; clip.write_bytes(bytes([128])*(128*96*3//2))
                args=[exe,'--preset','faster','-s','128x96','-fr','30','-f','1','-i',str(clip),'-b',str(p/'out.vvc'),
                      '--GOPSize=8','--PicReordering=0','--POC0IDR=1','--DecodingRefreshType=0',
                      '--VTMTargetBitrate=30000']+SERIAL+[change]
                result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('VTM23 RC',result.stdout)
                self.assertIn(reason,result.stdout)

if __name__=='__main__': unittest.main()
