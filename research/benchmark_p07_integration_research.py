#!/usr/bin/env python3
"""Performance/equivalence probe around frozen P07; never changes the reference."""
from __future__ import annotations
import cProfile,csv,json,math,pstats,shutil,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p07_joint_rigid_sprocket_pair_evidence_poc import BASE,CONFIG,P06,fit_pair
from research.render_physical_hole_problem_review import any_capture_boxes

FRAMES=[42,949,2117,3341,4589,4600]
OUT=ROOT/'research/output/sprocket_xy/p07_production_integration_research'
def placement(a,b):return math.hypot(a['upper_x']-b['upper_x'],a['upper_y']-b['upper_y'])
def classify(ref,test):
 if ref['safe']==test['safe'] and placement(ref,test)<1e-9 and ref['upper']['states']==test['upper']['states'] and ref['lower']['states']==test['lower']['states'] and abs(ref['score']-test['score'])<1e-9 and abs(ref['margin']-test['margin'])<1e-9:return 'IDENTICAL'
 if ref['safe']==test['safe'] and placement(ref,test)<=4:return 'NUMERICALLY_EQUIVALENT'
 return 'BEHAVIORAL_CHANGE'
def main():
 OUT.mkdir(parents=True,exist_ok=True);cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);base={int(r['frame']):r for r in csv.DictReader((BASE/'diagnostics.csv').open())};p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())};dev=DarktableMatchedDeveloper(load_calibration().match.report);tmp=Path(tempfile.mkdtemp(prefix='p07_perf_',dir=ROOT/'work'));profile=cProfile.Profile();results=[]
 try:
  t=time.perf_counter()
  with ThreadPoolExecutor(max_workers=3) as pool:
   fs=[pool.submit(dev.develop,spec['project']/'raw'/f'frame_{f:06d}.dng',tmp/f'frame_{f:06d}.tif') for f in FRAMES]
   for x in as_completed(fs):x.result()
  develop=time.perf_counter()-t
  for f in FRAMES:
   with Image.open(tmp/f'frame_{f:06d}.tif') as im:
    t=time.perf_counter();rgb=__import__('numpy').asarray(im.convert('RGB'));image_prep=time.perf_counter()-t
    boxes=any_capture_boxes(capture[f]);t=time.perf_counter();holes=[physical_hole(rgb,b,.25)[0] for b in boxes];normal=time.perf_counter()-t
    pr=p06[f];prior=(float(pr['model_x']),float(pr['model_y'])) if pr.get('model_x') not in ('',None) else None
    profile.enable();t=time.perf_counter();ref=fit_pair(rgb,boxes,holes,prior,cfg);reference=time.perf_counter()-t;profile.disable()
    variants={}
    for step in (24,32):
     vcfg={**cfg,'coarse_step':step};t=time.perf_counter();v=fit_pair(rgb,boxes,holes,prior,vcfg);elapsed=time.perf_counter()-t
     variants[str(step)]={'seconds':elapsed,'equivalence':classify(ref,v),'accepted':v['safe'],'upper_x':v['upper_x'],'upper_y':v['upper_y'],'score':v['score'],'margin':v['margin'],'placement_delta':placement(ref,v),'states_equal':ref['upper']['states']==v['upper']['states'] and ref['lower']['states']==v['lower']['states']}
    results.append({'frame':f,'image_prep_seconds':image_prep,'normal_physical_seconds':normal,'reference_seconds':reference,'reference':{'accepted':ref['safe'],'upper_x':ref['upper_x'],'upper_y':ref['upper_y'],'score':ref['score'],'margin':ref['margin']},'coarse_variants':variants})
  stats=pstats.Stats(profile).strip_dirs().sort_stats('cumulative');stats.dump_stats(str(OUT/'p07_reference_profile.pstats'))
  import io
  h=io.StringIO();pstats.Stats(profile,stream=h).strip_dirs().sort_stats('cumulative').print_stats(40);(OUT/'p07_reference_profile.txt').write_text(h.getvalue())
  summary={'frames':FRAMES,'dng_development_wall_seconds':develop,'results':results,'reference_median_seconds':float(__import__('numpy').median([r['reference_seconds'] for r in results])),'variant_equivalence':{step:{k:sum(r['coarse_variants'][step]['equivalence']==k for r in results) for k in ('IDENTICAL','NUMERICALLY_EQUIVALENT','BEHAVIORAL_CHANGE')} for step in ('24','32')}};(OUT/'benchmark.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
 finally:shutil.rmtree(tmp)
if __name__=='__main__':main()
