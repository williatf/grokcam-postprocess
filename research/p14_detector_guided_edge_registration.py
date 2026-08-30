#!/usr/bin/env python3
"""P14 detector-guided physical-edge registration feasibility POC."""
from __future__ import annotations

import argparse,csv,json,math,shutil,time
from collections import Counter,defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image,ImageDraw

from grokcam.config import load_calibration
from grokcam.encoding import encode_segment,verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper

WIDTH=381.5842105263158;HEIGHT=272.;PITCH=785.;LOWER_X=18.678947368421063;GAP=513.
ROOT=Path(__file__).resolve().parents[1];DEFAULT_CONFIG=ROOT/"research/config/p14_detector_guided_edge_registration.json"


def _subpixel(values,index,cfg):
    if not 0<index<len(values)-1:return float(index),False
    l,c,r=map(float,values[index-1:index+2]);den=l-2*c+r
    if den>=-cfg["subpixel_min_curvature"]:return float(index),False
    f=.5*(l-r)/den
    return (float(index+f),True) if abs(f)<=cfg["subpixel_max_fraction"] else (float(index),False)


def measure_edge(gray,expected_y,polarity,cfg):
    radius=cfg["search_radius_px"];ys=np.arange(math.floor(expected_y-radius),math.ceil(expected_y+radius)+1,dtype=float);columns=[]
    sy=cv2.Sobel(cv2.GaussianBlur(gray,(1,5),0),cv2.CV_32F,0,1,ksize=3)*polarity
    for x in range(0,gray.shape[1],cfg["column_step"]):
        yi=np.clip(np.rint(ys).astype(int),0,gray.shape[0]-1);profile=sy[yi,x];idx=int(np.argmax(profile));outside=np.delete(profile,np.arange(max(0,idx-1),min(len(profile),idx+2)));base=float(np.median(outside));noise=max(float(1.4826*np.median(np.abs(outside-base))),cfg["minimum_noise"]);peak=float(profile[idx]);prom=peak-base
        pos,stable=_subpixel(profile,idx,cfg)
        if idx in (0,len(profile)-1) or peak<cfg["minimum_peak"] or prom<cfg["minimum_prominence"] or prom/noise<cfg["minimum_snr"]:continue
        columns.append({"y":float(np.interp(pos,np.arange(len(ys)),ys)),"peak":peak,"prominence":prom,"snr":prom/noise,"subpixel":stable})
    if not columns:return {"valid":False,"y":None,"reason":"no_valid_columns","valid_columns":0,"total_columns":math.ceil(gray.shape[1]/cfg["column_step"])}
    positions=np.array([c["y"] for c in columns]);median=float(np.median(positions));mad=float(np.median(np.abs(positions-median)));limit=max(cfg["minimum_outlier_limit_px"],cfg["outlier_mad_multiplier"]*mad);inliers=[c for c in columns if abs(c["y"]-median)<=limit];positions=np.array([c["y"] for c in inliers]);fraction=len(inliers)/math.ceil(gray.shape[1]/cfg["column_step"]);valid=len(inliers)>=cfg["minimum_inlier_columns"] and fraction>=cfg["minimum_inlier_fraction"]
    return {"valid":valid,"y":float(np.median(positions)),"reason":None if valid else "insufficient_column_consensus","valid_columns":len(inliers),"total_columns":math.ceil(gray.shape[1]/cfg["column_step"]),"valid_fraction":fraction,"column_mad":float(np.median(np.abs(positions-np.median(positions)))),"median_snr":float(np.median([c["snr"] for c in inliers])),"subpixel_fraction":sum(c["subpixel"] for c in inliers)/len(inliers)}


def measure_frame(image,anchor_x,anchor_y,cfg):
    ux=anchor_x+17.125-LOWER_X/2;uy=anchor_y-PITCH/2;lx=ux+LOWER_X;ly=uy+PITCH;out={};started=time.perf_counter()
    for name,cx,expected,polarity in (("upper_bottom",ux,uy+HEIGHT/2,-1),("lower_top",lx,ly-HEIGHT/2,+1)):
        x0=max(0,int(cx-WIDTH*cfg["horizontal_half_fraction"]));x1=min(image.width,int(cx+WIDTH*cfg["horizontal_half_fraction"]));y0=max(0,int(expected-cfg["search_radius_px"]-5));y1=min(image.height,int(expected+cfg["search_radius_px"]+6));gray=cv2.cvtColor(np.asarray(image.crop((x0,y0,x1,y1)).convert("RGB")),cv2.COLOR_RGB2GRAY).astype(np.float32);result=measure_edge(gray,expected-y0,polarity,cfg)
        if result["y"] is not None:result["y"]+=y0
        result["expected_y"]=expected;result["offset"]=None if result["y"] is None else result["y"]-expected;out[name]=result
    out["runtime_ms"]=(time.perf_counter()-started)*1000;return out


def movement(values):
    d=np.diff(np.asarray(values,float));a=abs(d);return {"count":len(d),"median_absolute":float(np.median(a)),"mean_absolute":float(np.mean(a)),"p90_absolute":float(np.percentile(a,90)),"p95_absolute":float(np.percentile(a,95)),"maximum_absolute":float(max(a))}


def summary_stats(values):
    x=np.asarray(list(values),float)
    if not len(x):return {"count":0}
    med=float(np.median(x));a=abs(x)
    return {"count":len(x),"median":med,"mad":float(np.median(abs(x-med))),"mean_absolute":float(np.mean(a)),"p95_absolute":float(np.percentile(a,95)),"maximum_absolute":float(max(a))}


def flatten(frame,source,anchor,measurement,limit):
    u,l=measurement["upper_bottom"],measurement["lower_top"];cu=u["y"] if u["valid"] else None;cl=l["y"]-GAP if l["valid"] else None;dis=None if cu is None or cl is None else cu-cl;consistent=dis is None or abs(dis)<=limit
    if cu is not None and cl is not None and not consistent:chosen=None;reason="dual_edge_disagreement"
    elif cu is not None:chosen=cu;reason="upper_bottom"
    elif cl is not None:chosen=cl;reason="lower_top_fallback"
    else:chosen=None;reason="no_valid_edge"
    row={"frame":frame,"source":source,"trusted_anchor_y":anchor,"trusted_canonical_y":anchor-256.5,"canonical_from_upper":cu,"canonical_from_lower":cl,"canonical_disagreement":dis,"combined_canonical":None if cu is None or cl is None or not consistent else (cu+cl)/2,"selected_canonical":chosen,"selection":reason,"resolved":chosen is not None,"runtime_ms":measurement["runtime_ms"]}
    for prefix,result in (("upper_bottom",u),("lower_top",l)):
        for key in ("valid","y","offset","reason","valid_columns","total_columns","valid_fraction","column_mad","median_snr","subpixel_fraction"):row[f"{prefix}_{key}"]=result.get(key)
    return row


def run(args):
    cfg=json.loads(Path(args.config).read_text());manifest=json.loads(Path(args.manifest).read_text());records=sorted([r for s in manifest["segments"] for r in s["frame_records"] if args.first<=r["frame"]<=args.last and r.get("output_disposition")=="included"],key=lambda r:r["frame"]);output=Path(args.output_dir);output.mkdir(parents=True,exist_ok=True);stage=output/"staging";trusted_dir=stage/"trusted";edge_dir=stage/"edge";trusted_dir.mkdir(parents=True,exist_ok=True);edge_dir.mkdir(parents=True,exist_ok=True)
    calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report);working=stage/"developed.tif";rows=[];rendered=0;review=set(args.review_frames)
    for index,record in enumerate(records,1):
        frame=record["frame"];developer.develop(Path(args.raw_dir)/f"frame_{frame:06d}.dng",working)
        with Image.open(working) as image:
            measurement=measure_frame(image,record["anchor_x"],record["anchor_y"],cfg);row=flatten(frame,record["final_registration_source"],record["anchor_y"],measurement,cfg["consistency_limit_px"])
            if row["resolved"]:
                rendered+=1;base=CropGeometry(record["crop_left"],record["crop_top"],calibration.crop.width,calibration.crop.height);edge=CropGeometry(base.left,row["selected_canonical"]-156.5,base.width,base.height);registered_frame(image,base,calibration.contrast).save(trusted_dir/f"frame_{rendered:06d}.jpg",quality=95,subsampling=0);registered_frame(image,edge,calibration.contrast).save(edge_dir/f"frame_{rendered:06d}.jpg",quality=95,subsampling=0)
            if frame in review:
                crop=image.crop((100,950,700,1250)).convert("RGB");draw=ImageDraw.Draw(crop)
                for y,color,label in ((row["upper_bottom_y"],"cyan","upper-bottom"),(row["lower_top_y"],"magenta","lower-top")):
                    if y is not None:draw.line((0,y-950,crop.width,y-950),fill=color,width=2);draw.text((5,max(0,y-950-18)),label,fill=color,stroke_width=1,stroke_fill="black")
                crop.save(output/f"frame_{frame:06d}_edges.jpg",quality=94)
        working.unlink(missing_ok=True);rows.append(row)
        if index==1 or index%50==0 or index==len(records):print(f"P14 {index}/{len(records)}",flush=True)
    with (output/"measurements.csv").open("w",newline="") as f:writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    by_source={}
    for source in sorted({r["source"] for r in rows}):
        g=[r for r in rows if r["source"]==source];by_source[source]={"frames":len(g),"upper_valid":sum(r["upper_bottom_valid"] for r in g),"lower_valid":sum(r["lower_top_valid"] for r in g),"either_valid":sum(r["upper_bottom_valid"] or r["lower_top_valid"] for r in g),"both_valid":sum(r["upper_bottom_valid"] and r["lower_top_valid"] for r in g),"resolved":sum(r["resolved"] for r in g)}
    both=[r for r in rows if r["canonical_disagreement"] is not None];resolved_rows=[r for r in rows if r["resolved"]];trusted=[r["trusted_anchor_y"] for r in rows];result={"configuration":cfg,"coverage":{"frames":len(rows),"upper_valid":sum(r["upper_bottom_valid"] for r in rows),"lower_valid":sum(r["lower_top_valid"] for r in rows),"either_valid":sum(r["upper_bottom_valid"] or r["lower_top_valid"] for r in rows),"both_valid":len(both),"resolved":len(resolved_rows),"dual_disagreement_unresolved":sum(r["selection"]=="dual_edge_disagreement" for r in rows),"by_source":by_source},"agreement":summary_stats(r["canonical_disagreement"] for r in both),"movement":{"trusted_all":movement(trusted)},"runtime_ms":summary_stats(r["runtime_ms"] for r in rows),"movies":{}}
    for label,key in (("upper_bottom","canonical_from_upper"),("lower_top","canonical_from_lower"),("combined","combined_canonical")):
        valid=[r for r in rows if r[key] is not None];pairs=[(a,b) for a,b in zip(valid,valid[1:]) if b["frame"]==a["frame"]+1];result["movement"][label]={"eligible_frames":len(valid),"consecutive_pairs":len(pairs),"trusted_matched":movement([p[0]["trusted_anchor_y"] for p in pairs]+([pairs[-1][1]["trusted_anchor_y"]] if pairs else [])) if pairs and all(pairs[i][1]["frame"]==pairs[i+1][0]["frame"] for i in range(len(pairs)-1)) else None,"measured_pair_deltas":summary_stats(p[1][key]-p[0][key] for p in pairs),"trusted_pair_deltas":summary_stats(p[1]["trusted_anchor_y"]-p[0]["trusted_anchor_y"] for p in pairs)}
    if len(resolved_rows)/len(rows)>=cfg["minimum_movie_coverage"]:
        for name,directory in (("trusted",trusted_dir),("edge",edge_dir)):
            normalized=stage/f"{name}_normalized";normalized.mkdir();normalize_frames(sorted(directory.glob("frame_*.jpg")),normalized,None);movie=output/f"Reel_46335_2000_2350_p14_{name}.mp4";temporary=movie.with_suffix(".tmp.mp4");encode_segment(Path(args.ffmpeg),normalized,temporary,1,len(resolved_rows),args.fps);result["movies"][name]={"path":str(movie),"verification":verify_video(Path(args.ffmpeg),Path(args.ffprobe),temporary,len(resolved_rows))};temporary.replace(movie)
    (output/"summary.json").write_text(json.dumps(result,indent=2)+"\n");shutil.rmtree(stage);return result


def main():
    p=argparse.ArgumentParser();p.add_argument("--manifest",required=True);p.add_argument("--raw-dir",required=True);p.add_argument("--output-dir",required=True);p.add_argument("--config",default=str(DEFAULT_CONFIG));p.add_argument("--first",type=int,default=2000);p.add_argument("--last",type=int,default=2350);p.add_argument("--fps",type=int,default=16);p.add_argument("--ffmpeg",default="/usr/bin/ffmpeg");p.add_argument("--ffprobe",default="/usr/bin/ffprobe");p.add_argument("--review-frames",nargs="*",type=int,default=[2003,2004,2082,2083,2093,2094,2096,2097,2143,2144,2240,2241,2242,2161,2162,2146,2147]);a=p.parse_args();print(json.dumps(run(a),indent=2))
if __name__=="__main__":main()
