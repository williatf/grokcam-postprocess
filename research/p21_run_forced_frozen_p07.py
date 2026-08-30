#!/usr/bin/env python3
"""Run the frozen P07 stage directly, independent of historical cascade source."""
from __future__ import annotations
import argparse,csv,json,sys,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.physical_sprocket import (_p06_fit,_physical_hole,capture_boxes,detect_pair,load_capture_metadata)
from grokcam.raw_development import DarktableMatchedDeveloper

def forced_p07(image,capture_item):
 rgb=np.asarray(image.convert("RGB"),dtype=np.uint8);boxes=capture_boxes(capture_item);holes=[];reasons=[]
 for box in boxes:
  hole,reason=_physical_hole(rgb,box);holes.append(hole);reasons.append(reason)
 good=[h for h in holes if h is not None];p06_model=None;p06_detail=None
 if len(good)==1:
  seed=good[0];upper=seed.cy<rgb.shape[0]/2;prediction=(seed.cx+(18.678947368421063 if upper else -18.678947368421063),seed.cy+(785. if upper else -785.));p06_model,p06_detail=_p06_fit(rgb,prediction)
 priors=[(b[0],b[1]) for b in boxes]+[(h.cx,h.cy) for h in good]
 if p06_model is not None:priors.append(p06_model)
 result=detect_pair(image,priors);d=result.diagnostics
 return {"accepted":result.accepted,"classification":result.classification,"upper_x":d["upper_center"][0],"upper_y":d["upper_center"][1],"lower_x":d["lower_center"][0],"lower_y":d["lower_center"][1],"model_lower_top_y":d["lower_center"][1]-136.0,"joint_score":d["joint_score"],"geometric_residual":d["geometry_residual"],"competitor_score":d["competitor_score"],"competitor_margin":d["competitor_margin"],"supported":d["supported"],"missing":d["missing"],"contradicted":d["contradicted"],"upper_states_json":json.dumps(d["upper_states"],sort_keys=True),"lower_states_json":json.dumps(d["lower_states"],sort_keys=True),"prior_count":len(priors),"capture_box_count":len(boxes),"physical_hole_count":len(good),"physical_hole_reasons":";".join(reasons),"p06_prior_available":p06_model is not None,"p06_prior_detail_json":json.dumps(p06_detail,sort_keys=True) if p06_detail else ""}

def main():
 p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--p15",type=Path,required=True);p.add_argument("--raw-dir",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--population",choices=("valid","missing"),required=True);p.add_argument("--jobs",type=int,default=3);a=p.parse_args()
 m=json.loads(a.manifest.read_text());records={int(r["frame"]):r for s in m["segments"] for r in s["frame_records"]};valid={int(r["frame"]) for r in csv.DictReader(a.p15.open()) if r["lower_top_valid"]=="True"};frames=sorted(n for n in records if (n in valid)==(a.population=="valid"));capture=load_capture_metadata(a.raw_dir);dev=DarktableMatchedDeveloper(load_calibration().match.report);a.output.parent.mkdir(parents=True,exist_ok=True);results=[]
 for start in range(0,len(frames),24):
  batch=frames[start:start+24]
  with tempfile.TemporaryDirectory(prefix="p21_p07_",dir=ROOT/"work") as temp:
   temp=Path(temp)
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs=[pool.submit(dev.develop,a.raw_dir/f"frame_{n:06d}.dng",temp/f"frame_{n:06d}.tif") for n in batch]
    for f in as_completed(fs):f.result()
   def one(n):
    with Image.open(temp/f"frame_{n:06d}.tif") as image:r=forced_p07(image,capture.get(n))
    return {"frame":n,"historical_source":records[n]["final_registration_source"],**r}
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:results.extend(f.result() for f in as_completed([pool.submit(one,n) for n in batch]))
  print(f"P21 {a.population} {min(start+len(batch),len(frames))}/{len(frames)}",flush=True)
 results.sort(key=lambda r:r["frame"])
 with a.output.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
 print(json.dumps({"population":a.population,"frames":len(results),"accepted":sum(r["accepted"] for r in results),"rejected":sum(not r["accepted"] for r in results)},indent=2))
if __name__=="__main__":main()
