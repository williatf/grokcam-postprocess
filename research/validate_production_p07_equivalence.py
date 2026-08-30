#!/usr/bin/env python3
"""Validate the production P07 port against the frozen 198-frame oracle."""
from __future__ import annotations
import csv, json, shutil, tempfile, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.physical_sprocket import fit_pair
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS,load_capture
from research.p02_physical_hole_capture_prior_poc import physical_hole
from research.p07_joint_rigid_sprocket_pair_evidence_poc import P06
from research.render_physical_hole_problem_review import any_capture_boxes

ORACLE=ROOT/'research/output/sprocket_xy/joint_rigid_sprocket_pair_evidence_poc/Reel_46335'
OUT=ROOT/'research/output/sprocket_xy/production_p07_equivalence'

def main():
    oracle={int(r['frame']):r for r in csv.DictReader((ORACLE/'diagnostics.csv').open())}
    p06={int(r['frame']):r for r in csv.DictReader((P06/'diagnostics.csv').open())}
    spec=REELS['Reel_46335'];capture=load_capture(spec['project'])
    developer=DarktableMatchedDeveloper(load_calibration().match.report);results=[]
    for start in range(0,len(oracle),24):
        frames=sorted(oracle)[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='prod_p07_',dir=ROOT/'work'))
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs=[pool.submit(developer.develop,spec['project']/'raw'/f'frame_{n:06d}.dng',tmp/f'frame_{n:06d}.tif') for n in frames]
                for job in as_completed(jobs):job.result()
            def one(n):
                with Image.open(tmp/f'frame_{n:06d}.tif') as image:rgb=np.asarray(image.convert('RGB'))
                boxes=any_capture_boxes(capture[n]);holes=[physical_hole(rgb,b,.25)[0] for b in boxes]
                priors=[(b[0],b[1]) for b in boxes]+[(h.cx,h.cy) for h in holes if h is not None]
                row=p06[n]
                if row.get('model_x') not in ('',None):priors.append((float(row['model_x']),float(row['model_y'])))
                actual=fit_pair(rgb,priors);expected=oracle[n]
                exact=(str(actual['safe'])==expected['accepted'] and actual['upper_x']==float(expected['upper_x']) and actual['upper_y']==float(expected['upper_y']) and actual['lower_x']==float(expected['lower_x']) and actual['lower_y']==float(expected['lower_y']) and actual['score']==float(expected['joint_score']) and actual['margin']==float(expected['competitor_margin']) and actual['upper']['states']==json.loads(expected['upper_states_json']) and actual['lower']['states']==json.loads(expected['lower_states_json']) and actual['upper']['strengths']==json.loads(expected['upper_strengths_json']) and actual['lower']['strengths']==json.loads(expected['lower_strengths_json']) and actual['upper']['residuals']==json.loads(expected['upper_residuals_json']) and actual['lower']['residuals']==json.loads(expected['lower_residuals_json']))
                return {'frame':n,'identical':exact,'accepted':actual['safe'],'upper_x':actual['upper_x'],'upper_y':actual['upper_y'],'classification':expected['classification']}
            with ThreadPoolExecutor(max_workers=3) as pool:results.extend(job.result() for job in as_completed([pool.submit(one,n) for n in frames]))
        finally:shutil.rmtree(tmp)
        print(f'validated {min(start+len(frames),len(oracle))}/{len(oracle)}',flush=True)
    results.sort(key=lambda r:r['frame']);OUT.mkdir(parents=True,exist_ok=True)
    report={'population':len(results),'identical':sum(r['identical'] for r in results),'differences':[r for r in results if not r['identical']]}
    blind=set(json.loads((ROOT/'research/output/sprocket_xy/p07_frozen_blind_validation/population_manifest.json').read_text())['frames_in_blind_order'])
    safety=set(json.loads((ORACLE/'validation_report.json').read_text())['review_queue'])
    report['blind_subset']={'frames':len(blind),'identical':sum(r['identical'] for r in results if r['frame'] in blind)}
    report['safety_queue']={'frames':len(safety),'identical':sum(r['identical'] for r in results if r['frame'] in safety)}
    for n in (42,3341,4589,4600,2606,2608,4599,2117,2170,2199,2240):report[f'frame_{n}']=next(r for r in results if r['frame']==n)
    (OUT/'validation_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));raise SystemExit(0 if not report['differences'] else 1)
if __name__=='__main__':main()
