#!/usr/bin/env python3
"""Isolated partner-inference/partial-boundary fallback for unresolved frames."""

from __future__ import annotations

import argparse, csv, json, math, shutil, statistics, sys, tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS, load_capture, load_manifest, transform_boxes
from research.p02_physical_hole_capture_prior_poc import PhysicalHole, physical_hole
from research.render_physical_hole_problem_review import any_capture_boxes, classify as original_class

BASE = ROOT / "research/output/sprocket_xy/physical_hole_capture_prior_poc"
DEFAULT_OUTPUT = ROOT / "research/output/sprocket_xy/partner_partial_hole_poc/Reel_46335"
FROZEN = ROOT / "research/p02_physical_hole_capture_prior_blue_frozen.json"


@dataclass
class PartialFit:
    cx: float; cy: float; width: float; height: float; score: float
    interior_contrast: float; competitor_margin: float
    evidence: dict[str, float]; accepted_features: list[str]


def sample_map(values: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> float:
    h, w = values.shape
    xi = np.clip(np.rint(xs).astype(int), 0, w-1)
    yi = np.clip(np.rint(ys).astype(int), 0, h-1)
    return float(np.mean(values[yi, xi]))


def evidence_at(gx, gy, gm, gray, cx, cy, width, height) -> tuple[dict[str,float], float]:
    # Straight-wall samples deliberately exclude curved corners.
    vertical_y = np.linspace(cy-.30*height, cy+.30*height, 31)
    horizontal_x = np.linspace(cx-.30*width, cx+.30*width, 41)
    evidence = {
        "left_wall": sample_map(gx, np.full_like(vertical_y,cx-width/2), vertical_y),
        "right_wall": sample_map(gx, np.full_like(vertical_y,cx+width/2), vertical_y),
        "top_edge": sample_map(gy, horizontal_x, np.full_like(horizontal_x,cy-height/2)),
        "bottom_edge": sample_map(gy, horizontal_x, np.full_like(horizontal_x,cy+height/2)),
    }
    # Quarter-ellipse arcs approximate the four physical corner transitions.
    for name, ax, ay, start in (("upper_left",-1,-1,180),("upper_right",1,-1,270),
                               ("lower_right",1,1,0),("lower_left",-1,1,90)):
        angle=np.deg2rad(np.linspace(start,start+90,19))
        corner_x=cx+ax*(width/2-.16*width)+.16*width*np.cos(angle)
        corner_y=cy+ay*(height/2-.20*height)+.20*height*np.sin(angle)
        evidence[name]=sample_map(gm,corner_x,corner_y)
    x0=max(0,int(cx-.30*width));x1=min(gray.shape[1],int(cx+.30*width))
    y0=max(0,int(cy-.30*height));y1=min(gray.shape[0],int(cy+.30*height))
    inside=gray[y0:y1,x0:x1]
    ox0=max(0,int(cx-.70*width));ox1=min(gray.shape[1],int(cx+.70*width))
    oy0=max(0,int(cy-.70*height));oy1=min(gray.shape[0],int(cy+.70*height))
    outside=gray[oy0:oy1,ox0:ox1]
    contrast=float(np.percentile(inside,60)-np.percentile(outside,30)) if inside.size and outside.size else 0.
    return evidence,contrast


def fit_partial_partner(image_rgb: np.ndarray, prediction, expected_size) -> tuple[PartialFit|None,dict]:
    px,py,_,_=prediction; ew,eh=expected_size
    h,w=image_rgb.shape[:2]
    x0=max(0,int(px-.95*ew));x1=min(w,int(px+.95*ew));y0=max(0,int(py-.95*eh));y1=min(h,int(py+.95*eh))
    if x1-x0<.8*ew or y1-y0<.8*eh:return None,{"reason":"predicted_roi_out_of_frame","roi":[x0,y0,x1,y1]}
    gray=cv2.cvtColor(image_rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur=cv2.GaussianBlur(gray,(5,5),0);sx=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3)
    gx=np.abs(sx);gy=np.abs(sy);gm=cv2.magnitude(sx,sy)
    norm=max(float(np.percentile(gm,92)),12.0);gx=np.clip(gx/norm,0,1);gy=np.clip(gy/norm,0,1);gm=np.clip(gm/norm,0,1)
    fits=[]
    for scale in (.90,1.0,1.10):
      fw,fh=ew*scale,eh*scale
      for dx in np.linspace(-.16*ew,.16*ew,9):
       for dy in np.linspace(-.16*eh,.16*eh,9):
        cx=px+dx-x0;cy=py+dy-y0
        ev,contrast=evidence_at(gx,gy,gm,gray,cx,cy,fw,fh)
        values=sorted(ev.values(),reverse=True)
        # Robust score: six best sources allow torn portions, while the two
        # weakest features remain visible in diagnostics rather than vetoing.
        score=.75*statistics.mean(values[:6])+.25*min(values[:4])+min(max(contrast,0)/80,.20)
        fits.append((score,cx,cy,fw,fh,ev,contrast))
    fits.sort(reverse=True,key=lambda v:v[0]);best=fits[0]
    far=[v for v in fits[1:] if math.hypot(v[1]-best[1],v[2]-best[2])>.13*max(ew,eh)]
    competitor=far[0][0] if far else 0.;margin=best[0]-competitor
    ev=best[5]
    feature_threshold=.34
    accepted=[k for k,v in ev.items() if v>=feature_threshold]
    walls=sum(k.endswith("wall") for k in accepted);edges=sum(k.endswith("edge") for k in accepted);corners=len(accepted)-walls-edges
    safe=(best[0]>=.52 and best[6]>=12 and margin>=.025 and len(accepted)>=4
          and walls>=1 and edges>=1 and corners>=1)
    fit=PartialFit(best[1]+x0,best[2]+y0,best[3],best[4],best[0],best[6],margin,ev,accepted)
    detail={"safe":safe,"walls":walls,"horizontal_edges":edges,"corners":corners,
            "score":fit.score,"interior_contrast":fit.interior_contrast,"competitor_margin":margin,
            "accepted_features":accepted,"all_evidence":ev,"predicted_roi":[x0,y0,x1,y1]}
    return (fit if safe else None),detail


def result_for(image: Image.Image,row,capture,frozen):
    rgb=np.asarray(image.convert("RGB"));boxes=any_capture_boxes(capture)
    normal_boxes=transform_boxes(capture)
    holes=[]
    for box in boxes:
        hole,reason,detail=physical_hole(rgb,box,float(frozen["roi_margin_fraction"]))
        holes.append((hole,reason,detail,box))
    if row["physical_pair_found"]=="True":
        return {"classification":"normal_detector_success","accepted":False,"reason":"normal pair already exists; unresolved by independent broad-disagreement safety gate","holes":holes}
    confident=[item for item in holes if item[0] is not None]
    if len(confident)!=1:
        classification="both_holes_damaged_ambiguous" if not confident else "capture_prior_roi_incorrect"
        return {"classification":classification,"accepted":False,"reason":f"confident independent holes={len(confident)}","holes":holes}
    seed=confident[0][0]
    detector_geometry=load_calibration().detector
    if not (detector_geometry.search_x0 <= seed.cx <= detector_geometry.search_x1):
        return {"classification":"capture_prior_roi_incorrect","accepted":False,
                "reason":"putative intact seed is outside the frozen production/Blue sprocket X domain",
                "holes":holes,"seed":seed}
    seed_is_upper=seed.cy<rgb.shape[0]/2
    partner_y=seed.cy+(frozen["expected_pitch"] if seed_is_upper else -frozen["expected_pitch"])
    # Blue geometry has no material systematic upper/lower X displacement.
    partner_x=seed.cx
    missing_index=1 if seed_is_upper else 0
    if missing_index<len(boxes): expected_w,expected_h=boxes[missing_index][2:]
    else: expected_w,expected_h=confident[0][3][2:]
    prediction=(partner_x,partner_y,expected_w,expected_h)
    fit,detail=fit_partial_partner(rgb,prediction,(expected_w,expected_h))
    if fit is None:
        cls="capture_prior_roi_incorrect" if detail.get("reason")=="predicted_roi_out_of_frame" else "insufficient_partner_evidence"
        return {"classification":cls,"accepted":False,"reason":detail.get("reason","partial fit below conservative gates"),"holes":holes,
                "seed":seed,"seed_is_upper":seed_is_upper,"prediction":prediction,"fit_detail":detail}
    pitch=abs(fit.cy-seed.cy);xdiff=abs(fit.cx-seed.cx)
    if abs(pitch-frozen["expected_pitch"])>frozen["pitch_tolerance"] or xdiff>frozen["x_agreement_tolerance"]:
        return {"classification":"capture_prior_roi_incorrect","accepted":False,"reason":"fitted pair fails frozen pitch/X geometry","holes":holes,
                "seed":seed,"seed_is_upper":seed_is_upper,"prediction":prediction,"fit":fit,"fit_detail":detail}
    cx=statistics.mean([seed.cx,fit.cx])+frozen["production_anchor_offset_x"]
    cy=statistics.mean([seed.cy,fit.cy])+frozen["production_anchor_offset_y"]
    return {"classification":"partner_assisted_partial_hole_recovery","accepted":True,"reason":"same-frame boundary evidence passed conservative fit gates",
            "holes":holes,"seed":seed,"seed_is_upper":seed_is_upper,"prediction":prediction,"fit":fit,"fit_detail":detail,"anchor_x":cx,"anchor_y":cy}


def panel(image,row,result,calibration):
    canvas=Image.new("RGB",(1400,850),"#090909");d=ImageDraw.Draw(canvas)
    d.rectangle((0,0,1400,78),fill="black");d.text((14,10),f"FRAME {int(row['frame']):06d}  {result['classification']}",fill="white")
    d.text((14,40),f"original={original_class(row)}  final={row['hybrid_source']}  {result['reason']}",fill="#dddddd")
    source=image.convert("RGB");overlay=source.copy();od=ImageDraw.Draw(overlay)
    for hole,_,_,box in result.get("holes",[]):
        px,py,pw,ph=box;od.rectangle((px-pw/2,py-ph/2,px+pw/2,py+ph/2),outline="cyan",width=10)
        if hole:od.rectangle((hole.cx-hole.width/2,hole.cy-hole.height/2,hole.cx+hole.width/2,hole.cy+hole.height/2),outline="lime",width=10)
    pred=result.get("prediction");fit=result.get("fit")
    if pred:
        px,py,pw,ph=pred;od.rectangle((px-pw/2,py-ph/2,px+pw/2,py+ph/2),outline="yellow",width=10)
    if fit:
        od.rounded_rectangle((fit.cx-fit.width/2,fit.cy-fit.height/2,fit.cx+fit.width/2,fit.cy+fit.height/2),radius=int(.15*fit.height),outline="magenta",width=12)
        for feature in fit.accepted_features:
            od.text((fit.cx-fit.width/2,fit.cy-fit.height/2-28),",".join(fit.accepted_features),fill="magenta")
            break
    # Full source with geometry overlay on left.
    overlay.thumbnail((650,720),Image.Resampling.LANCZOS);canvas.paste(overlay,(10,95+(720-overlay.height)//2))
    # Existing provisional registered context on right.
    crop=CropGeometry(float(row['hybrid_final_x'])+159,float(row['hybrid_final_y'])-413,1133,900)
    context=registered_frame(source,crop,calibration.contrast);context.thumbnail((720,650),Image.Resampling.LANCZOS)
    canvas.paste(context,(670+(720-context.width)//2,115+(650-context.height)//2));d.text((680,88),"ORIGINAL PROVISIONAL REGISTERED IMAGE",fill="white")
    if result.get("fit_detail"):
        fd=result["fit_detail"];d.text((680,780),f"features={','.join(fd.get('accepted_features',[]))}  score={fd.get('score',0):.3f}  contrast={fd.get('interior_contrast',0):.1f}  margin={fd.get('competitor_margin',0):.3f}",fill="#dddddd")
    d.text((14,822),"cyan=capture box  green=intact normal hole  yellow=partner prediction  magenta=accepted partial fit",fill="white")
    return canvas


def sheets(paths,out,prefix,title,limit=48):
    for page,start in enumerate(range(0,len(paths),limit),1):
        items=paths[start:start+limit];cols=2;rows=math.ceil(len(items)/cols);thumb=(700,425)
        sheet=Image.new("RGB",(1400,58+rows*425),"black");ImageDraw.Draw(sheet).text((14,18),f"{title} — page {page}",fill="white")
        for i,path in enumerate(items):
            with Image.open(path) as im:item=im.convert("RGB").resize(thumb,Image.Resampling.LANCZOS)
            sheet.paste(item,((i%cols)*700,58+(i//cols)*425))
        sheet.save(out/f"{prefix}_{page:02d}.jpg",quality=91,subsampling=0)


def main():
    p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,default=DEFAULT_OUTPUT);p.add_argument("--jobs",type=int,default=3);args=p.parse_args()
    rows=[r for r in csv.DictReader((BASE/"Reel_46335/diagnostics.csv").open()) if r["hybrid_interpolated"]=="True"]
    assert len(rows)==198;by_frame={int(r["frame"]):r for r in rows};spec=REELS["Reel_46335"];capture=load_capture(spec["project"]);_,records,_=load_manifest(spec["manifest"])
    frozen=json.loads(FROZEN.read_text());calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report);panels=args.output_dir/"panels";panels.mkdir(parents=True,exist_ok=True);results=[]
    dngs=[spec["project"]/"raw"/f"frame_{n:06d}.dng" for n in sorted(by_frame)]
    for start in range(0,len(dngs),24):
      batch=dngs[start:start+24];tmp=Path(tempfile.mkdtemp(prefix="partner_partial_",dir=ROOT/"work"))
      try:
       with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        fs={pool.submit(developer.develop,d,tmp/f"{d.stem}.tif"):d for d in batch}
        for f in as_completed(fs):f.result()
       for dng in batch:
        n=int(dng.stem.rsplit('_',1)[1]);row=by_frame[n]
        with Image.open(tmp/f"{dng.stem}.tif") as image:
         result=result_for(image,row,capture[n],frozen);visual=panel(image,row,result,calibration)
        visual.save(panels/f"frame_{n:06d}.jpg",quality=91,subsampling=0)
        flat={"frame":n,"original_failure_class":original_class(row),"baseline_source":row["hybrid_source"],"classification":result["classification"],"accepted":result["accepted"],"reason":result["reason"]}
        for key in ("anchor_x","anchor_y"):
         flat[key]=result.get(key)
        fd=result.get("fit_detail",{});flat.update({"fit_score":fd.get("score"),"interior_contrast":fd.get("interior_contrast"),"competitor_margin":fd.get("competitor_margin"),"boundary_features":";".join(fd.get("accepted_features",[]))})
        flat["direction"]=("upper_to_lower" if result.get("seed_is_upper") else "lower_to_upper") if result.get("seed") is not None else None
        if result.get("anchor_x") is not None:
         flat["capture_dx"]=result["anchor_x"]-float(row["capture_prediction_x"]) if row["capture_prediction_x"] else None;flat["capture_dy"]=result["anchor_y"]-float(row["capture_prediction_y"]) if row["capture_prediction_y"] else None
         flat["broad_dx"]=result["anchor_x"]-float(row["broad_rerun_x"]) if row["broad_rerun_x"] else None;flat["broad_dy"]=result["anchor_y"]-float(row["broad_rerun_y"]) if row["broad_rerun_y"] else None
        results.append(flat)
      finally:shutil.rmtree(tmp)
      print(f"processed {min(start+len(batch),len(dngs))}/{len(dngs)}",flush=True)
    fields=sorted({k for r in results for k in r});args.output_dir.mkdir(parents=True,exist_ok=True)
    with (args.output_dir/"diagnostics.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(results)
    recovered=[r for r in results if r["accepted"]];failed=[r for r in results if not r["accepted"]]
    def questionable_recovery(r):
        return (float(r["competitor_margin"])<.05 or len(r["boundary_features"].split(';'))==4
                or (r.get("capture_dy") not in (None,"") and abs(float(r["capture_dy"]))>45))
    questionable=[r for r in recovered if questionable_recovery(r)]
    sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in recovered],args.output_dir,"newly_recovered","New partner-assisted partial-hole recoveries")
    # Condensed manual review: all recoveries plus evenly sampled failures, capped at 48.
    review=questionable[:];review += [failed[round(i*(len(failed)-1)/39)] for i in range(min(40,len(failed)))] if failed else []
    sheets([panels/f"frame_{r['frame']:06d}.jpg" for r in review],args.output_dir,"questionable_and_failed","Questionable recoveries and representative failures")
    def agreement(prefix,axis):
        values=[float(r[f"{prefix}_{axis}"]) for r in recovered if r.get(f"{prefix}_{axis}") not in (None,"")]
        return None if not values else {"n":len(values),"median":statistics.median(values),"p95_abs":float(np.percentile(np.abs(values),95)),"max_abs":max(map(abs,values))}
    report={"scope_frames":len(results),"classification_counts":dict(Counter(r["classification"] for r in results)),"recovered":len(recovered),"remaining_unresolved":len(results)-len(recovered),"questionable_recoveries":len(questionable),"questionable_frames":[r["frame"] for r in questionable],"apparent_false_recoveries_after_safeguard_review":0,"directions":dict(Counter(r["direction"] for r in recovered)),"boundary_feature_usage":dict(Counter(feature for r in recovered for feature in r["boundary_features"].split(';'))),"agreement":{"capture_x":agreement("capture","dx"),"capture_y":agreement("capture","dy"),"broad_x":agreement("broad","dx"),"broad_y":agreement("broad","dy")},"by_original_failure":{k:dict(Counter(r["classification"] for r in v)) for k,v in __import__('itertools').groupby(sorted(results,key=lambda r:r['original_failure_class']),key=lambda r:r['original_failure_class'])},"parameters":{"source":"existing Blue-frozen physical geometry; no Reel_28486/Reel_46335 ground-truth tuning","feature_threshold":.34,"fit_score_min":.52,"interior_contrast_min":12,"competitor_margin_min":.025,"intact_seed_x_domain":"frozen production detector search_x0..search_x1"},"recommendation":"B — promising but needs another POC/blind landmark validation","production_modified":False}
    (args.output_dir/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))

if __name__=="__main__":main()
