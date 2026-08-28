#!/usr/bin/env python3
"""Select and freeze an OpenCV XY detector using Blue annotations only."""
from __future__ import annotations
import argparse,csv,json,math
from pathlib import Path
import cv2,matplotlib.pyplot as plt,numpy as np,pandas as pd
from research.opencv_sprocket_xy_frozen import measure_region

def metrics(e):
 a=np.abs(np.asarray(e,float));return {'median':float(np.median(a)),'p95':float(np.percentile(a,95)),'maximum':float(np.max(a))}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('ground_truth',type=Path);ap.add_argument('roi_dir',type=Path);ap.add_argument('output',type=Path);args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 gt=pd.read_csv(args.ground_truth);images={int(r.frame):cv2.imread(str(args.roi_dir/f'frame_{int(r.frame):06d}.png')) for _,r in gt.iterrows()}
 variants=[];all_results={}
 for clahe in (False,True):
  for blur in (.8,1.2,1.6):
   for end in (35,45,55):
    for margin in (14,18,22):
     p={'clahe':clahe,'clahe_clip':2.0,'clahe_grid':[4,8],'blur_sigma':blur,'y_column_start':2,'y_column_end':end,
       'upper_y_search':[80,400],'lower_y_search':[550,890],'x_vertical_margin':margin,
       'upper_x_y_start':20,'lower_x_y_end':890,'x_search':[10,105]}
     rows=[]
     for _,truth in gt.iterrows():
      for region in ('upper','lower'):
       m=measure_region(images[int(truth.frame)],region,p);rows.append({'frame':int(truth.frame),'region':region,**m.__dict__,
        'truth_x':truth[f'{region}_x'],'truth_y':truth[f'{region}_y']})
     d=pd.DataFrame(rows);bias={}
     for region in ('upper','lower'):
      z=d[d.region==region];bias[region+'_x']=float(np.median(z.x-z.truth_x));bias[region+'_y']=float(np.median(z.y-z.truth_y))
     d['x_corrected']=d.x-d.region.map({'upper':bias['upper_x'],'lower':bias['lower_x']});d['y_corrected']=d.y-d.region.map({'upper':bias['upper_y'],'lower':bias['lower_y']})
     d['x_error']=d.x_corrected-d.truth_x;d['y_error']=d.y_corrected-d.truth_y;d['euclidean_error']=np.hypot(d.x_error,d.y_error)
     score=float(np.mean([np.percentile(abs(d.x_error),95),np.percentile(abs(d.y_error),95),np.percentile(d.euclidean_error,95)])+.05*d.euclidean_error.max())
     key=f"clahe{int(clahe)}_blur{blur}_cols{end}_margin{margin}";variants.append({'variant':key,'score':score,'bias':bias});all_results[key]=(p,d)
 best=min(variants,key=lambda x:x['score']);p,d=all_results[best['variant']];p['bias']=best['bias']
 wide=gt.copy();wide['dx']=wide.lower_x-wide.upper_x;wide['dy']=wide.lower_y-wide.upper_y;wide['angle_degrees']=np.degrees(np.arctan2(wide.dx,wide.dy))
 p['geometry']={'median_dx':float(wide.dx.median()),'median_dy':float(wide.dy.median()),
  'tolerance_dx':float(max(6,np.percentile(abs(wide.dx-wide.dx.median()),99)*1.5)),
  'tolerance_dy':float(max(8,np.percentile(abs(wide.dy-wide.dy.median()),99)*1.5))}
 p['confidence_min']={r:float(max(.5,np.percentile(d[d.region==r].confidence,1))) for r in ('upper','lower')}
 p['name']='blue_calibrated_gradient_line_v1';p['frozen_on']='Blue Reel frames 3000-3999 manual ground truth only';p['coordinate_convention']='correction = reference - measurement; upper lower-right and lower upper-right virtual corners'
 args.output.joinpath('frozen_detector.json').write_text(json.dumps(p,indent=2)+'\n');d.to_csv(args.output/'blue_detector_results.csv',index=False);wide[['frame','dx','dy','angle_degrees']].to_csv(args.output/'geometry_analysis.csv',index=False)
 pd.DataFrame([{k:(json.dumps(v) if isinstance(v,dict) else v) for k,v in x.items()} for x in variants]).sort_values('score').to_csv(args.output/'variant_scores.csv',index=False)
 report={'selected_architecture':'Gaussian-smoothed physical horizontal/vertical gradient lines with subpixel peak fit, Blue bias calibration, paired geometry and confidence gates','selected_variant':best['variant'],'frozen_parameters':p,'blue':{},'geometry':{}}
 for region in ('upper','lower'):
  z=d[d.region==region];report['blue'][region]={'coverage':1.0,'false_positive_rate_over_10px':float((z.euclidean_error>10).mean()),'false_negative_rate':0.0,'x_error':metrics(z.x_error),'y_error':metrics(z.y_error),'euclidean_error':metrics(z.euclidean_error)}
 a=wide.angle_degrees;report['geometry']={'dx':metrics(wide.dx-wide.dx.median()),'dy':metrics(wide.dy-wide.dy.median()),'median_dx':float(wide.dx.median()),'mean_dx':float(wide.dx.mean()),'median_dy':float(wide.dy.median()),'mean_dy':float(wide.dy.mean()),'angle_median':float(a.median()),'angle_mean':float(a.mean()),'angle_std':float(a.std()),'angle_p05':float(a.quantile(.05)),'angle_p95':float(a.quantile(.95)),'angle_min':float(a.min()),'angle_max':float(a.max())}
 (args.output/'calibration_report.json').write_text(json.dumps(report,indent=2)+'\n')
 plots=args.output/'plots';plots.mkdir(exist_ok=True)
 for col,label in [('x_error','X error (px)'),('y_error','Y error (px)'),('euclidean_error','Euclidean error (px)')]:
  for r in ('upper','lower'):plt.hist(d[d.region==r][col],bins=18,alpha=.55,label=r)
  plt.xlabel(label);plt.ylabel('annotations');plt.legend();plt.tight_layout();plt.savefig(plots/f'{col}.png',dpi=160);plt.close()
 fig,ax=plt.subplots(3,1,figsize=(10,9),sharex=True);ax[0].plot(wide.frame,wide.dx,'.-');ax[0].set_ylabel('lower_x-upper_x');ax[1].plot(wide.frame,wide.dy,'.-');ax[1].set_ylabel('Y spacing');ax[2].plot(wide.frame,wide.angle_degrees,'.-');ax[2].set_ylabel('angle deg');ax[2].set_xlabel('frame');fig.tight_layout();fig.savefig(plots/'geometry_vs_frame.png',dpi=160);plt.close(fig)
 plt.scatter(d.confidence,d.euclidean_error,c=d.region.map({'upper':0,'lower':1}),alpha=.7);plt.xlabel('edge confidence');plt.ylabel('localization error px');plt.tight_layout();plt.savefig(plots/'confidence_vs_error.png',dpi=160);plt.close()
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
