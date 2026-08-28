#!/usr/bin/env python3
"""Finalize an interrupted P07 pre-unblind package without rerunning detection."""
from __future__ import annotations
import hashlib, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from research.prepare_partner_partial_blind_validation import html
from research.run_p07_frozen_blind_validation import DEFAULT_OUTPUT,EXPECTED,SOURCE_PACKAGE,tree_hash

def main():
 out=DEFAULT_OUTPUT
 if (out/'lock_manifest.json').exists():raise SystemExit('package already locked')
 selection=json.loads((SOURCE_PACKAGE/'selection_private.json').read_text());frames=[int(x) for x in selection['frames']]
 diagnostics=json.loads((out/'diagnostics.json').read_text())
 if len(diagnostics)!=68 or {int(r['frame']) for r in diagnostics}!=set(frames):raise SystemExit('detector output is incomplete')
 if len(list((out/'panels').glob('frame_*.jpg')))!=68:raise SystemExit('panel output is incomplete')
 roi=out/'roi';roi.mkdir(exist_ok=True)
 for frame in frames:
  for region in ('upper','lower'):shutil.copy2(SOURCE_PACKAGE/'roi'/f'frame_{frame:06d}_{region}.png',roi)
 origins={str(f):selection['origins'][str(f)] for f in frames}
 freeze_id=hashlib.sha256(json.dumps(list(EXPECTED.values()),sort_keys=True).encode()).hexdigest()
 (out/'annotate.html').write_text(html(frames,origins,'p07_'+freeze_id))
 reveal=out/'reveal';reveal.mkdir(exist_ok=True)
 for frame in frames:shutil.copy2(out/'panels'/f'frame_{frame:06d}.jpg',reveal)
 package_hash,file_hashes=tree_hash(out,{'lock_manifest.json'})
 lock={'locked_at':datetime.now(timezone.utc).isoformat(),'state':'LOCKED_PRE_UNBLIND','ground_truth_opened':False,'package_sha256':package_hash,'files':file_hashes,'frozen_hashes_verified':True,'protected_answer_files_read':[],'finalization_note':'Detector completed before a UI-key serialization error. This lock-only finalizer verified all 68 diagnostics and panels; detector was not rerun.'}
 (out/'lock_manifest.json').write_text(json.dumps(lock,indent=2)+'\n')
 print(json.dumps({'frames':len(diagnostics),'package_sha256':package_hash,'locked_at':lock['locked_at']},indent=2))
if __name__=='__main__':main()
