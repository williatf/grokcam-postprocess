#!/usr/bin/env python3
"""Run frozen P15, forced P07, and P22 on one predeclared P23 population."""
from __future__ import annotations
import argparse,csv,json,sys,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.physical_sprocket import load_capture_metadata
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p14_detector_guided_edge_registration import measure_frame
from research.p21_run_forced_frozen_p07 import forced_p07
from research.p22_refine_frozen_p07_y import priors_for_image,refine

def main():
 p=argparse.ArgumentParser();p.add_argument('--population-id',required=True);p.add_argument('--reel',required=True);p.add_argument('--raw-dir',type=Path,required=True);p.add_argument('--first',type=int,required=True);p.add_argument('--last',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();frames=list(range(a.first,a.last+1));capture=load_capture_metadata(a.raw_dir);p15cfg=json.loads((ROOT/'research/config/p14_detector_guided_edge_registration.json').read_text());dev=DarktableMatchedDeveloper(load_calibration().match.report);results=[];a.output.parent.mkdir(parents=True,exist_ok=True)
 for start in range(0,len(frames),24):
  batch=frames[start:start+24]
  with tempfile.TemporaryDirectory(prefix='p23_',dir=ROOT/'work') as temp:
   temp=Path(temp)
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs=[pool.submit(dev.develop,a.raw_dir/f'frame_{n:06d}.dng',temp/f'frame_{n:06d}.tif') for n in batch]
    for f in as_completed(fs):f.result()
   def one(n):
    with Image.open(temp/f'frame_{n:06d}.tif') as image:
     p07=forced_p07(image,capture.get(n));anchor_x=(float(p07['upper_x'])+float(p07['lower_x']))/2-17.125;anchor_y=(float(p07['upper_y'])+float(p07['lower_y']))/2;p15=measure_frame(image,anchor_x,anchor_y,p15cfg)['lower_top'];shift=None;diag={}
     if p07['accepted']:shift,diag=refine(image,float(p07['upper_x']),float(p07['upper_y']),priors_for_image(image,capture.get(n)))
    refined=None if shift is None else float(p07['model_lower_top_y'])+shift
    return {'population_id':a.population_id,'reel':a.reel,'frame':n,'p15_valid':p15['valid'],'p15_lower_top_y':p15['y'] if p15['valid'] else None,'p15_reason':p15.get('reason'),'p15_valid_columns':p15.get('valid_columns'),'p15_valid_fraction':p15.get('valid_fraction'),'p15_column_mad':p15.get('column_mad'),'p15_median_snr':p15.get('median_snr'),'p07_accepted':p07['accepted'],'p07_classification':p07['classification'],'p07_upper_x':p07['upper_x'],'p07_upper_y':p07['upper_y'],'p07_lower_x':p07['lower_x'],'p07_lower_y':p07['lower_y'],'p07_model_lower_top_y':p07['model_lower_top_y'],'p07_joint_score':p07['joint_score'],'p07_geometric_residual':p07['geometric_residual'],'p07_competitor_margin':p07['competitor_margin'],'p07_supported':p07['supported'],'p07_missing':p07['missing'],'p07_contradicted':p07['contradicted'],'p07_upper_states_json':p07['upper_states_json'],'p07_lower_states_json':p07['lower_states_json'],'p07_prior_count':p07['prior_count'],'p07_physical_hole_count':p07['physical_hole_count'],'p22_completed':shift is not None,'p22_shift_y':shift,'p22_refined_model_lower_top_y':refined,'p22_calibrated_register_y':None if refined is None else refined+4.17878784687116,'p22_local_score':diag.get('local_score'),'p22_local_margin_1px':diag.get('local_score_margin_1px'),'p22_score_range':diag.get('score_range'),'p22_maximum_tie_count':diag.get('maximum_tie_count'),'p22_boundary_hit':diag.get('search_boundary_hit'),'p22_shallow':None if shift is None else diag['local_score_margin_1px']<=.01,'authoritative_source':'P15' if p15['valid'] else ('P22' if shift is not None else 'unresolved'),'authoritative_register_y':p15['y'] if p15['valid'] else (None if refined is None else refined+4.17878784687116)}
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:results.extend(f.result() for f in as_completed([pool.submit(one,n) for n in batch]))
  print(f"P23 {a.population_id} {min(start+len(batch),len(frames))}/{len(frames)}",flush=True)
 results.sort(key=lambda r:r['frame'])
 with a.output.open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
 print(json.dumps({'population':a.population_id,'frames':len(results),'p15_valid':sum(r['p15_valid'] for r in results),'p07_accepted':sum(r['p07_accepted'] for r in results),'coverage':sum(r['authoritative_source']!='unresolved' for r in results)},indent=2))
if __name__=='__main__':main()
