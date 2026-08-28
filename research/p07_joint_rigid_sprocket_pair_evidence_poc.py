#!/usr/bin/env python3
"""P07: direct joint evidence for one immutable two-sprocket template."""
from __future__ import annotations
import argparse,csv,json,math,shutil,statistics,sys,tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture,transform_boxes
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p06_partner_predicted_rigid_template_evidence_poc import Model,_feature_overlay,_outline,_template_evidence
from research.render_physical_hole_problem_review import any_capture_boxes,classify as original_class
BASE=ROOT/'research/output/sprocket_xy/physical_hole_capture_prior_poc/Reel_46335'
P03=ROOT/'research/output/sprocket_xy/partner_partial_hole_poc/Reel_46335'
P04=ROOT/'research/output/sprocket_xy/calibrated_geometry_partial_hole_poc/Reel_46335'
P05=ROOT/'research/output/sprocket_xy/rigid_consensus_partial_hole_poc/Reel_46335'
P06=ROOT/'research/output/sprocket_xy/partner_predicted_rigid_template_evidence_poc/Reel_46335'
CONFIG=ROOT/'research/p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json'
DEFAULT_OUTPUT=ROOT/'research/output/sprocket_xy/joint_rigid_sprocket_pair_evidence_poc/Reel_46335'

def _features(ev,state='supported'):return [k for k,v in ev['states'].items() if v==state]
def _axis_classes(names):
 x=any(n.endswith('wall') or n in ('upper_left','upper_right','lower_left','lower_right') for n in names);y=any(n.endswith('edge') or n in ('upper_left','upper_right','lower_left','lower_right') for n in names);return int(x)+int(y)
def _prefer_direct_support(ev,cfg):
 """A nearby parallel edge cannot contradict an already-supported boundary."""
 old_penalty=sum(ev['contradictions'][n] for n,s in ev['states'].items() if s=='contradicted')
 for name,state in list(ev['states'].items()):
  threshold=cfg['corner_threshold'] if name in ('upper_left','upper_right','lower_left','lower_right') else cfg['feature_threshold']
  if state=='contradicted' and ev['strengths'][name]>=threshold:ev['states'][name]='supported'
  elif state=='contradicted' and ev['residuals'].get(name) not in (None,0):ev['states'][name]='missing'
 ev['supported']=sum(s=='supported' for s in ev['states'].values());ev['missing']=sum(s=='missing' for s in ev['states'].values());ev['contradicted']=sum(s=='contradicted' for s in ev['states'].values());new_penalty=sum(ev['contradictions'][n] for n,s in ev['states'].items() if s=='contradicted');ev['score']+=.8*(old_penalty-new_penalty);ev['strongest_contradiction']=max((ev['contradictions'][n] for n,s in ev['states'].items() if s=='contradicted'),default=0.);return ev
def _pair_candidate(gray,sx,sy,ux,uy,cfg,full=False):
 w,h=cfg['hole_width'],cfg['hole_height'];lx=ux+cfg['lower_minus_upper_x'];ly=uy+cfg['pitch'];upper=_prefer_direct_support(_template_evidence(gray,sx,sy,ux,uy,w,h,cfg,full),cfg);lower=_prefer_direct_support(_template_evidence(gray,sx,sy,lx,ly,w,h,cfg,full),cfg);us=_features(upper);ls=_features(lower);supported=len(us)+len(ls);contradicted=upper['contradicted']+lower['contradicted'];independent_log_support=sum(-math.log(max(.04,1-upper['strengths'][n])) for n in us)+sum(-math.log(max(.04,1-lower['strengths'][n])) for n in ls);distribution=min(len(us),len(ls))/4+(_axis_classes(us)+_axis_classes(ls))/8;straight_residuals=[v for ev in (upper,lower) for k,v in ev['residuals'].items() if v is not None and k in _features(ev) and (k.endswith('wall') or k.endswith('edge'))];median_residual=statistics.median(straight_residuals) if straight_residuals else 999.;geometric=max(0.,1-median_residual/max(cfg['strong_feature_alignment_px']*2,1))*distribution+.08*independent_log_support;penalty=.8*sum(ev['contradictions'][n] for ev in (upper,lower) for n,s in ev['states'].items() if s=='contradicted');score=upper['score']+lower['score']+.35*geometric-penalty
 return {'upper_x':ux,'upper_y':uy,'lower_x':lx,'lower_y':ly,'upper':upper,'lower':lower,'upper_score':upper['score'],'lower_score':lower['score'],'supported':supported,'upper_supported':len(us),'lower_supported':len(ls),'contradicted':contradicted,'missing':upper['missing']+lower['missing'],'strongest_contradiction':max(upper['strongest_contradiction'],lower['strongest_contradiction']),'geometric_contribution':geometric,'geometric_residual':median_residual,'contradiction_penalty':penalty,'raw_score':score}
def _add_grid(points,cx0,cx1,cy0,cy1,step,cfg):
 xmin,xmax=cfg['sprocket_x_domain'];ymin,ymax=cfg['upper_y_domain'];a=max(xmin,cx0);b=min(xmax,cx1);c=max(ymin,cy0);d=min(ymax,cy1)
 for y in np.arange(c,d+.1,step):
  for x in np.arange(a,b+.1,step):points.add((round(float(x),3),round(float(y),3)))
def _upper_from_center(x,y,cfg,image_h):return (x,y) if y<image_h/2 else (x-cfg['lower_minus_upper_x'],y-cfg['pitch'])
def fit_pair(image,capture_boxes,normal_holes,p06_prior,cfg):
 H,W=image.shape[:2];w,h=cfg['hole_width'],cfg['hole_height'];xmin,xmax=cfg['sprocket_x_domain'];ymin,ymax=cfg['upper_y_domain'];x0=max(0,int(xmin-w/2-40));x1=min(W,int(xmax+w/2+40));y0=max(0,int(ymin-h/2-40));y1=min(H,int(ymax+cfg['pitch']+h/2+40));gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1)
 priors=[]
 for b in capture_boxes:priors.append(_upper_from_center(b[0],b[1],cfg,H))
 for hole in normal_holes:
  if hole is not None:priors.append(_upper_from_center(hole.cx,hole.cy,cfg,H))
 if p06_prior:priors.append(_upper_from_center(p06_prior[0],p06_prior[1],cfg,H))
 points=set();_add_grid(points,xmin,xmax,ymin,ymax,cfg['coarse_step'],cfg)
 for px,py in priors:_add_grid(points,px-cfg['prior_radius'],px+cfg['prior_radius'],py-cfg['prior_radius'],py+cfg['prior_radius'],cfg['prior_step'],cfg)
 coarse=[]
 for ux,uy in points:
  c=_pair_candidate(gray,sx,sy,ux-x0,uy-y0,cfg);c['upper_x']+=x0;c['lower_x']+=x0;c['upper_y']+=y0;c['lower_y']+=y0;prior_dist=min((math.hypot(ux-px,uy-py) for px,py in priors),default=0);c['prior_distance']=prior_dist;c['score']=c['raw_score']-cfg['weak_prior_weight']*min(prior_dist,200)/200;coarse.append(c)
 coarse.sort(key=lambda z:z['score'],reverse=True);refine=set()
 for c in coarse[:cfg['refine_hypotheses']]:_add_grid(refine,c['upper_x']-cfg['refine_radius'],c['upper_x']+cfg['refine_radius'],c['upper_y']-cfg['refine_radius'],c['upper_y']+cfg['refine_radius'],cfg['refine_step'],cfg)
 fine=[]
 for ux,uy in refine:
  c=_pair_candidate(gray,sx,sy,ux-x0,uy-y0,cfg);c['upper_x']+=x0;c['lower_x']+=x0;c['upper_y']+=y0;c['lower_y']+=y0;prior_dist=min((math.hypot(ux-px,uy-py) for px,py in priors),default=0);c['prior_distance']=prior_dist;c['score']=c['raw_score']-cfg['weak_prior_weight']*min(prior_dist,200)/200;fine.append(c)
 candidates=sorted(fine or coarse,key=lambda z:z['score'],reverse=True);best0=candidates[0];best=_pair_candidate(gray,sx,sy,best0['upper_x']-x0,best0['upper_y']-y0,cfg,True);best['upper_x']+=x0;best['lower_x']+=x0;best['upper_y']+=y0;best['lower_y']+=y0;best['prior_distance']=best0['prior_distance'];best['score']=best['raw_score']-cfg['weak_prior_weight']*min(best['prior_distance'],200)/200;competitors=[c for c in candidates[1:] if math.hypot(c['upper_x']-best['upper_x'],c['upper_y']-best['upper_y'])>=cfg['competitor_separation_px']];runner=competitors[0] if competitors else None;margin=best['score']-(runner['score'] if runner else 0);best['margin']=margin;pair_contrast=best['upper']['contrast']+best['lower']['contrast'];weaker=min(best['upper_supported'],best['lower_supported']);safe=(best['score']>=cfg['joint_score_min'] and best['geometric_contribution']>=cfg['geometric_contribution_min'] and best['supported']>=cfg['minimum_total_supported'] and weaker>=cfg['minimum_weaker_hole_supported'] and best['contradicted']<=cfg['maximum_total_contradicted'] and best['strongest_contradiction']<=cfg['maximum_contradiction_strength'] and pair_contrast>=cfg['pair_contrast_min'] and margin>=cfg['competitor_margin_min']);best['safe']=safe;best['pair_contrast']=pair_contrast;best['competitors']=[{'upper_x':c['upper_x'],'upper_y':c['upper_y'],'score':c['score'],'supported':c['supported'],'contradicted':c['contradicted']} for c in competitors[:5]];return best
def _capture_distance(best,boxes):
 if len(boxes)<2:return None
 ordered=sorted(boxes,key=lambda b:b[1]);return math.hypot(best['upper_x']-ordered[0][0],best['upper_y']-ordered[0][1])+math.hypot(best['lower_x']-ordered[-1][0],best['lower_y']-ordered[-1][1])
def evaluate(image,row,capture,p06row,cfg):
 rgb=np.asarray(image.convert('RGB'));boxes=any_capture_boxes(capture);eligible=transform_boxes(capture) or [];holes=[]
 for b in boxes:holes.append(physical_hole(rgb,b,.25)[0])
 p06prior=(float(p06row['model_x']),float(p06row['model_y'])) if p06row.get('model_x') not in (None,'') else None;best=fit_pair(rgb,boxes,holes,p06prior,cfg);capture_distance=_capture_distance(best,eligible);p06_distance=math.hypot(best['upper_x']-p06prior[0],best['upper_y']-p06prior[1]) if p06prior and p06prior[1]<rgb.shape[0]/2 else math.hypot(best['lower_x']-p06prior[0],best['lower_y']-p06prior[1]) if p06prior else None
 if best['safe']:classification='joint_pair_recovery'
 elif best['margin']<cfg['competitor_margin_min']:classification='ambiguous_competing_pair_positions'
 elif best['contradicted']>cfg['maximum_total_contradicted'] or best['strongest_contradiction']>cfg['maximum_contradiction_strength']:classification='contradictory_pair_evidence'
 elif min(best['upper_supported'],best['lower_supported'])<cfg['minimum_weaker_hole_supported']:classification='insufficient_cross_hole_distribution'
 elif best['supported']<cfg['minimum_total_supported'] or best['score']<cfg['joint_score_min']:classification='insufficient_joint_support'
 else:classification='geometric_consistency_failure'
 anchor_x=statistics.mean([best['upper_x'],best['lower_x']])-17.125 if best['safe'] else None;anchor_y=statistics.mean([best['upper_y'],best['lower_y']]) if best['safe'] else None
 return {'classification':classification,'accepted':best['safe'],'best':best,'boxes':boxes,'holes':holes,'normal_detected_count':sum(h is not None for h in holes),'capture_distance':capture_distance,'p06_distance':p06_distance,'anchor_x':anchor_x,'anchor_y':anchor_y}
def _draw_pair(draw,best,cfg,accepted):
 w,h=cfg['hole_width'],cfg['hole_height'];color='magenta' if accepted else 'deeppink'
 for key in ('upper','lower'):
  cx=best[f'{key}_x'];cy=best[f'{key}_y'];m=Model(cx,cy,w,h,0,0,0,{},[],key,{});_outline(draw,cx,cy,w,h,color,8)
  for name,state in best[key]['states'].items():_feature_overlay(draw,m,name,state)
 for c in best['competitors'][:3]:
  _outline(draw,c['upper_x'],c['upper_y'],w,h,'purple',2);_outline(draw,c['upper_x']+cfg['lower_minus_upper_x'],c['upper_y']+cfg['pitch'],w,h,'purple',2)
def panel(image,row,r,cal,cfg):
 canvas=Image.new('RGB',(1400,850),'#090909');d=ImageDraw.Draw(canvas);best=r['best'];d.text((14,10),f"FRAME {int(row['frame']):06d} {r['classification']}",fill='white');d.text((14,34),f"upper/lower support={best['upper_supported']}/{best['lower_supported']} contradicted={best['contradicted']} score={best['score']:.3f} margin={best['margin']:.3f} residual={best['geometric_residual']:.1f}",fill='white');o=image.convert('RGB');od=ImageDraw.Draw(o)
 for b,hole in zip(r['boxes'],r['holes']):
  x,y,w,h=b;od.rectangle((x-w/2,y-h/2,x+w/2,y+h/2),outline='cyan',width=6)
  if hole:od.rectangle((hole.cx-hole.width/2,hole.cy-hole.height/2,hole.cx+hole.width/2,hole.cy+hole.height/2),outline='yellow',width=6)
 _draw_pair(od,best,cfg,r['accepted']);o.thumbnail((650,720),Image.Resampling.LANCZOS);canvas.paste(o,(10,90));crop=CropGeometry(float(row['hybrid_final_x'])+159,float(row['hybrid_final_y'])-413,1133,900);ctx=registered_frame(image,crop,cal.contrast);ctx.thumbnail((720,650),Image.Resampling.LANCZOS);canvas.paste(ctx,(670,110));d.text((14,820),'cyan=capture  yellow=normal detector  green=observed support  gray=inferred/missing  red=contradicted  magenta=winner  purple=competitors',fill='white');return canvas
def make_sheets(paths,out,prefix):
 for page,start in enumerate(range(0,len(paths),48),1):
  items=paths[start:start+48]
  if not items:continue
  sheet=Image.new('RGB',(1400,58+math.ceil(len(items)/2)*425),'black');ImageDraw.Draw(sheet).text((14,18),prefix,fill='white')
  for i,p in enumerate(items):
   with Image.open(p) as im:q=im.resize((700,425),Image.Resampling.LANCZOS)
   sheet.paste(q,((i%2)*700,58+(i//2)*425))
  sheet.save(out/f'{prefix}_{page:02d}.jpg',quality=91)
def _summary(v):return {'min':min(v),'median':float(np.median(v)),'p95':float(np.percentile(v,95)),'max':max(v)} if v else {}
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();rows=[r for r in csv.DictReader((BASE/'diagnostics.csv').open()) if r['hybrid_interpolated']=='True'];assert len(rows)==198;by={int(r['frame']):r for r in rows};prior={name:{int(r['frame']):r for r in csv.DictReader((path/'diagnostics.csv').open())} for name,path in [('p03',P03),('p04',P04),('p05',P05),('p06',P06)]};cfg=json.loads(CONFIG.read_text());spec=REELS['Reel_46335'];capture=load_capture(spec['project']);cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);panels=a.output_dir/'panels';panels.mkdir(parents=True,exist_ok=True);results=[];dngs=[spec['project']/'raw'/f"frame_{n:06d}.dng" for n in sorted(by)]
 for start in range(0,len(dngs),24):
  batch=dngs[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='p07_pair_',dir=ROOT/'work'))
  try:
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs={pool.submit(dev.develop,d,tmp/f'{d.stem}.tif'):d for d in batch}
    for f in as_completed(fs):f.result()
   def process(dng):
    n=int(dng.stem.rsplit('_',1)[1]);row=by[n]
    with Image.open(tmp/f'{dng.stem}.tif') as im:r=evaluate(im,row,capture[n],prior['p06'][n],cfg);panel(im,row,r,cal,cfg).save(panels/f'frame_{n:06d}.jpg',quality=91)
    return n,row,r
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:processed=[f.result() for f in as_completed([pool.submit(process,d) for d in batch])]
   for n,row,r in processed:
    b=r['best'];results.append({'frame':n,'classification':r['classification'],'accepted':r['accepted'],'original_failure_class':original_class(row),'normal_detector_count':r['normal_detected_count'],'p03_accepted':prior['p03'][n]['accepted'],'p04_accepted':prior['p04'][n]['accepted'],'p05_accepted':prior['p05'][n]['accepted'],'p06_accepted':prior['p06'][n]['accepted'],'p06_classification':prior['p06'][n]['classification'],'upper_x':b['upper_x'],'upper_y':b['upper_y'],'lower_x':b['lower_x'],'lower_y':b['lower_y'],'fixed_width':cfg['hole_width'],'fixed_height':cfg['hole_height'],'fixed_pitch':cfg['pitch'],'fixed_x_offset':cfg['lower_minus_upper_x'],'upper_states_json':json.dumps(b['upper']['states'],sort_keys=True),'lower_states_json':json.dumps(b['lower']['states'],sort_keys=True),'upper_strengths_json':json.dumps(b['upper']['strengths'],sort_keys=True),'lower_strengths_json':json.dumps(b['lower']['strengths'],sort_keys=True),'upper_residuals_json':json.dumps(b['upper']['residuals'],sort_keys=True),'lower_residuals_json':json.dumps(b['lower']['residuals'],sort_keys=True),'upper_supported':b['upper_supported'],'lower_supported':b['lower_supported'],'total_supported':b['supported'],'missing_count':b['missing'],'contradicted_count':b['contradicted'],'strongest_contradiction':b['strongest_contradiction'],'upper_score':b['upper_score'],'lower_score':b['lower_score'],'geometric_contribution':b['geometric_contribution'],'geometric_residual':b['geometric_residual'],'joint_score':b['score'],'contradiction_penalty':b['contradiction_penalty'],'competitor_score':b['score']-b['margin'],'competitor_margin':b['margin'],'competitors_json':json.dumps(b['competitors'],sort_keys=True),'capture_pair_distance':r['capture_distance'],'p06_distance':r['p06_distance'],'final_anchor_x':r['anchor_x'],'final_anchor_y':r['anchor_y']})
  finally:shutil.rmtree(tmp)
  print(f'processed {min(start+len(batch),len(dngs))}/{len(dngs)}',flush=True)
 results.sort(key=lambda r:r['frame'])
 a.output_dir.mkdir(parents=True,exist_ok=True);fields=sorted({k for r in results for k in r});
 with (a.output_dir/'diagnostics.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(results)
 (a.output_dir/'diagnostics.json').write_text(json.dumps(results,indent=2)+'\n');accepted=[r for r in results if r['accepted']];failed=[r for r in results if not r['accepted']];current={r['frame'] for r in accepted};p06set={r['frame'] for r in results if r['p06_accepted']=='True'};new=[r for r in accepted if r['frame'] not in p06set];dropped=[r for r in failed if r['frame'] in p06set];no_seed=[r for r in accepted if int(r['normal_detector_count'])==0];both=[r for r in results if r['p06_classification']=='both_holes_damaged_ambiguous'];path=lambda rs:[panels/f"frame_{r['frame']:06d}.jpg" for r in rs]
 make_sheets(path(accepted),a.output_dir,'01_all_recoveries');make_sheets(path(new),a.output_dir,'02_new_vs_p06');make_sheets(path(dropped),a.output_dir,'03_p06_dropped');make_sheets(path(failed),a.output_dir,'04_remaining_failures');make_sheets(path(both),a.output_dir,'05_both_damaged_or_bridged');make_sheets(path(sorted(accepted,key=lambda r:float(r['competitor_margin']))[:25]),a.output_dir,'06_lowest_margins');make_sheets(path(sorted([r for r in results if r['capture_pair_distance'] not in (None,'') or r['p06_distance'] not in (None,'')],key=lambda r:max(float(r['capture_pair_distance'] or 0),float(r['p06_distance'] or 0)),reverse=True)[:25]),a.output_dir,'07_largest_prior_translation');make_sheets(path(sorted(results,key=lambda r:float(r['strongest_contradiction']),reverse=True)[:25]),a.output_dir,'08_strongest_contradictions');make_sheets(path(sorted(accepted,key=lambda r:float(r['joint_score']))[:25]),a.output_dir,'09_weakest_accepted');make_sheets(path(no_seed),a.output_dir,'10_no_normal_seed')
 review=[r['frame'] for r in accepted if float(r['competitor_margin'])<.2 or float(r['geometric_residual'])>10 or int(r['contradicted_count'])>0 or int(r['normal_detector_count'])==0];report={'frames':198,'recoveries':len(accepted),'unresolved':len(failed),'lineage_recoveries':{k:sum(r[f'{k}_accepted']=='True' for r in results) for k in ('p03','p04','p05','p06')}|{'p07':len(accepted)},'comparison_with_p06':{'retained':len(current&p06set),'new':len(current-p06set),'dropped':len(p06set-current),'new_by_p06_classification':dict(Counter(r['p06_classification'] for r in new))},'recovery_by_original_failure':dict(Counter(r['original_failure_class'] for r in accepted)),'recovery_by_p06_failure_class':dict(Counter(r['p06_classification'] for r in new)),'recovered_without_normal_seed':len(no_seed),'evidence_distribution':dict(Counter(f"{r['upper_supported']}+{r['lower_supported']}" for r in accepted)),'competitor_margin':_summary([float(r['competitor_margin']) for r in accepted]),'geometric_residual':_summary([float(r['geometric_residual']) for r in accepted]),'contradiction_distribution':dict(Counter(int(r['contradicted_count']) for r in accepted)),'capture_distance':_summary([float(r['capture_pair_distance']) for r in accepted if r['capture_pair_distance'] not in (None,'')]),'p06_distance':_summary([float(r['p06_distance']) for r in accepted if r['p06_distance'] not in (None,'')]),'classifications':dict(Counter(r['classification'] for r in results)),'review_queue':review,'frame_42':next(r for r in results if r['frame']==42),'frame_3341':next(r for r in results if r['frame']==3341),'protected_blind_annotations_used':False};(a.output_dir/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
