#!/usr/bin/env python3
"""Read-only audit of a production batch stopped by conservative P07 policy."""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.physical_sprocket import detect_fallback,load_capture_metadata
from grokcam.sprocket_detection import _batch_acceptance,detect

def number(path):return int(path.stem.rsplit('_',1)[1])
def main():
 p=argparse.ArgumentParser();p.add_argument('tiff_dir',type=Path);p.add_argument('raw_dir',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 paths=sorted(a.tiff_dir.glob('frame_*.tif'),key=number);cal=load_calibration();capture=load_capture_metadata(a.raw_dir);primary=[]
 for path in paths:
  with Image.open(path) as image:
   try:primary.append(detect(image,cal.detector))
   except ValueError:primary.append(None)
 _,detected,accepted=_batch_acceptance(primary,cal.detector);rows=[]
 for index,path in enumerate(paths):
  if accepted[index]:continue
  with Image.open(path) as image:result=detect_fallback(image,capture.get(number(path)))
  rows.append({'frame':number(path),'primary_detected':bool(detected[index]),'fallback_accepted':result.accepted,'classification':result.classification,'stage':result.diagnostics.get('stage'),'diagnostics':result.diagnostics})
 unresolved=[r for r in rows if not r['fallback_accepted']];a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'batch':[number(paths[0]),number(paths[-1])],'fallback_frames':rows,'unresolved':unresolved},indent=2)+'\n');print(json.dumps({'fallback_count':len(rows),'unresolved':[(r['frame'],r['classification']) for r in unresolved]},indent=2))
if __name__=='__main__':main()
