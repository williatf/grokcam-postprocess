#!/usr/bin/env python3
"""P17 four-edge short-segment recovery of the P15 lower-top landmark."""
from __future__ import annotations

import argparse,csv,hashlib,json,math,shutil
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
try:
    from research.p14_detector_guided_edge_registration import measure_edge
except ModuleNotFoundError:
    from p14_detector_guided_edge_registration import measure_edge

ROOT=Path(__file__).resolve().parents[1];DEFAULT_CONFIG=ROOT/"research/config/p17_four_edge_partial_landmark_recovery.json"
WIDTH=381.5842105263158;HEIGHT=272.;PITCH=785.;LOWER_X=18.678947368421063
EDGES=("lower_top","upper_bottom","lower_bottom","upper_top")

def truth(value):return str(value).lower()=="true"
def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def expected_geometry(anchor_x,anchor_y):
    ux=anchor_x+17.125-LOWER_X/2;uy=anchor_y-PITCH/2;lx=ux+LOWER_X;ly=uy+PITCH
    return {"upper_top":(ux,uy-HEIGHT/2,+1),"upper_bottom":(ux,uy+HEIGHT/2,-1),"lower_top":(lx,ly-HEIGHT/2,+1),"lower_bottom":(lx,ly+HEIGHT/2,-1)}

def measure_partial_edges(image,anchor_x,anchor_y,cfg):
    geometry=expected_geometry(anchor_x,anchor_y);results={}
    segment_cfg={**cfg}
    for edge,(cx,expected_y,polarity) in geometry.items():
        segments=[]
        for number,fraction in enumerate(cfg["window_center_fractions_of_hole_width"]):
            center=cx+fraction*WIDTH;x0=max(0,int(round(center-cfg["window_width_px"]/2)));x1=min(image.width,int(round(center+cfg["window_width_px"]/2)));y0=max(0,int(math.floor(expected_y-cfg["search_radius_px"]-5)));y1=min(image.height,int(math.ceil(expected_y+cfg["search_radius_px"]+6)))
            gray=np.asarray(image.crop((x0,y0,x1,y1)).convert("L"),dtype=np.float32);measured=measure_edge(gray,expected_y-y0,polarity,segment_cfg)
            y=None if measured["y"] is None else measured["y"]+y0
            segments.append({"index":number,"x0":x0,"x1":x1,"expected_y":expected_y,"valid":bool(measured["valid"]),"y":y,"reason":measured.get("reason"),"valid_columns":measured.get("valid_columns",0),"valid_fraction":measured.get("valid_fraction"),"median_snr":measured.get("median_snr"),"column_mad":measured.get("column_mad")})
        valid=[s for s in segments if s["valid"]]
        if not valid: accepted=False;reason="no_convincing_segment";value=None
        elif len(valid)>1 and max(s["y"] for s in valid)-min(s["y"] for s in valid)>cfg["within_edge_consensus_tolerance_px"]:accepted=False;reason="contradictory_segments";value=None
        else:accepted=True;reason=None;value=float(np.median([s["y"] for s in valid]))
        results[edge]={"accepted":accepted,"y":value,"reason":reason,"accepted_segments":len(valid),"segments":segments}
    return results

def robust(values):
    values=np.asarray(list(values),float)
    if not len(values):return {"count":0}
    med=float(np.median(values));a=np.abs(values)
    return {"count":len(values),"median_error_px":med,"mad_error_px":float(np.median(np.abs(values-med))),"median_absolute_error_px":float(np.median(a)),"p95_absolute_error_px":float(np.percentile(a,95)),"maximum_absolute_error_px":float(np.max(a))}

def canonical_consensus(measurements,offsets,cfg):
    estimates={edge:value["y"]+offsets[edge] for edge,value in measurements.items() if value["accepted"]}
    if not estimates:return None,"no_accepted_physical_segment",estimates
    values=list(estimates.values())
    if len(values)>1 and max(values)-min(values)>cfg["cross_edge_consensus_tolerance_px"]:return None,"cross_edge_disagreement",estimates
    return float(np.median(values)),None,estimates

def annotate(canvas,record,measurements,canonical,reason,destination):
    canvas=canvas.convert("RGB");draw=ImageDraw.Draw(canvas);colors={"lower_top":"cyan","upper_bottom":"yellow","lower_bottom":"magenta","upper_top":"lime"}
    for edge,result in measurements.items():
        for segment in result["segments"]:
            if segment["valid"]:draw.line((segment["x0"]-50,segment["y"]-180,segment["x1"]-50,segment["y"]-180),fill=colors[edge],width=3)
    draw.text((8,8),f"frame {record['frame']} {record['final_registration_source']}\n{reason or 'ACCEPT'} canonical={canonical}",fill="white",stroke_width=2,stroke_fill="black");canvas.save(destination,quality=94)

def run(args):
    cfg=json.loads(Path(args.config).read_text());p14_rows=list(csv.DictReader(Path(args.p14_measurements).open()));p14={int(r["frame"]):r for r in p14_rows};p16=json.loads(Path(args.p16_summary).read_text());unresolved=set(p16["unresolved_frames"]);manifest=json.loads(Path(args.manifest).read_text());records={r["frame"]:r for segment in manifest["segments"] for r in segment["frame_records"] if args.first<=r["frame"]<=args.last and r.get("output_disposition")=="included"}
    calibration_frames=sorted(f for f,r in p14.items() if r["source"]=="primary" and f%2==0 and truth(r["lower_top_valid"]));validation_frames=sorted(f for f,r in p14.items() if r["source"]=="primary" and f%2==1 and truth(r["lower_top_valid"]));evaluation_frames=sorted(unresolved);required=calibration_frames+validation_frames+evaluation_frames
    output=Path(args.output_dir);review=output/"review";contexts=output/"review_contexts";review.mkdir(parents=True,exist_ok=True);contexts.mkdir(parents=True,exist_ok=True);calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report);working=output/"developed_working.tif";measured={}
    for index,frame in enumerate(required,1):
        record=records[frame];developer.develop(Path(args.raw_dir)/f"frame_{frame:06d}.dng",working)
        with Image.open(working) as image:
            measured[frame]=measure_partial_edges(image,record["anchor_x"],record["anchor_y"],cfg)
            if frame in unresolved:image.crop((50,180,720,1550)).convert("RGB").save(contexts/f"frame_{frame:06d}.jpg",quality=94,subsampling=0)
        working.unlink(missing_ok=True)
        if index==1 or index%50==0 or index==len(required):print(f"P17 measure {index}/{len(required)}",flush=True)
    recomputed_offsets={edge:float(np.median([float(p14[f]["lower_top_y"])-measured[f][edge]["y"] for f in calibration_frames if measured[f][edge]["accepted"]])) for edge in EDGES}
    offsets=cfg["frozen_edge_offsets_to_lower_top_px"]
    if any(abs(recomputed_offsets[edge]-offsets[edge])>1e-9 for edge in EDGES):raise RuntimeError("frozen P17 edge calibration does not reproduce")
    calibration_counts={edge:sum(measured[f][edge]["accepted"] for f in calibration_frames) for edge in EDGES}
    validation={};false_threshold=cfg["false_error_threshold_px"]
    for edge in EDGES:
        errors=[measured[f][edge]["y"]+offsets[edge]-float(p14[f]["lower_top_y"]) for f in validation_frames if measured[f][edge]["accepted"]]
        validation[edge]={**robust(errors),"truth_frames":len(validation_frames),"unavailable_or_ambiguous":len(validation_frames)-len(errors),"unavailable_or_ambiguous_rate":(len(validation_frames)-len(errors))/len(validation_frames),"false_count_over_3px":sum(abs(e)>false_threshold for e in errors),"false_rate_of_accepted":sum(abs(e)>false_threshold for e in errors)/len(errors) if errors else None}
    qualified_edges=[edge for edge,value in validation.items() if value["count"]>=cfg["minimum_held_out_accepts_to_qualify_edge"] and value["false_rate_of_accepted"]<=cfg["maximum_false_rate_to_qualify_edge"] and value["p95_absolute_error_px"]<=cfg["maximum_p95_error_to_qualify_edge_px"]]
    for edge,value in validation.items():value["qualified_for_unresolved_evaluation"]=edge in qualified_edges
    rows=[];accepted_count=rejected_count=0
    for frame in evaluation_frames:
        record=records[frame];eligible_measurements={edge:value for edge,value in measured[frame].items() if edge in qualified_edges};canonical,reason,estimates=canonical_consensus(eligible_measurements,offsets,cfg);accepted=canonical is not None
        row={"frame":frame,"source":record["final_registration_source"],"accepted":accepted,"canonical_lower_top_y":canonical,"crop_top":None if canonical is None else canonical+cfg["p15_crop_top_minus_lower_top_y"],"decision_reason":reason,"accepted_edge_count":len(estimates),"accepted_edges":";".join(estimates),"canonical_estimates_json":json.dumps(estimates,sort_keys=True)}
        for edge in EDGES:row[f"{edge}_accepted"]=measured[frame][edge]["accepted"];row[f"{edge}_y"]=measured[frame][edge]["y"];row[f"{edge}_segments"]=measured[frame][edge]["accepted_segments"];row[f"{edge}_reason"]=measured[frame][edge]["reason"]
        rows.append(row)
        should_render=(accepted and accepted_count<6) or ((not accepted) and rejected_count<6)
        if should_render:
            with Image.open(contexts/f"frame_{frame:06d}.jpg") as image:annotate(image,record,measured[frame],canonical,reason,review/f"frame_{frame:06d}_{'accepted' if accepted else 'rejected'}.jpg")
            if accepted:accepted_count+=1
            else:rejected_count+=1
    shutil.rmtree(contexts)
    with (output/"recoveries.csv").open("w",newline="") as handle:writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    accepted=[r for r in rows if r["accepted"]];unresolved_rows=[r for r in rows if not r["accepted"]];by_source=Counter(r["source"] for r in accepted);by_edge=Counter(edge for r in accepted for edge in r["accepted_edges"].split(";") if edge)
    reasons=Counter(r["decision_reason"] for r in unresolved_rows)
    summary={"version":cfg["version"],"configuration":cfg,"calibration":{"frames":len(calibration_frames),"accepted_measurements_by_edge":calibration_counts,"frozen_offsets_to_lower_top_px":offsets},"validation":validation,"qualified_edge_types":qualified_edges,"evaluation":{"input_unresolved":len(rows),"recovered":len(accepted),"unresolved":len(unresolved_rows),"resulting_total_coverage":288+len(accepted),"resulting_coverage_percent":100*(288+len(accepted))/351,"recovery_by_source":dict(by_source),"recovery_by_edge":dict(by_edge),"single_edge_recoveries":sum(r["accepted_edge_count"]==1 for r in accepted),"multi_edge_consensus_recoveries":sum(r["accepted_edge_count"]>1 for r in accepted),"unresolved_reasons":dict(reasons),"recovered_frames":[r["frame"] for r in accepted],"unresolved_frames":[r["frame"] for r in unresolved_rows]},"provenance":{"config_sha256":sha256(args.config),"p14_measurements_sha256":sha256(args.p14_measurements),"p16_summary_sha256":sha256(args.p16_summary),"manifest_sha256":sha256(args.manifest)}}
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n");return summary

def main():
    p=argparse.ArgumentParser();p.add_argument("--manifest",default=str(ROOT/"work/Reel_46335_p07_trusted_only_target_2000_2350_20260828/processing_manifest.json"));p.add_argument("--raw-dir",default="/mnt/GrokCam/projects/Reel_46335/raw");p.add_argument("--p14-measurements",default=str(ROOT/"research/output/sprocket_xy/p14_detector_guided_edge_registration/reel_46335_2000_2350/measurements.csv"));p.add_argument("--p16-summary",default=str(ROOT/"research/output/sprocket_xy/p16_calibrated_physical_edge_fallback/reel_46335_2000_2350/summary.json"));p.add_argument("--config",default=str(DEFAULT_CONFIG));p.add_argument("--output-dir",default=str(ROOT/"research/output/sprocket_xy/p17_four_edge_partial_landmark_recovery/reel_46335_2000_2350"));p.add_argument("--first",type=int,default=2000);p.add_argument("--last",type=int,default=2350);a=p.parse_args();print(json.dumps(run(a),indent=2))
if __name__=="__main__":main()
