#!/usr/bin/env python3
"""cProfile the exact cached evaluator on the established six hard frames."""
from __future__ import annotations
import cProfile,csv,io,json,pstats,shutil,sys,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p07_joint_rigid_sprocket_pair_evidence_poc import CONFIG,P06
from research.p07_exact_cached_candidate_poc import fit_pair_cached
from research.render_physical_hole_problem_review import any_capture_boxes
FRAMES=[42,949,2117,3341,4589,4600];OUT=ROOT/'research/output/sprocket_xy/p07_exact_template_optimization'
def main():
 cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())};dev=DarktableMatchedDeveloper(load_calibration().match.report);tmp=Path(tempfile.mkdtemp(prefix='p07_exact_profile_',dir=ROOT/'work'));profile=cProfile.Profile();metrics=[]
 try:
  with ThreadPoolExecutor(max_workers=3) as pool:
   fs=[pool.submit(dev.develop,spec['project']/'raw'/f'frame_{f:06d}.dng',tmp/f'frame_{f:06d}.tif') for f in FRAMES]
   for x in as_completed(fs):x.result()
  for f in FRAMES:
   with Image.open(tmp/f'frame_{f:06d}.tif') as im:rgb=np.asarray(im.convert('RGB'))
   boxes=any_capture_boxes(capture[f]);holes=[physical_hole(rgb,b,.25)[0] for b in boxes];r=p06[f];prior=(float(r['model_x']),float(r['model_y'])) if r.get('model_x') not in ('',None) else None;m={};profile.enable();fit_pair_cached(rgb,boxes,holes,prior,cfg,m);profile.disable();metrics.append({'frame':f,**m})
  profile.dump_stats(str(OUT/'optimized_profile.pstats'));h=io.StringIO();pstats.Stats(profile,stream=h).strip_dirs().sort_stats('cumulative').print_stats(40);(OUT/'optimized_profile.txt').write_text(h.getvalue());(OUT/'optimized_profile_metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
 finally:shutil.rmtree(tmp)
if __name__=='__main__':main()
