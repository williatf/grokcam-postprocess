#!/usr/bin/env python3
"""Prepare a locked, blind human review for the frozen partial-hole fallback."""

from __future__ import annotations

import argparse, csv, hashlib, json, random, shutil, sys, tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS, load_capture
from research.p03_partner_assisted_partial_hole_poc import result_for

POC_ROOT=ROOT/'research/output/sprocket_xy/partner_partial_hole_poc/Reel_46335'
DEFAULT_OUTPUT=ROOT/'research/output/sprocket_xy/partner_partial_hole_blind_validation'
QUESTIONABLE={42,2163,2216,2217,2243,2290,4589};MANDATORY_NEGATIVE=3341;SEED=463350827
FROZEN_FILES=[ROOT/'research/p03_partner_assisted_partial_hole_poc.py',ROOT/'research/p02_physical_hole_capture_prior_poc.py',ROOT/'research/p02_physical_hole_capture_prior_blue_frozen.json',POC_ROOT/'diagnostics.csv',POC_ROOT/'validation_report.json']

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def select(rows):
 rng=random.Random(SEED);by={int(r['frame']):r for r in rows}
 strong=[r for r in rows if r['accepted']=='True' and int(r['frame']) not in QUESTIONABLE]
 groups=defaultdict(list)
 for r in strong:groups[(r['direction'],min(3,(int(r['frame'])-1)*4//4615))].append(r)
 chosen=[]
 for key in sorted(groups):
  rng.shuffle(groups[key]);chosen.extend(groups[key][:2])
 remaining=[r for r in strong if r not in chosen];rng.shuffle(remaining);chosen.extend(remaining[:40-len(chosen)])
 assert len(chosen)==40 and {r['direction'] for r in chosen}=={'upper_to_lower','lower_to_upper'}
 controls=[r for r in rows if r['accepted']!='True' and int(r['frame'])!=MANDATORY_NEGATIVE]
 control=[]
 for quartile in range(4):
  group=[r for r in controls if min(3,(int(r['frame'])-1)*4//4615)==quartile];rng.shuffle(group);control.extend(group[:5])
 assert len(control)==20
 categories={**{f:'questionable_recovery' for f in QUESTIONABLE},**{int(r['frame']):'strong_recovery' for r in chosen},**{int(r['frame']):'negative_control' for r in control},MANDATORY_NEGATIVE:'mandatory_negative_regression'}
 frames=list(categories);rng.shuffle(frames)
 return frames,categories

def html(frames,origins,freeze_id):
 return f"""<!doctype html><meta charset='utf-8'><title>Blind partial-hole validation</title>
<style>body{{font:16px sans-serif;background:#151515;color:#eee;margin:16px}}button,select,input{{font-size:15px;margin:4px;padding:5px}}button.primary{{background:#17783a;color:white;font-weight:bold;padding:10px 18px}}button.reveal{{background:#6845a8;color:white}}button:disabled{{opacity:.35}}.row{{display:flex;gap:16px}}.roi canvas{{border:2px solid #777;max-width:46vw;max-height:65vh;cursor:crosshair;image-rendering:auto}}.controls{{margin-top:8px;padding:10px;background:#222}}#nav{{display:grid;grid-template-columns:repeat(12,1fr);gap:3px;margin-top:10px}}#nav button{{font-size:11px;margin:0;padding:4px;background:#444;color:white}}#nav .done{{background:#19733a}}#nav .current{{outline:3px solid #ffd54a}}#message{{color:#ffdc71;font-weight:bold;min-height:24px}}#revealImage{{max-width:96vw;border:2px solid #a881ff;margin-top:10px}}.definition{{background:#273346;padding:10px}}</style>
<h1>Blind partner/partial-hole validation</h1><p class='definition'><b>Landmark definition:</b> upper opening lower-right film-side corner; lower opening upper-right film-side corner. Click only when physically identifiable. Otherwise classify the hole as damaged but inferable, ambiguous, or not measurable.</p>
<p>No detector marker, fit, score, recovery status, or classification is loaded before submission. Submitted judgments are locked. Reveal is optional and happens only afterward.</p>
<button class='primary' id='submit' onclick='submitFrame()'>SUBMIT BLIND JUDGMENT & NEXT</button><button onclick='prev()'>Previous</button><button onclick='next()'>Next</button><button class='reveal' id='reveal' onclick='revealFit()' disabled>Reveal frozen detector fit</button><button id='post' onclick='postRevealEdit()' disabled>Explicit post-reveal correction</button><button id='download' onclick='downloadCsv()' disabled>Download completed CSV</button>
<div id='message'></div><h2 id='title'></h2><h3 id='progress'></h3><div class='row'><div class='roi'><b>UPPER — click lower-right film-side corner</b><br><canvas id='upper'></canvas></div><div class='roi'><b>LOWER — click upper-right film-side corner</b><br><canvas id='lower'></canvas></div></div>
<div class='controls'><label>Upper judgment <select id='upperStatus'>{''.join('<option>'+x+'</option>' for x in ['unreviewed','measurable','damaged_inferable','ambiguous','not_measurable'])}</select></label><label>Lower judgment <select id='lowerStatus'>{''.join('<option>'+x+'</option>' for x in ['unreviewed','measurable','damaged_inferable','ambiguous','not_measurable'])}</select></label><label>Frame condition <select id='condition'>{''.join('<option>'+x+'</option>' for x in ['clean','damaged','partial','merged','dark','bright','out_of_frame','capture_problem','other'])}</select></label><label>Notes <input id='notes' size='55'></label></div><div id='nav'></div><div id='revealBox'></div>
<script>
const frames={json.dumps(frames)}, origins={json.dumps(origins)}, key='grokcam_partner_partial_blind_{freeze_id[:16]}';let index=0,labels={{}},images={{upper:new Image(),lower:new Image()}};try{{labels=JSON.parse(localStorage.getItem(key)||'{{}}')}}catch(_){{labels={{}}}}
const $=id=>document.getElementById(id),statuses=['upper','lower'];function blank(){{return {{upper_status:'unreviewed',upper_x:'',upper_y:'',lower_status:'unreviewed',lower_x:'',lower_y:'',condition:'clean',notes:'',submitted:false,revealed:false,post_reveal:null}}}}function current(){{let f=frames[index];return labels[f]||(labels[f]=blank())}}function save(){{localStorage.setItem(key,JSON.stringify(labels))}}function count(){{return frames.filter(f=>labels[f]&&labels[f].submitted).length}}
function editable(r){{return r.correction_mode?r.post_reveal:r}}function draw(k){{let c=$(k),ctx=c.getContext('2d'),im=images[k],r=editable(current());c.width=im.naturalWidth;c.height=im.naturalHeight;ctx.drawImage(im,0,0);let x=r[k+'_x'],y=r[k+'_y'];if(x!==''){{ctx.strokeStyle=k==='upper'?'#38ff72':'#32ddff';ctx.lineWidth=5;ctx.beginPath();ctx.arc(x,y,14,0,Math.PI*2);ctx.moveTo(x-22,y);ctx.lineTo(x+22,y);ctx.moveTo(x,y-22);ctx.lineTo(x,y+22);ctx.stroke()}}}}
function point(e,c){{let q=c.getBoundingClientRect();return {{x:(e.clientX-q.left)*c.width/q.width,y:(e.clientY-q.top)*c.height/q.height}}}}for(const k of statuses)$(k).onclick=e=>{{let base=current();if(base.submitted&&!base.correction_mode)return;let r=editable(base),p=point(e,$(k));r[k+'_x']=p.x;r[k+'_y']=p.y;r[k+'_status']='measurable';$(k+'Status').value='measurable';save();draw(k)}};
function formToRecord(){{let base=current();if(base.submitted&&!base.correction_mode)return;let r=editable(base);r.upper_status=$('upperStatus').value;r.lower_status=$('lowerStatus').value;r.condition=$('condition').value;r.notes=$('notes').value;save()}}function validate(r){{for(const k of statuses){{if(r[k+'_status']==='unreviewed')return 'Classify the '+k+' hole.';if(r[k+'_status']==='measurable'&&r[k+'_x']==='')return 'Click the '+k+' landmark or choose a non-measurable classification.'}}return ''}}
function submitFrame(){{formToRecord();let r=current(),err=validate(r);if(err){{$('message').textContent=err;return}}r.submitted=true;r.submitted_at=new Date().toISOString();save();load();if(index<frames.length-1){{index++;load()}}}}function revealFit(){{let r=current();if(!r.submitted)return;r.revealed=true;r.revealed_at=new Date().toISOString();save();$('revealBox').innerHTML='<h3>POST-SUBMISSION FROZEN RESULT</h3><img id="revealImage" src="reveal/frame_'+String(frames[index]).padStart(6,'0')+'.jpg">';$('post').disabled=false}}
function postRevealEdit(){{let r=current();if(r.correction_mode){{formToRecord();r.correction_mode=false;r.post_reveal.saved_at=new Date().toISOString();save();load();$('message').textContent='Post-reveal correction saved separately. Original blind fields remain locked.';return}}if(!r.revealed||!confirm('Enter correction mode? Original blind fields remain immutable.'))return;r.post_reveal={{started_at:new Date().toISOString(),upper_status:r.upper_status,upper_x:r.upper_x,upper_y:r.upper_y,lower_status:r.lower_status,lower_x:r.lower_x,lower_y:r.lower_y,condition:r.condition,notes:r.notes}};r.correction_mode=true;save();load();$('message').textContent='CORRECTION MODE: place new markers, then click Save post-reveal correction.'}}
function load(){{let f=frames[index],r=current(),v=editable(r);$('title').textContent='Frame '+String(f).padStart(6,'0')+' — '+(index+1)+' / '+frames.length;$('progress').textContent='Submitted: '+count()+' / '+frames.length;$('upperStatus').value=v.upper_status;$('lowerStatus').value=v.lower_status;$('condition').value=v.condition;$('notes').value=v.notes;$('message').textContent=r.correction_mode?'CORRECTION MODE: original blind fields remain locked.':r.submitted?'Blind judgment locked. You may reveal the frozen fit.':'';$('submit').disabled=r.submitted;$('reveal').disabled=!r.submitted;$('post').disabled=!r.revealed;$('post').textContent=r.correction_mode?'Save post-reveal correction':'Explicit post-reveal correction';$('download').disabled=count()!==frames.length;$('revealBox').innerHTML='';for(const k of statuses){{$(k+'Status').disabled=r.submitted&&!r.correction_mode;$('condition').disabled=r.submitted&&!r.correction_mode;$('notes').disabled=r.submitted&&!r.correction_mode;images[k].onload=()=>draw(k);images[k].src='roi/frame_'+String(f).padStart(6,'0')+'_'+k+'.png'}}renderNav()}}function next(){{formToRecord();index=Math.min(frames.length-1,index+1);load()}}function prev(){{formToRecord();index=Math.max(0,index-1);load()}}function renderNav(){{$('nav').innerHTML='';frames.forEach((f,i)=>{{let b=document.createElement('button');b.textContent=f;b.className=(labels[f]&&labels[f].submitted?'done ':'')+(i===index?'current':'');b.onclick=()=>{{formToRecord();index=i;load()}};$('nav').appendChild(b)}})}}
function q(v){{return '"'+String(v??'').replaceAll('"','""')+'"'}}function downloadCsv(){{if(count()!==frames.length)return;let fields=['frame','upper_status','upper_x','upper_y','upper_full_x','upper_full_y','lower_status','lower_x','lower_y','lower_full_x','lower_full_y','condition','notes','submitted','submitted_at','revealed','revealed_at','post_reveal_json'],lines=[fields.join(',')];for(const f of frames){{let r=labels[f],o=origins[f],row={{...r,frame:f,upper_full_x:r.upper_x===''?'':+r.upper_x+o.upper[0],upper_full_y:r.upper_y===''?'':+r.upper_y+o.upper[1],lower_full_x:r.lower_x===''?'':+r.lower_x+o.lower[0],lower_full_y:r.lower_y===''?'':+r.lower_y+o.lower[1],post_reveal_json:r.post_reveal?JSON.stringify(r.post_reveal):''}};lines.push(fields.map(k=>q(row[k])).join(','))}}let a=document.createElement('a'),u=URL.createObjectURL(new Blob([lines.join('\\n')+'\\n'],{{type:'text/csv'}}));a.href=u;a.download='partner_partial_blind_ground_truth.csv';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}}for(const k of statuses)$(k+'Status').onchange=()=>{{let r=current(),v=$(k+'Status').value;if(v!=='measurable'){{r[k+'_x']='';r[k+'_y']=''}}formToRecord();draw(k)}};for(const id of ['condition','notes'])$(id).onchange=formToRecord;load();
</script>"""

def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT);p.add_argument('--jobs',type=int,default=3);a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 rows=list(csv.DictReader((POC_ROOT/'diagnostics.csv').open()));frames,categories=select(rows);by={int(r['frame']):r for r in rows}
 baseline_path=ROOT/'research/output/sprocket_xy/physical_hole_capture_prior_poc/Reel_46335/diagnostics.csv'
 baseline={int(r['frame']):r for r in csv.DictReader(baseline_path.open())}
 hashes={str(path.relative_to(ROOT)):sha(path) for path in FROZEN_FILES};freeze_id=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest();frozen_dir=a.output_dir/'frozen';frozen_dir.mkdir(exist_ok=True)
 for path in FROZEN_FILES:shutil.copy2(path,frozen_dir/path.name)
 freeze={'created':datetime.now(timezone.utc).isoformat(),'freeze_id':freeze_id,'sha256':hashes,'selection_seed':SEED,'logic_or_threshold_changes':False};(a.output_dir/'freeze_manifest.json').write_text(json.dumps(freeze,indent=2)+'\n')
 spec=REELS['Reel_46335'];capture=load_capture(spec['project']);frozen_config=json.loads((ROOT/'research/p02_physical_hole_capture_prior_blue_frozen.json').read_text());cal=load_calibration();dev=DarktableMatchedDeveloper(cal.match.report);roi=a.output_dir/'roi';reveal=a.output_dir/'reveal';roi.mkdir(exist_ok=True);reveal.mkdir(exist_ok=True);origins={};predictions=[]
 dngs=[spec['project']/'raw'/f'frame_{f:06d}.dng' for f in frames]
 for start in range(0,len(dngs),24):
  batch=dngs[start:start+24];tmp=Path(tempfile.mkdtemp(prefix='blind_partial_',dir=ROOT/'work'))
  try:
   with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    fs={pool.submit(dev.develop,d,tmp/f'{d.stem}.tif'):d for d in batch}
    for future in as_completed(fs):future.result()
   for dng in batch:
    frame=int(dng.stem.rsplit('_',1)[1]);r=by[frame]
    anchor_y=float(r.get('anchor_y') or baseline[frame]['hybrid_final_y'])
    with Image.open(tmp/f'{dng.stem}.tif') as im:
     image=im.convert('RGB');centers={'upper':anchor_y-392.5,'lower':anchor_y+392.5};origins[str(frame)]={}
     for region,cy in centers.items():
      x0=0;x1=min(image.width,850);y0=max(0,int(round(cy-330)));y1=min(image.height,int(round(cy+330)));image.crop((x0,y0,x1,y1)).save(roi/f'frame_{frame:06d}_{region}.png');origins[str(frame)][region]=[x0,y0]
     result=result_for(image,baseline[frame],capture[frame],frozen_config)
     prediction={'frame':frame,'classification':result['classification'],'accepted':result['accepted'],'direction':('upper_to_lower' if result.get('seed_is_upper') else 'lower_to_upper') if result.get('seed') is not None else ''}
     if result.get('seed') is not None and result.get('fit') is not None:
      upper=result['seed'] if result['seed_is_upper'] else result['fit'];lower=result['fit'] if result['seed_is_upper'] else result['seed']
      prediction.update({'upper_center_x':upper.cx,'upper_center_y':upper.cy,'upper_width':upper.width,'upper_height':upper.height,'upper_landmark_x':upper.cx+upper.width/2,'upper_landmark_y':upper.cy+upper.height/2,'lower_center_x':lower.cx,'lower_center_y':lower.cy,'lower_width':lower.width,'lower_height':lower.height,'lower_landmark_x':lower.cx+lower.width/2,'lower_landmark_y':lower.cy-lower.height/2,'pair_anchor_x':result.get('anchor_x'),'pair_anchor_y':result.get('anchor_y'),'boundary_features':';'.join(result.get('fit_detail',{}).get('accepted_features',[]))})
     predictions.append(prediction)
    shutil.copy2(POC_ROOT/'panels'/f'frame_{frame:06d}.jpg',reveal/f'frame_{frame:06d}.jpg')
  finally:shutil.rmtree(tmp)
  print(f'rendered {min(start+len(batch),len(dngs))}/{len(dngs)}',flush=True)
 private={'frames':frames,'categories':{str(k):v for k,v in categories.items()},'origins':origins,'selection':{'questionable':7,'strong':40,'negative_controls':20,'mandatory_negative':3341,'total':68},'feature_definition':'upper lower-right and lower upper-right physical sprocket-opening corners','freeze_id':freeze_id};(a.output_dir/'selection_private.json').write_text(json.dumps(private,indent=2)+'\n');(a.output_dir/'annotate.html').write_text(html(frames,origins,freeze_id))
 prediction_path=frozen_dir/'frozen_predictions_private.csv';fields=sorted({k for r in predictions for k in r})
 with prediction_path.open('w',newline='') as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(sorted(predictions,key=lambda r:r['frame']))
 freeze['derived_prediction_sha256']=sha(prediction_path);(a.output_dir/'freeze_manifest.json').write_text(json.dumps(freeze,indent=2)+'\n');print(json.dumps(private['selection'],indent=2))

if __name__=='__main__':main()
