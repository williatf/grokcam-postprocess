"""Frozen production port of the validated P07 rigid sprocket-pair detector.

Source P07 implementation SHA-256: d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d
Source P07 configuration SHA-256: 334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6
Source exact-cache implementation SHA-256: 459093853b1f4fb5843849ffd034d31984a89f554a0535b190ccbf4253d3899c

Detector version: physical-p07-v1. Geometry, scoring, physical-evidence,
search, percentile, ordering, and competitor semantics are frozen. The only
optimization is invocation-local memoization of identical candidate requests.
"""
from __future__ import annotations

import math
import statistics
import json
import glob
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

DETECTOR_MODE = "physical-p07-v1"
P07_IMPLEMENTATION_SHA256 = "d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d"
P07_CONFIGURATION_SHA256 = "334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6"
EXACT_CACHE_IMPLEMENTATION_SHA256 = "459093853b1f4fb5843849ffd034d31984a89f554a0535b190ccbf4253d3899c"

FROZEN_CONFIG = {
    "hole_width": 381.5842105263158, "hole_height": 272.0, "pitch": 785.0,
    "lower_minus_upper_x": 18.678947368421063,
    "feature_threshold": .34, "corner_threshold": .25,
    "feature_residual_search": 24, "strong_feature_threshold": .45,
    "strong_feature_alignment_px": 10, "sprocket_x_domain": (100., 570.),
    "upper_y_domain": (150., 650.), "coarse_step": 16,
    "prior_radius": 64, "prior_step": 8, "refine_radius": 16,
    "refine_step": 4, "refine_hypotheses": 20,
    "competitor_separation_px": 16., "competitor_margin_min": .10,
    "weak_prior_weight": .02, "joint_score_min": 5.2,
    "geometric_contribution_min": .45, "minimum_total_supported": 8,
    "minimum_weaker_hole_supported": 2, "maximum_total_contradicted": 2,
    "maximum_contradiction_strength": .75, "pair_contrast_min": 20.,
}


@dataclass(frozen=True)
class PhysicalPairResult:
    accepted: bool
    classification: str
    anchor_x: float | None
    anchor_y: float | None
    diagnostics: dict


@dataclass(frozen=True)
class PhysicalHole:
    cx: float; cy: float; width: float; height: float
    contour_area: float; fill: float; solidity: float
    distance: float; method: str; score: float


def load_capture_metadata(raw_dir) -> dict[int, dict]:
    """Load optional capture JSONL by exact frame number from project/debug."""
    result = {}
    for name in sorted(glob.glob(str(raw_dir.parent / "debug/raw_capture_metadata_*.jsonl"))):
        with open(name, encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if "frame_number" not in item: continue
                number = int(item["frame_number"])
                if number in result: raise RuntimeError(f"duplicate capture metadata for frame {number}")
                result[number] = item
    return result


def capture_boxes(item):
    if not item or item.get("raw_registration_mode") != "pair" or item.get("selected_source") != "pair_actual": return []
    sprockets=item.get("sprockets") or []
    if len(sprockets)<2:return []
    pair=sorted(sprockets,key=lambda v:float(v[1]))[:2]
    sx=float(item["raw_width"])/float(item["preview_width"]);sy=float(item["raw_height"])/float(item["preview_height"])
    return [(float(v[0])*sx,float(v[1])*sy,float(v[2])*sx,float(v[3])*sy) for v in pair]


def _physical_hole(rgb, prediction, margin=.25):
    px,py,pw,ph=prediction;H,W=rgb.shape[:2];x0=max(0,int(math.floor(px-pw*(.5+margin))));x1=min(W,int(math.ceil(px+pw*(.5+margin))));y0=max(0,int(math.floor(py-ph*(.5+margin))));y1=min(H,int(math.ceil(py+ph*(.5+margin))) )
    if x1-x0<16 or y1-y0<16:return None,"empty_roi"
    gray=cv2.cvtColor(rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY);p40=float(np.percentile(gray,40));p995=float(np.percentile(gray,99.5));contrast=p995-p40
    if contrast<10:return None,"threshold_brightness"
    local=int(max(80,min(250,p40+.58*contrast)));_,relative=cv2.threshold(gray,local,255,cv2.THRESH_BINARY);blur=cv2.GaussianBlur(gray,(5,5),0);adaptive=cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,41,7);_,otsu=cv2.threshold(blur,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    candidates=[];reasons=[]
    for method,mask in (("relative",relative),("adaptive_otsu",cv2.bitwise_and(adaptive,otsu))):
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8));mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8));left=max(0,int(round(px-x0-.62*pw)));right=min(mask.shape[1],int(round(px-x0+.62*pw)));mask[:,:left]=0;mask[:,right:]=0
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area=float(cv2.contourArea(contour));x,y,w,h=cv2.boundingRect(contour)
            if area<=0 or w<.50*pw or w>1.35*pw or h<.50*ph or h>1.55*ph or not .9<=w/float(h)<=2.5:reasons.append("size_shape");continue
            fill=area/float(w*h);hull_area=float(cv2.contourArea(cv2.convexHull(contour)));solidity=area/hull_area if hull_area else 0
            if fill<.52:reasons.append("fill");continue
            if solidity<.78:reasons.append("solidity");continue
            if x<=1 or x+w>=mask.shape[1]-1 or (y<=1 and y+h>=mask.shape[0]-1):reasons.append("roi_edge_escape");continue
            cx=x0+x+w/2;cy=y0+y+h/2;distance=math.hypot((cx-px)/max(pw,1),(cy-py)/max(ph,1))
            if distance>.70:reasons.append("distance");continue
            score=abs(w-pw)/pw+abs(h-ph)/ph+.8*distance+.5*(1-fill)+.5*(1-solidity);candidates.append(PhysicalHole(cx,cy,float(w),float(h),area,fill,solidity,distance,method,score))
    candidates.sort(key=lambda c:c.score);unique=[]
    for candidate in candidates:
        if not any(math.hypot(candidate.cx-other.cx,candidate.cy-other.cy)<.2*max(pw,ph) for other in unique):unique.append(candidate)
    if not unique:return None,reasons[0] if reasons else "no_component"
    if len(unique)>1 and unique[1].score<=unique[0].score*1.15+.03:return None,"ambiguous_structure"
    return unique[0],"success"


def _p06_fit(rgb, prediction):
    """Frozen P06 translation search for a partner predicted from an intact hole."""
    cfg={**FROZEN_CONFIG,"translation_radius":48,"translation_step":4,"prediction_distance_weight":.03,
         "interior_contrast_min":12.,"template_score_min":1.4,"minimum_feature_classes":4,
         "minimum_walls":1,"minimum_edges":1,"minimum_corners":1,"maximum_contradicted_features":1,
         "competitor_separation_px":12.,"competitor_margin_min":.025}
    px,py=prediction;w,h=cfg["hole_width"],cfg["hole_height"];pad=cfg["translation_radius"]+cfg["feature_residual_search"]+8;H,W=rgb.shape[:2];x0=max(0,int(px-w/2-pad));x1=min(W,int(px+w/2+pad));y0=max(0,int(py-h/2-pad));y1=min(H,int(py+h/2+pad))
    if x1-x0<w or y1-y0<h:return None,{"classification":"predicted_roi_out_of_frame"}
    gray=cv2.cvtColor(rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32);blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3);norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1);candidates=[]
    for dy in range(-48,49,4):
        for dx in range(-48,49,4):
            ev=_template_evidence(gray,sx,sy,px-x0+dx,py-y0+dy,w,h,cfg);score=ev["score"]-.03*math.hypot(dx,dy)/48;candidates.append({"cx":px+dx,"cy":py+dy,"dx":dx,"dy":dy,"score":score,"evidence":ev})
    candidates.sort(key=lambda z:z["score"],reverse=True);best=candidates[0];full=_template_evidence(gray,sx,sy,best["cx"]-x0,best["cy"]-y0,w,h,cfg,True);raw=full["score"];score=raw-.03*math.hypot(best["dx"],best["dy"])/48;competitors=[c for c in candidates[1:] if math.hypot(c["dx"]-best["dx"],c["dy"]-best["dy"])>=12];margin=score-(competitors[0]["score"] if competitors else 0);names=_features(full);walls=sum(n.endswith("wall") for n in names);edges=sum(n.endswith("edge") for n in names);corners=sum(n in ("upper_left","upper_right","lower_left","lower_right") for n in names)
    safe=(full["contrast"]>=12 and raw>=1.4 and margin>=.025 and len(names)>=4 and walls>=1 and edges>=1 and corners>=1 and full["contradicted"]<=1 and full["strongest_contradiction"]<=.75)
    return ((best["cx"],best["cy"]) if safe else None),{"safe":safe,"candidate":[best["cx"],best["cy"]],"states":full["states"],"score":raw,"margin":margin,"contradicted":full["contradicted"]}


def _sample(a, xs, ys):
    xi = np.clip(np.rint(xs).astype(int), 0, a.shape[1] - 1)
    yi = np.clip(np.rint(ys).astype(int), 0, a.shape[0] - 1)
    return a[yi, xi]


def _coherent_strength(values):
    values = np.asarray(values)
    return float(.55 * np.mean(np.clip(values, 0, 1)) + .45 * np.mean(values > .18))


def _line_strength(sx, sy, cx, cy, w, h, name, offset=0):
    if name in ("left_wall", "right_wall"):
        x = cx + (-w / 2 if name == "left_wall" else w / 2) + offset
        ys = np.linspace(cy - .30 * h, cy + .30 * h, 31)
        signed = _sample(sx, np.full_like(ys, x), ys) * (1 if name == "left_wall" else -1)
    else:
        y = cy + (-h / 2 if name == "top_edge" else h / 2) + offset
        xs = np.linspace(cx - .30 * w, cx + .30 * w, 41)
        signed = _sample(sy, xs, np.full_like(xs, y)) * (1 if name == "top_edge" else -1)
    return _coherent_strength(signed), _coherent_strength(-signed)


def _corner_strength(sx, sy, cx, cy, w, h, name):
    rx, ry = .16 * w, .20 * h
    angles = {"upper_left": np.linspace(math.pi, 1.5 * math.pi, 13),
              "upper_right": np.linspace(1.5 * math.pi, 2 * math.pi, 13),
              "lower_right": np.linspace(0, .5 * math.pi, 13),
              "lower_left": np.linspace(.5 * math.pi, math.pi, 13)}[name]
    ox, oy = {"upper_left": (cx-w/2+rx, cy-h/2+ry),
              "upper_right": (cx+w/2-rx, cy-h/2+ry),
              "lower_right": (cx+w/2-rx, cy+h/2-ry),
              "lower_left": (cx-w/2+rx, cy+h/2-ry)}[name]
    xs, ys = ox + rx*np.cos(angles), oy + ry*np.sin(angles)
    signed = _sample(sx, xs, ys)*-np.cos(angles) + _sample(sy, xs, ys)*-np.sin(angles)
    return _coherent_strength(signed), _coherent_strength(-signed)


def _template_evidence(gray, sx, sy, cx, cy, w, h, cfg, full=False):
    states, strengths, contradictions, residuals = {}, {}, {}, {}
    for name in ("left_wall", "right_wall", "top_edge", "bottom_edge"):
        support, opposite = _line_strength(sx, sy, cx, cy, w, h, name)
        best = (support, 0)
        if full:
            for off in range(-cfg["feature_residual_search"], cfg["feature_residual_search"] + 1, 2):
                value, _ = _line_strength(sx, sy, cx, cy, w, h, name, off)
                if value > best[0]: best = (value, off)
        displaced = full and best[0] >= cfg["strong_feature_threshold"] and abs(best[1]) > cfg["strong_feature_alignment_px"]
        contradiction = max(opposite, best[0] if displaced else 0)
        state = "supported" if support >= cfg["feature_threshold"] and not displaced else "contradicted" if contradiction >= cfg["feature_threshold"] else "missing"
        states[name], strengths[name], contradictions[name], residuals[name] = state, support, contradiction, abs(best[1])
    for name in ("upper_left", "upper_right", "lower_right", "lower_left"):
        support, opposite = _corner_strength(sx, sy, cx, cy, w, h, name)
        state = "supported" if support >= cfg["corner_threshold"] else "contradicted" if opposite >= cfg["corner_threshold"] else "missing"
        states[name], strengths[name], contradictions[name] = state, support, opposite
        residuals[name] = 0 if state == "supported" else None
    inside = gray[max(0,int(cy-.28*h)):min(gray.shape[0],int(cy+.28*h)), max(0,int(cx-.28*w)):min(gray.shape[1],int(cx+.28*w))]
    outer = gray[max(0,int(cy-.70*h)):min(gray.shape[0],int(cy+.70*h)), max(0,int(cx-.70*w)):min(gray.shape[1],int(cx+.70*w))]
    contrast = float(np.percentile(inside, 60)-np.percentile(outer, 30)) if inside.size and outer.size else 0
    majors = sum(strengths[n] for n in ("left_wall", "right_wall", "top_edge", "bottom_edge"))
    corners = sorted((strengths[n] for n in ("upper_left", "upper_right", "lower_right", "lower_left")), reverse=True)
    penalty = sum(contradictions[n] for n, state in states.items() if state == "contradicted")
    score = majors + .6*sum(corners[:2]) + min(max(contrast, 0)/80, .25) - .8*penalty
    return {"states": states, "strengths": strengths, "contradictions": contradictions,
            "residuals": residuals, "contrast": contrast, "score": score,
            "supported": sum(s == "supported" for s in states.values()),
            "missing": sum(s == "missing" for s in states.values()),
            "contradicted": sum(s == "contradicted" for s in states.values()),
            "strongest_contradiction": max(contradictions.values())}


def _features(ev, state="supported"):
    return [key for key, value in ev["states"].items() if value == state]


def _axis_classes(names):
    x = any(n.endswith("wall") or n in ("upper_left","upper_right","lower_left","lower_right") for n in names)
    y = any(n.endswith("edge") or n in ("upper_left","upper_right","lower_left","lower_right") for n in names)
    return int(x) + int(y)


def _prefer_direct_support(ev, cfg):
    old = sum(ev["contradictions"][n] for n,s in ev["states"].items() if s == "contradicted")
    for name, state in list(ev["states"].items()):
        threshold = cfg["corner_threshold"] if name in ("upper_left","upper_right","lower_left","lower_right") else cfg["feature_threshold"]
        if state == "contradicted" and ev["strengths"][name] >= threshold: ev["states"][name] = "supported"
        elif state == "contradicted" and ev["residuals"].get(name) not in (None, 0): ev["states"][name] = "missing"
    ev["supported"] = sum(s == "supported" for s in ev["states"].values())
    ev["missing"] = sum(s == "missing" for s in ev["states"].values())
    ev["contradicted"] = sum(s == "contradicted" for s in ev["states"].values())
    new = sum(ev["contradictions"][n] for n,s in ev["states"].items() if s == "contradicted")
    ev["score"] += .8*(old-new)
    ev["strongest_contradiction"] = max((ev["contradictions"][n] for n,s in ev["states"].items() if s == "contradicted"), default=0.)
    return ev


def _pair_candidate(gray, sx, sy, ux, uy, cfg, full=False):
    w,h=cfg["hole_width"],cfg["hole_height"]; lx=ux+cfg["lower_minus_upper_x"]; ly=uy+cfg["pitch"]
    upper=_prefer_direct_support(_template_evidence(gray,sx,sy,ux,uy,w,h,cfg,full),cfg)
    lower=_prefer_direct_support(_template_evidence(gray,sx,sy,lx,ly,w,h,cfg,full),cfg)
    us,ls=_features(upper),_features(lower); supported=len(us)+len(ls)
    independent=sum(-math.log(max(.04,1-upper["strengths"][n])) for n in us)+sum(-math.log(max(.04,1-lower["strengths"][n])) for n in ls)
    distribution=min(len(us),len(ls))/4+(_axis_classes(us)+_axis_classes(ls))/8
    residuals=[v for ev in (upper,lower) for k,v in ev["residuals"].items() if v is not None and k in _features(ev) and (k.endswith("wall") or k.endswith("edge"))]
    median=statistics.median(residuals) if residuals else 999.
    geometric=max(0.,1-median/max(cfg["strong_feature_alignment_px"]*2,1))*distribution+.08*independent
    penalty=.8*sum(ev["contradictions"][n] for ev in (upper,lower) for n,s in ev["states"].items() if s=="contradicted")
    raw=upper["score"]+lower["score"]+.35*geometric-penalty
    return {"upper_x":ux,"upper_y":uy,"lower_x":lx,"lower_y":ly,"upper":upper,"lower":lower,
            "upper_score":upper["score"],"lower_score":lower["score"],"supported":supported,
            "upper_supported":len(us),"lower_supported":len(ls),"contradicted":upper["contradicted"]+lower["contradicted"],
            "missing":upper["missing"]+lower["missing"],"strongest_contradiction":max(upper["strongest_contradiction"],lower["strongest_contradiction"]),
            "geometric_contribution":geometric,"geometric_residual":median,"contradiction_penalty":penalty,"raw_score":raw}


def _add_grid(points,cx0,cx1,cy0,cy1,step,cfg):
    xmin,xmax=cfg["sprocket_x_domain"]; ymin,ymax=cfg["upper_y_domain"]
    for y in np.arange(max(ymin,cy0),min(ymax,cy1)+.1,step):
        for x in np.arange(max(xmin,cx0),min(xmax,cx1)+.1,step): points.add((round(float(x),3),round(float(y),3)))


def fit_pair(image: Image.Image | np.ndarray, priors=(), metrics=None):
    """Return the exact cached P07 candidate result for one developed image."""
    rgb=np.asarray(image.convert("RGB") if isinstance(image,Image.Image) else image)
    cfg=FROZEN_CONFIG; H,W=rgb.shape[:2]; w,h=cfg["hole_width"],cfg["hole_height"]
    xmin,xmax=cfg["sprocket_x_domain"]; ymin,ymax=cfg["upper_y_domain"]
    x0=max(0,int(xmin-w/2-40)); x1=min(W,int(xmax+w/2+40)); y0=max(0,int(ymin-h/2-40)); y1=min(H,int(ymax+cfg["pitch"]+h/2+40))
    gray=cv2.cvtColor(rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32); blur=cv2.GaussianBlur(gray,(5,5),0)
    sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3); sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3)
    norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12); sx=np.clip(sx0/norm,-1,1); sy=np.clip(sy0/norm,-1,1)
    normalized=[]
    for px,py in priors: normalized.append((px,py) if py<H/2 else (px-cfg["lower_minus_upper_x"],py-cfg["pitch"]))
    cache={}; counts={"candidate_cache_hits":0,"candidate_cache_misses":0,"template_evaluations_avoided":0,"percentile_calls_avoided":0}
    def candidate(ux,uy,full=False):
        key=(ux,uy,full)
        if key in cache:
            counts["candidate_cache_hits"]+=1; counts["template_evaluations_avoided"]+=2; counts["percentile_calls_avoided"]+=4
            return cache[key].copy()
        counts["candidate_cache_misses"]+=1
        c=_pair_candidate(gray,sx,sy,ux-x0,uy-y0,cfg,full); c["upper_x"]+=x0;c["lower_x"]+=x0;c["upper_y"]+=y0;c["lower_y"]+=y0;cache[key]=c
        return c.copy()
    points=set(); _add_grid(points,xmin,xmax,ymin,ymax,cfg["coarse_step"],cfg)
    for px,py in normalized: _add_grid(points,px-cfg["prior_radius"],px+cfg["prior_radius"],py-cfg["prior_radius"],py+cfg["prior_radius"],cfg["prior_step"],cfg)
    coarse=[]
    for ux,uy in points:
        c=candidate(ux,uy); d=min((math.hypot(ux-px,uy-py) for px,py in normalized),default=0);c["prior_distance"]=d;c["score"]=c["raw_score"]-cfg["weak_prior_weight"]*min(d,200)/200;coarse.append(c)
    coarse.sort(key=lambda z:z["score"],reverse=True); refine=set()
    for c in coarse[:cfg["refine_hypotheses"]]: _add_grid(refine,c["upper_x"]-cfg["refine_radius"],c["upper_x"]+cfg["refine_radius"],c["upper_y"]-cfg["refine_radius"],c["upper_y"]+cfg["refine_radius"],cfg["refine_step"],cfg)
    fine=[]
    for ux,uy in refine:
        c=candidate(ux,uy);d=min((math.hypot(ux-px,uy-py) for px,py in normalized),default=0);c["prior_distance"]=d;c["score"]=c["raw_score"]-cfg["weak_prior_weight"]*min(d,200)/200;fine.append(c)
    candidates=sorted(fine or coarse,key=lambda z:z["score"],reverse=True);best0=candidates[0];best=candidate(best0["upper_x"],best0["upper_y"],True)
    best["prior_distance"]=best0["prior_distance"];best["score"]=best["raw_score"]-cfg["weak_prior_weight"]*min(best["prior_distance"],200)/200
    competitors=[c for c in candidates[1:] if math.hypot(c["upper_x"]-best["upper_x"],c["upper_y"]-best["upper_y"])>=cfg["competitor_separation_px"]]
    runner=competitors[0] if competitors else None;best["margin"]=best["score"]-(runner["score"] if runner else 0);best["pair_contrast"]=best["upper"]["contrast"]+best["lower"]["contrast"]
    best["safe"]=(best["score"]>=cfg["joint_score_min"] and best["geometric_contribution"]>=cfg["geometric_contribution_min"] and best["supported"]>=cfg["minimum_total_supported"] and min(best["upper_supported"],best["lower_supported"])>=cfg["minimum_weaker_hole_supported"] and best["contradicted"]<=cfg["maximum_total_contradicted"] and best["strongest_contradiction"]<=cfg["maximum_contradiction_strength"] and best["pair_contrast"]>=cfg["pair_contrast_min"] and best["margin"]>=cfg["competitor_margin_min"])
    best["competitors"]=[{"upper_x":c["upper_x"],"upper_y":c["upper_y"],"score":c["score"],"supported":c["supported"],"contradicted":c["contradicted"]} for c in competitors[:5]]
    counts.update({"cache_entries":len(cache),"coarse_candidates":len(points),"fine_candidates":len(refine),"candidate_calls":len(points)+len(refine)+1,"template_evaluations":2*counts["candidate_cache_misses"],"percentile_calls":4*counts["candidate_cache_misses"]+1})
    if metrics is not None: metrics.update(counts)
    return best


def detect_pair(image: Image.Image, priors=()) -> PhysicalPairResult:
    cache_metrics={};best=fit_pair(image,priors,cache_metrics)
    if best["safe"]: classification="joint_pair_recovery"
    elif best["margin"]<FROZEN_CONFIG["competitor_margin_min"]: classification="ambiguous_competing_pair_positions"
    elif best["contradicted"]>FROZEN_CONFIG["maximum_total_contradicted"] or best["strongest_contradiction"]>FROZEN_CONFIG["maximum_contradiction_strength"]: classification="contradictory_pair_evidence"
    elif min(best["upper_supported"],best["lower_supported"])<FROZEN_CONFIG["minimum_weaker_hole_supported"]: classification="insufficient_cross_hole_distribution"
    elif best["supported"]<FROZEN_CONFIG["minimum_total_supported"] or best["score"]<FROZEN_CONFIG["joint_score_min"]: classification="insufficient_joint_support"
    else: classification="geometric_consistency_failure"
    anchor_x=statistics.mean((best["upper_x"],best["lower_x"]))-17.125 if best["safe"] else None
    anchor_y=statistics.mean((best["upper_y"],best["lower_y"])) if best["safe"] else None
    diagnostics={"classification":classification,"upper_center":[best["upper_x"],best["upper_y"]],"lower_center":[best["lower_x"],best["lower_y"]],"anchor":[anchor_x,anchor_y],"upper_states":best["upper"]["states"],"lower_states":best["lower"]["states"],"joint_score":best["score"],"geometry_residual":best["geometric_residual"],"competitor_score":best["score"]-best["margin"],"competitor_margin":best["margin"],"supported":best["supported"],"missing":best["missing"],"contradicted":best["contradicted"],"cache_metrics":cache_metrics,"physical_detector_version":DETECTOR_MODE,"p07_implementation_sha256":P07_IMPLEMENTATION_SHA256,"p07_configuration_sha256":P07_CONFIGURATION_SHA256,"exact_cache_implementation_sha256":EXACT_CACHE_IMPLEMENTATION_SHA256}
    return PhysicalPairResult(best["safe"],classification,anchor_x,anchor_y,diagnostics)


def detect_fallback(image: Image.Image, capture_item=None) -> PhysicalPairResult:
    """Run capture-seeded physical pair, P06, then full-domain frozen P07."""
    rgb=np.asarray(image.convert("RGB"),dtype=np.uint8);boxes=capture_boxes(capture_item);holes=[];hole_reasons=[]
    for box in boxes:
        hole,reason=_physical_hole(rgb,box);holes.append(hole);hole_reasons.append(reason)
    if len(holes)==2 and all(h is not None for h in holes):
        upper,lower=sorted(holes,key=lambda h:h.cy)
        if abs((lower.cy-upper.cy)-785.)<=100 and abs(lower.cx-upper.cx)<=100:
            ax=statistics.mean((upper.cx,lower.cx))-17.125;ay=statistics.mean((upper.cy,lower.cy))
            return PhysicalPairResult(True,"physical_hole_pair",ax,ay,{"classification":"physical_hole_pair","stage":"physical_pair","capture_roi_boxes":boxes,"independent_holes":[vars(h) if h else None for h in holes],"upper_center":[upper.cx,upper.cy],"lower_center":[lower.cx,lower.cy],"anchor":[ax,ay],"hole_reasons":hole_reasons})
    good=[h for h in holes if h is not None]
    p06_detail=None;p06_model=None
    if len(good)==1:
        seed=good[0];upper=seed.cy<rgb.shape[0]/2;prediction=(seed.cx+(18.678947368421063 if upper else -18.678947368421063),seed.cy+(785. if upper else -785.));p06_model,p06_detail=_p06_fit(rgb,prediction)
        if p06_model is not None:
            mx,my=p06_model;ax=statistics.mean((seed.cx,mx))-17.125;ay=statistics.mean((seed.cy,my))
            return PhysicalPairResult(True,"partner_predicted_template_recovery",ax,ay,{"classification":"partner_predicted_template_recovery","stage":"p06","capture_roi_boxes":boxes,"independent_holes":[vars(h) if h else None for h in holes],"seed_center":[seed.cx,seed.cy],"partner_center":[mx,my],"anchor":[ax,ay],"p06":p06_detail,"hole_reasons":hole_reasons})
    priors=[(b[0],b[1]) for b in boxes]+[(h.cx,h.cy) for h in good]
    if p06_model is not None:priors.append(p06_model)
    result=detect_pair(image,priors)
    detail=dict(result.diagnostics);detail.update({"stage":"p07","capture_roi_boxes":boxes,"independent_holes":[vars(h) if h else None for h in holes],"physical_hole_reasons":hole_reasons,"p06":p06_detail})
    return PhysicalPairResult(result.accepted,result.classification,result.anchor_x,result.anchor_y,detail)
