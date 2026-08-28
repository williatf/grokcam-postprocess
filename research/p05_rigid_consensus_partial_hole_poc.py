#!/usr/bin/env python3
"""Rigid fixed-geometry, landmark-consensus partial sprocket recovery POC."""
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
CURRENT=ROOT/'research/output/sprocket_xy/calibrated_geometry_partial_hole_poc/Reel_46335'
CONFIG=ROOT/'research/p05_rigid_consensus_partial_hole_blue_frozen.json'
DEFAULT_OUTPUT=ROOT/'research/output/sprocket_xy/rigid_consensus_partial_hole_poc/Reel_46335'
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
def _weighted_median(values,weights):
 order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order];return float(v[np.searchsorted(np.cumsum(w),w.sum()/2)])
def _axis_consensus(votes,radius):
 """Return robust 1-D clusters, allowing one assignment per raw landmark."""
 clusters=[]
 for seed in (v['value'] for v in votes):
  center=float(seed)
  for _ in range(3):
   choices={}
   for v in votes:
    residual=abs(v['value']-center)
    if residual<=radius and (v['obs_id'] not in choices or residual<choices[v['obs_id']][0]):choices[v['obs_id']]=(residual,v)
   if not choices:break
   chosen=[z[1] for z in choices.values()];center=_weighted_median([v['value'] for v in chosen],[max(v['strength'],.05) for v in chosen])
  chosen=[v for _,v in choices.values()];score=sum(max(v['strength'],.05) for v in chosen)
  clusters.append({'value':center,'score':score,'votes':chosen})
 clusters.sort(key=lambda z:(z['score'],len(z['votes'])),reverse=True);unique=[]
 for c in clusters:
  if all(abs(c['value']-u['value'])>radius/2 for u in unique):unique.append(c)
 return unique[:5]
def _assign_landmarks(observations,cx,cy,w,h,inlier_radius):
 expected={'left_wall':(cx-w/2,None),'right_wall':(cx+w/2,None),'top_edge':(None,cy-h/2),'bottom_edge':(None,cy+h/2),'upper_left':(cx-w/2,cy-h/2),'upper_right':(cx+w/2,cy-h/2),'lower_right':(cx+w/2,cy+h/2),'lower_left':(cx-w/2,cy+h/2)}
 assigned=[]
 for o in observations:
  names=('left_wall','right_wall') if o['kind']=='vertical' else ('top_edge','bottom_edge') if o['kind']=='horizontal' else ('upper_left','upper_right','lower_right','lower_left')
  candidates=[]
  for name in names:
   ex,ey=expected[name];dx=0 if ex is None else o['x']-ex;dy=0 if ey is None else o['y']-ey;candidates.append((math.hypot(dx,dy),name,dx,dy))
  residual,name,dx,dy=min(candidates);assigned.append({**o,'feature_class':name,'residual':residual,'dx':dx,'dy':dy,'inlier':residual<=inlier_radius})
 return assigned
def fit_consensus(image,prediction,cfg):
 px,py=prediction;w=cfg['hole_width'];h=cfg['hole_height'];H,W=image.shape[:2];x0=max(0,int(px-.9*w));x1=min(W,int(px+.9*w));y0=max(0,int(py-.9*h));y1=min(H,int(py+.9*h))
 if x1-x0<.8*w or y1-y0<.8*h:return None,{'reason':'predicted_roi_out_of_frame'},[]
 gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);gx=np.abs(sx);gy=np.abs(sy);gm=cv2.magnitude(sx,sy);norm=max(float(np.percentile(gm,92)),12);gx=np.clip(gx/norm,0,1);gy=np.clip(gy/norm,0,1);gm=np.clip(gm/norm,0,1)
 observations=[];xvotes=[];yvotes=[]
 for i,x in enumerate(peaks(gx.mean(axis=0))):
  X=float(x+x0);o={'obs_id':f'v{i}','kind':'vertical','x':X,'y':None,'strength':float(gx.mean(axis=0)[x])};observations.append(o)
  for name,offset in [('left_wall',-w/2),('right_wall',w/2)]:xvotes.append({'obs_id':o['obs_id'],'class':name,'value':X-offset,'strength':o['strength']})
 for i,y in enumerate(peaks(gy.mean(axis=1))):
  Y=float(y+y0);o={'obs_id':f'h{i}','kind':'horizontal','x':None,'y':Y,'strength':float(gy.mean(axis=1)[y])};observations.append(o)
  for name,offset in [('top_edge',-h/2),('bottom_edge',h/2)]:yvotes.append({'obs_id':o['obs_id'],'class':name,'value':Y-offset,'strength':o['strength']})
 corners=cv2.goodFeaturesToTrack(np.uint8(np.clip(gm*255,0,255)),maxCorners=32,qualityLevel=.08,minDistance=18);corner_offsets={'upper_left':(-w/2,-h/2),'upper_right':(w/2,-h/2),'lower_right':(w/2,h/2),'lower_left':(-w/2,h/2)}
 if corners is not None:
  for i,q in enumerate(corners[:,0,:]):
   X=float(q[0]+x0);Y=float(q[1]+y0);o={'obs_id':f'c{i}','kind':'corner','x':X,'y':Y,'strength':float(gm[int(q[1]),int(q[0])])};observations.append(o)
   for name,(ox,oy) in corner_offsets.items():
    cx=X-ox;cy=Y-oy
    if abs(cx-px)<=.22*w and abs(cy-py)<=.22*h:xvotes.append({'obs_id':o['obs_id'],'class':name,'value':cx,'strength':o['strength']});yvotes.append({'obs_id':o['obs_id'],'class':name,'value':cy,'strength':o['strength']})
 radius=cfg['consensus_inlier_radius'];xclusters=_axis_consensus(xvotes,radius);yclusters=_axis_consensus(yvotes,radius)
 fits=[]
 for xc in xclusters:
  for yc in yclusters:
   cx,cy=xc['value'],yc['value'];lx,ly=cx-x0,cy-y0
   if lx-w/2<0 or lx+w/2>=gray.shape[1] or ly-h/2<0 or ly+h/2>=gray.shape[0]:continue
   assigned=_assign_landmarks(observations,cx,cy,w,h,radius);inliers=[o for o in assigned if o['inlier']];classes=sorted(set(o['feature_class'] for o in inliers));e,contrast,_=feature_values(gx,gy,gm,gray,lx,ly,w,h);vals=sorted(e.values(),reverse=True);image_score=.75*statistics.mean(vals[:6])+.25*min(vals[:4])+min(max(contrast,0)/80,.2);support=sum(max(o['strength'],.05) for o in inliers);score=image_score+.02*len(inliers)+.01*len(classes)+.005*support
   fits.append({'score':score,'image_score':image_score,'cx':cx,'cy':cy,'evidence':e,'contrast':contrast,'assigned':assigned,'inliers':inliers,'classes':classes})
 fits.sort(key=lambda z:z['score'],reverse=True)
 if not fits:return None,{'reason':'no_consensus_hypothesis','observed_landmarks':len(observations)},observations
 best=fits[0];far=[f for f in fits[1:] if math.hypot(f['cx']-best['cx'],f['cy']-best['cy'])>.13*max(w,h)];margin=best['score']-(far[0]['score'] if far else 0);res=[o['residual'] for o in best['inliers']];classes=best['classes'];walls=sum(k.endswith('wall') for k in classes);edges=sum(k.endswith('edge') for k in classes);corners=sum(k in corner_offsets for k in classes);median=statistics.median(res) if res else 999.;maximum=max(res) if res else 999.
 safe=(best['contrast']>=cfg['interior_contrast_min'] and best['image_score']>=cfg['model_score_min'] and margin>=cfg['competitor_margin_min'] and len(best['inliers'])>=cfg['minimum_supporting_landmarks'] and len(classes)>=cfg['minimum_feature_classes'] and walls>=cfg['minimum_walls'] and edges>=cfg['minimum_edges'] and corners>=cfg['minimum_corners'] and median<=cfg['corroboration_residual_max'])
 residuals={o['obs_id']:o['residual'] for o in best['assigned']};model=Model(best['cx'],best['cy'],w,h,best['image_score'],best['contrast'],margin,best['evidence'],classes,'rigid_consensus',residuals);competitors=[{'x':f['cx'],'y':f['cy'],'score':f['score'],'landmark_count':len(f['inliers']),'class_count':len(f['classes'])} for f in fits[1:6]];detail={'safe':safe,'anchor_type':'rigid_consensus','features':classes,'score':best['image_score'],'consensus_score':best['score'],'contrast':best['contrast'],'margin':margin,'supporting_landmarks':len(best['inliers']),'feature_classes':len(classes),'inlier_count':len(best['inliers']),'residual_median':median,'residual_max':maximum,'residuals':residuals,'assignments':best['assigned'],'competing_hypotheses':competitors}
 return (model if safe else None),detail,observations

# Kept as a compatibility entry point for focused tests; unlike P04 it is now
# a consensus solver and never selects a single landmark as the anchor.
fit_fixed=fit_consensus
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
 return {'classification':'rigid_consensus_recovery','accepted':True,'holes':holes,'seed':seed,'seed_is_upper':upper,'prediction':(px,py),'model':model,'detail':detail,'landmarks':landmarks,'anchor_x':statistics.mean([seed.cx,model.cx])-17.125,'anchor_y':statistics.mean([seed.cy,model.cy])}
def panel(image,row,r,cal):
 c=Image.new('RGB',(1400,850),'#090909');d=ImageDraw.Draw(c);d.text((14,10),f"FRAME {int(row['frame']):06d} {r['classification']}",fill='white');o=image.convert('RGB');od=ImageDraw.Draw(o)
 for z in r.get('holes',[]):
  hole=z[0];b=z[3];px,py,pw,ph=b;od.rectangle((px-pw/2,py-ph/2,px+pw/2,py+ph/2),outline='cyan',width=8)
  if hole:od.rectangle((hole.cx-hole.width/2,hole.cy-hole.height/2,hole.cx+hole.width/2,hole.cy+hole.height/2),outline='lime',width=8)
 m=r.get('model')
 if m:
  for a in r.get('detail',{}).get('assignments',[]):
   color='orange' if a['inlier'] else 'red'
   if a['kind']=='vertical':od.line((a['x'],m.cy-.30*m.height,a['x'],m.cy+.30*m.height),fill=color,width=7)
   elif a['kind']=='horizontal':od.line((m.cx-.30*m.width,a['y'],m.cx+.30*m.width,a['y']),fill=color,width=7)
   else:od.ellipse((a['x']-7,a['y']-7,a['x']+7,a['y']+7),outline=color,width=4)
  od.rounded_rectangle((m.cx-m.width/2,m.cy-m.height/2,m.cx+m.width/2,m.cy+m.height/2),radius=45,outline='magenta',width=10)
  od.line((m.cx-18,m.cy,m.cx+18,m.cy),fill='magenta',width=5);od.line((m.cx,m.cy-18,m.cx,m.cy+18),fill='magenta',width=5)
 o.thumbnail((650,720),Image.Resampling.LANCZOS);c.paste(o,(10,90));crop=CropGeometry(float(row['hybrid_final_x'])+159,float(row['hybrid_final_y'])-413,1133,900);ctx=registered_frame(image,crop,cal.contrast);ctx.thumbnail((720,650),Image.Resampling.LANCZOS);c.paste(ctx,(670,110));d.text((14,820),'cyan=capture ROI  green=intact partner  orange=inlier  red=outlier  magenta=fixed model at consensus',fill='white');return c
def make_sheets(paths,out,prefix):
 for page,start in enumerate(range(0,len(paths),48),1):
  items=paths[start:start+48];sheet=Image.new('RGB',(1400,58+math.ceil(len(items)/2)*425),'black');ImageDraw.Draw(sheet).text((14,18),prefix,fill='white')
  for i,p in enumerate(items):
   with Image.open(p) as im:q=im.resize((700,425),Image.Resampling.LANCZOS)
   sheet.paste(q,((i%2)*700,58+(i//2)*425))
  sheet.save(out/f'{prefix}_{page:02d}.jpg',quality=91)
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();rows=[r for r in csv.DictReader((BASE/'diagnostics.csv').open()) if r['hybrid_interpolated']=='True'];assert len(rows)==198;by={int(r['frame']):r for r in rows};prev={int(r['frame']):r for r in csv.DictReader((CURRENT/'diagnostics.csv').open())};cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);panels=a.output_dir/'panels';panels.mkdir(parents=True,exist_ok=True);results=[]
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
    v.save(panels/f'frame_{n:06d}.jpg',quality=91);detail=r.get('detail',{});results.append({'frame':n,'original_failure_class':original_class(row),'classification':r['classification'],'accepted':r['accepted'],'p04_accepted':prev[n]['accepted'],'feature_classes_list':';'.join(detail.get('features',[])),'supporting_landmarks':detail.get('supporting_landmarks'),'feature_class_count':detail.get('feature_classes'),'inlier_count':detail.get('inlier_count'),'image_score':detail.get('score'),'consensus_score':detail.get('consensus_score'),'competitor_margin':detail.get('margin'),'residual_median':detail.get('residual_median'),'residual_max':detail.get('residual_max'),'all_landmark_residuals_json':json.dumps(detail.get('residuals',{}),sort_keys=True),'competing_hypotheses_json':json.dumps(detail.get('competing_hypotheses',[]),sort_keys=True),'model_x':getattr(r.get('model'),'cx',None),'model_y':getattr(r.get('model'),'cy',None),'model_width':getattr(r.get('model'),'width',None),'model_height':getattr(r.get('model'),'height',None),'anchor_x':r.get('anchor_x'),'anchor_y':r.get('anchor_y')})
  finally:shutil.rmtree(tmp)
  print(f'processed {min(start+len(batch),len(dngs))}/{len(dngs)}',flush=True)
 fields=sorted({k for r in results for k in r});a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/'diagnostics.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(results)
 recovered=[r for r in results if r['accepted']];failed=[r for r in results if not r['accepted']];make_sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in recovered],a.output_dir,'recovered');make_sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in failed[:48]],a.output_dir,'failed_review')
 previous={r['frame'] for r in results if r['p04_accepted']=='True'};current={r['frame'] for r in recovered};medians=[float(r['residual_median']) for r in recovered];maxima=[float(r['residual_max']) for r in recovered]
 questionable=[r['frame'] for r in recovered if float(r['residual_median'])>20 or float(r['residual_max'])>=24 or float(r['competitor_margin'])<.05]
 report={'frames':198,'recovered':len(recovered),'unresolved':198-len(recovered),'classifications':dict(Counter(r['classification'] for r in results)),'by_original_failure':{k:sum(r['accepted'] and r['original_failure_class']==k for r in results) for k in sorted(set(r['original_failure_class'] for r in results))},'feature_combinations':dict(Counter(r['feature_classes_list'] for r in recovered)),'landmark_residuals':{'median_of_model_medians':float(np.median(medians)) if medians else None,'p95_of_model_medians':float(np.percentile(medians,95)) if medians else None,'maximum_model_median':max(medians) if medians else None,'median_of_model_maxima':float(np.median(maxima)) if maxima else None,'p95_of_model_maxima':float(np.percentile(maxima,95)) if maxima else None,'maximum_inlier_residual':max(maxima) if maxima else None},'questionable_review_frames':questionable,'p04_recovered':len(previous),'comparison_with_p04':{'retained':len(current&previous),'new':len(current-previous),'dropped':len(previous-current)},'fixed_geometry':{'width':cfg['hole_width'],'height':cfg['hole_height'],'pitch':cfg['pitch'],'lower_minus_upper_x':cfg['lower_minus_upper_x'],'scale_fitted':False,'rotation_fitted':False},'frame_42':next(r for r in results if r['frame']==42),'frame_3341':next(r for r in results if r['frame']==3341),'protected_blind_annotations_used':False};(a.output_dir/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
