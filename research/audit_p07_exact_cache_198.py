#!/usr/bin/env python3
"""Paired full-population exact-equivalence and timing audit for P07 cache POC."""
from __future__ import annotations
import csv,hashlib,json,os,platform,resource,shutil,statistics,sys,tempfile,time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p07_joint_rigid_sprocket_pair_evidence_poc import CONFIG,P06,fit_pair
from research.p07_exact_cached_candidate_poc import fit_pair_cached
from research.render_physical_hole_problem_review import any_capture_boxes
REFOUT=ROOT/'research/output/sprocket_xy/joint_rigid_sprocket_pair_evidence_poc/Reel_46335';OUT=ROOT/'research/output/sprocket_xy/p07_exact_template_optimization'
FROZEN={'research/p07_joint_rigid_sprocket_pair_evidence_poc.py':'d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d','research/p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json':'334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6','research/test_p07_joint_rigid_sprocket_pair_evidence_poc.py':'82bc6487ffd3d9bc8c9dc86a206355f4973202ed19b79f9c59a8cb1438558e4d'}
VARIANT=['research/p07_exact_cached_candidate_poc.py','research/p07_exact_cached_candidate_blue_frozen.json','research/test_p07_exact_cached_candidate_poc.py']
def sha(p):return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def summary(v):return {'median':statistics.median(v),'mean':statistics.mean(v),'p95':float(np.percentile(v,95)),'maximum':max(v),'sum':sum(v)}
def main():
 bad={p:(want,sha(p)) for p,want in FROZEN.items() if sha(p)!=want}
 if bad:raise SystemExit(f'frozen hash mismatch {bad}')
 oracle={int(r['frame']):r for r in csv.DictReader((REFOUT/'diagnostics.csv').open())};p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())};cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);dev=DarktableMatchedDeveloper(load_calibration().match.report);rows=[];wall0=time.perf_counter()
 for start in range(0,len(oracle),24):
  frames=sorted(oracle)[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='p07_exact198_',dir=ROOT/'work'))
  try:
   with ThreadPoolExecutor(max_workers=3) as pool:
    fs=[pool.submit(dev.develop,spec['project']/'raw'/f'frame_{f:06d}.dng',tmp/f'frame_{f:06d}.tif') for f in frames]
    for x in as_completed(fs):x.result()
   def one(f):
    with Image.open(tmp/f'frame_{f:06d}.tif') as im:rgb=np.asarray(im.convert('RGB'))
    boxes=any_capture_boxes(capture[f]);holes=[physical_hole(rgb,b,.25)[0] for b in boxes];r=p06[f];prior=(float(r['model_x']),float(r['model_y'])) if r.get('model_x') not in ('',None) else None
    # Alternate order by frame parity while retaining the same resident input.
    metrics={}
    if f%2:
     t=time.perf_counter();a=fit_pair(rgb,boxes,holes,prior,cfg);rt=time.perf_counter()-t;t=time.perf_counter();b=fit_pair_cached(rgb,boxes,holes,prior,cfg,metrics);ot=time.perf_counter()-t
    else:
     t=time.perf_counter();b=fit_pair_cached(rgb,boxes,holes,prior,cfg,metrics);ot=time.perf_counter()-t;t=time.perf_counter();a=fit_pair(rgb,boxes,holes,prior,cfg);rt=time.perf_counter()-t
    exact=a==b;o=oracle[f];oracle_match=(str(b['safe'])==o['accepted'] and b['upper_x']==float(o['upper_x']) and b['upper_y']==float(o['upper_y']) and b['lower_x']==float(o['lower_x']) and b['lower_y']==float(o['lower_y']) and b['score']==float(o['joint_score']) and b['margin']==float(o['competitor_margin']) and b['upper']['states']==json.loads(o['upper_states_json']) and b['lower']['states']==json.loads(o['lower_states_json']))
    return {'frame':f,'classification':'IDENTICAL' if exact and oracle_match else 'BEHAVIORAL_CHANGE','reference_seconds':rt,'optimized_seconds':ot,'speedup':rt/ot,'exact_pair_dictionary':exact,'matches_frozen_oracle':oracle_match,**metrics}
   with ThreadPoolExecutor(max_workers=3) as pool:rows.extend(x.result() for x in as_completed([pool.submit(one,f) for f in frames]))
  finally:shutil.rmtree(tmp)
  print(f'audited {min(start+len(frames),len(oracle))}/{len(oracle)}',flush=True)
 rows.sort(key=lambda r:r['frame']);fields=list(rows[0]);
 with (OUT/'full_198_equivalence.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(rows)
 ref=[r['reference_seconds'] for r in rows];opt=[r['optimized_seconds'] for r in rows];blind=set(json.load((ROOT/'research/output/sprocket_xy/p07_frozen_blind_validation/population_manifest.json').open())['frames_in_blind_order']);queue=set(json.load((REFOUT/'validation_report.json').open())['review_queue']);mandatory={42,3341,4589,4600,2117,2170,2199,2240,2606,2608,4599};audit={'frozen_hashes':FROZEN,'variant_hashes':{p:sha(p) for p in VARIANT},'population':{'frozen_198':len(rows),'blind_subset':len(blind),'safety_queue':len(queue),'mandatory':sorted(mandatory)},'classifications':dict(Counter(r['classification'] for r in rows)),'behavioral_changes':[r for r in rows if r['classification']!='IDENTICAL'],'subset_failures':{'blind':[f for f in blind if next(r for r in rows if r['frame']==f)['classification']!='IDENTICAL'],'safety_queue':[f for f in queue if next(r for r in rows if r['frame']==f)['classification']!='IDENTICAL'],'mandatory':[f for f in mandatory if next(r for r in rows if r['frame']==f)['classification']!='IDENTICAL']},'timing':{'reference':summary(ref),'optimized':summary(opt),'aggregate_speedup':sum(ref)/sum(opt),'complete_wall_seconds':time.perf_counter()-wall0},'cache':{'calls':sum(r['candidate_calls'] for r in rows),'hits':sum(r['candidate_cache_hits'] for r in rows),'misses':sum(r['candidate_cache_misses'] for r in rows),'hit_rate':sum(r['candidate_cache_hits'] for r in rows)/sum(r['candidate_calls'] for r in rows),'template_evaluations_avoided':sum(r['template_evaluations_avoided'] for r in rows),'percentile_calls_avoided':sum(r['percentile_calls_avoided'] for r in rows)},'environment':{'python':platform.python_version(),'numpy':np.__version__,'opencv':cv2.__version__,'platform':platform.platform(),'cpu_count':os.cpu_count(),'thread_environment':{k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')},'jobs':3,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}};(OUT/'equivalence_audit.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps({k:v for k,v in audit.items() if k not in ('behavioral_changes','environment')}|{'behavioral_change_count':len(audit['behavioral_changes'])},indent=2))
if __name__=='__main__':main()
