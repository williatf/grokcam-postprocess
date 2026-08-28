#!/usr/bin/env python3
"""Full frozen-population equivalence test for experimental P07 coarse step 32."""
from __future__ import annotations
import csv,json,math,shutil,sys,tempfile,time
from collections import Counter
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
from research.render_physical_hole_problem_review import any_capture_boxes
OUT=ROOT/'research/output/sprocket_xy/p07_production_integration_research'
def main():
 ref={int(r['frame']):r for r in csv.DictReader((ROOT/'research/output/sprocket_xy/joint_rigid_sprocket_pair_evidence_poc/Reel_46335/diagnostics.csv').open())};base={int(r['frame']):r for r in csv.DictReader((BASE/'diagnostics.csv').open())};p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())};cfg={**json.loads(CONFIG.read_text()),'coarse_step':32};spec=REELS['Reel_46335'];capture=load_capture(spec['project']);dev=DarktableMatchedDeveloper(load_calibration().match.report);results=[];start_all=time.perf_counter()
 for start in range(0,len(ref),24):
  frames=sorted(ref)[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='p07_c32_',dir=ROOT/'work'))
  try:
   with ThreadPoolExecutor(max_workers=3) as pool:
    fs=[pool.submit(dev.develop,spec['project']/'raw'/f'frame_{f:06d}.dng',tmp/f'frame_{f:06d}.tif') for f in frames]
    for x in as_completed(fs):x.result()
   def one(f):
    with Image.open(tmp/f'frame_{f:06d}.tif') as im:rgb=np.asarray(im.convert('RGB'))
    boxes=any_capture_boxes(capture[f]);holes=[physical_hole(rgb,b,.25)[0] for b in boxes];r=p06[f];prior=(float(r['model_x']),float(r['model_y'])) if r.get('model_x') not in ('',None) else None;t=time.perf_counter();v=fit_pair(rgb,boxes,holes,prior,cfg);elapsed=time.perf_counter()-t;o=ref[f];states=(json.loads(o['upper_states_json'])==v['upper']['states'] and json.loads(o['lower_states_json'])==v['lower']['states']);delta=math.hypot(float(o['upper_x'])-v['upper_x'],float(o['upper_y'])-v['upper_y']);identical=(o['accepted']==str(v['safe']) and delta<1e-9 and states and abs(float(o['joint_score'])-v['score'])<1e-9 and abs(float(o['competitor_margin'])-v['margin'])<1e-9);numeric=(o['accepted']==str(v['safe']) and delta<=4);return {'frame':f,'classification':'IDENTICAL' if identical else 'NUMERICALLY_EQUIVALENT' if numeric else 'BEHAVIORAL_CHANGE','reference_accepted':o['accepted']=='True','variant_accepted':v['safe'],'placement_delta':delta,'states_equal':states,'score_delta':v['score']-float(o['joint_score']),'margin_delta':v['margin']-float(o['competitor_margin']),'seconds':elapsed}
   with ThreadPoolExecutor(max_workers=3) as pool:results.extend(x.result() for x in as_completed([pool.submit(one,f) for f in frames]))
  finally:shutil.rmtree(tmp)
  print(f'tested {min(start+len(frames),len(ref))}/{len(ref)}',flush=True)
 results.sort(key=lambda r:r['frame']);fields=list(results[0]);
 with (OUT/'coarse32_equivalence.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(results)
 summary={'frames':len(results),'classifications':dict(Counter(r['classification'] for r in results)),'decision_changes':sum(r['reference_accepted']!=r['variant_accepted'] for r in results),'median_seconds':float(np.median([r['seconds'] for r in results])),'p95_seconds':float(np.percentile([r['seconds'] for r in results],95)),'total_worker_seconds':sum(r['seconds'] for r in results),'wall_seconds':time.perf_counter()-start_all,'non_identical':[r for r in results if r['classification']!='IDENTICAL']};(OUT/'coarse32_equivalence.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='non_identical'}|{'non_identical_count':len(summary['non_identical'])},indent=2))
if __name__=='__main__':main()
