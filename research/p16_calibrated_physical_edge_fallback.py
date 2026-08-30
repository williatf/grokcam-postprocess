#!/usr/bin/env python3
"""P16 calibrated upper-bottom fallback analysis over frozen P14/P15 data."""
from __future__ import annotations

import argparse,csv,hashlib,json
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_CONFIG=ROOT/"research/config/p16_calibrated_physical_edge_fallback.json"


def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def truth(value): return str(value).lower()=="true"


def stats(values):
    values=np.asarray(list(values),float)
    if not len(values): return {"count":0}
    med=float(np.median(values)); absolute=np.abs(values)
    return {"count":len(values),"median_error_px":med,"mad_error_px":float(np.median(np.abs(values-med))),"median_absolute_error_px":float(np.median(absolute)),"p95_absolute_error_px":float(np.percentile(absolute,95)),"maximum_absolute_error_px":float(np.max(absolute))}


def analyze(rows,cfg):
    offset=cfg["lower_top_minus_upper_bottom_px"]; crop_offset=cfg["p15_crop_top_minus_lower_top_y"]
    output=[]
    for row in rows:
        frame=int(row["frame"]); lower=truth(row["lower_top_valid"]); upper=truth(row["upper_bottom_valid"])
        inferred=float(row["upper_bottom_y"])+offset if upper else None
        error=inferred-float(row["lower_top_y"]) if upper and lower else None
        fallback=not lower and upper
        output.append({"frame":frame,"source":row["source"],"p15_lower_top_valid":lower,"upper_bottom_valid":upper,"measured_lower_top_y":row["lower_top_y"] or None,"upper_bottom_y":row["upper_bottom_y"] or None,"inferred_lower_top_y":inferred,"inference_error_px":error,"p16_fallback_accepted":fallback,"p16_crop_top":inferred+crop_offset if fallback else None,"final_poc_source":"p15_lower_top" if lower else ("p16_upper_bottom" if fallback else "unresolved")})
    calibration=[r for r in output if r["source"]=="primary" and r["p15_lower_top_valid"] and r["upper_bottom_valid"] and r["frame"]%2==0]
    held_primary=[r for r in output if r["source"]=="primary" and r["p15_lower_top_valid"] and r["upper_bottom_valid"] and r["frame"]%2==1]
    validation={"held_out_primary":stats(r["inference_error_px"] for r in held_primary),"by_source":{}}
    for source in sorted({r["source"] for r in output}):
        group=[r for r in output if r["source"]==source and r["p15_lower_top_valid"] and r["upper_bottom_valid"] and not (source=="primary" and r["frame"]%2==0)]
        validation["by_source"][source]=stats(r["inference_error_px"] for r in group)
    missing=[r for r in output if not r["p15_lower_top_valid"]]; recovered=[r for r in missing if r["p16_fallback_accepted"]]; unresolved=[r for r in missing if not r["p16_fallback_accepted"]]
    source_missing=Counter(r["source"] for r in missing); source_recovered=Counter(r["source"] for r in recovered)
    summary={"version":cfg["version"],"frozen_calibration":cfg,"calibration_verification":{"actual_frame_count":len(calibration),"recomputed_offset_px":float(np.median([float(next(x for x in rows if int(x["frame"])==r["frame"])["lower_top_y"])-float(next(x for x in rows if int(x["frame"])==r["frame"])["upper_bottom_y"]) for r in calibration]))},"validation":validation,"fallback":{"p15_missing_frames":len(missing),"recovered":len(recovered),"recovery_percent":100*len(recovered)/len(missing),"by_source":{s:{"missing":source_missing[s],"recovered":source_recovered[s]} for s in sorted(source_missing)},"recovered_frames":[r["frame"] for r in recovered]},"combined_coverage":{"p15":sum(r["p15_lower_top_valid"] for r in output),"p16_added":len(recovered),"total":len(output),"covered":len(output)-len(unresolved),"percent":100*(len(output)-len(unresolved))/len(output)},"unresolved_frames":[r["frame"] for r in unresolved]}
    return output,summary


def evaluate_lower_bottom(p14_rows,p09_rows,cfg):
    p09={int(r["frame"]):r for r in p09_rows}; offset=-cfg["exploratory_lower_bottom_minus_lower_top_px"]
    results=[]
    for row in p14_rows:
        frame=int(row["frame"]); candidate=p09[frame]; lower=truth(row["lower_top_valid"]); valid=truth(candidate["lower_bottom_valid"])
        error=float(candidate["lower_bottom_y"])+offset-float(row["lower_top_y"]) if lower and valid else None
        results.append({"frame":frame,"source":row["source"],"p15_valid":lower,"candidate_valid":valid,"error":error})
    validation={}
    for source in sorted({r["source"] for r in results}):
        group=[r for r in results if r["source"]==source and r["error"] is not None and not (source=="primary" and r["frame"]%2==0)]
        validation[source]=stats(r["error"] for r in group)
    recovered=[r["frame"] for r in results if not r["p15_valid"] and r["candidate_valid"]]
    return {"landmark":"lower_sprocket_bottom","calibration":"even clean Primary frames only","lower_top_minus_candidate_px":offset,"validation_by_source":validation,"candidate_missing_frame_recoveries":recovered,"candidate_recovery_count":len(recovered),"accepted_for_fallback":False,"rejection_reason":"Only four candidates and held-out P07 errors reached 8.40 px; insufficiently reliable for registration."}


def run(args):
    config_path=Path(args.config); measurement_path=Path(args.p14_measurements); p09_path=Path(args.p09_measurements); cfg=json.loads(config_path.read_text()); rows=list(csv.DictReader(measurement_path.open())); p09_rows=list(csv.DictReader(p09_path.open())); output=Path(args.output_dir); output.mkdir(parents=True,exist_ok=True); detailed,summary=analyze(rows,cfg); summary["secondary_candidate_evaluation"]=evaluate_lower_bottom(rows,p09_rows,cfg); summary["provenance"]={"config":str(config_path.resolve()),"config_sha256":sha256(config_path),"p14_measurements":str(measurement_path.resolve()),"p14_measurements_sha256":sha256(measurement_path),"p09_measurements":str(p09_path.resolve()),"p09_measurements_sha256":sha256(p09_path),"dngs_developed":0,"note":"Reused frozen P14/P09 measurements; no image development or detector rerun."}
    with (output/"measurements.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(detailed[0]));writer.writeheader();writer.writerows(detailed)
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n");return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--p14-measurements",default=str(ROOT/"research/output/sprocket_xy/p14_detector_guided_edge_registration/reel_46335_2000_2350/measurements.csv"));parser.add_argument("--p09-measurements",default=str(ROOT/"research/output/sprocket_xy/p09_sprocket_y_landmark_metrology/reel_46335_2000_2350/measurements.csv"));parser.add_argument("--config",default=str(DEFAULT_CONFIG));parser.add_argument("--output-dir",default=str(ROOT/"research/output/sprocket_xy/p16_calibrated_physical_edge_fallback/reel_46335_2000_2350"));args=parser.parse_args();print(json.dumps(run(args),indent=2))
if __name__=="__main__":main()
