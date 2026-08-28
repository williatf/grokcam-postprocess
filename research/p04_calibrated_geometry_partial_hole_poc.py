#!/usr/bin/env python3
"""Fixed-geometry, landmark-anchored partial sprocket recovery POC."""
from __future__ import annotations
import argparse,csv,json,math,shutil,statistics,sys,tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture,load_manifest,transform_boxes
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.render_physical_hole_problem_review import any_capture_boxes,classify as original_class
BASE=ROOT/'research/output/sprocket_xy/physical_hole_capture_prior_poc/Reel_46335'
PREVIOUS=ROOT/'research/output/sprocket_xy/partner_partial_hole_poc/Reel_46335'
CONFIG=ROOT/'research/p04_calibrated_geometry_partial_hole_blue_frozen.json'
DEFAULT_OUTPUT=ROOT/'research/output/sprocket_xy/calibrated_geometry_partial_hole_poc/Reel_46335'
@dataclass
class Model:
 cx:float;cy:float;width:float;height:float;score:float;interior_contrast:float;competitor_margin:float;evidence:dict;accepted_features:list;anchor_type:str;residuals:dict
def sample(a,xs,ys):
 xi=np.clip(np.rint(xs).astype(int),0,a.shape[1]-1);yi=np.clip(np.rint(ys).astype(int),0,a.shape[0]-1);return float(np.mean(a[yi,xi]))
def feature_values(gx,gy,gm,gray,cx,cy,w,h):
 vy=np.linspace(cy-.30*h,cy+.30*h,31);hx=np.linspace(cx-.30*w,cx+.30*w,41)
 e={'left_wall':sample(gx,np.full_like(vy,cx-w/2),vy),'right_wall':sample(gx,np.full_like(vy,cx+w/2),vy),'top_edge':sample(gy,hx,np.full_like(hx,cy-h/2)),'bottom_edge':sample(gy,hx,np.full_like(hx,cy+h/2))}
 corners={'upper_left':(cx-w/2,cy-h/2),'upper_right':(cx+w/2,cy-h/2),'lower_right':(cx+w/2,cy+h/2),'lower_left':(cx-w/2,cy+h/2)}
 for k,(x,y) in corners.items():
  yy,xx=np.mgrid[max(0,int(y-12)):min(gm.shape[0],int(y+13)),max(0,int(x-12)):min(gm.shape[1],int(x+13))];e[k]=float(np.percentile(gm[yy,xx],90)) if xx.size else 0
 inside=gray[max(0,int(cy-.3*h)):min(gray.shape[0],int(cy+.3*h)),max(0,int(cx-.3*w)):min(gray.shape[1],int(cx+.3*w))];outer=gray[max(0,int(cy-.7*h)):min(gray.shape[0],int(cy+.7*h)),max(0,int(cx-.7*w)):min(gray.shape[1],int(cx+.7*w))]
 contrast=float(np.percentile(inside,60)-np.percentile(outer,30)) if inside.size and outer.size else 0
 return e,contrast,corners
def peaks(profile,n=7):
 order=np.argsort(profile)[::-1];out=[]
 for i in order:
  if all(abs(int(i)-j)>12 for j in out):out.append(int(i))
  if len(out)>=n:break
 return out
def fit_fixed(image,prediction,cfg):
 px,py=prediction;w=cfg['hole_width'];h=cfg['hole_height'];H,W=image.shape[:2];x0=max(0,int(px-.9*w));x1=min(W,int(px+.9*w));y0=max(0,int(py-.9*h));y1=min(H,int(py+.9*h))
 if x1-x0<.8*w or y1-y0<.8*h:return None,{'reason':'predicted_roi_out_of_frame'},[]
 gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);gx=np.abs(sx);gy=np.abs(sy);gm=cv2.magnitude(sx,sy);norm=max(float(np.percentile(gm,92)),12);gx=np.clip(gx/norm,0,1);gy=np.clip(gy/norm,0,1);gm=np.clip(gm/norm,0,1)
 vprof=gx.mean(axis=0);hprof=gy.mean(axis=1);landmarks=[];hyp=[]
 for x in peaks(vprof):
  X=x+x0;landmarks.append(('vertical',X,None,float(vprof[x])));hyp += [('left_wall',X+w/2,py),('right_wall',X-w/2,py)]
 for y in peaks(hprof):
  Y=y+y0;landmarks.append(('horizontal',None,Y,float(hprof[y])));hyp += [('top_edge',px,Y+h/2),('bottom_edge',px,Y-h/2)]
 corners=cv2.goodFeaturesToTrack(np.uint8(np.clip(gm*255,0,255)),maxCorners=32,qualityLevel=.08,minDistance=18)
 expected={'upper_left':(-w/2,-h/2),'upper_right':(w/2,-h/2),'lower_right':(w/2,h/2),'lower_left':(-w/2,h/2)}
 if corners is not None:
  for q in corners[:,0,:]:
   X=float(q[0]+x0);Y=float(q[1]+y0)
   for name,(ox,oy) in expected.items():
    cx=X-ox;cy=Y-oy
    if abs(cx-px)<=.22*w and abs(cy-py)<=.22*h:
     hyp.append((name,cx,cy));landmarks.append((name,X,Y,float(gm[int(q[1]),int(q[0])])) )
 fits=[]
 for anchor,cx,cy in hyp:
  lx=cx-x0;ly=cy-y0
  if lx-w/2<0 or lx+w/2>=gray.shape[1] or ly-h/2<0 or ly+h/2>=gray.shape[0]:continue
  e,contrast,cpos=feature_values(gx,gy,gm,gray,lx,ly,w,h);vals=sorted(e.values(),reverse=True);score=.75*statistics.mean(vals[:6])+.25*min(vals[:4])+min(max(contrast,0)/80,.2);features=[k for k,v in e.items() if v>=cfg['feature_threshold']]
  residual={}
  residual['left_wall']=min((abs((cx-w/2)-a[1]) for a in landmarks if a[0]=='vertical'),default=999);residual['right_wall']=min((abs((cx+w/2)-a[1]) for a in landmarks if a[0]=='vertical'),default=999);residual['top_edge']=min((abs((cy-h/2)-a[2]) for a in landmarks if a[0]=='horizontal'),default=999);residual['bottom_edge']=min((abs((cy+h/2)-a[2]) for a in landmarks if a[0]=='horizontal'),default=999)
  for name,(xx,yy) in cpos.items():
   xa=max(0,int(xx-25));xb=min(gm.shape[1],int(xx+26));ya=max(0,int(yy-25));yb=min(gm.shape[0],int(yy+26));patch=gm[ya:yb,xa:xb]
   if patch.size:
    iy,ix=np.unravel_index(np.argmax(patch),patch.shape);residual[name]=math.hypot((xa+ix)-xx,(ya+iy)-yy)
   else:residual[name]=999
  fits.append((score,cx,cy,e,contrast,features,anchor,residual))
 fits.sort(reverse=True,key=lambda z:z[0]);
 if not fits:return None,{'reason':'no_landmark_hypothesis'},landmarks
 best=fits[0];far=[f for f in fits[1:] if math.hypot(f[1]-best[1],f[2]-best[2])>.13*max(w,h)];margin=best[0]-(far[0][0] if far else 0);features=best[5];walls=sum(k.endswith('wall') for k in features);edges=sum(k.endswith('edge') for k in features);corners=sum(k in expected for k in features);res=[best[7][k] for k in features];residual_median=statistics.median(res) if res else 999.;residual_max=max(res) if res else 999.;safe=(best[4]>=cfg['interior_contrast_min'] and best[0]>=cfg['model_score_min'] and margin>=cfg['competitor_margin_min'] and len(features)>=cfg['minimum_features'] and walls>=cfg['minimum_walls'] and edges>=cfg['minimum_edges'] and corners>=cfg['minimum_corners'] and residual_median<=cfg['corroboration_residual_max'])
 model=Model(best[1],best[2],w,h,best[0],best[4],margin,best[3],features,best[6],best[7]);detail={'safe':safe,'anchor_type':best[6],'features':features,'score':best[0],'contrast':best[4],'margin':margin,'residual_median':residual_median,'residual_max':residual_max,'residuals':best[7]}
 return (model if safe else None),detail,landmarks
def evaluate(image,row,capture,cfg):
 rgb=np.asarray(image.convert('RGB'));boxes=any_capture_boxes(capture);holes=[]
 for b in boxes:holes.append((*physical_hole(rgb,b,.25),b))
 if row['physical_pair_found']=='True':return {'classification':'normal_detector_success','accepted':False,'holes':holes}
 good=[z for z in holes if z[0] is not None]
 if len(good)!=1:return {'classification':'both_holes_damaged_ambiguous' if not good else 'capture_prior_roi_incorrect','accepted':False,'holes':holes}
 seed=good[0][0]
 if not(cfg['seed_x_domain'][0]<=seed.cx<=cfg['seed_x_domain'][1]):return {'classification':'capture_prior_roi_incorrect','accepted':False,'holes':holes,'seed':seed}
 upper=seed.cy<rgb.shape[0]/2;px=seed.cx+(cfg['lower_minus_upper_x'] if upper else -cfg['lower_minus_upper_x']);py=seed.cy+(cfg['pitch'] if upper else -cfg['pitch']);model,detail,landmarks=fit_fixed(rgb,(px,py),cfg)
 if model is None:return {'classification':'insufficient_partner_evidence','accepted':False,'holes':holes,'seed':seed,'seed_is_upper':upper,'prediction':(px,py),'detail':detail,'landmarks':landmarks}
 pitch=abs(model.cy-seed.cy);xd=abs((model.cx-seed.cx)-(cfg['lower_minus_upper_x'] if upper else -cfg['lower_minus_upper_x']))
 if abs(pitch-cfg['pitch'])>100 or xd>100:return {'classification':'capture_prior_roi_incorrect','accepted':False,'holes':holes,'seed':seed,'model':model,'detail':detail,'landmarks':landmarks}
 return {'classification':'calibrated_geometry_recovery','accepted':True,'holes':holes,'seed':seed,'seed_is_upper':upper,'prediction':(px,py),'model':model,'detail':detail,'landmarks':landmarks,'anchor_x':statistics.mean([seed.cx,model.cx])-17.125,'anchor_y':statistics.mean([seed.cy,model.cy])}
def panel(image,row,r,cal):
 c=Image.new('RGB',(1400,850),'#090909');d=ImageDraw.Draw(c);d.text((14,10),f"FRAME {int(row['frame']):06d} {r['classification']}",fill='white');o=image.convert('RGB');od=ImageDraw.Draw(o)
 for z in r.get('holes',[]):
  hole=z[0];b=z[3];px,py,pw,ph=b;od.rectangle((px-pw/2,py-ph/2,px+pw/2,py+ph/2),outline='cyan',width=8)
  if hole:od.rectangle((hole.cx-hole.width/2,hole.cy-hole.height/2,hole.cx+hole.width/2,hole.cy+hole.height/2),outline='lime',width=8)
 for lm in r.get('landmarks',[]):
  if lm[1] is not None and lm[2] is not None:od.ellipse((lm[1]-7,lm[2]-7,lm[1]+7,lm[2]+7),outline='orange',width=4)
 m=r.get('model')
 if m:
  # Observed one-dimensional boundary evidence is deliberately rendered
  # separately from the calibrated model.  Only peaks close enough to
  # corroborate a predicted wall/edge are drawn, avoiding a forest of unrelated
  # image-content gradients.
  for kind,x,y,_strength in r.get('landmarks',[]):
   if kind=='vertical' and min(abs(x-(m.cx-m.width/2)),abs(x-(m.cx+m.width/2)))<=25:od.line((x,m.cy-.30*m.height,x,m.cy+.30*m.height),fill='orange',width=7)
   if kind=='horizontal' and min(abs(y-(m.cy-m.height/2)),abs(y-(m.cy+m.height/2)))<=25:od.line((m.cx-.30*m.width,y,m.cx+.30*m.width,y),fill='orange',width=7)
  od.rounded_rectangle((m.cx-m.width/2,m.cy-m.height/2,m.cx+m.width/2,m.cy+m.height/2),radius=45,outline='magenta',width=10)
 o.thumbnail((650,720),Image.Resampling.LANCZOS);c.paste(o,(10,90));crop=CropGeometry(float(row['hybrid_final_x'])+159,float(row['hybrid_final_y'])-413,1133,900);ctx=registered_frame(image,crop,cal.contrast);ctx.thumbnail((720,650),Image.Resampling.LANCZOS);c.paste(ctx,(670,110));d.text((14,820),'cyan=capture  green=intact hole  orange=observed walls/edges/corners  magenta=fixed calibrated model',fill='white');return c
def make_sheets(paths,out,prefix):
 for page,start in enumerate(range(0,len(paths),48),1):
  items=paths[start:start+48];sheet=Image.new('RGB',(1400,58+math.ceil(len(items)/2)*425),'black');ImageDraw.Draw(sheet).text((14,18),prefix,fill='white')
  for i,p in enumerate(items):
   with Image.open(p) as im:q=im.resize((700,425),Image.Resampling.LANCZOS)
   sheet.paste(q,((i%2)*700,58+(i//2)*425))
  sheet.save(out/f'{prefix}_{page:02d}.jpg',quality=91)
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();rows=[r for r in csv.DictReader((BASE/'diagnostics.csv').open()) if r['hybrid_interpolated']=='True'];assert len(rows)==198;by={int(r['frame']):r for r in rows};prev={int(r['frame']):r for r in csv.DictReader((PREVIOUS/'diagnostics.csv').open())};cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);panels=a.output_dir/'panels';panels.mkdir(parents=True,exist_ok=True);results=[]
 dngs=[spec['project']/'raw'/f"frame_{n:06d}.dng" for n in sorted(by)]
 for start in range(0,len(dngs),24):
  batch=dngs[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='fixed_geometry_',dir=ROOT/'work'))
  try:
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs={pool.submit(dev.develop,d,tmp/f'{d.stem}.tif'):d for d in batch}
    for f in as_completed(fs):f.result()
   for dng in batch:
    n=int(dng.stem.rsplit('_',1)[1]);row=by[n]
    with Image.open(tmp/f'{dng.stem}.tif') as im:r=evaluate(im,row,capture[n],cfg);v=panel(im,row,r,cal)
    v.save(panels/f'frame_{n:06d}.jpg',quality=91);detail=r.get('detail',{});results.append({'frame':n,'original_failure_class':original_class(row),'classification':r['classification'],'accepted':r['accepted'],'previous_partial_accepted':prev[n]['accepted'],'anchor_type':detail.get('anchor_type'),'boundary_features':';'.join(detail.get('features',[])),'residual_median':detail.get('residual_median'),'residual_max':detail.get('residual_max'),'model_width':getattr(r.get('model'),'width',None),'model_height':getattr(r.get('model'),'height',None),'anchor_x':r.get('anchor_x'),'anchor_y':r.get('anchor_y')})
  finally:shutil.rmtree(tmp)
  print(f'processed {min(start+len(batch),len(dngs))}/{len(dngs)}',flush=True)
 fields=sorted({k for r in results for k in r});a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/'diagnostics.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(results)
 recovered=[r for r in results if r['accepted']];failed=[r for r in results if not r['accepted']];make_sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in recovered],a.output_dir,'recovered');make_sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in failed[:48]],a.output_dir,'failed_review')
 previous={r['frame'] for r in results if r['previous_partial_accepted']=='True'};current={r['frame'] for r in recovered};medians=[float(r['residual_median']) for r in recovered];maxima=[float(r['residual_max']) for r in recovered]
 questionable=[r['frame'] for r in recovered if float(r['residual_median'])>20 or float(r['residual_max'])>40]
 report={'frames':198,'recovered':len(recovered),'unresolved':198-len(recovered),'classifications':dict(Counter(r['classification'] for r in results)),'by_original_failure':{k:sum(r['accepted'] and r['original_failure_class']==k for r in results) for k in sorted(set(r['original_failure_class'] for r in results))},'feature_combinations':dict(Counter(r['boundary_features'] for r in recovered)),'anchor_types':dict(Counter(r['anchor_type'] for r in recovered)),'landmark_residuals':{'median_of_model_medians':float(np.median(medians)),'p95_of_model_medians':float(np.percentile(medians,95)),'maximum_model_median':max(medians),'median_of_model_maxima':float(np.median(maxima)),'p95_of_model_maxima':float(np.percentile(maxima,95)),'maximum_feature_residual':max(maxima)},'questionable_review_frames':questionable,'previous_partial_recovered':len(previous),'comparison_with_previous':{'retained':len(current&previous),'new':len(current-previous),'dropped':len(previous-current)},'fixed_dimensions':{'width':cfg['hole_width'],'height':cfg['hole_height']},'frame_42':next(r for r in results if r['frame']==42),'frame_3341':next(r for r in results if r['frame']==3341),'protected_blind_annotations_used':False};(a.output_dir/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
