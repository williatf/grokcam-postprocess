#!/usr/bin/env python3
"""P08: bounded same-frame Y refinement of an already-trusted sprocket pair.

This module cannot detect or rescue a frame.  It accepts a trusted anchor,
holds the frozen P07 geometry and X coordinate fixed, and evaluates only the
configured local Y offsets using horizontal physical-hole boundary polarity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from grokcam.config import load_calibration
from grokcam.encoding import encode_segment, verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "research/config/p08_same_frame_y_refinement.json"
GEOMETRY = {"width": 381.5842105263158, "height": 272.0,
            "pitch": 785.0, "lower_minus_upper_x": 18.678947368421063}


@dataclass(frozen=True)
class Refinement:
    trusted: bool
    integer_offset: int
    subpixel_offset: float
    integer_accepted: bool
    subpixel_accepted: bool
    rejection_reason: str | None
    diagnostics: dict


def _sample(array, xs, ys):
    xi = np.clip(np.rint(xs).astype(int), 0, array.shape[1] - 1)
    yi = np.clip(np.rint(ys).astype(int), 0, array.shape[0] - 1)
    return array[yi, xi]


def _coherent(values, threshold):
    values = np.asarray(values, dtype=float)
    return float(.55 * np.mean(np.clip(values, 0, 1)) +
                 .45 * np.mean(values > threshold))


def _horizontal_score(sy, cx, cy, width, height, threshold):
    xs = np.linspace(cx - .30 * width, cx + .30 * width, 61)
    top = _sample(sy, xs, np.full_like(xs, cy - height / 2))
    bottom = -_sample(sy, xs, np.full_like(xs, cy + height / 2))
    return _coherent(top, threshold), _coherent(bottom, threshold)


def _prepare(image: Image.Image, anchor_x: float, anchor_y: float, cfg: dict):
    w, h = GEOMETRY["width"], GEOMETRY["height"]
    upper_x = anchor_x + 17.125 - GEOMETRY["lower_minus_upper_x"] / 2
    upper_y = anchor_y - GEOMETRY["pitch"] / 2
    lower_x = upper_x + GEOMETRY["lower_minus_upper_x"]
    lower_y = upper_y + GEOMETRY["pitch"]
    pad = cfg["roi_padding_px"] + cfg["bound_px"]
    left = max(0, int(math.floor(min(upper_x, lower_x) - w / 2 - pad)))
    right = min(image.width, int(math.ceil(max(upper_x, lower_x) + w / 2 + pad)))
    top = max(0, int(math.floor(upper_y - h / 2 - pad)))
    bottom = min(image.height, int(math.ceil(lower_y + h / 2 + pad)))
    rgb = np.asarray(image.crop((left, top, right, bottom)).convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    sy0 = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    norm = max(float(np.percentile(np.abs(sy0), cfg["gradient_percentile"])),
               cfg["minimum_gradient_norm"])
    sy = np.clip(sy0 / norm, -1, 1)
    centers = ((upper_x-left, upper_y-top), (lower_x-left, lower_y-top))
    return sy, centers, (left, top, right, bottom), norm


def refine(image: Image.Image, anchor_x: float | None, anchor_y: float | None,
           cfg: dict) -> Refinement:
    if anchor_x is None or anchor_y is None:
        return Refinement(False, 0, 0., False, False, "no_trusted_anchor",
                          {"score_curve": []})
    started = time.perf_counter()
    sy, centers, roi, norm = _prepare(image, anchor_x, anchor_y, cfg)
    prepared = time.perf_counter()
    offsets = list(range(-cfg["bound_px"], cfg["bound_px"] + 1))
    curve = []
    for offset in offsets:
        hole_scores = []
        features = []
        for cx, cy in centers:
            top, bottom = _horizontal_score(
                sy, cx, cy + offset, GEOMETRY["width"], GEOMETRY["height"],
                cfg["coherent_sample_threshold"])
            features.extend((top, bottom)); hole_scores.append((top + bottom) / 2)
        curve.append({"offset": offset, "upper": hole_scores[0],
                      "lower": hole_scores[1], "joint": float(np.mean(features)),
                      "supported_boundaries": sum(v >= cfg["boundary_support_min"]
                                                  for v in features),
                      "features": features})
    def peak_center(field):
        peak=max(x[field] for x in curve); plateau=[x for x in curve if peak-x[field]<=cfg["peak_plateau_tolerance"]]
        center=float(np.mean([x["offset"] for x in plateau]))
        return min(plateau,key=lambda x:abs(x["offset"]-center)),plateau
    upper_best,_ = peak_center("upper")
    lower_best,_ = peak_center("lower")
    best, plateau = peak_center("joint")
    best_index=curve.index(best)
    plateau_offsets={x["offset"] for x in plateau}
    separated = [x for x in curve if x["offset"] not in plateau_offsets and
                 min(abs(x["offset"]-p) for p in plateau_offsets)>=1]
    competitor = max(separated, key=lambda x: x["joint"]) if separated else best
    margin = best["joint"] - competitor["joint"]
    curvature = 0.
    subpixel = float(best["offset"])
    subpixel_stable = False
    if 0 < best_index < len(curve) - 1:
        left_score, center_score, right_score = (curve[best_index-1]["joint"],
                                                 best["joint"],
                                                 curve[best_index+1]["joint"])
        denominator = left_score - 2 * center_score + right_score
        curvature = -denominator
        if denominator < -cfg["subpixel_min_curvature"]:
            fraction = .5 * (left_score - right_score) / denominator
            if abs(fraction) <= cfg["subpixel_max_fraction"]:
                subpixel += fraction
                subpixel_stable = True
    reasons = []
    if best["joint"] < cfg["joint_score_min"]: reasons.append("weak_peak")
    if margin < cfg["separated_margin_min"]: reasons.append("ambiguous_peak")
    if best["supported_boundaries"] < cfg["minimum_supported_boundaries"]:
        reasons.append("insufficient_boundaries")
    disagreement = abs(upper_best["offset"] - lower_best["offset"])
    if disagreement > cfg["upper_lower_agreement_px"]:
        reasons.append("upper_lower_disagreement")
    if cfg["reject_search_boundary_peak"] and abs(best["offset"]) == cfg["bound_px"]:
        reasons.append("search_boundary_peak")
    accepted = not reasons
    integer = int(best["offset"]) if accepted else 0
    subpixel_value = float(np.clip(subpixel, -cfg["bound_px"], cfg["bound_px"])) if accepted and subpixel_stable else float(integer)
    evaluated = time.perf_counter()
    diagnostics = {
        "score_curve": curve, "upper_offset": upper_best["offset"],
        "lower_offset": lower_best["offset"], "upper_lower_disagreement": disagreement,
        "joint_peak": best["joint"], "competitor_offset": competitor["offset"],
        "competitor_score": competitor["joint"], "separated_margin": margin,
        "curvature": curvature, "subpixel_stable": subpixel_stable,
        "supported_boundaries": best["supported_boundaries"],
        "roi": roi, "gradient_norm": norm,
        "prepare_ms": (prepared-started)*1000,
        "evaluate_ms": (evaluated-prepared)*1000,
        "total_ms": (evaluated-started)*1000,
    }
    return Refinement(True, integer, subpixel_value, accepted,
                      accepted and subpixel_stable, ";".join(reasons) or None,
                      diagnostics)


def _records(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    return manifest, sorted([r for s in manifest["segments"] for r in s["frame_records"]],
                            key=lambda r: r["frame"])


def movement(values):
    delta = np.diff(np.asarray(values, dtype=float)); absolute = np.abs(delta)
    if not len(delta): return {"count": 0}
    return {"count": len(delta), "median_absolute": float(np.median(absolute)),
            "mean_absolute": float(np.mean(absolute)),
            **{f"p{p}_absolute": float(np.percentile(absolute, p)) for p in (90,95,99)},
            "maximum_absolute": float(np.max(absolute))}


def _write_overlay(image, path, anchor_x, anchor_y, refinement, source):
    w,h=GEOMETRY["width"],GEOMETRY["height"]; ux=anchor_x+17.125-GEOMETRY["lower_minus_upper_x"]/2;uy=anchor_y-GEOMETRY["pitch"]/2
    roi=image.crop((0,max(0,int(uy-h)),min(image.width,800),min(image.height,int(uy+GEOMETRY["pitch"]+h)))).convert("RGB")
    yshift=max(0,int(uy-h)); draw=ImageDraw.Draw(roi)
    for offset,color,label in ((0,"cyan","trusted"),(refinement.subpixel_offset,"magenta","refined")):
        for cx,cy in ((ux,uy),(ux+GEOMETRY["lower_minus_upper_x"],uy+GEOMETRY["pitch"])):
            draw.rectangle((cx-w/2,cy+offset-h/2-yshift,cx+w/2,cy+offset+h/2-yshift),outline=color,width=4)
        draw.text((15,15 if offset==0 else 40),f"{label}: {offset:+.3f}px",fill=color,stroke_width=2,stroke_fill="black")
    draw.text((15,65),f"source={source} accepted={refinement.integer_accepted} peak={refinement.diagnostics['joint_peak']:.3f}",fill="white",stroke_width=2,stroke_fill="black")
    path.parent.mkdir(parents=True,exist_ok=True);roi.save(path,quality=94)


def _encode(ffmpeg, ffprobe, source_dir, output, count, fps):
    temporary=output.with_suffix(".tmp.mp4")
    encode_segment(Path(ffmpeg), source_dir, temporary, 1, count, fps)
    verification=verify_video(Path(ffmpeg),Path(ffprobe),temporary,count)
    temporary.replace(output);return verification


def run(args):
    cfg=json.loads(Path(args.config).read_text()); output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True)
    manifest, records=_records(args.manifest); records=[r for r in records if args.first<=r["frame"]<=args.last]
    raw_dir=Path(args.raw_dir); calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report)
    staging=output/"staging";tiff=staging/"developed.tif"; variants={k:staging/k for k in ("trusted","integer","best")}
    for path in variants.values():path.mkdir(parents=True,exist_ok=True)
    overlays=output/"review_overlays"; rows=[];total_started=time.perf_counter(); checkpoint=output/"per_frame_checkpoint.jsonl";checkpoint.write_text("")
    review_frames=set(args.review_frames)
    for index,record in enumerate(records,1):
        frame=record["frame"];dng=raw_dir/f"frame_{frame:06d}.dng"
        if record.get("output_disposition")!="included" or record.get("anchor_y") is None:
            rows.append({"frame":frame,"trusted":False,"source":record.get("final_registration_source"),"original_anchor_y":None,"integer_offset":0,"subpixel_offset":0,"integer_accepted":False,"subpixel_accepted":False,"rejection_reason":"no_trusted_anchor","diagnostics":{"score_curve":[]}});continue
        developer.develop(dng,tiff)
        with Image.open(tiff) as image:
            result=refine(image,record["anchor_x"],record["anchor_y"],cfg)
            base=CropGeometry(record["crop_left"],record["crop_top"],calibration.crop.width,calibration.crop.height)
            crops={"trusted":base,"integer":CropGeometry(base.left,base.top+result.integer_offset,base.width,base.height),"best":CropGeometry(base.left,base.top+result.subpixel_offset,base.width,base.height)}
            for name,crop in crops.items(): registered_frame(image,crop,calibration.contrast).save(variants[name]/f"frame_{index:06d}.jpg",quality=95,subsampling=0)
            if frame in review_frames or abs(result.subpixel_offset)>=cfg["overlay_correction_min_px"]:
                _write_overlay(image,overlays/f"frame_{frame:06d}.jpg",record["anchor_x"],record["anchor_y"],result,record["final_registration_source"])
        tiff.unlink(missing_ok=True)
        rows.append({"frame":frame,"trusted":True,"source":record["final_registration_source"],"original_anchor_y":record["anchor_y"],"integer_offset":result.integer_offset,"subpixel_offset":result.subpixel_offset,"integer_accepted":result.integer_accepted,"subpixel_accepted":result.subpixel_accepted,"rejection_reason":result.rejection_reason,"diagnostics":result.diagnostics})
        with checkpoint.open("a") as handle: handle.write(json.dumps(rows[-1])+"\n")
        if index==1 or index%25==0 or index==len(records):print(f"P08 {index}/{len(records)}",flush=True)
    # Use identical normalization and encoding mechanics independently for all variants.
    movies={};verifications={}
    for name,path in variants.items():
        normalized=staging/f"{name}_normalized"; normalized.mkdir(exist_ok=True)
        normalize_frames(sorted(path.glob("frame_*.jpg")),normalized,None)
        movie=output/f"Reel_46335_2000_2350_p08_{name}.mp4"
        verifications[name]=_encode(args.ffmpeg,args.ffprobe,normalized,movie,len([r for r in rows if r["trusted"]]),args.fps);movies[name]=str(movie)
    trusted_rows=[r for r in rows if r["trusted"]]; original=[r["original_anchor_y"] for r in trusted_rows];integer=[r["original_anchor_y"]+r["integer_offset"] for r in trusted_rows];best=[r["original_anchor_y"]+r["subpixel_offset"] for r in trusted_rows]
    offsets=np.array([r["subpixel_offset"] for r in trusted_rows]); accepted=np.array([r["integer_accepted"] for r in trusted_rows])
    summary={"configuration":cfg,"population":{"source":len(rows),"trusted":len(trusted_rows),"untrusted":len(rows)-len(trusted_rows)},"accepted_refinements":int(accepted.sum()),"rejected_refinements":int((~accepted).sum()),"correction":{"mean":float(offsets.mean()),"median":float(np.median(offsets)),"mean_absolute":float(np.abs(offsets).mean()),**{f"p{p}_absolute":float(np.percentile(np.abs(offsets),p)) for p in (90,95,99)},"maximum_absolute":float(np.abs(offsets).max())},"movement":{"trusted":movement(original),"integer":movement(integer),"best":movement(best)},"runtime":{"wall_seconds":time.perf_counter()-total_started,"mean_prepare_ms":float(np.mean([r["diagnostics"]["prepare_ms"] for r in trusted_rows])),"mean_evaluate_ms":float(np.mean([r["diagnostics"]["evaluate_ms"] for r in trusted_rows])),"mean_refinement_ms":float(np.mean([r["diagnostics"]["total_ms"] for r in trusted_rows]))},"movies":movies,"verification":verifications}
    summary["runtime"]["projected_seconds"]={str(n):summary["runtime"]["mean_refinement_ms"]*n/1000 for n in (4000,16000,32000)}
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (output/"score_curves.json").write_text(json.dumps({str(r["frame"]):r["diagnostics"]["score_curve"] for r in rows},indent=2)+"\n")
    with (output/"diagnostics.csv").open("w",newline="") as f:
        fields=["frame","trusted","source","original_anchor_y","integer_offset","subpixel_offset","integer_accepted","subpixel_accepted","rejection_reason","upper_offset","lower_offset","upper_lower_disagreement","joint_peak","separated_margin","curvature","supported_boundaries","prepare_ms","evaluate_ms","total_ms"]
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in rows:
            d=r["diagnostics"];writer.writerow({k:(r.get(k) if k in r else d.get(k)) for k in fields})
    shutil.rmtree(staging)
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--manifest",required=True);parser.add_argument("--raw-dir",required=True);parser.add_argument("--output-dir",required=True);parser.add_argument("--config",default=str(DEFAULT_CONFIG));parser.add_argument("--first",type=int,default=2000);parser.add_argument("--last",type=int,default=2350);parser.add_argument("--fps",type=int,default=16);parser.add_argument("--ffmpeg",default="/usr/bin/ffmpeg");parser.add_argument("--ffprobe",default="/usr/bin/ffprobe");parser.add_argument("--review-frames",type=int,nargs="*",default=[2000,2057,2117,2170,2199,2240,2293,2350]);args=parser.parse_args();print(json.dumps(run(args),indent=2))


if __name__=="__main__":main()
