#!/usr/bin/env python3
"""Evaluate the frozen P19 affirmative Y-residual consensus."""
from __future__ import annotations
import argparse,csv,json
from collections import Counter
from pathlib import Path
import numpy as np

LABEL={"primary":"Primary","physical_pair":"physical-pair","physical_p06":"P06","physical_p07":"P07"}

def metrics(values):
 v=np.asarray(list(values),float)
 if not len(v):return {"count":0}
 a=np.abs(v);m=float(np.median(v))
 return {"count":len(v),"median_bias_px":m,"mad_px":float(np.median(np.abs(v-m))),"median_absolute_error_px":float(np.median(a)),"p95_absolute_error_px":float(np.percentile(a,95)),"max_absolute_error_px":float(max(a)),"over_2_px":int(sum(a>2)),"over_3_px":int(sum(a>3)),"over_5_px":int(sum(a>5))}

def estimate(row,cfg):
 fs=row["features"];name=cfg["reference_feature"];ref=fs[name]
 def affirmative(k,z):
  threshold=.34 if k.endswith("edge") else .25
  return z["strength"]>=threshold and z["strength"]>=z["opposite_strength"] and not z["at_boundary"]
 if not affirmative(name,ref):return None,"reference_not_affirmative",[]
 corroborators=[k for k,z in fs.items() if k!=name and affirmative(k,z) and abs(z["residual_y"]-ref["residual_y"])<=cfg["corroboration_tolerance_px"]]
 if len(corroborators)<cfg["minimum_corroborating_features"]:return None,"uncorroborated_reference",corroborators
 return ref["residual_y"],"accepted",corroborators

def main():
 p=argparse.ArgumentParser();p.add_argument("--valid-evidence",type=Path,required=True);p.add_argument("--missing-evidence",type=Path,required=True);p.add_argument("--p15",type=Path,required=True);p.add_argument("--p18",type=Path,required=True);p.add_argument("--config",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True);a=p.parse_args()
 cfg=json.loads(a.config.read_text());ev=[*map(json.loads,a.valid_evidence.open()),*map(json.loads,a.missing_evidence.open())];truth={int(r["frame"]):r for r in csv.DictReader(a.p15.open()) if r["lower_top_valid"]=="True"};p18={int(r["frame"]):r for r in csv.DictReader(a.p18.open())};rows=[]
 for r in sorted(ev,key=lambda x:x["frame"]):
  n=r["frame"];delta,status,corroborators=estimate(r,cfg);base=p18[n];true=float(truth[n]["lower_top_y"]) if n in truth else None;anchor=float(base["trusted_anchor_y"])
  existing_error=None if true is None else (float(base["existing_error_px"]) if base.get("existing_error_px") not in (None,"") else anchor+260.53694474339045-true)
  p18_error=None if true is None else (float(base["refined_error_px"]) if base.get("refined_error_px") not in (None,"") else float(base["refined_anchor_y"])+260.53905176455373-true)
  rows.append({"frame":n,"source":LABEL[r["source"]],"p15_valid":n in truth,"accepted":delta is not None,"reason":status,"trusted_anchor_y":anchor,"p19_delta_y":delta,"p19_anchor_y":None if delta is None else anchor+delta,"corroborating_count":len(corroborators),"corroborating_features":";".join(corroborators),"true_registration_y":true,"p19_error_px":None if delta is None or true is None else anchor+delta+cfg["anchor_to_true_registration_y_px"]-true,"existing_error_px":existing_error,"p18_error_px":p18_error})
 a.output_dir.mkdir(parents=True,exist_ok=True)
 with (a.output_dir/"measurements.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 valid=[r for r in rows if r["p15_valid"]];accepted=[r for r in valid if r["accepted"]];held=[r for r in accepted if r["frame"]%2];hard=[r for r in rows if not r["p15_valid"]];hard_ok=[r for r in hard if r["accepted"]]
 report={"version":cfg["version"],"frozen_config":cfg,"validation_1":{"coverage":{"accepted":len(accepted),"total":len(valid),"rejected":len(valid)-len(accepted)},"p19":{"overall":metrics(r["p19_error_px"] for r in accepted),"held_out":metrics(r["p19_error_px"] for r in held),"by_source":{s:metrics(r["p19_error_px"] for r in accepted if r["source"]==s) for s in ("Primary","physical-pair","P06","P07")}},"existing_all_284":metrics(r["existing_error_px"] for r in valid),"p18_all_284":metrics(r["p18_error_px"] for r in valid)},"validation_2":{"sufficient_affirmative_y_evidence":len(hard_ok),"rejected":len(hard)-len(hard_ok),"rejection_reasons":dict(Counter(r["reason"] for r in hard if not r["accepted"])),"accepted_frames":[r["frame"] for r in hard_ok],"correction_distribution":({"min":min(r["p19_delta_y"] for r in hard_ok),"median":float(np.median([r["p19_delta_y"] for r in hard_ok])),"max":max(r["p19_delta_y"] for r in hard_ok)} if hard_ok else {}),"search_boundary_hits_accepted":sum(abs(r["p19_delta_y"])==cfg["search_radius_px"] for r in hard_ok),"p18_negative_collapse_eliminated":sum(r["accepted"] and r["p19_delta_y"]<=-10 for r in hard)==0},"known_and_controls":{str(r["frame"]):r for r in rows if r["frame"] in {2003,2082,2093,2097,2144,2240,2242,2161,2162,2146,2147}}}
 (a.output_dir/"summary.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
