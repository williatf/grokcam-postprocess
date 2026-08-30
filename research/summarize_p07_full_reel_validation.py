#!/usr/bin/env python3
"""Build the audit package for a complete or conservatively stopped P07 run."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def write_csv(path,rows):
 fields=sorted({k for row in rows for k in row}) if rows else ['frame'];
 with path.open('w',newline='') as h:w=csv.DictWriter(h,fields);w.writeheader();w.writerows(rows)

def main():
 p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();d=a.directory
 manifest=json.loads((d/'processing_manifest.json').read_text());segments=manifest.get('segments',[]);records=sorted([r for s in segments for r in s.get('frame_records',[])],key=lambda r:r['frame']);by={r['frame']:r for r in records};sources=Counter(r.get('final_registration_source','unknown') for r in records)
 primary_accepted=sum(r.get('final_registration_source')=='primary' for r in records);primary_failed=len(records)-primary_accepted
 counts={'selected_reel_frames':manifest['frame_count'],'completed_frames':len(records),'verified_segments':len(segments),'primary_accepted':primary_accepted,'primary_rejected_or_missing':primary_failed,'clean_bypassed_fallback':primary_accepted,'physical_pair_recoveries':sources['physical_pair'],'p06_attempted':sum(r.get('p06_attempted',False) for r in records),'p06_accepted':sum(r.get('p06_accepted',False) for r in records),'p06_rejected':sum(r.get('p06_attempted',False) and not r.get('p06_accepted',False) for r in records),'p07_attempted':sum(r.get('p07_attempted',False) for r in records),'p07_accepted':sum(r.get('p07_accepted',False) for r in records),'p07_rejected':sum(r.get('p07_attempted',False) and not r.get('p07_accepted',False) for r in records),'interpolated_after_physical':sources['interpolated_after_p07_ambiguity'],'unresolved_or_review':manifest['frame_count']-len(records),'final_sources':dict(sources)}
 reasons=Counter(r.get('physical_rejection_reason') for r in records if r.get('p07_attempted') and not r.get('p07_accepted'));counts['p07_rejection_reasons']=dict(reasons)
 cache=['candidate_cache_hits','candidate_cache_misses','template_evaluations_avoided','percentile_calls_avoided'];counts['exact_cache']={k:sum((r.get('physical_diagnostics') or {}).get('cache_metrics',{}).get(k,0) for r in records) for k in cache}
 interpolated=[]
 for r in records:
  if r.get('final_registration_source')!='interpolated_after_p07_ambiguity':continue
  n=r['frame'];prev=max((x for x in by if x<n and not by[x].get('interpolated',False) and by[x].get('final_registration_source')!='interpolated_after_p07_ambiguity'),default=None);nxt=min((x for x in by if x>n and by[x].get('final_registration_source')!='interpolated_after_p07_ambiguity'),default=None)
  interpolated.append({'frame':n,'same_frame_failure':r.get('physical_rejection_reason'),'p06_attempted':r.get('p06_attempted'),'p06_accepted':r.get('p06_accepted'),'p07_attempted':r.get('p07_attempted'),'p07_accepted':r.get('p07_accepted'),'p07_reason':r.get('physical_rejection_reason'),'previous_trusted':prev,'next_trusted':nxt,'span':None if prev is None or nxt is None else nxt-prev,'source':r.get('final_registration_source'),'interpolation_reason':r.get('interpolation_reason')})
 safety=[]
 for n in (40,41,42,43,44,2117,2170,2199,2240,2606,2607,2608,3341,4589,4599,4600,4601):
  r=by.get(n)
  safety.append({'frame':n,'processed':r is not None,'source':None if r is None else r.get('final_registration_source'),'stage':None if r is None else r.get('physical_fallback_stage'),'p06_attempted':None if r is None else r.get('p06_attempted'),'p06_accepted':None if r is None else r.get('p06_accepted'),'p07_attempted':None if r is None else r.get('p07_attempted'),'p07_accepted':None if r is None else r.get('p07_accepted'),'classification':None if r is None else (r.get('physical_diagnostics') or {}).get('classification'),'anchor':None if r is None else [r.get('anchor_x'),r.get('anchor_y')],'residual_source':None if r is None else r.get('residual_source'),'residual_correction_y':None if r is None else r.get('residual_correction_y'),'post_valid':None if r is None else r.get('post_correction_measurement_valid')})
 log=(d/'validation_run.log').read_text();elapsed=sum(float(x) for x in re.findall(r'elapsed_seconds[^\n]*',log)) if False else sum(float(x) for x in re.findall(r'Timing breakdown[^\n]*',log)) if False else None
 stage_times={};
 for stage in ('rawpy_develop','sprocket_detect','crop_register','normalize','ffmpeg_encode'):stage_times[stage]=sum(float(x) for x in re.findall(rf'{stage}\s+([0-9.]+)s',log))
 invalid=[r for r in records if r.get('vertical_stabilization_enabled') and not r.get('post_correction_measurement_valid',False)];large=[r for r in records if abs(float(r.get('residual_correction_y',0)))>50]
 provenance={'manifest_mode':manifest.get('sprocket_registration',{}).get('mode'),'manifest_module_sha256':manifest.get('sprocket_registration',{}).get('production_module_sha256'),'disk_module_sha256':hashlib.sha256((ROOT/'grokcam/physical_sprocket.py').read_bytes()).hexdigest(),'hash_match':manifest.get('sprocket_registration',{}).get('production_module_sha256')==hashlib.sha256((ROOT/'grokcam/physical_sprocket.py').read_bytes()).hexdigest(),'sprocket_registration':manifest.get('sprocket_registration'),'vertical_stabilization':manifest.get('vertical_stabilization')}
 failed=json.loads((d/'failed_batch_2401_2700_audit.json').read_text()) if (d/'failed_batch_2401_2700_audit.json').exists() else None
 summary={'status':'blocked' if len(records)<manifest['frame_count'] else 'complete','blocker':'adjacent unresolved same-frame physical failures' if len(records)<manifest['frame_count'] else None,'counts':counts,'failed_batch_audit':failed,'performance':{'completed_stage_seconds':stage_times,'completed_total_stage_seconds':sum(stage_times.values()),'average_stage_seconds_per_completed_frame':sum(stage_times.values())/len(records)},'vertical_stabilization_audit':{'post_measurement_invalid':len(invalid),'over_50px_corrections':len(large),'post_invalid_frames':[r['frame'] for r in invalid],'over_50px_frames':[r['frame'] for r in large]},'provenance':provenance}
 (d/'cascade_summary.json').write_text(json.dumps(summary,indent=2)+'\n');write_csv(d/'cascade_counts.csv',[counts|{k:json.dumps(v,sort_keys=True) for k,v in counts.items() if isinstance(v,dict)}]);write_csv(d/'interpolation_audit.csv',interpolated);(d/'safety_regression_summary.json').write_text(json.dumps(safety,indent=2)+'\n');(d/'performance_summary.json').write_text(json.dumps(summary['performance'],indent=2)+'\n');(d/'provenance_hash_summary.json').write_text(json.dumps(provenance,indent=2)+'\n');(d/'exact_command.txt').write_text('/home/todd/telecine/.venv/bin/python -m grokcam.cli.process_reel /mnt/GrokCam/projects/Reel_46335/raw '+str(d.resolve())+' --batch-frames 300 --fps 16 --jobs 3 --minimum-free-gib 22 --sprocket-detector-mode physical-p07-v1 --vertical-stabilization\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
