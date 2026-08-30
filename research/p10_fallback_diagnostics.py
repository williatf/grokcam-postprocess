#!/usr/bin/env python3
"""P10: Diagnose lower-boundary measurement failures on fallback-source frames."""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from collections import defaultdict

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
    """Measure boundary with detailed diagnostic data."""
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
    
    # Diagnostic data
    diagnostics = {
        "search_y0": y0, "search_y1": y1, "search_center": expected_y,
        "profile_index": index, "profile_length": len(profile),
        "peak_position_px": float(ys[index]) if index < len(ys) else None,
        "peak_at_boundary": boundary_peak,
        "peak_value": peak, "baseline": baseline, "noise": noise,
        "prominence": prominence, "snr": snr,
        "peak_passes_threshold": peak >= cfg["minimum_peak"],
        "prominence_passes_threshold": prominence >= cfg["minimum_prominence"],
        "snr_passes_threshold": snr >= cfg["minimum_snr"],
    }
    
    return {
        "y":coordinate,"valid":bool(valid),"subpixel_stable":bool(stable),
        "peak":peak,"prominence":prominence,"snr":snr,"curvature":curvature,
        "offset":coordinate-expected_y,"failure_reason":reason,"profile":[float(v) for v in profile],
        "diagnostics": diagnostics
    }


def measure_frame(image, anchor_x, anchor_y, cfg):
    """Measure frame with diagnostic focus on lower boundaries."""
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


def run(args):
    cfg=json.loads(Path(args.config).read_text());manifest=json.loads(Path(args.manifest).read_text())
    
    # Get P09 measurements for reference and to find specific failure frames
    p09_csv = Path(args.p09_csv)
    p09_rows = {}
    fallback_frames = set()  # Track fallback-source frames from P09
    if p09_csv.exists():
        with p09_csv.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                frame = int(row["frame"])
                p09_rows[frame] = row
                src = row.get("source", "").lower()
                if args.fallback_sources:
                    if src in [s.lower() for s in args.fallback_sources]:
                        fallback_frames.add(frame)
                else:
                    # Default: P06, P07, physical-pair (not primary)
                    if src in {"physical_p06", "physical_p07", "physical_pair"}:
                        fallback_frames.add(frame)
    
    # Build record list, focusing on fallback frames
    # The manifest may not have output_disposition, so just check frame range and anchor
    records=sorted([r for s in manifest["segments"] for r in s["frame_records"] 
                   if args.first<=r["frame"]<=args.last 
                   and r.get("anchor_y") is not None
                   and r["frame"] in fallback_frames],
                   key=lambda r:r["frame"])
    
    output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
    
    calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report)
    tiff=output/"developed_working.tif"
    rows=[]
    
    print(f"Measuring {len(records)} fallback-source frames for diagnostics...")
    
    for index,record in enumerate(records,1):
        frame=record["frame"]
        # Get source from P09 measurements
        source = p09_rows.get(frame, {}).get("source", "unknown") if frame in p09_rows else "unknown"
        developer.develop(Path(args.raw_dir)/f"frame_{frame:06d}.dng",tiff)
        with Image.open(tiff) as image: measurements=measure_frame(image,record["anchor_x"],record["anchor_y"],cfg)
        tiff.unlink(missing_ok=True)
        
        row={
            "frame":frame,"source":source,
            "trusted_anchor_x":record["anchor_x"],
            "trusted_anchor_y":record["anchor_y"],
        }
        
        # Extract measurement data and diagnostics
        for name in ("lower_top", "lower_bottom"):
            m = measurements[name]
            for key in ("y", "valid", "peak", "prominence", "snr", "offset", "failure_reason"):
                row[f"{name}_{key}"] = m[key]
            # Flatten diagnostics
            diag = m.get("diagnostics", {})
            for key, val in diag.items():
                row[f"{name}_diag_{key}"] = val
        
        # Check if this frame failed in P09
        if frame in p09_rows:
            p09_row = p09_rows[frame]
            row["p09_lower_top_valid"] = p09_row.get("lower_top_valid") == "True"
            row["p09_lower_bottom_valid"] = p09_row.get("lower_bottom_valid") == "True"
        
        rows.append(row)
        
        if index == 1 or index % 10 == 0 or index == len(records):
            print(f"P10 diagnostics {index}/{len(records)}", flush=True)
    
    # Write detailed CSV
    if rows:
        fields = list(rows[0].keys())
        with (output/"fallback_diagnostics.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--p09-csv", required=True, help="Path to P09 measurements.csv for comparison")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--first", type=int, default=2000)
    p.add_argument("--last", type=int, default=2350)
    p.add_argument("--fallback-sources", nargs="*", help="Specific fallback sources to analyze (default: P06, P07, physical-pair)")
    args = p.parse_args()
    
    rows = run(args)
    print(json.dumps({"frames_measured": len(rows), "output": str(Path(args.output_dir)/"fallback_diagnostics.csv")}, indent=2))


if __name__ == "__main__":
    main()
