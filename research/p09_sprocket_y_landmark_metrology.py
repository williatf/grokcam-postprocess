#!/usr/bin/env python3
"""P09: independent local Y metrology for four trusted sprocket boundaries."""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper


ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"research/config/p09_sprocket_y_landmark_metrology.json"
WIDTH=381.5842105263158;HEIGHT=272.0;PITCH=785.0;LOWER_X=18.678947368421063


def _subpixel(profile, index, minimum_curvature, maximum_fraction):
    if not 0 < index < len(profile)-1:return float(index),False,0.
    left,center,right=map(float,profile[index-1:index+2]); denominator=left-2*center+right
    curvature=-denominator
    if denominator>=-minimum_curvature:return float(index),False,curvature
    fraction=.5*(left-right)/denominator
    if abs(fraction)>maximum_fraction:return float(index),False,curvature
    return float(index+fraction),True,curvature


def measure_boundary(gray, expected_y, polarity, cfg):
    radius=cfg["search_radius_px"]; y0=max(1,int(math.floor(expected_y-radius-2)));y1=min(gray.shape[0]-1,int(math.ceil(expected_y+radius+3)))
    strip=gray[y0-1:y1+1];sy=cv2.Sobel(cv2.GaussianBlur(strip,(1,5),0),cv2.CV_32F,0,1,ksize=3)*polarity
    profile=np.percentile(sy[:,1:-1],cfg["horizontal_percentile"],axis=1)
    # Sobel output row is in the strip coordinate system. Restrict explicitly
    # to the immutable local search neighborhood.
    ys=np.arange(y0-1,y1+1,dtype=float); keep=(ys>=expected_y-radius)&(ys<=expected_y+radius)
    ys=ys[keep];profile=profile[keep];index=int(np.argmax(profile));peak=float(profile[index])
    outside=np.delete(profile,np.arange(max(0,index-1),min(len(profile),index+2)))
    baseline=float(np.median(outside)) if len(outside) else 0.;noise=float(1.4826*np.median(np.abs(outside-baseline))) if len(outside) else 0.
    position_index,stable,curvature=_subpixel(profile,index,cfg["subpixel_min_curvature"],cfg["subpixel_max_fraction"])
    coordinate=float(np.interp(position_index,np.arange(len(ys)),ys));prominence=peak-baseline;snr=prominence/max(noise,cfg["minimum_noise"])
    boundary_peak=index in (0,len(profile)-1);valid=(not boundary_peak and peak>=cfg["minimum_peak"] and prominence>=cfg["minimum_prominence"] and snr>=cfg["minimum_snr"])
    reason=None if valid else "search_boundary_peak" if boundary_peak else "weak_edge"
    return {"y":coordinate,"valid":bool(valid),"subpixel_stable":bool(stable),"peak":peak,"prominence":prominence,"snr":snr,"curvature":curvature,"offset":coordinate-expected_y,"failure_reason":reason,"profile":[float(v) for v in profile]}


def measure_frame(image, anchor_x, anchor_y, cfg):
    ux=anchor_x+17.125-LOWER_X/2;uy=anchor_y-PITCH/2;lx=ux+LOWER_X;ly=uy+PITCH
    results={};started=time.perf_counter()
    for hole,cx,cy in (("upper",ux,uy),("lower",lx,ly)):
        x0=max(0,int(math.floor(cx-WIDTH*cfg["horizontal_half_fraction"])));x1=min(image.width,int(math.ceil(cx+WIDTH*cfg["horizontal_half_fraction"])))
        y0=max(0,int(math.floor(cy-HEIGHT/2-cfg["search_radius_px"]-4)));y1=min(image.height,int(math.ceil(cy+HEIGHT/2+cfg["search_radius_px"]+4)))
        gray=cv2.cvtColor(np.asarray(image.crop((x0,y0,x1,y1)).convert("RGB")),cv2.COLOR_RGB2GRAY).astype(np.float32)
        names=(f"{hole}_top",f"{hole}_bottom")
        results[names[0]]=measure_boundary(gray,cy-HEIGHT/2-y0,+1,cfg)
        results[names[1]]=measure_boundary(gray,cy+HEIGHT/2-y0,-1,cfg)
        for name in names: results[name]["y"]+=y0
    results["runtime_ms"]=(time.perf_counter()-started)*1000
    return results


def _derive(measurements):
    result={}
    for name,value in measurements.items():
        if isinstance(value,dict):
            for key in ("y","valid","subpixel_stable","peak","prominence","snr","curvature","offset","failure_reason"):
                result[f"{name}_{key}"]=value[key]
    ut,ub,lt,lb=(measurements[n]["y"] for n in ("upper_top","upper_bottom","lower_top","lower_bottom"))
    uc=(ut+ub)/2;lc=(lt+lb)/2
    result.update({"upper_height":ub-ut,"lower_height":lb-lt,"upper_center":uc,"lower_center":lc,"lower_equivalent_center":lc-PITCH,"observed_pitch":lc-uc,"center_disagreement":lc-PITCH-uc,"joint_center":((uc)+(lc-PITCH))/2})
    return result


def run(args):
    cfg=json.loads(Path(args.config).read_text());manifest=json.loads(Path(args.manifest).read_text());records=sorted([r for s in manifest["segments"] for r in s["frame_records"] if args.first<=r["frame"]<=args.last],key=lambda r:r["frame"])
    output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True);checkpoint=output/"measurements_checkpoint.jsonl";checkpoint.write_text("")
    calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report);tiff=output/"developed_working.tif";rows=[]
    for index,record in enumerate(records,1):
        if record.get("output_disposition")!="included" or record.get("anchor_y") is None:continue
        frame=record["frame"];developer.develop(Path(args.raw_dir)/f"frame_{frame:06d}.dng",tiff)
        with Image.open(tiff) as image: measurements=measure_frame(image,record["anchor_x"],record["anchor_y"],cfg)
        tiff.unlink(missing_ok=True);row={"frame":frame,"source":record["final_registration_source"],"trusted_anchor_x":record["anchor_x"],"trusted_anchor_y":record["anchor_y"],**_derive(measurements),"runtime_ms":measurements["runtime_ms"]};rows.append(row)
        with checkpoint.open("a") as f:f.write(json.dumps(row)+"\n")
        if index==1 or index%50==0 or index==len(records):print(f"P09 {index}/{len(records)}",flush=True)
    fields=list(rows[0]);
    with (output/"measurements.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    checkpoint.unlink();return rows


def main():
    p=argparse.ArgumentParser();p.add_argument("--manifest",required=True);p.add_argument("--raw-dir",required=True);p.add_argument("--output-dir",required=True);p.add_argument("--config",default=str(DEFAULT_CONFIG));p.add_argument("--first",type=int,default=2000);p.add_argument("--last",type=int,default=2350);args=p.parse_args();rows=run(args);print(json.dumps({"frames":len(rows),"output":str(Path(args.output_dir)/"measurements.csv")},indent=2))


if __name__=="__main__":main()
