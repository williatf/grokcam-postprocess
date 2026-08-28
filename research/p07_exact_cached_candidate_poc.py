#!/usr/bin/env python3
"""Exact P07 variant: memoize only identical pair-candidate computations."""
from __future__ import annotations
import math
import cv2,numpy as np
from research.p07_joint_rigid_sprocket_pair_evidence_poc import _add_grid,_pair_candidate,_upper_from_center

def fit_pair_cached(image,capture_boxes,normal_holes,p06_prior,cfg,metrics=None):
 H,W=image.shape[:2];w,h=cfg['hole_width'],cfg['hole_height'];xmin,xmax=cfg['sprocket_x_domain'];ymin,ymax=cfg['upper_y_domain'];x0=max(0,int(xmin-w/2-40));x1=min(W,int(xmax+w/2+40));y0=max(0,int(ymin-h/2-40));y1=min(H,int(ymax+cfg['pitch']+h/2+40));gray=cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1)
 priors=[]
 for b in capture_boxes:priors.append(_upper_from_center(b[0],b[1],cfg,H))
 for hole in normal_holes:
  if hole is not None:priors.append(_upper_from_center(hole.cx,hole.cy,cfg,H))
 if p06_prior:priors.append(_upper_from_center(p06_prior[0],p06_prior[1],cfg,H))
 cache={};counts={'coarse_candidates':0,'fine_candidates':0,'full_candidates':0,'candidate_cache_hits':0,'candidate_cache_misses':0,'template_evaluations_avoided':0,'percentile_calls_avoided':0}
 def candidate(ux,uy,full=False):
  key=(ux,uy,full)
  if key in cache:
   counts['candidate_cache_hits']+=1;counts['template_evaluations_avoided']+=2;counts['percentile_calls_avoided']+=4;return cache[key].copy()
  counts['candidate_cache_misses']+=1;c=_pair_candidate(gray,sx,sy,ux-x0,uy-y0,cfg,full);c['upper_x']+=x0;c['lower_x']+=x0;c['upper_y']+=y0;c['lower_y']+=y0;cache[key]=c;return c.copy()
 points=set();_add_grid(points,xmin,xmax,ymin,ymax,cfg['coarse_step'],cfg)
 for px,py in priors:_add_grid(points,px-cfg['prior_radius'],px+cfg['prior_radius'],py-cfg['prior_radius'],py+cfg['prior_radius'],cfg['prior_step'],cfg)
 coarse=[];counts['coarse_candidates']=len(points)
 for ux,uy in points:
  c=candidate(ux,uy);prior_dist=min((math.hypot(ux-px,uy-py) for px,py in priors),default=0);c['prior_distance']=prior_dist;c['score']=c['raw_score']-cfg['weak_prior_weight']*min(prior_dist,200)/200;coarse.append(c)
 coarse.sort(key=lambda z:z['score'],reverse=True);refine=set()
 for c in coarse[:cfg['refine_hypotheses']]:_add_grid(refine,c['upper_x']-cfg['refine_radius'],c['upper_x']+cfg['refine_radius'],c['upper_y']-cfg['refine_radius'],c['upper_y']+cfg['refine_radius'],cfg['refine_step'],cfg)
 fine=[];counts['fine_candidates']=len(refine)
 for ux,uy in refine:
  c=candidate(ux,uy);prior_dist=min((math.hypot(ux-px,uy-py) for px,py in priors),default=0);c['prior_distance']=prior_dist;c['score']=c['raw_score']-cfg['weak_prior_weight']*min(prior_dist,200)/200;fine.append(c)
 candidates=sorted(fine or coarse,key=lambda z:z['score'],reverse=True);best0=candidates[0];counts['full_candidates']=1;best=candidate(best0['upper_x'],best0['upper_y'],True);best['prior_distance']=best0['prior_distance'];best['score']=best['raw_score']-cfg['weak_prior_weight']*min(best['prior_distance'],200)/200;competitors=[c for c in candidates[1:] if math.hypot(c['upper_x']-best['upper_x'],c['upper_y']-best['upper_y'])>=cfg['competitor_separation_px']];runner=competitors[0] if competitors else None;margin=best['score']-(runner['score'] if runner else 0);best['margin']=margin;pair_contrast=best['upper']['contrast']+best['lower']['contrast'];weaker=min(best['upper_supported'],best['lower_supported']);safe=(best['score']>=cfg['joint_score_min'] and best['geometric_contribution']>=cfg['geometric_contribution_min'] and best['supported']>=cfg['minimum_total_supported'] and weaker>=cfg['minimum_weaker_hole_supported'] and best['contradicted']<=cfg['maximum_total_contradicted'] and best['strongest_contradiction']<=cfg['maximum_contradiction_strength'] and pair_contrast>=cfg['pair_contrast_min'] and margin>=cfg['competitor_margin_min']);best['safe']=safe;best['pair_contrast']=pair_contrast;best['competitors']=[{'upper_x':c['upper_x'],'upper_y':c['upper_y'],'score':c['score'],'supported':c['supported'],'contradicted':c['contradicted']} for c in competitors[:5]]
 counts['cache_entries']=len(cache);counts['candidate_calls']=counts['coarse_candidates']+counts['fine_candidates']+1;counts['template_evaluations']=2*counts['candidate_cache_misses'];counts['percentile_calls']=4*counts['candidate_cache_misses']+1
 if metrics is not None:metrics.update(counts)
 return best
