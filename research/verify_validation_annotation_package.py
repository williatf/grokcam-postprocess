#!/usr/bin/env python3
"""Verify a frozen-prediction validation package without executing inference."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
import cv2,numpy as np,pandas as pd

def main():
 ap=argparse.ArgumentParser();ap.add_argument('package',type=Path);ap.add_argument('results',type=Path);args=ap.parse_args()
 html=(args.package/'annotate.html').read_text();selection=json.loads((args.package/'selection.json').read_text());results=pd.read_csv(args.results).set_index('frame')
 match=re.search(r'const frames=(\[.*?\]), predictions=(\{.*\}), scale=2, roiWidth=120;',html)
 if not match:raise RuntimeError('could not parse embedded frames and predictions')
 frames=json.loads(match.group(1));predictions=json.loads(match.group(2));assert frames==selection['frames'];assert len(frames)==50
 required=['ACCEPT PREDICTIONS',"e.key==='Enter'",'canvas.onpointerdown','canvas.onpointermove',
  'localStorage.getItem','Reviewed: ','prediction_unreviewed','accepted_prediction','corrected_prediction',
  'manual_annotation','not_visible','upper_prediction_available','lower_prediction_available',
  "downloadButton.disabled=n!==frames.length",'confirmation required','Upper detail','Lower detail']
 missing=[token for token in required if token not in html]
 if missing:raise RuntimeError(f'missing UI behavior tokens: {missing}')
 checked=0
 for frame in frames:
  image=cv2.imread(str(args.package/f'roi/frame_{frame:06d}.png'))
  if image is None or image.shape[:2]!=(900,120):raise RuntimeError(f'bad ROI for {frame}')
  row=results.loc[frame]
  for region in ('upper','lower'):
   p=predictions[str(frame)][region];expected=bool(pd.notna(row[f'{region}_x']) and pd.notna(row[f'{region}_y']))
   assert p['available']==expected
   if expected:
    assert abs(p['x']-float(row[f'{region}_x']))<1e-12
    assert abs(p['y']-float(row[f'{region}_y']))<1e-12
   checked+=1
 print(json.dumps({'dataset':selection['dataset'],'frames_verified':len(frames),
  'prediction_records_verified':checked,'first_frame':frames[0],'last_frame':frames[-1],
  'explicit_review_required':True,'download_locked_until_complete':True},indent=2))
if __name__=='__main__':main()
