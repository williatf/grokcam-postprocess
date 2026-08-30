#!/usr/bin/env python3
"""Analyze the frozen P23 run and render its predeclared contiguous populations."""
from __future__ import annotations
import csv,json,sys,tempfile
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.encoding import encode_segment,file_sha256,verify_video
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.normalization import normalize_frames
from grokcam.raw_development import DarktableMatchedDeveloper
OFFSET=4.17878784687116
LOWER_TOP_TO_CROP_TOP=-673.5297914597816

def boolean(v): return str(v).lower()=='true'
def number(v): return None if v in ('',None,'None') else float(v)
def metrics(values):
 v=np.asarray(list(values),float); a=np.abs(v); med=float(np.median(v))
 return {'n':len(v),'median_error_px':med,'mad_px':float(np.median(np.abs(v-med))),
  'median_absolute_error_px':float(np.median(a)),'p90_absolute_error_px':float(np.percentile(a,90)),
  'p95_absolute_error_px':float(np.percentile(a,95)),'p99_absolute_error_px':float(np.percentile(a,99)),
  'maximum_absolute_error_px':float(max(a)),**{f'over_{q}_px':int(sum(a>q)) for q in (1,2,3,5)}}

def main():
 cfg=json.loads((ROOT/'research/config/p23_independent_validation_freeze.json').read_text())
 source=ROOT/'work/p23_independent_validation'; out=ROOT/'work/Reel_P23_independent_validation'; out.mkdir(parents=True,exist_ok=True)
 rows=[]
 for pop in cfg['populations']:
  path=source/f"{pop['id']}.csv"
  for r in csv.DictReader(path.open()):
   for k in ('p15_valid','p07_accepted','p22_completed','p22_boundary_hit','p22_shallow'): r[k]=boolean(r[k])
   for k in ('p15_lower_top_y','p07_model_lower_top_y','p22_shift_y','p22_refined_model_lower_top_y','p22_calibrated_register_y','p22_local_margin_1px','p22_score_range','p07_joint_score','p07_competitor_margin','authoritative_register_y'): r[k]=number(r[k])
   r['frame']=int(r['frame']);r['error_px']=None if not (r['p15_valid'] and r['p07_accepted']) else r['p22_calibrated_register_y']-r['p15_lower_top_y'];rows.append(r)
 fields=list(rows[0]);
 with (out/'measurements.csv').open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
 overlap=[r for r in rows if r['error_px'] is not None];pops={}
 for pop in cfg['populations']:
  rr=[r for r in rows if r['population_id']==pop['id']];oo=[r for r in rr if r['error_px'] is not None];miss=[r for r in rr if not r['p15_valid']]
  pops[pop['id']]={'total':len(rr),'p15_successes':sum(r['p15_valid'] for r in rr),'p15_misses':len(miss),'p07_accepted_on_p15_valid':sum(r['p15_valid'] and r['p07_accepted'] for r in rr),'overlap':metrics(r['error_px'] for r in oo),'independent_median_model_to_p15_offset_px':float(np.median([r['p15_lower_top_y']-r['p22_refined_model_lower_top_y'] for r in oo])),'fallback_attempts':len(miss),'fallback_accepts':sum(r['p07_accepted'] for r in miss),'fallback_rejects':sum(not r['p07_accepted'] for r in miss),'final_coverage':sum(r['authoritative_source']!='unresolved' for r in rr),'unresolved_frames':[r['frame'] for r in rr if r['authoritative_source']=='unresolved']}
 shifts=np.array([r['p22_shift_y'] for r in rows if r['p22_completed']]); shallow=[r for r in overlap if r['p22_shallow']];non=[r for r in overlap if not r['p22_shallow']]
 fallback=[r for r in rows if not r['p15_valid']]
 failures=[r for r in overlap if abs(r['error_px'])>2]
 summary={'frozen':cfg,'populations':pops,'overall':{'total':len(rows),'p15_successes':sum(r['p15_valid'] for r in rows),'p15_misses':sum(not r['p15_valid'] for r in rows),'p07_accepted':sum(r['p07_accepted'] for r in rows),'overlap':metrics(r['error_px'] for r in overlap),'independent_median_model_to_p15_offset_px':float(np.median([r['p15_lower_top_y']-r['p22_refined_model_lower_top_y'] for r in overlap])),'frozen_offset_px':OFFSET,'median_offset_difference_px':float(np.median([r['p15_lower_top_y']-r['p22_refined_model_lower_top_y'] for r in overlap]))-OFFSET,'final_coverage':sum(r['authoritative_source']!='unresolved' for r in rows)},'refinement':{'n':len(shifts),'median_shift_px':float(np.median(shifts)),'mad_shift_px':float(np.median(abs(shifts-np.median(shifts)))),'p5_px':float(np.percentile(shifts,5)),'p95_px':float(np.percentile(shifts,95)),'min_px':float(min(shifts)),'max_px':float(max(shifts)),'boundary_hits':sum(r['p22_boundary_hit'] for r in rows),'exact_ties':sum(int(float(r['p22_maximum_tie_count']))>1 for r in rows),'shallow_flags':sum(r['p22_shallow'] for r in rows),'shift_histogram':dict(Counter(str(x) for x in shifts))},'shallow_diagnostic':{'shallow':metrics(r['error_px'] for r in shallow),'non_shallow':metrics(r['error_px'] for r in non),'shallow_accurate_le_1_px':[{'population':r['population_id'],'frame':r['frame'],'error_px':r['error_px']} for r in shallow if abs(r['error_px'])<=1]},'fallback_rows':fallback,'failure_rows_over_2px':failures,'movies':{}}
 cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);audit=out/'audit';audit.mkdir(exist_ok=True)
 audit_rows={f"{r['population_id']}:{r['frame']}":r for r in failures+fallback+[r for r in rows if r['p22_boundary_hit'] or abs(r['p22_shift_y'])>=2.5 or int(float(r['p22_maximum_tie_count']))>1]}
 with tempfile.TemporaryDirectory(prefix='p23_audit_',dir=ROOT/'work') as td:
  tif=Path(td)/'developed.tif'
  for key,r in audit_rows.items():
   pop=next(p for p in cfg['populations'] if p['id']==r['population_id']);dev.develop(Path(pop['raw_dir'])/f"frame_{r['frame']:06d}.dng",tif)
   with Image.open(tif) as im:
    x=int(float(r['p07_upper_x'])-90); y=int(min(r['p15_lower_top_y'] or r['p22_calibrated_register_y'],r['p22_calibrated_register_y'])-80); panel=im.crop((x,y,x+420,y+240)).convert('RGB');d=ImageDraw.Draw(panel)
    py=r['p15_lower_top_y'];qy=r['p22_calibrated_register_y'];
    if py is not None:d.line((0,py-y,419,py-y),fill=(0,255,255),width=2)
    d.line((0,qy-y,419,qy-y),fill=(255,0,255),width=2);d.rectangle((0,0,419,26),fill='black');d.text((5,6),f"{r['population_id']} {r['frame']} err={r['error_px']}",fill='white');panel.save(audit/f"{r['population_id']}_{r['frame']}.jpg",quality=95)
 for pop in cfg['populations']:
  rr=[r for r in rows if r['population_id']==pop['id']]
  with tempfile.TemporaryDirectory(prefix='p23_render_',dir=ROOT/'work') as td:
   td=Path(td);reg=td/'registered';norm=td/'normalized';reg.mkdir();tif=td/'developed.tif'
   for i,r in enumerate(rr,1):
    dev.develop(Path(pop['raw_dir'])/f"frame_{r['frame']:06d}.dng",tif)
    with Image.open(tif) as im: frame=registered_frame(im,CropGeometry((float(r['p07_upper_x'])+float(r['p07_lower_x']))/2-17.125+159,r['authoritative_register_y']+LOWER_TOP_TO_CROP_TOP,cal.crop.width,cal.crop.height),cal.contrast)
    d=ImageDraw.Draw(frame);d.rectangle((0,0,330,32),fill='black');d.text((8,8),f"{r['reel']} {r['frame']} Y={r['authoritative_source']}",fill='white');frame.save(reg/f"frame_{r['frame']:06d}.jpg",quality=95,subsampling=0)
    if i%50==0: print(f"render {pop['id']} {i}/{len(rr)}",flush=True)
   _,target=normalize_frames(sorted(reg.glob('*.jpg')),norm,None);movie=out/f"{pop['id']}_p15_first_p22_fallback_16fps.mp4";tmp=movie.with_suffix('.tmp.mp4');encode_segment(Path('/usr/bin/ffmpeg'),norm,tmp,pop['first'],pop['frames'],16);verification=verify_video(Path('/usr/bin/ffmpeg'),Path('/usr/bin/ffprobe'),tmp,pop['frames']);tmp.replace(movie);summary['movies'][pop['id']]={'path':str(movie.resolve()),'sha256':file_sha256(movie),'bytes':movie.stat().st_size,'normalization_target_luma':target,'verification':verification}
 (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'output':str(out),'movies':summary['movies']},indent=2))
if __name__=='__main__':main()
