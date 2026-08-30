#!/usr/bin/env python3
"""Sub-grid common-Y refinement of an already accepted frozen P07 hypothesis."""
from __future__ import annotations
import argparse,csv,json,math,sys,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import cv2,numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.physical_sprocket import FROZEN_CONFIG,_p06_fit,_pair_candidate,_physical_hole,capture_boxes,load_capture_metadata
from grokcam.raw_development import DarktableMatchedDeveloper

def priors_for_image(image,capture_item):
 rgb=np.asarray(image.convert('RGB'),dtype=np.uint8);boxes=capture_boxes(capture_item);holes=[]
 for box in boxes:holes.append(_physical_hole(rgb,box)[0])
 good=[h for h in holes if h is not None];p06=None
 if len(good)==1:
  seed=good[0];upper=seed.cy<rgb.shape[0]/2;prediction=(seed.cx+(18.678947368421063 if upper else -18.678947368421063),seed.cy+(785. if upper else -785.));p06,_=_p06_fit(rgb,prediction)
 priors=[(b[0],b[1]) for b in boxes]+[(h.cx,h.cy) for h in good]
 if p06 is not None:priors.append(p06)
 return priors

def refine(image,upper_x,upper_y,priors,radius=3.,step=.25):
 rgb=np.asarray(image.convert('RGB'));cfg=FROZEN_CONFIG;H,W=rgb.shape[:2];w,h=cfg['hole_width'],cfg['hole_height'];xmin,xmax=cfg['sprocket_x_domain'];ymin,ymax=cfg['upper_y_domain'];x0=max(0,int(xmin-w/2-40));x1=min(W,int(xmax+w/2+40));y0=max(0,int(ymin-h/2-40));y1=min(H,int(ymax+cfg['pitch']+h/2+40));gray=cv2.cvtColor(rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1)
 normalized=[(px,py) if py<H/2 else (px-cfg['lower_minus_upper_x'],py-cfg['pitch']) for px,py in priors];candidates=[]
 for shift in np.arange(-radius,radius+step/2,step):
  uy=upper_y+float(shift);c=_pair_candidate(gray,sx,sy,upper_x-x0,uy-y0,cfg,False);distance=min((math.hypot(upper_x-px,uy-py) for px,py in normalized),default=0.);score=c['raw_score']-cfg['weak_prior_weight']*min(distance,200)/200;candidates.append({'shift':float(shift),'score':score,'raw_score':c['raw_score'],'prior_distance':distance})
 maximum=max(c['score'] for c in candidates);winners=[c for c in candidates if abs(c['score']-maximum)<=1e-12];best=min(winners,key=lambda c:(abs(c['shift']),c['shift']));separated=[c for c in candidates if abs(c['shift']-best['shift'])>=1.0];runner=max((c['score'] for c in separated),default=maximum)
 return best['shift'],{'local_score':best['score'],'local_raw_score':best['raw_score'],'local_prior_distance':best['prior_distance'],'local_score_margin_1px':best['score']-runner,'maximum_tie_count':len(winners),'search_boundary_hit':abs(best['shift'])==radius,'score_range':maximum-min(c['score'] for c in candidates),'candidates_json':json.dumps(candidates,separators=(',',':'))}

def main():
 p=argparse.ArgumentParser();p.add_argument('--p07',type=Path,required=True);p.add_argument('--raw-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();base=list(csv.DictReader(a.p07.open()));assert all(r['accepted']=='True' for r in base);capture=load_capture_metadata(a.raw_dir);dev=DarktableMatchedDeveloper(load_calibration().match.report);results=[];a.output.parent.mkdir(parents=True,exist_ok=True)
 for start in range(0,len(base),24):
  batch=base[start:start+24]
  with tempfile.TemporaryDirectory(prefix='p22_refine_',dir=ROOT/'work') as temp:
   temp=Path(temp)
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs=[pool.submit(dev.develop,a.raw_dir/f"frame_{int(r['frame']):06d}.dng",temp/f"frame_{int(r['frame']):06d}.tif") for r in batch]
    for f in as_completed(fs):f.result()
   def one(r):
    n=int(r['frame'])
    with Image.open(temp/f"frame_{n:06d}.tif") as image:ps=priors_for_image(image,capture.get(n));shift,diag=refine(image,float(r['upper_x']),float(r['upper_y']),ps)
    return {**r,'refined_shift_y':shift,'refined_upper_y':float(r['upper_y'])+shift,'refined_lower_y':float(r['lower_y'])+shift,'refined_model_lower_top_y':float(r['model_lower_top_y'])+shift,**diag}
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:results.extend(f.result() for f in as_completed([pool.submit(one,r) for r in batch]))
  print(f"P22 {min(start+len(batch),len(base))}/{len(base)}",flush=True)
 results.sort(key=lambda r:int(r['frame']))
 with a.output.open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
 print(json.dumps({'frames':len(results),'completed':len(results),'boundary_hits':sum(r['search_boundary_hit'] for r in results)},indent=2))
if __name__=='__main__':main()
