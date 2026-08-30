#!/usr/bin/env python3
"""P15 single-landmark lower-sprocket-top registration POC."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from grokcam.config import load_calibration
from grokcam.encoding import encode_segment, verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper
try:
    from research.p14_detector_guided_edge_registration import measure_frame
except ModuleNotFoundError:  # Direct execution places research/ on sys.path.
    from p14_detector_guided_edge_registration import measure_frame

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "research/config/p15_single_landmark_lower_top_registration.json"
KNOWN = [2003,2004,2082,2083,2093,2094,2096,2097,2143,2144,2240,2241,2242,2161,2162,2146,2147]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contiguous_runs(frames: list[int]) -> list[dict]:
    if not frames:
        return []
    runs=[]; start=previous=frames[0]
    for frame in frames[1:]:
        if frame != previous + 1:
            runs.append({"first":start,"last":previous,"count":previous-start+1}); start=frame
        previous=frame
    runs.append({"first":start,"last":previous,"count":previous-start+1})
    return sorted(runs,key=lambda r:(-r["count"],r["first"]))


def robust(values) -> dict:
    values=np.asarray(list(values),float)
    if not len(values): return {"count":0}
    absolute=np.abs(values)
    return {"count":len(values),"median":float(np.median(values)),"median_absolute":float(np.median(absolute)),"mean_absolute":float(np.mean(absolute)),"p90_absolute":float(np.percentile(absolute,90)),"p95_absolute":float(np.percentile(absolute,95)),"maximum_absolute":float(np.max(absolute))}


def run(args):
    p15_path=Path(args.config); p15=json.loads(p15_path.read_text()); p14_path=ROOT/p15["p14_measurement_config"]; p14=json.loads(p14_path.read_text())
    manifest=json.loads(Path(args.manifest).read_text()); records=sorted([r for segment in manifest["segments"] for r in segment["frame_records"] if args.first<=r["frame"]<=args.last and r.get("output_disposition")=="included"],key=lambda r:r["frame"])
    output=Path(args.output_dir); stage=output/"staging"; trusted_dir=stage/"trusted"; lower_dir=stage/"lower_top"
    trusted_dir.mkdir(parents=True,exist_ok=True); lower_dir.mkdir(parents=True,exist_ok=True)
    calibration=load_calibration(); developer=DarktableMatchedDeveloper(calibration.match.report); working=stage/"developed.tif"; rows=[]; rendered=0
    for index,record in enumerate(records,1):
        frame=record["frame"]; developer.develop(Path(args.raw_dir)/f"frame_{frame:06d}.dng",working)
        with Image.open(working) as image:
            measurement=measure_frame(image,record["anchor_x"],record["anchor_y"],p14)["lower_top"]
            valid=bool(measurement["valid"]); lower_y=measurement["y"] if valid else None; lower_crop=None
            if valid:
                rendered+=1; lower_crop=lower_y+p15["crop_top_minus_lower_top_y"]
                trusted=CropGeometry(record["crop_left"],record["crop_top"],calibration.crop.width,calibration.crop.height)
                edge=CropGeometry(record["crop_left"],lower_crop,calibration.crop.width,calibration.crop.height)
                registered_frame(image,trusted,calibration.contrast).save(trusted_dir/f"frame_{rendered:06d}.jpg",quality=95,subsampling=0)
                registered_frame(image,edge,calibration.contrast).save(lower_dir/f"frame_{rendered:06d}.jpg",quality=95,subsampling=0)
            rows.append({"frame":frame,"source":record["final_registration_source"],"trusted_anchor_y":record["anchor_y"],"trusted_crop_top":record["crop_top"],"lower_top_valid":valid,"lower_top_y":lower_y,"lower_top_reason":measurement.get("reason"),"lower_top_valid_columns":measurement.get("valid_columns"),"lower_top_valid_fraction":measurement.get("valid_fraction"),"lower_top_column_mad":measurement.get("column_mad"),"lower_top_median_snr":measurement.get("median_snr"),"lower_top_crop_top":lower_crop,"crop_top_difference":None if lower_crop is None else lower_crop-record["crop_top"],"matched_video_index":rendered if valid else None})
        working.unlink(missing_ok=True)
        if index==1 or index%50==0 or index==len(records): print(f"P15 {index}/{len(records)}",flush=True)
    output.mkdir(parents=True,exist_ok=True)
    with (output/"measurements.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    valid_rows=[r for r in rows if r["lower_top_valid"]]; frames=[r["frame"] for r in valid_rows]; by_source={}
    for source in sorted({r["source"] for r in rows}):
        group=[r for r in rows if r["source"]==source]; count=sum(r["lower_top_valid"] for r in group); by_source[source]={"frames":len(group),"valid":count,"coverage_percent":100*count/len(group)}
    pairs=[(a,b) for a,b in zip(valid_rows,valid_rows[1:]) if b["frame"]==a["frame"]+1]
    summary={"version":p15["version"],"scope":{"first":args.first,"last":args.last,"trusted_frames":len(rows)},"frozen_mapping":p15,"provenance":{"p15_config_sha256":sha256(p15_path),"p14_config":str(p14_path),"p14_config_sha256":sha256(p14_path),"manifest":str(Path(args.manifest).resolve()),"manifest_sha256":sha256(Path(args.manifest))},"coverage":{"valid":len(valid_rows),"total":len(rows),"percent":100*len(valid_rows)/len(rows),"by_source":by_source},"matched_frame_count":len(valid_rows),"contiguous_valid_runs":contiguous_runs(frames),"movement_diagnostic":{"consecutive_matched_pairs":len(pairs),"trusted_crop_delta":robust(b["trusted_crop_top"]-a["trusted_crop_top"] for a,b in pairs),"lower_top_crop_delta":robust(b["lower_top_crop_top"]-a["lower_top_crop_top"] for a,b in pairs)},"known_cases":{str(r["frame"]):r for r in rows if r["frame"] in KNOWN},"movies":{}}
    for name,directory in (("trusted",trusted_dir),("lower_top",lower_dir)):
        normalized=stage/f"{name}_normalized"; _,target=normalize_frames(sorted(directory.glob("frame_*.jpg")),normalized,None)
        movie=output/f"Reel_46335_2000_2350_p15_{name}_matched.mp4"; temporary=movie.with_suffix(".tmp.mp4")
        encode_segment(Path(args.ffmpeg),normalized,temporary,1,len(valid_rows),args.fps); verification=verify_video(Path(args.ffmpeg),Path(args.ffprobe),temporary,len(valid_rows)); temporary.replace(movie)
        summary["movies"][name]={"path":str(movie.resolve()),"normalization_target_luma":target,"verification":verification}
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n"); shutil.rmtree(stage); return summary


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--manifest",required=True); parser.add_argument("--raw-dir",required=True); parser.add_argument("--output-dir",required=True); parser.add_argument("--config",default=str(DEFAULT_CONFIG)); parser.add_argument("--first",type=int,default=2000); parser.add_argument("--last",type=int,default=2350); parser.add_argument("--fps",type=int,default=16); parser.add_argument("--ffmpeg",default="/usr/bin/ffmpeg"); parser.add_argument("--ffprobe",default="/usr/bin/ffprobe"); args=parser.parse_args(); print(json.dumps(run(args),indent=2))
if __name__=="__main__": main()
