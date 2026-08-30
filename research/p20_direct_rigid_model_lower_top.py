#!/usr/bin/env python3
"""P20 direct stored rigid-model lower-top versus frozen P15."""
from __future__ import annotations
import argparse,csv,json
from collections import Counter
from pathlib import Path
import numpy as np

HOLE_HEIGHT=272.0
PITCH=785.0
LABEL={"physical_p06":"P06","physical_p07":"P07"}
KNOWN={2003,2082,2093,2097,2144,2240,2242,2161,2162,2146,2147}

def raw_delta_stats(values):
 v=np.asarray(list(values),float);med=float(np.median(v));a=np.abs(v-med)
 return {"n":len(v),"median_delta_px":med,"mad_px":float(np.median(a)),"median_absolute_residual_px":float(np.median(a)),"p95_absolute_residual_px":float(np.percentile(a,95)),"max_absolute_residual_px":float(max(a)),"over_1_px":int(sum(a>1)),"over_2_px":int(sum(a>2)),"over_3_px":int(sum(a>3)),"over_5_px":int(sum(a>5))}

def error_stats(values):
 v=np.asarray(list(values),float);a=np.abs(v);med=float(np.median(v))
 return {"n":len(v),"median_error_px":med,"mad_px":float(np.median(np.abs(v-med))),"median_absolute_error_px":float(np.median(a)),"p95_absolute_error_px":float(np.percentile(a,95)),"max_absolute_error_px":float(max(a)),"over_1_px":int(sum(a>1)),"over_2_px":int(sum(a>2)),"over_3_px":int(sum(a>3)),"over_5_px":int(sum(a>5))}

def model_lower_top(record):
 source=record["final_registration_source"];d=record.get("physical_diagnostics") or {}
 if source=="physical_p07":
  return float(d["lower_center"][1])-HOLE_HEIGHT/2,"stored P07 fixed-template lower_center_y - fixed_height/2"
 if source=="physical_p06":
  py=float(d["partner_center"][1]);lower=py if py>800 else py+PITCH
  return lower-HOLE_HEIGHT/2,"P06 fitted partner template propagated to rigid lower center by fixed pitch when partner is upper, then - fixed_height/2"
 return None,{"primary":"no rigid-template pair geometry","physical_pair":"two independent segmented holes; variable measured size/pitch, not the fixed rigid template"}.get(source,"no comparable rigid model")

def main():
 p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--p15",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);a=p.parse_args()
 m=json.loads(a.manifest.read_text());records=sorted((r for s in m["segments"] for r in s["frame_records"] if 2000<=int(r["frame"])<=2350),key=lambda r:int(r["frame"]));truth={int(r["frame"]):float(r["lower_top_y"]) for r in csv.DictReader(a.p15.open()) if r["lower_top_valid"]=="True"};rows=[]
 for r in records:
  n=int(r["frame"]);model,derivation=model_lower_top(r);p15=truth.get(n);rows.append({"frame":n,"source":LABEL.get(r["final_registration_source"],r["final_registration_source"]),"genuine_rigid_model":model is not None,"derivation":derivation,"model_lower_top_y":model,"p15_valid":p15 is not None,"p15_lower_top_y":p15,"raw_delta_px":None if model is None or p15 is None else p15-model})
 comparable=[r for r in rows if r["genuine_rigid_model"] and r["p15_valid"]];train=[r for r in comparable if r["frame"]%2==0];offset=float(np.median([r["raw_delta_px"] for r in train]))
 for r in rows:r["calibrated_lower_top_y"]=None if not r["genuine_rigid_model"] else r["model_lower_top_y"]+offset;r["calibrated_error_px"]=None if not r["genuine_rigid_model"] or not r["p15_valid"] else r["calibrated_lower_top_y"]-r["p15_lower_top_y"]
 held=[r for r in comparable if r["frame"]%2];hard=[r for r in rows if not r["p15_valid"] and r["genuine_rigid_model"]]
 a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/"measurements.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 report={"scope":{"frames":351,"p15_valid":284,"comparable_p15_valid":len(comparable)},"source_geometry":{"Primary":"No comparable rigid pair. Primary stores thresholded bright-band center only.","physical-pair":"No comparable rigid pair. It stores two independently segmented centers with measured, variable dimensions and pitch.","P06":"One fixed template is fitted to the damaged partner. The genuine implied rigid pair is propagated from that fitted partner using fixed 785 px pitch and 272 px height; the independent seed center is not substituted.","P07":"Stores fixed-template upper/lower centers directly; lower top is lower_center_y - 136 px."},"fixed_geometry":{"hole_height_px":HOLE_HEIGHT,"pitch_px":PITCH},"raw_delta_by_source":{s:raw_delta_stats(r["raw_delta_px"] for r in comparable if r["source"]==s) for s in ("P06","P07")},"calibration":{"population":"even-numbered comparable P06/P07 P15-valid frames","n":len(train),"fixed_offset_px":offset},"held_out":{"population":"odd-numbered comparable P06/P07 P15-valid frames","overall":error_stats(r["calibrated_error_px"] for r in held),"by_source":{s:error_stats(r["calibrated_error_px"] for r in held if r["source"]==s) for s in ("P06","P07")}},"calibrated_all_by_source":{s:error_stats(r["calibrated_error_px"] for r in comparable if r["source"]==s) for s in ("P06","P07")},"known_and_controls":{str(r["frame"]):r for r in rows if r["frame"] in KNOWN},"hard_frames":{"genuine_p06_p07_models":len(hard),"source_breakdown":dict(Counter(r["source"] for r in hard)),"model_lower_top_distribution_px":{"min":min(r["model_lower_top_y"] for r in hard),"median":float(np.median([r["model_lower_top_y"] for r in hard])),"max":max(r["model_lower_top_y"] for r in hard)},"p15_equivalent_requires_beyond_frozen_offset":False,"accuracy_claimed":False,"frames":[r["frame"] for r in hard]}}
 (a.output_dir/"summary.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
