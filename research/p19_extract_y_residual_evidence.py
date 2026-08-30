#!/usr/bin/env python3
"""Extract position-bearing P06/P07 feature responses for P19.

This extractor does not estimate or score against P15 truth. It samples the
existing frozen line and corner responses while holding the detected X and all
rigid-pair geometry fixed.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.physical_sprocket import FROZEN_CONFIG, _corner_strength, _line_strength
from grokcam.raw_development import DarktableMatchedDeveloper


def feature_peak(offsets, support, opposite):
    support = np.asarray(support, float); opposite = np.asarray(opposite, float)
    maximum = float(np.max(support))
    plateau = np.flatnonzero(np.isclose(support, maximum, atol=1e-12))
    center_index = int(plateau[len(plateau)//2])
    center = float(offsets[center_index])
    separated = np.abs(offsets-center) >= 2.0
    runner = float(np.max(support[separated])) if separated.any() else 0.0
    return {"residual_y": center, "strength": maximum,
            "opposite_strength": float(opposite[center_index]),
            "prominence_2px": maximum-runner,
            "at_boundary": bool(abs(center) == max(abs(offsets[0]), abs(offsets[-1])))}


def extract(image, anchor_x, anchor_y, radius=12.0, step=.25):
    rgb = np.asarray(image.convert("RGB")); cfg = FROZEN_CONFIG; H, W = rgb.shape[:2]
    w, h = cfg["hole_width"], cfg["hole_height"]
    xmin, xmax = cfg["sprocket_x_domain"]; ymin, ymax = cfg["upper_y_domain"]
    x0=max(0,int(xmin-w/2-40));x1=min(W,int(xmax+w/2+40))
    y0=max(0,int(ymin-h/2-40));y1=min(H,int(ymax+cfg["pitch"]+h/2+40))
    gray=cv2.cvtColor(rgb[y0:y1,x0:x1],cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur=cv2.GaussianBlur(gray,(5,5),0);sx0=cv2.Sobel(blur,cv2.CV_32F,1,0,ksize=3);sy0=cv2.Sobel(blur,cv2.CV_32F,0,1,ksize=3)
    norm=max(float(np.percentile(cv2.magnitude(sx0,sy0),92)),12);sx=np.clip(sx0/norm,-1,1);sy=np.clip(sy0/norm,-1,1)
    ux=anchor_x+17.125-cfg["lower_minus_upper_x"]/2-x0;uy=anchor_y-cfg["pitch"]/2-y0
    holes=(("upper",ux,uy),("lower",ux+cfg["lower_minus_upper_x"],uy+cfg["pitch"]))
    offsets=np.arange(-radius,radius+step/2,step); result={}
    for hole,cx,cy in holes:
        for name in ("top_edge","bottom_edge"):
            values=[_line_strength(sx,sy,cx,cy,w,h,name,float(off)) for off in offsets]
            result[f"{hole}_{name}"]=feature_peak(offsets,[v[0] for v in values],[v[1] for v in values])
        for name in ("upper_left","upper_right","lower_right","lower_left"):
            values=[_corner_strength(sx,sy,cx,cy+float(off),w,h,name) for off in offsets]
            result[f"{hole}_{name}"]=feature_peak(offsets,[v[0] for v in values],[v[1] for v in values])
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--p15",type=Path,required=True)
    p.add_argument("--raw-dir",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--population",choices=("valid","missing","all"),required=True);a=p.parse_args()
    manifest=json.loads(a.manifest.read_text());records={int(r["frame"]):r for s in manifest["segments"] for r in s["frame_records"]}
    valid={int(r["frame"]) for r in csv.DictReader(a.p15.open()) if r["lower_top_valid"]=="True"}
    frames=sorted(n for n in records if a.population=="all" or (n in valid)==(a.population=="valid"))
    developer=DarktableMatchedDeveloper(load_calibration().match.report);a.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p19_extract_",dir=ROOT/"work") as temp,a.output.open("w") as out:
        tif=Path(temp)/"developed.tif"
        for index,frame in enumerate(frames,1):
            row=records[frame];developer.develop(a.raw_dir/f"frame_{frame:06d}.dng",tif)
            with Image.open(tif) as image:evidence=extract(image,float(row["anchor_x"]),float(row["anchor_y"]))
            out.write(json.dumps({"frame":frame,"source":row["final_registration_source"],"features":evidence},sort_keys=True)+"\n")
            if index==1 or index%25==0 or index==len(frames):print(f"P19 {a.population} {index}/{len(frames)}",flush=True)

if __name__=="__main__":main()
