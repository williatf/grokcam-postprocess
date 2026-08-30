#!/usr/bin/env python3
"""Create the predeclared P24/P25 retrospective-P07 sample without using P07 outcomes."""
from __future__ import annotations
import argparse,json
from pathlib import Path

INTERVAL=10
BOUNDARY_CASES_PER_METRIC=3

def main():
 p=argparse.ArgumentParser();p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 data=json.loads(a.manifest.read_text());records=[r for s in data['segments'] for r in s.get('frame_records',[])]
 rescued=[r for r in records if r.get('final_registration_source')=='p24_capture_p15']
 selected={}
 def add(r,reason):selected.setdefault(int(r['frame']),[]).append(reason)
 for i,r in enumerate(sorted(rescued,key=lambda x:x['frame'])):
  if i%INTERVAL==0:add(r,f'every_{INTERVAL}th_rescue')
 metrics={
  'pitch_low':lambda p:abs(p['capture_pitch']-740.0),'pitch_high':lambda p:abs(p['capture_pitch']-835.0),
  'width_min':lambda p:min(p['capture_upper'][2],p['capture_lower'][2])-350.0,
  'height_low':lambda p:min(p['capture_upper'][3],p['capture_lower'][3])-250.0,
  'height_high':lambda p:340.0-max(p['capture_upper'][3],p['capture_lower'][3]),
  'height_difference':lambda p:p['capture_height_difference']-20.0,
  'x_displacement':lambda p:30.0-abs(p['capture_x_displacement']),
  'y_agreement':lambda p:8.0-p['capture_physical_y_disagreement'],
  'upper_fit_score':lambda p:.30-p['physical_holes'][0]['score'],
  'lower_fit_score':lambda p:.30-p['physical_holes'][1]['score'],
 }
 for name,fn in metrics.items():
  ranked=sorted(rescued,key=lambda r:fn(r['registration_diagnostics']['p24']))
  for r in ranked[:BOUNDARY_CASES_PER_METRIC]:add(r,'nearest_'+name)
 output={'policy':{'interval':INTERVAL,'boundary_cases_per_metric':BOUNDARY_CASES_PER_METRIC,
   'selection_uses_p07':False},'rescue_count':len(rescued),'sample_count':len(selected),
   'frames':[{'frame':n,'reasons':reasons} for n,reasons in sorted(selected.items())]}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(output,indent=2)+'\n')
 print(json.dumps({'rescues':len(rescued),'sample':len(selected),'output':str(a.output)},indent=2))
if __name__=='__main__':main()
