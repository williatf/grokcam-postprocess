#!/usr/bin/env python3
"""Matched six-frame benchmark for frozen P07 versus exact candidate cache."""
from __future__ import annotations
import csv,json,resource,shutil,statistics,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p07_joint_rigid_sprocket_pair_evidence_poc import BASE,CONFIG,P06,fit_pair
from research.p07_exact_cached_candidate_poc import fit_pair_cached
from research.render_physical_hole_problem_review import any_capture_boxes
FRAMES=[42,949,2117,3341,4589,4600];OUT=ROOT/'research/output/sprocket_xy/p07_exact_template_optimization'
def main():
 OUT.mkdir(parents=True,exist_ok=True);cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())};dev=DarktableMatchedDeveloper(load_calibration().match.report);tmp=Path(tempfile.mkdtemp(prefix='p07_exact_bench_',dir=ROOT/'work'));rows=[]
 try:
  with ThreadPoolExecutor(max_workers=3) as pool:
   fs=[pool.submit(dev.develop,spec['project']/'raw'/f'frame_{f:06d}.dng',tmp/f'frame_{f:06d}.tif') for f in FRAMES]
   for x in as_completed(fs):x.result()
  inputs={}
  for f in FRAMES:
   with Image.open(tmp/f'frame_{f:06d}.tif') as im:rgb=np.asarray(im.convert('RGB'))
   boxes=any_capture_boxes(capture[f]);holes=[physical_hole(rgb,b,.25)[0] for b in boxes];r=p06[f];prior=(float(r['model_x']),float(r['model_y'])) if r.get('model_x') not in ('',None) else None;inputs[f]=(rgb,boxes,holes,prior)
  # Warm both implementations once on identical resident arrays.
  for f in FRAMES:
   fit_pair(*inputs[f],cfg);fit_pair_cached(*inputs[f],cfg,{})
  for rep in range(3):
   order=FRAMES if rep%2==0 else list(reversed(FRAMES))
   for f in order:
    args=inputs[f];metrics={}
    if rep%2==0:
     t=time.perf_counter();a=fit_pair(*args,cfg);rt=time.perf_counter()-t;t=time.perf_counter();b=fit_pair_cached(*args,cfg,metrics);ot=time.perf_counter()-t
    else:
     t=time.perf_counter();b=fit_pair_cached(*args,cfg,metrics);ot=time.perf_counter()-t;t=time.perf_counter();a=fit_pair(*args,cfg);rt=time.perf_counter()-t
    rows.append({'frame':f,'repetition':rep+1,'reference_seconds':rt,'optimized_seconds':ot,'speedup':rt/ot,'identical':a==b,**metrics})
  fields=list(rows[0]);
  with (OUT/'six_frame_benchmark.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(rows)
  ref=[r['reference_seconds'] for r in rows];opt=[r['optimized_seconds'] for r in rows];summary={'frames':FRAMES,'repetitions':3,'comparisons':len(rows),'identical':sum(r['identical'] for r in rows),'behavioral_changes':sum(not r['identical'] for r in rows),'reference':{'median':statistics.median(ref),'mean':statistics.mean(ref),'p95':sorted(ref)[int(.95*(len(ref)-1))],'maximum':max(ref),'wall_sum':sum(ref)},'optimized':{'median':statistics.median(opt),'mean':statistics.mean(opt),'p95':sorted(opt)[int(.95*(len(opt)-1))],'maximum':max(opt),'wall_sum':sum(opt)},'aggregate_speedup':sum(ref)/sum(opt),'cache':{'median_hits':statistics.median(r['candidate_cache_hits'] for r in rows),'median_calls':statistics.median(r['candidate_calls'] for r in rows),'hit_rate':sum(r['candidate_cache_hits'] for r in rows)/sum(r['candidate_calls'] for r in rows),'template_evaluations_avoided':sum(r['template_evaluations_avoided'] for r in rows),'percentile_calls_avoided':sum(r['percentile_calls_avoided'] for r in rows)},'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss};(OUT/'six_frame_benchmark.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
 finally:shutil.rmtree(tmp)
if __name__=='__main__':main()
