"""Check raw final-selected inter pixel triples against TPSM CTU trace."""
import argparse,csv,struct,json
from collections import defaultdict
from pathlib import Path
import numpy as np

def verify(binary,trace):
 totals=defaultdict(lambda:[0,0,0]);seen=set();blocks=0
 with open(binary,'rb') as f:
  while True:
   head=f.read(24)
   if not head:break
   if len(head)!=24:raise ValueError('truncated audit header')
   poc,ctu,x,y,w,h=struct.unpack('<6i',head)
   if min(x,y)<0 or min(w,h)<=0:raise ValueError('invalid audit geometry')
   raw=f.read(w*h*6)
   if len(raw)!=w*h*6:raise ValueError('truncated pixel triples')
   v=np.frombuffer(raw,dtype='<i2').astype(np.int64).reshape(-1,3)
   for yy in range(y,y+h):
    for xx in range(x,x+w):
     key=(poc,xx,yy)
     if key in seen:raise ValueError('overlapping final inter CUs')
     seen.add(key)
   key=(poc,ctu);totals[key][0]+=int(np.sum((v[:,0]-v[:,2])**2));totals[key][1]+=int(np.sum((v[:,0]-v[:,1])**2));totals[key][2]+=w*h;blocks+=1
 with open(trace,newline='') as f:rows=list(csv.DictReader(f))
 if len({(int(r['poc']),int(r['ctu'])) for r in rows})!=len(rows):raise ValueError('duplicate trace rows')
 for row in rows:
  key=(int(row['poc']),int(row['ctu']));actual=totals.pop(key,[0,0,0]);expected=[float(row[k]) for k in ('d','mcp','pixels')]
  if actual!=expected:raise ValueError(f'audit mismatch {key}: {actual} != {expected}')
 if totals:raise ValueError('audit contains CTUs missing from trace')
 return {'blocks':blocks,'pixels':len(seen),'trace_ctus':len(rows)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('binary');p.add_argument('trace');a=p.parse_args();print(json.dumps(verify(a.binary,a.trace)))
