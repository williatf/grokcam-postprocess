#!/usr/bin/env python3
"""Score locked P07 output after the protected human CSV is exported."""
from __future__ import annotations
import csv,hashlib,json,math,statistics,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research.p07_joint_rigid_sprocket_pair_evidence_poc import make_sheets
OUT=ROOT/'research/output/sprocket_xy/p07_frozen_blind_validation'
SOURCE=ROOT/'research/output/sprocket_xy/partner_partial_hole_blind_validation'
GT=OUT/'partner_partial_blind_ground_truth.csv';W=381.5842105263158;H=272.0

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stats(v):
 v=sorted(v);return {'median':statistics.median(v),'p95':float(v[int(.95*(len(v)-1))]),'maximum':max(v)} if v else {}
def point(draw,xy,color,label):
 x,y=xy;draw.ellipse((x-11,y-11,x+11,y+11),outline=color,width=5);draw.line((x-18,y,x+18,y),fill=color,width=3);draw.line((x,y-18,x,y+18),fill=color,width=3);draw.text((x+14,y-22),label,fill=color)
def sheet_or_placeholder(paths,prefix):
 if paths:make_sheets(paths,OUT,prefix)
 else:
  im=Image.new('RGB',(1000,180),'black');ImageDraw.Draw(im).text((20,30),prefix+'\nNONE',fill='white');im.save(OUT/f'{prefix}_01.jpg')
def main():
 lock=json.loads((OUT/'lock_manifest.json').read_text());bad=[r for r,w in lock['files'].items() if sha(OUT/r)!=w]
 if bad:raise SystemExit(f'locked package changed: {bad}')
 gt=list(csv.DictReader(GT.open()));diag={int(r['frame']):r for r in csv.DictReader((OUT/'diagnostics.csv').open())};selection=json.loads((SOURCE/'selection_private.json').read_text());origins=selection['origins'];categories={int(k):v for k,v in selection['categories'].items()}
 if len(gt)!=68 or any(r['submitted'].lower()!='true' for r in gt):raise SystemExit('ground truth incomplete')
 scored=[];scored_dir=OUT/'scored_overlays';scored_dir.mkdir(exist_ok=True)
 for human in gt:
  f=int(human['frame']);corrected=bool(human['post_reveal_json']);v={**human,**(json.loads(human['post_reveal_json']) if corrected else {})};o=origins[str(f)];d=diag[f]
  measurable=v['upper_status']=='measurable' and v['lower_status']=='measurable'
  hu=(float(v['upper_x'])+o['upper'][0]-W/2,float(v['upper_y'])+o['upper'][1]-H/2) if v['upper_status']=='measurable' else None
  hl=(float(v['lower_x'])+o['lower'][0]-W/2,float(v['lower_y'])+o['lower'][1]+H/2) if v['lower_status']=='measurable' else None
  du=math.hypot(float(d['upper_x'])-hu[0],float(d['upper_y'])-hu[1]) if hu else None;dl=math.hypot(float(d['lower_x'])-hl[0],float(d['lower_y'])-hl[1]) if hl else None
  ha=((hu[0]+hl[0])/2-17.125,(hu[1]+hl[1])/2) if measurable else None
  da=math.hypot(float(d['final_anchor_x'])-ha[0],float(d['final_anchor_y'])-ha[1]) if ha and d['accepted']=='True' else None
  accepted=d['accepted']=='True'
  # Fixed before unblinding: <=25 px pair-anchor error is correct; larger is incorrect.
  # An acceptance without two measurable human landmarks is uncertain, not silently correct.
  outcome=('correct_accept' if accepted and measurable and da<=25 else 'incorrect_accept' if accepted and measurable and da>25 else 'uncertain_accept' if accepted else 'false_reject' if measurable else 'correct_reject')
  row={'frame':f,'selection_category':categories[f],'outcome':outcome,'accepted':accepted,'human_corrected_post_reveal':corrected,'upper_status':v['upper_status'],'lower_status':v['lower_status'],'condition':v['condition'],'upper_error':du,'lower_error':dl,'anchor_error':da,'anchor_dx':float(d['final_anchor_x'])-ha[0] if da is not None else None,'anchor_dy':float(d['final_anchor_y'])-ha[1] if da is not None else None,**{k:d[k] for k in ['classification','normal_detector_count','p06_classification','upper_supported','lower_supported','total_supported','missing_count','contradicted_count','geometric_residual','joint_score','competitor_margin','capture_pair_distance','p06_distance','accepted_without_normal_seed']}}
  scored.append(row)
  up=Image.open(OUT/'roi'/f'frame_{f:06d}_upper.png').convert('RGB');lo=Image.open(OUT/'roi'/f'frame_{f:06d}_lower.png').convert('RGB');ud=ImageDraw.Draw(up);ld=ImageDraw.Draw(lo)
  if hu:
   point(ud,(hu[0]-o['upper'][0]+W/2,hu[1]-o['upper'][1]+H/2),'cyan','HUMAN')
  if hl:point(ld,(hl[0]-o['lower'][0]+W/2,hl[1]-o['lower'][1]-H/2),'cyan','HUMAN')
  point(ud,(float(d['upper_x'])+W/2-o['upper'][0],float(d['upper_y'])+H/2-o['upper'][1]),'magenta','P07')
  point(ld,(float(d['lower_x'])+W/2-o['lower'][0],float(d['lower_y'])-H/2-o['lower'][1]),'magenta','P07')
  canvas=Image.new('RGB',(1700,1050),'#090909');q=ImageDraw.Draw(canvas);q.text((15,10),f'FRAME {f:06d}  {outcome}  anchor_error={da if da is not None else "n/a"}',fill='white');up.thumbnail((825,650));lo.thumbnail((825,650));canvas.paste(up,(10,50));canvas.paste(lo,(865,50));base=Image.open(OUT/'panels'/f'frame_{f:06d}.jpg');base.thumbnail((1200,330));canvas.paste(base,(250,715));canvas.save(scored_dir/f'frame_{f:06d}.jpg',quality=92)
 fields=sorted({k for r in scored for k in r});
 with (OUT/'scored_diagnostics.csv').open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(sorted(scored,key=lambda r:r['frame']))
 (OUT/'scored_diagnostics.json').write_text(json.dumps(scored,indent=2)+'\n')
 path=lambda rows:[scored_dir/f"frame_{r['frame']:06d}.jpg" for r in rows]
 accepted=[r for r in scored if r['accepted']];incorrect=[r for r in scored if r['outcome']=='incorrect_accept'];uncertain=[r for r in scored if r['outcome']=='uncertain_accept'];rejects=[r for r in scored if not r['accepted']]
 sheet_or_placeholder(path(incorrect),'20_incorrect_accepts');sheet_or_placeholder(path(uncertain),'21_uncertain_accepts');sheet_or_placeholder(path(rejects),'22_all_rejects');sheet_or_placeholder(path(sorted(accepted,key=lambda r:float(r['competitor_margin']))[:25]),'23_lowest_margins');sheet_or_placeholder(path(sorted(accepted,key=lambda r:float(r['joint_score']))[:25]),'24_weakest_evidence');sheet_or_placeholder(path(sorted(accepted,key=lambda r:r['anchor_error'],reverse=True)[:25]),'25_largest_coordinate_errors');sheet_or_placeholder(path(sorted(accepted,key=lambda r:max(float(r['capture_pair_distance'] or 0),float(r['p06_distance'] or 0)),reverse=True)[:25]),'26_largest_prior_translation');sheet_or_placeholder(path([r for r in accepted if r['accepted_without_normal_seed']=='True']),'27_no_normal_seed');sheet_or_placeholder(path([r for r in scored if r['p06_classification']=='both_holes_damaged_ambiguous']),'28_both_damaged');sheet_or_placeholder(path([r for r in scored if r['condition']=='merged']),'29_bridged_tears');sheet_or_placeholder(path([r for r in scored if r['frame']==3341]),'30_picture_content_challenge');sheet_or_placeholder(path([r for r in scored if r['condition'] in ('capture_problem','out_of_frame') or r['frame']==4600]),'31_transport_capture_failures')
 errors=[r for r in accepted if r['anchor_error'] is not None];outcomes=Counter(r['outcome'] for r in scored);dx=[r['anchor_dx'] for r in errors];dy=[r['anchor_dy'] for r in errors]
 summary={'scored_at':datetime.now(timezone.utc).isoformat(),'detector_package_sha256':lock['package_sha256'],'ground_truth_sha256':sha(GT),'frames':68,'accepted':len(accepted),'rejected':len(rejects),'outcomes':dict(outcomes),'false_accept_rate':len(incorrect)/len(accepted) if accepted else 0,'acceptance_rate':len(accepted)/68,'upper_error':stats([r['upper_error'] for r in scored if r['upper_error'] is not None and r['accepted']]),'lower_error':stats([r['lower_error'] for r in scored if r['lower_error'] is not None and r['accepted']]),'anchor_error':stats([r['anchor_error'] for r in errors]),'anchor_bias':{'mean_dx':statistics.mean(dx),'median_dx':statistics.median(dx),'mean_dy':statistics.mean(dy),'median_dy':statistics.median(dy)},'competitor_margin':stats([float(r['competitor_margin']) for r in accepted]),'support_distribution':dict(Counter(f"{r['upper_supported']}+{r['lower_supported']}" for r in accepted)),'contradiction_distribution':dict(Counter(int(r['contradicted_count']) for r in accepted)),'geometry_residual':stats([float(r['geometric_residual']) for r in accepted]),'no_normal_seed':sum(r['accepted_without_normal_seed']=='True' for r in accepted),'post_reveal_corrections':[r['frame'] for r in scored if r['human_corrected_post_reveal']],'frame_3341':next(r for r in scored if r['frame']==3341),'individual_non_correct_accepts':[r for r in scored if r['outcome']!='correct_accept'],'scoring_rule':{'correct_accept':'both human landmarks measurable and pair-anchor Euclidean error <=25 px','incorrect_accept':'both measurable and pair-anchor error >25 px','uncertain_accept':'accepted without two measurable human landmarks'}}
 (OUT/'blind_validation_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 (OUT/'unblind_audit.json').write_text(json.dumps({'detector_locked_at':lock['locked_at'],'detector_package_sha256':lock['package_sha256'],'locked_detector_files_verified':len(lock['files']),'ground_truth_sha256':sha(GT),'ground_truth_rows':len(gt),'all_rows_submitted':True,'post_reveal_corrections_used':[r['frame'] for r in scored if r['human_corrected_post_reveal']],'scored_at':summary['scored_at'],'frozen_detector_modified':False},indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
