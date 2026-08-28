#!/usr/bin/env python3
"""Blue-calibrated research detector for physical sprocket X/Y boundaries."""

from __future__ import annotations

import argparse, csv, json, time
from dataclasses import dataclass, asdict
from pathlib import Path
import av, cv2, numpy as np

@dataclass
class EdgeMeasurement:
    region:str; x:float; y:float; x_strength:float; y_strength:float
    x_prominence:float; y_prominence:float; confidence:float

def subpixel(values:np.ndarray,index:int)->float:
    if not 0<index<len(values)-1:return float(index)
    a,b,c=map(float,values[index-1:index+2]);d=a-2*b+c
    return float(index+(0 if abs(d)<1e-12 else np.clip(.5*(a-c)/d,-.75,.75)))

def prominence(values:np.ndarray,index:int)->float:
    base=float(np.median(values));scale=float(np.median(np.abs(values-base)))+1e-6
    return float((values[index]-base)/scale)

def measure_region(bgr:np.ndarray,region:str,p:dict)->EdgeMeasurement:
    gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
    if p['clahe']:
        gray=cv2.createCLAHE(p['clahe_clip'],tuple(p['clahe_grid'])).apply(gray)
    q=gray.astype(np.float32)/255.0; blur=float(p['blur_sigma'])
    ylo,yhi=p['upper_y_search'] if region=='upper' else p['lower_y_search']
    profile=cv2.GaussianBlur(q[:,p['y_column_start']:p['y_column_end']],(0,0),blur).mean(1)
    yg=np.gradient(profile)*(-1 if region=='upper' else 1)
    yi=int(ylo+np.argmax(yg[ylo:yhi])); y=subpixel(yg,yi)
    margin=int(p['x_vertical_margin'])
    yr=(p['upper_x_y_start'],max(p['upper_x_y_start']+5,int(y-margin))) if region=='upper' else \
       (min(p['lower_x_y_end']-5,int(y+margin)),p['lower_x_y_end'])
    xp=cv2.GaussianBlur(q[yr[0]:yr[1]],(0,0),blur).mean(0);xg=-np.gradient(xp)
    xlo,xhi=p['x_search'];xi=int(xlo+np.argmax(xg[xlo:xhi]));x=subpixel(xg,xi)
    px=prominence(xg[xlo:xhi],xi-xlo);py=prominence(yg[ylo:yhi],yi-ylo)
    confidence=float(np.sqrt(max(0,px)*max(0,py)))
    return EdgeMeasurement(region,x,y,float(xg[xi]),float(yg[yi]),px,py,confidence)

def measure_frame(bgr:np.ndarray,p:dict)->dict:
    u=measure_region(bgr,'upper',p);l=measure_region(bgr,'lower',p)
    ux=u.x-p['bias']['upper_x'];uy=u.y-p['bias']['upper_y']
    lx=l.x-p['bias']['lower_x'];ly=l.y-p['bias']['lower_y']
    dx=lx-ux;dy=ly-uy
    geometry_error_x=dx-p['geometry']['median_dx'];geometry_error_y=dy-p['geometry']['median_dy']
    confidence_ok=(u.confidence>=p['confidence_min']['upper'] and l.confidence>=p['confidence_min']['lower'])
    geometry_ok=(abs(geometry_error_x)<=p['geometry']['tolerance_dx'] and
                 abs(geometry_error_y)<=p['geometry']['tolerance_dy'])
    return {'upper_x':ux,'upper_y':uy,'lower_x':lx,'lower_y':ly,
      'upper_confidence':u.confidence,'lower_confidence':l.confidence,
      'upper_x_prominence':u.x_prominence,'upper_y_prominence':u.y_prominence,
      'lower_x_prominence':l.x_prominence,'lower_y_prominence':l.y_prominence,
      'dx':dx,'dy':dy,'geometry_error_x':geometry_error_x,'geometry_error_y':geometry_error_y,
      'confidence_ok':confidence_ok,'geometry_ok':geometry_ok,'accepted':confidence_ok and geometry_ok,
      'rejection_reason':'' if confidence_ok and geometry_ok else
        ';'.join(x for x,ok in [('low_edge_confidence',confidence_ok),('geometry_disagreement',geometry_ok)] if not ok)}

def main()->None:
    ap=argparse.ArgumentParser();ap.add_argument('video',type=Path);ap.add_argument('config',type=Path)
    ap.add_argument('output',type=Path);ap.add_argument('--first-frame',type=int,default=1);args=ap.parse_args()
    p=json.loads(args.config.read_text());args.output.mkdir(parents=True,exist_ok=True);rows=[];start=time.perf_counter()
    with av.open(str(args.video)) as container:
      for i,frame in enumerate(container.decode(video=0)):
        row={'frame':args.first_frame+i,**measure_frame(frame.to_ndarray(format='bgr24'),p)};rows.append(row)
    elapsed=time.perf_counter()-start
    with (args.output/'detector_results.csv').open('w',newline='') as h:
      w=csv.DictWriter(h,rows[0]);w.writeheader();w.writerows(rows)
    summary={'video':str(args.video),'frames':len(rows),'accepted':sum(r['accepted'] for r in rows),
      'rejected':sum(not r['accepted'] for r in rows),'coverage':sum(r['accepted'] for r in rows)/len(rows),
      'elapsed_seconds':elapsed,'throughput_fps':len(rows)/elapsed,'frozen_config':str(args.config)}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()

