#!/usr/bin/env python3
"""Analyze and render the frozen P21 P15-first/P07-fallback architecture."""
from __future__ import annotations
import argparse,csv,json,shutil,tempfile,sys
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.encoding import encode_segment,file_sha256,verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper

LOWER_TOP_TO_CROP_TOP=-673.5297914597816

def stats(values,raw=False):
 v=np.asarray(list(values),float);med=float(np.median(v));a=np.abs(v-med if raw else v)
 d={"n":len(v),("median_delta_px" if raw else "median_error_px"):med,"mad_px":float(np.median(np.abs(v-med))),("median_absolute_residual_px" if raw else "median_absolute_error_px"):float(np.median(a)),"p90_absolute_px":float(np.percentile(a,90)),"p95_absolute_px":float(np.percentile(a,95)),"max_absolute_px":float(max(a))}
 d.update({f"over_{q}_px":int(sum(a>q)) for q in (1,2,3,5)});return d

def main():
 p=argparse.ArgumentParser();p.add_argument("--valid-p07",type=Path,required=True);p.add_argument("--missing-p07",type=Path,required=True);p.add_argument("--p15",type=Path,required=True);p.add_argument("--config",type=Path,required=True);p.add_argument("--raw-dir",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--render",action="store_true");a=p.parse_args()
 cfg=json.loads(a.config.read_text());p07={int(r["frame"]):r for path in (a.valid_p07,a.missing_p07) for r in csv.DictReader(path.open())};p15={int(r["frame"]):float(r["lower_top_y"]) for r in csv.DictReader(a.p15.open()) if r["lower_top_valid"]=="True"};offset=cfg["p07_model_to_p15_lower_top_offset_px"];rows=[]
 for n in range(2000,2351):
  d=p07[n];model=float(d["model_lower_top_y"]);source="P15" if n in p15 else "P07";register=p15.get(n,model+offset);anchor_x=(float(d["upper_x"])+float(d["lower_x"]))/2-17.125
  rows.append({"frame":n,"register_source":source,"register_y":register,"p15_lower_top_y":p15.get(n),"p07_accepted":d["accepted"]=="True","p07_upper_x":float(d["upper_x"]),"p07_upper_y":float(d["upper_y"]),"p07_lower_x":float(d["lower_x"]),"p07_lower_y":float(d["lower_y"]),"p07_model_lower_top_y":model,"p07_calibrated_lower_top_y":model+offset,"p07_anchor_x":anchor_x,"p07_joint_score":float(d["joint_score"]),"p07_geometric_residual":float(d["geometric_residual"]),"p07_competitor_margin":float(d["competitor_margin"]),"p07_supported":int(d["supported"]),"p07_missing":int(d["missing"]),"p07_contradicted":int(d["contradicted"]),"historical_source":d["historical_source"],"overlap_delta_px":None if n not in p15 else p15[n]-model,"overlap_error_px":None if n not in p15 else model+offset-p15[n]})
 for prev,row in zip(rows,rows[1:]):row["register_jump_from_previous_px"]=row["register_y"]-prev["register_y"];row["source_transition_from_previous"]=prev["register_source"]!=row["register_source"]
 rows[0]["register_jump_from_previous_px"]=None;rows[0]["source_transition_from_previous"]=False
 a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/"measurements.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 overlap=[r for r in rows if r["register_source"]=="P15"];held=[r for r in overlap if r["frame"]%2];fallback=[r for r in rows if r["register_source"]=="P07"];trans=[r for r in rows if r["source_transition_from_previous"]];j=np.array([r["register_jump_from_previous_px"] for r in trans]);frac=Counter(round(r["p07_lower_y"]%4,3) for r in overlap)
 suspicious=[r for r in fallback if r["p07_contradicted"]>0 or r["p07_joint_score"]<11 or r["p07_competitor_margin"]<1]
 summary={"architecture":{"p15_success":len(overlap),"p07_fallback_success":len(fallback),"total_coverage":len(rows),"total_frames":len(rows),"unresolved":0,"unresolved_frames":[]},"p07_overlap":{"attempted":len(overlap),"accepted":sum(r["p07_accepted"] for r in overlap),"rejected":sum(not r["p07_accepted"] for r in overlap),"raw_delta":stats((r["overlap_delta_px"] for r in overlap),True),"held_out":stats(r["overlap_error_px"] for r in held),"lower_y_modulo_4_distribution":dict(frac)},"calibration":cfg,"fallback":{"attempted":67,"accepted":len(fallback),"rejected":0,"historical_source_breakdown":dict(Counter(r["historical_source"] for r in fallback)),"diagnostic_distribution":{"joint_score":{"min":min(r["p07_joint_score"] for r in fallback),"median":float(np.median([r["p07_joint_score"] for r in fallback])),"max":max(r["p07_joint_score"] for r in fallback)},"competitor_margin":{"min":min(r["p07_competitor_margin"] for r in fallback),"median":float(np.median([r["p07_competitor_margin"] for r in fallback])),"max":max(r["p07_competitor_margin"] for r in fallback)},"supported":dict(Counter(r["p07_supported"] for r in fallback)),"contradicted":dict(Counter(r["p07_contradicted"] for r in fallback))},"suspicious_by_conservative_audit":[{"frame":r["frame"],"score":r["p07_joint_score"],"margin":r["p07_competitor_margin"],"supported":r["p07_supported"],"contradicted":r["p07_contradicted"]} for r in suspicious],"accuracy_claimed":False},"transitions":{"count":len(trans),"median_absolute_jump_px":float(np.median(abs(j))),"p95_absolute_jump_px":float(np.percentile(abs(j),95)),"max_absolute_jump_px":float(max(abs(j))),"records":[{"frame":r["frame"],"from":"P07" if r["register_source"]=="P15" else "P15","to":r["register_source"],"jump_px":r["register_jump_from_previous_px"]} for r in trans]},"movie":None}
 if a.render:
  stage=a.output_dir/"staging";reg=stage/"registered";norm=stage/"normalized";reg.mkdir(parents=True,exist_ok=True);dev=DarktableMatchedDeveloper(load_calibration().match.report);cal=load_calibration();tif=stage/"developed.tif"
  for i,r in enumerate(rows,1):
   n=r["frame"];dev.develop(a.raw_dir/f"frame_{n:06d}.dng",tif)
   with Image.open(tif) as image:out=registered_frame(image,CropGeometry(r["p07_anchor_x"]+159,r["register_y"]+LOWER_TOP_TO_CROP_TOP,cal.crop.width,cal.crop.height),cal.contrast)
   d=ImageDraw.Draw(out);d.rectangle((0,0,270,32),fill="black");d.text((8,8),f"{n}  Y={r['register_source']}",fill=(255,255,255));out.save(reg/f"frame_{n:06d}.jpg",quality=95,subsampling=0)
   if i==1 or i%50==0 or i==len(rows):print(f"P21 render {i}/{len(rows)}",flush=True)
  _,target=normalize_frames(sorted(reg.glob("frame_*.jpg")),norm,None);movie=a.output_dir/"Reel_46335_002000_002350_p21_p15_first_p07_fallback_16fps.mp4";tmp=movie.with_suffix(".tmp.mp4");encode_segment(Path('/usr/bin/ffmpeg'),norm,tmp,2000,351,16);verification=verify_video(Path('/usr/bin/ffmpeg'),Path('/usr/bin/ffprobe'),tmp,351);tmp.replace(movie);summary["movie"]={"path":str(movie.resolve()),"sha256":file_sha256(movie),"bytes":movie.stat().st_size,"normalization_target_luma":target,"verification":verification,"x_register":"forced P07 model X on every frame","overlay":"frame number and authoritative Y source"};shutil.rmtree(stage)
 (a.output_dir/"summary.json").write_text(json.dumps(summary,indent=2)+"\n");print(json.dumps(summary,indent=2))
if __name__=="__main__":main()
