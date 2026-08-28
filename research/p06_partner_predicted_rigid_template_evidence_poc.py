#!/usr/bin/env python3
"""Partner-predicted rigid-template evidence partial sprocket recovery POC."""
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
P04=ROOT/'research/output/sprocket_xy/calibrated_geometry_partial_hole_poc/Reel_46335'
P05=ROOT/'research/output/sprocket_xy/rigid_consensus_partial_hole_poc/Reel_46335'
CONFIG=ROOT/'research/p06_partner_predicted_rigid_template_evidence_blue_frozen.json'
DEFAULT_OUTPUT=ROOT/'research/output/sprocket_xy/partner_predicted_rigid_template_evidence_poc/Reel_46335'
@dataclass
class Model:
 cx:float;cy:float;width:float;height:float;score:float;interior_contrast:float;competitor_margin:float;evidence:dict;accepted_features:list;anchor_type:str;residuals:dict
def _sample(a,xs,ys):
 xi=np.clip(np.rint(xs).astype(int),0,a.shape[1]-1);yi=np.clip(np.rint(ys).astype(int),0,a.shape[0]-1);return a[yi,xi]
def _coherent_strength(values):
 values=np.asarray(values);return float(.55*np.mean(np.clip(values,0,1))+.45*np.mean(values>.18))
def _line_strength(sx,sy,cx,cy,w,h,name,offset=0):
 if name in ('left_wall','right_wall'):
  x=cx+(-w/2 if name=='left_wall' else w/2)+offset;ys=np.linspace(cy-.30*h,cy+.30*h,31);xs=np.full_like(ys,x);signed=_sample(sx,xs,ys)*(1 if name=='left_wall' else -1)
 else:
  y=cy+(-h/2 if name=='top_edge' else h/2)+offset;xs=np.linspace(cx-.30*w,cx+.30*w,41);ys=np.full_like(xs,y);signed=_sample(sy,xs,ys)*(1 if name=='top_edge' else -1)
 return _coherent_strength(signed),_coherent_strength(-signed)
def _corner_strength(sx,sy,cx,cy,w,h,name):
 rx=.16*w;ry=.20*h;angles={'upper_left':np.linspace(math.pi,1.5*math.pi,13),'upper_right':np.linspace(1.5*math.pi,2*math.pi,13),'lower_right':np.linspace(0,.5*math.pi,13),'lower_left':np.linspace(.5*math.pi,math.pi,13)}[name];centers={'upper_left':(cx-w/2+rx,cy-h/2+ry),'upper_right':(cx+w/2-rx,cy-h/2+ry),'lower_right':(cx+w/2-rx,cy+h/2-ry),'lower_left':(cx-w/2+rx,cy+h/2-ry)};ox,oy=centers[name];xs=ox+rx*np.cos(angles);ys=oy+ry*np.sin(angles);nx=-np.cos(angles);ny=-np.sin(angles);signed=_sample(sx,xs,ys)*nx+_sample(sy,xs,ys)*ny;return _coherent_strength(signed),_coherent_strength(-signed)
def _template_evidence(gray,sx,sy,cx,cy,w,h,cfg,full=False):
 features={};residuals={};states={};strengths={};contradictions={}
 for name in ('left_wall','right_wall','top_edge','bottom_edge'):
  support,opposite=_line_strength(sx,sy,cx,cy,w,h,name);best=(support,0)
  if full:
   for off in range(-cfg['feature_residual_search'],cfg['feature_residual_search']+1,2):
    s,_=_line_strength(sx,sy,cx,cy,w,h,name,off)
    if s>best[0]:best=(s,off)
  displaced=full and best[0]>=cfg['strong_feature_threshold'] and abs(best[1])>cfg['strong_feature_alignment_px'];contr=max(opposite,best[0] if displaced else 0);state='supported' if support>=cfg['feature_threshold'] and not displaced else 'contradicted' if contr>=cfg['feature_threshold'] else 'missing';features[name]=state;strengths[name]=support;contradictions[name]=contr;residuals[name]=abs(best[1])
 for name in ('upper_left','upper_right','lower_right','lower_left'):
  support,opposite=_corner_strength(sx,sy,cx,cy,w,h,name);state='supported' if support>=cfg['corner_threshold'] else 'contradicted' if opposite>=cfg['corner_threshold'] else 'missing';features[name]=state;strengths[name]=support;contradictions[name]=opposite;residuals[name]=0 if state=='supported' else None
 yi=slice(max(0,int(cy-.28*h)),min(gray.shape[0],int(cy+.28*h)));xi=slice(max(0,int(cx-.28*w)),min(gray.shape[1],int(cx+.28*w)));yo=slice(max(0,int(cy-.70*h)),min(gray.shape[0],int(cy+.70*h)));xo=slice(max(0,int(cx-.70*w)),min(gray.shape[1],int(cx+.70*w)));inside=gray[yi,xi];outer=gray[yo,xo];contrast=float(np.percentile(inside,60)-np.percentile(outer,30)) if inside.size and outer.size else 0
 majors=sum(strengths[n] for n in ('left_wall','right_wall','top_edge','bottom_edge'));corner_scores=sorted((strengths[n] for n in ('upper_left','upper_right','lower_right','lower_left')),reverse=True);penalty=sum(contradictions[n] for n,s in features.items() if s=='contradicted');support_score=majors+.6*sum(corner_scores[:2])+min(max(contrast,0)/80,.25)-.8*penalty
 return {'states':features,'strengths':strengths,'contradictions':contradictions,'residuals':residuals,'contrast':contrast,'score':support_score,'supported':sum(s=='supported' for s in features.values()),'missing':sum(s=='missing' for s in features.values()),'contradicted':sum(s=='contradicted' for s in features.values()),'strongest_contradiction':max(contradictions.values())}
def fit_template(image,prediction,cfg):
 px,py=prediction;w=cfg['hole_width'];h=cfg['hole_height'];pad=cfg['translation_radius']+cfg['feature_residual_search']+8;H,W=image.shape[:2];x0=max(0,int(px-w/2-pad));x1=min(W,int(px+w/2+pad));y0=max(0,int(py-h/2-pad));y1=min(H,int(py+h/2+pad))
 if x1-x0<w or y1-y0<h:return None,{'reason':'predicted_roi_out_of_frame'},[]
 gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1);lpx,lpy=px-x0,py-y0;candidates=[]
 step=cfg['translation_step'];radius=cfg['translation_radius']
 for dy in range(-radius,radius+1,step):
  for dx in range(-radius,radius+1,step):
   ev=_template_evidence(gray,sx,sy,lpx+dx,lpy+dy,w,h,cfg);distance=math.hypot(dx,dy);total=ev['score']-cfg['prediction_distance_weight']*distance/radius;candidates.append({'cx':px+dx,'cy':py+dy,'dx':dx,'dy':dy,'score':total,'raw_score':ev['score'],'evidence':ev})
 candidates.sort(key=lambda z:z['score'],reverse=True);best=candidates[0];full=_template_evidence(gray,sx,sy,best['cx']-x0,best['cy']-y0,w,h,cfg,True);best['evidence']=full;best['raw_score']=full['score'];best['score']=full['score']-cfg['prediction_distance_weight']*math.hypot(best['dx'],best['dy'])/radius
 competitors=[c for c in candidates[1:] if math.hypot(c['dx']-best['dx'],c['dy']-best['dy'])>=cfg['competitor_separation_px']];runner=competitors[0] if competitors else None;margin=best['score']-(runner['score'] if runner else 0);states=full['states'];classes=[n for n,s in states.items() if s=='supported'];walls=sum(n.endswith('wall') for n in classes);edges=sum(n.endswith('edge') for n in classes);corners=sum('left' in n or 'right' in n for n in classes)-walls;safe=(full['contrast']>=cfg['interior_contrast_min'] and best['raw_score']>=cfg['template_score_min'] and margin>=cfg['competitor_margin_min'] and len(classes)>=cfg['minimum_feature_classes'] and walls>=cfg['minimum_walls'] and edges>=cfg['minimum_edges'] and corners>=cfg['minimum_corners'] and full['contradicted']<=cfg['maximum_contradicted_features'] and full['strongest_contradiction']<=cfg['maximum_contradiction_strength'])
 model=Model(best['cx'],best['cy'],w,h,best['raw_score'],full['contrast'],margin,full['strengths'],classes,'partner_predicted_template',full['residuals']);top=[{'x':c['cx'],'y':c['cy'],'dx':c['dx'],'dy':c['dy'],'score':c['score'],'supported':c['evidence']['supported'],'contradicted':c['evidence']['contradicted']} for c in competitors[:5]];detail={'safe':safe,'anchor_type':'partner_predicted_template','candidate_x':best['cx'],'candidate_y':best['cy'],'features':classes,'feature_states':states,'feature_strengths':full['strengths'],'contradiction_strengths':full['contradictions'],'score':best['raw_score'],'contrast':full['contrast'],'margin':margin,'supporting_landmarks':len(classes),'feature_classes':len(classes),'inlier_count':len(classes),'missing_count':full['missing'],'contradicted_count':full['contradicted'],'strongest_contradiction':full['strongest_contradiction'],'residual_median':statistics.median([v for v in full['residuals'].values() if v is not None]),'residual_max':max(v for v in full['residuals'].values() if v is not None),'residuals':full['residuals'],'translation_x':best['dx'],'translation_y':best['dy'],'translation_distance':math.hypot(best['dx'],best['dy']),'search_region':{'x_min':px-radius,'x_max':px+radius,'y_min':py-radius,'y_max':py+radius},'competing_hypotheses':top}
 return (model if safe else None),detail,[]
fit_fixed=fit_template
def evaluate(image,row,capture,cfg):
 rgb=np.asarray(image.convert('RGB'));boxes=any_capture_boxes(capture);holes=[]
 for b in boxes:holes.append((*physical_hole(rgb,b,.25),b))
 if row['physical_pair_found']=='True':return {'classification':'normal_detector_success','accepted':False,'holes':holes}
 good=[z for z in holes if z[0] is not None]
 if len(good)!=1:return {'classification':'both_holes_damaged_ambiguous' if not good else 'capture_prior_roi_incorrect','accepted':False,'holes':holes}
 seed=good[0][0]
 if not(cfg['seed_x_domain'][0]<=seed.cx<=cfg['seed_x_domain'][1]):return {'classification':'capture_prior_roi_incorrect','accepted':False,'holes':holes,'seed':seed}
 upper=seed.cy<rgb.shape[0]/2;px=seed.cx+(cfg['lower_minus_upper_x'] if upper else -cfg['lower_minus_upper_x']);py=seed.cy+(cfg['pitch'] if upper else -cfg['pitch']);model,detail,landmarks=fit_fixed(rgb,(px,py),cfg);eligible_boxes=transform_boxes(capture);partner_box=min(eligible_boxes,key=lambda b:abs(b[1]-py)) if eligible_boxes else None
 if partner_box and model:detail['capture_displacement_x']=model.cx-partner_box[0];detail['capture_displacement_y']=model.cy-partner_box[1];detail['capture_displacement']=math.hypot(model.cx-partner_box[0],model.cy-partner_box[1])
 if model is None:
  if detail.get('reason')=='predicted_roi_out_of_frame':classification='capture_roi_anomaly'
  elif detail.get('contradicted_count',0)>cfg['maximum_contradicted_features'] or detail.get('strongest_contradiction',0)>cfg['maximum_contradiction_strength']:classification='contradictory_physical_evidence'
  elif detail.get('margin',999)<cfg['competitor_margin_min']:classification='ambiguous_competing_template_positions'
  else:classification='insufficient_template_support'
  review_model=Model(detail['candidate_x'],detail['candidate_y'],cfg['hole_width'],cfg['hole_height'],detail['score'],detail['contrast'],detail['margin'],detail.get('feature_strengths',{}),detail.get('features',[]),'rejected_template_candidate',detail.get('residuals',{})) if detail.get('candidate_x') is not None else None
  return {'classification':classification,'accepted':False,'holes':holes,'seed':seed,'seed_is_upper':upper,'prediction':(px,py),'partner_box':partner_box,'review_model':review_model,'detail':detail,'landmarks':landmarks}
 pitch=abs(model.cy-seed.cy);xd=abs((model.cx-seed.cx)-(cfg['lower_minus_upper_x'] if upper else -cfg['lower_minus_upper_x']))
 if abs(pitch-cfg['pitch'])>100 or xd>100:return {'classification':'pair_geometry_failure','accepted':False,'holes':holes,'seed':seed,'model':model,'prediction':(px,py),'partner_box':partner_box,'detail':detail,'landmarks':landmarks}
 return {'classification':'partner_predicted_template_recovery','accepted':True,'holes':holes,'seed':seed,'seed_is_upper':upper,'prediction':(px,py),'partner_box':partner_box,'model':model,'detail':detail,'landmarks':landmarks,'anchor_x':statistics.mean([seed.cx,model.cx])-17.125,'anchor_y':statistics.mean([seed.cy,model.cy])}
def _outline(draw,cx,cy,w,h,color,width=5):draw.rounded_rectangle((cx-w/2,cy-h/2,cx+w/2,cy+h/2),radius=45,outline=color,width=width)
def _feature_overlay(draw,m,name,state):
 color={'supported':'lime','missing':'gray','contradicted':'red'}[state];w=m.width;h=m.height
 if name=='left_wall':draw.line((m.cx-w/2,m.cy-.3*h,m.cx-w/2,m.cy+.3*h),fill=color,width=8)
 elif name=='right_wall':draw.line((m.cx+w/2,m.cy-.3*h,m.cx+w/2,m.cy+.3*h),fill=color,width=8)
 elif name=='top_edge':draw.line((m.cx-.3*w,m.cy-h/2,m.cx+.3*w,m.cy-h/2),fill=color,width=8)
 elif name=='bottom_edge':draw.line((m.cx-.3*w,m.cy+h/2,m.cx+.3*w,m.cy+h/2),fill=color,width=8)
 else:
  box={'upper_left':(m.cx-w/2,m.cy-h/2,m.cx-w/2+.32*w,m.cy-h/2+.4*h),'upper_right':(m.cx+w/2-.32*w,m.cy-h/2,m.cx+w/2,m.cy-h/2+.4*h),'lower_right':(m.cx+w/2-.32*w,m.cy+h/2-.4*h,m.cx+w/2,m.cy+h/2),'lower_left':(m.cx-w/2,m.cy+h/2-.4*h,m.cx-w/2+.32*w,m.cy+h/2)}[name];angles={'upper_left':(180,270),'upper_right':(270,360),'lower_right':(0,90),'lower_left':(90,180)}[name];draw.arc(box,*angles,fill=color,width=8)
def panel(image,row,r,cal):
 c=Image.new('RGB',(1400,850),'#090909');d=ImageDraw.Draw(c);d.text((14,10),f"FRAME {int(row['frame']):06d} {r['classification']}",fill='white');o=image.convert('RGB');od=ImageDraw.Draw(o)
 for z in r.get('holes',[]):
  hole=z[0];b=z[3];px,py,pw,ph=b;od.rectangle((px-pw/2,py-ph/2,px+pw/2,py+ph/2),outline='cyan',width=8)
  if hole:od.rectangle((hole.cx-hole.width/2,hole.cy-hole.height/2,hole.cx+hole.width/2,hole.cy+hole.height/2),outline='lime',width=8)
 pred=r.get('prediction');cfg=json.loads(CONFIG.read_text());w=cfg['hole_width'];h=cfg['hole_height']
 if pred:
  _outline(od,pred[0],pred[1],w,h,'yellow',5);radius=cfg['translation_radius'];od.rectangle((pred[0]-w/2-radius,pred[1]-h/2-radius,pred[0]+w/2+radius,pred[1]+h/2+radius),outline='gold',width=3)
 m=r.get('model') or r.get('review_model')
 if m:
  for comp in r.get('detail',{}).get('competing_hypotheses',[])[:3]:_outline(od,comp['x'],comp['y'],m.width,m.height,'purple',2)
  _outline(od,m.cx,m.cy,m.width,m.height,'magenta',10)
  for name,state in r.get('detail',{}).get('feature_states',{}).items():_feature_overlay(od,m,name,state)
  od.line((m.cx-18,m.cy,m.cx+18,m.cy),fill='magenta',width=5);od.line((m.cx,m.cy-18,m.cx,m.cy+18),fill='magenta',width=5)
 detail=r.get('detail',{});d.text((14,35),f"dx/dy={detail.get('translation_x')}/{detail.get('translation_y')} support/missing/contradicted={detail.get('feature_classes')}/{detail.get('missing_count')}/{detail.get('contradicted_count')} margin={detail.get('margin')}",fill='white');o.thumbnail((650,720),Image.Resampling.LANCZOS);c.paste(o,(10,90));crop=CropGeometry(float(row['hybrid_final_x'])+159,float(row['hybrid_final_y'])-413,1133,900);ctx=registered_frame(image,crop,cal.contrast);ctx.thumbnail((720,650),Image.Resampling.LANCZOS);c.paste(ctx,(670,110));d.text((14,820),'cyan=capture ROI  green=intact/supported  yellow=prediction/search  magenta=winner  purple=runner-up  gray=missing  red=contradicted',fill='white');return c
def make_sheets(paths,out,prefix):
 for page,start in enumerate(range(0,len(paths),48),1):
  items=paths[start:start+48];sheet=Image.new('RGB',(1400,58+math.ceil(len(items)/2)*425),'black');ImageDraw.Draw(sheet).text((14,18),prefix,fill='white')
  for i,p in enumerate(items):
   with Image.open(p) as im:q=im.resize((700,425),Image.Resampling.LANCZOS)
   sheet.paste(q,((i%2)*700,58+(i//2)*425))
  sheet.save(out/f'{prefix}_{page:02d}.jpg',quality=91)
def _summary(values):return {'min':min(values),'median':float(np.median(values)),'p95':float(np.percentile(values,95)),'max':max(values)} if values else {}
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();rows=[r for r in csv.DictReader((BASE/'diagnostics.csv').open()) if r['hybrid_interpolated']=='True'];assert len(rows)==198;by={int(r['frame']):r for r in rows};p03={int(r['frame']):r for r in csv.DictReader((PREVIOUS/'diagnostics.csv').open())};p04={int(r['frame']):r for r in csv.DictReader((P04/'diagnostics.csv').open())};p05={int(r['frame']):r for r in csv.DictReader((P05/'diagnostics.csv').open())};cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);panels=a.output_dir/'panels';panels.mkdir(parents=True,exist_ok=True);results=[]
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
    v.save(panels/f'frame_{n:06d}.jpg',quality=91);detail=r.get('detail',{});results.append({'frame':n,'original_failure_class':original_class(row),'classification':r['classification'],'accepted':r['accepted'],'p03_accepted':p03[n]['accepted'],'p04_accepted':p04[n]['accepted'],'p05_accepted':p05[n]['accepted'],'p05_classification':p05[n]['classification'],'feature_classes_list':';'.join(detail.get('features',[])),'feature_states_json':json.dumps(detail.get('feature_states',{}),sort_keys=True),'feature_strengths_json':json.dumps(detail.get('feature_strengths',{}),sort_keys=True),'contradiction_strengths_json':json.dumps(detail.get('contradiction_strengths',{}),sort_keys=True),'supported_count':detail.get('feature_classes'),'missing_count':detail.get('missing_count'),'contradicted_count':detail.get('contradicted_count'),'strongest_contradiction':detail.get('strongest_contradiction'),'template_score':detail.get('score'),'competitor_margin':detail.get('margin'),'translation_x':detail.get('translation_x'),'translation_y':detail.get('translation_y'),'translation_distance':detail.get('translation_distance'),'capture_displacement_x':detail.get('capture_displacement_x'),'capture_displacement_y':detail.get('capture_displacement_y'),'capture_displacement':detail.get('capture_displacement'),'feature_residuals_json':json.dumps(detail.get('residuals',{}),sort_keys=True),'competing_hypotheses_json':json.dumps(detail.get('competing_hypotheses',[]),sort_keys=True),'model_x':getattr(r.get('model'),'cx',None),'model_y':getattr(r.get('model'),'cy',None),'model_width':getattr(r.get('model'),'width',None),'model_height':getattr(r.get('model'),'height',None),'anchor_x':r.get('anchor_x'),'anchor_y':r.get('anchor_y')})
  finally:shutil.rmtree(tmp)
  print(f'processed {min(start+len(batch),len(dngs))}/{len(dngs)}',flush=True)
 fields=sorted({k for r in results for k in r});a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/'diagnostics.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(results)
 recovered=[r for r in results if r['accepted']];failed=[r for r in results if not r['accepted']];current={r['frame'] for r in recovered};p05set={r['frame'] for r in results if r['p05_accepted']=='True'};new=[r for r in recovered if r['frame'] not in p05set];dropped=[r for r in failed if r['frame'] in p05set]
 def paths(rs):return [panels/f"frame_{r['frame']:06d}.jpg" for r in rs]
 make_sheets(paths(recovered),a.output_dir,'01_all_recoveries');make_sheets(paths(new),a.output_dir,'02_new_p05_failures');make_sheets(paths(dropped),a.output_dir,'03_p05_recoveries_rejected');make_sheets(paths(failed),a.output_dir,'04_remaining_failures');make_sheets(paths(sorted(recovered,key=lambda r:float(r['competitor_margin']))[:25]),a.output_dir,'05_lowest_competitor_margins');make_sheets(paths(sorted([r for r in results if r['translation_distance'] not in (None,'')],key=lambda r:float(r['translation_distance']),reverse=True)[:25]),a.output_dir,'06_largest_translations');make_sheets(paths(sorted([r for r in results if r['strongest_contradiction'] not in (None,'')],key=lambda r:float(r['strongest_contradiction']),reverse=True)[:25]),a.output_dir,'07_strongest_contradictions')
 questionable=[r['frame'] for r in recovered if float(r['competitor_margin'])<.05 or int(r['contradicted_count'])>0 or float(r['translation_distance'])>=.8*cfg['translation_radius']]
 measured=[r for r in results if r['supported_count'] not in (None,'')];report={'frames':198,'recovered':len(recovered),'unresolved':198-len(recovered),'classifications':dict(Counter(r['classification'] for r in results)),'lineage_recoveries':{'p03':sum(r['p03_accepted']=='True' for r in results),'p04':sum(r['p04_accepted']=='True' for r in results),'p05':len(p05set),'p06':len(current)},'comparison_with_p05':{'retained':len(current&p05set),'new':len(current-p05set),'dropped':len(p05set-current),'new_by_p05_classification':dict(Counter(r['p05_classification'] for r in new))},'by_original_failure':{k:sum(r['accepted'] and r['original_failure_class']==k for r in results) for k in sorted(set(r['original_failure_class'] for r in results))},'supported_feature_class_distribution':dict(Counter(int(r['supported_count']) for r in recovered)),'contradiction_distribution_accepted':dict(Counter(int(r['contradicted_count']) for r in recovered)),'contradiction_distribution_all_candidates':dict(Counter(int(r['contradicted_count']) for r in measured)),'competitor_margins':_summary([float(r['competitor_margin']) for r in recovered]),'translation_from_prediction':_summary([float(r['translation_distance']) for r in recovered]),'translation_from_capture':_summary([float(r['capture_displacement']) for r in recovered if r['capture_displacement'] not in (None,'')]),'questionable_review_frames':questionable,'fixed_geometry':{'width':cfg['hole_width'],'height':cfg['hole_height'],'pitch':cfg['pitch'],'lower_minus_upper_x':cfg['lower_minus_upper_x'],'scale_fitted':False,'rotation_fitted':False},'frame_42':next(r for r in results if r['frame']==42),'frame_3341':next(r for r in results if r['frame']==3341),'protected_blind_annotations_used':False};(a.output_dir/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
