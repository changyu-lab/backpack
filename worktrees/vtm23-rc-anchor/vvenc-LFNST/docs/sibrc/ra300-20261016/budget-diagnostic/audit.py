import json,csv,gzip,re,subprocess,hashlib,math
from pathlib import Path
B=Path('/root/sibrc-ra300-budget-audit-20261016');RUN=Path('/root/sibrc-ra300-20261016');results=[];details=[];fields=0
for record in sorted((RUN/'runs').rglob('*.run.json')):
 r=json.loads(record.read_text())
 if r['label']=='cqp':continue
 pre=Path(r['prefix']);path=pre.with_suffix('.vtm.csv');op=gzip.open if not path.exists() else open
 if not path.exists():path=Path(str(path)+'.gz')
 pictures=[];begins=[]
 with op(path,'rt') as f:
  for row in csv.DictReader(f):
   if row['event']=='picture':pictures.append(row)
   elif row['event']=='begin':begins.append(row)
 assert len(pictures)==len(r['pocs'])
 fixture=B/(r['sequence']+'_'+r['label']+'_R'+str(r['point'])+'.fixture')
 fixture.write_text('%d 300 3840 1920 30 %d\n'%(r['target_bps'],len(pictures))+''.join('%s %s\n'%(x['poc'],x['bits']) for x in pictures))
 outs=[]
 for kernel in ['official','compat']:
  dest=fixture.with_suffix('.'+kernel+'.txt');subprocess.run([str(B/('budget_'+kernel)),str(fixture),str(dest)],check=True);outs.append(dest.read_text())
 assert outs[0]==outs[1],'Reference divergence '+str(fixture)
 rows=outs[0].splitlines();init=rows[0].split();total=int(init[1]);assert total==int(begins[0]['seq_left'])
 consumed=0;first=None;iratotal=0;text=pre.with_suffix('.log').read_text();types={int(n):k for n,k in re.findall(r'POC\s+(\d+).*?\(.*?\b([IPB])-SLICE',text)}
 for i,row in enumerate(pictures):
  values=rows[i+1].split();poc,left,remaining=int(values[0]),int(values[1]),int(values[2]);assert poc==int(row['poc']) and left==299-i and remaining==int(row['seq_left']);fields+=4
  consumed+=int(row['bits']);assert remaining==total-consumed
  if types[poc]=='I':iratotal+=int(row['bits'])
  entry=dict(sequence=r['sequence'],method=r['label'],point=r['point'],coding_index=i,poc=poc,type=types[poc],bits=int(row['bits']),target_budget_bits=total,cumulative_bits=consumed,remaining_frames=left,remaining_bits=remaining,left_average_bits=None if values[3]=='END' else int(values[3]),live_seq_left=int(row['seq_left']))
  details.append(entry)
  if remaining<=0 and first is None:first=entry
  if i+1<len(begins):assert int(begins[i+1]['seq_left'])==remaining
 if left>0:org=int(remaining/left)
 else:org=None
 last=details[-1]
 res=dict(sequence=r['sequence'],method=r['label'],point=r['point'],verified_full300=r['verified'],feedback_frames=len(pictures),target_bps=r['target_bps'],total_budget_bits=total,consumed_bits=consumed,consumed_budget_percent=100*consumed/total,IRAP_bits=iratotal,IRAP_share_percent=100*iratotal/consumed,remaining_bits=remaining,remaining_frames=left,left_average_bits=org,first_nonpositive=first,official_compat_exact=True,live_budget_exact=True,fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest())
 if not r['verified']:
  assert org is not None and org<=0
  res['next_expected_IRAP_POC']=288;res['intra_refinement_domain']='nonpositive orgBits; negative base to fractional exponent for any positive SATD cost'
 results.append(res);print('PASS',r['sequence'],r['label'],r['point'],'frames',len(pictures),'left',remaining,'IRAPshare',round(res['IRAP_share_percent'],2),flush=True)
with (B/'budget-ledger.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(details[0]));w.writeheader();w.writerows(details)
(B/'budget-audit.json').write_text(json.dumps(dict(status='PASS',scope='Official EncRCSeq versus VtmRcSeq sequence-budget create/update/getLeftAverageBits on identical actual picture feedback in coding order; not full CTU decision replay or encoder equivalence',streams=len(results),picture_feedback_rows=len(details),integer_comparison_fields=fields,results=results),indent=2))
print('ALL SEQUENCE BUDGET REPLAY PASS',flush=True)
