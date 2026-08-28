#!/usr/bin/env python3
"""Repair only the P07 blind annotation UI and supersede its audit lock."""
from __future__ import annotations
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research.prepare_partner_partial_blind_validation import html
from research.run_p07_frozen_blind_validation import DEFAULT_OUTPUT,EXPECTED,SOURCE_PACKAGE,tree_hash

def main():
 out=DEFAULT_OUTPUT;old=json.loads((out/'lock_manifest.json').read_text())
 selection=json.loads((SOURCE_PACKAGE/'selection_private.json').read_text());frames=[int(x) for x in selection['frames']]
 # Prove every previously locked detector result remains byte-identical.
 protected=[r for r in old['files'] if r.startswith(('diagnostics.','panels/','reveal/','frozen/','pre_unblind_summary','population_manifest'))]
 changed=[r for r in protected if hashlib.sha256((out/r).read_bytes()).hexdigest()!=old['files'][r]]
 if changed:raise SystemExit(f'detector/audit artifacts changed: {changed}')
 origins={str(f):selection['origins'][str(f)] for f in frames};freeze_id=hashlib.sha256(json.dumps(list(EXPECTED.values()),sort_keys=True).encode()).hexdigest()
 (out/'annotate.html').write_text(html(frames,origins,'p07_'+freeze_id))
 package_hash,files=tree_hash(out,{'lock_manifest.json'})
 lock={'locked_at':datetime.now(timezone.utc).isoformat(),'state':'LOCKED_PRE_UNBLIND','ground_truth_opened':False,'package_sha256':package_hash,'files':files,'frozen_hashes_verified':True,'protected_answer_files_read':[],'supersedes_package_sha256':old['package_sha256'],'ui_repair':'Corrected invalid JavaScript newline escaping in CSV download construction. Detector outputs, decisions, diagnostics, panels, and ROIs unchanged.','unchanged_detector_artifacts_verified':len(protected)}
 (out/'lock_manifest.json').write_text(json.dumps(lock,indent=2)+'\n');print(json.dumps({'old':old['package_sha256'],'new':package_hash,'verified_unchanged':len(protected)},indent=2))
if __name__=='__main__':main()
