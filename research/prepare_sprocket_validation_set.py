#!/usr/bin/env python3
"""Create stratified frozen-detector validation annotations without tuning."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
import av,cv2,numpy as np,pandas as pd
from research.prepare_sprocket_ground_truth import FIELDS,annotate_review

KNOWN={'reel_28486':{130,2596,5017,5063},'reel_46335':{1954,2243,2532,2822,3111,3122,3318,3513,3709,3905}}
VALIDATION_FIELDS = FIELDS + [
 'upper_prediction_available','upper_predicted_x','upper_predicted_y','upper_annotation_status',
 'lower_prediction_available','lower_predicted_x','lower_predicted_y','lower_annotation_status','reviewed']

def validation_annotation_html(frames,predictions,dataset):
 payload=json.dumps(frames);prediction_payload=json.dumps(predictions);storage=f'grokcam_sprocket_xy_{dataset}'
 download=f'{dataset}_validation_ground_truth.csv';title=dataset.replace('_',' ').title()
 return f"""<!doctype html><meta charset='utf-8'><title>{title} validation annotation</title>
<style>body{{font:16px sans-serif;background:#171717;color:#eee;margin:16px}}button,select,input{{font-size:15px;margin:4px}}
button.primary{{background:#187a39;color:white;font-weight:bold;font-size:18px;padding:10px 18px}}button:disabled{{opacity:.4}}
#canvas{{image-rendering:pixelated;border:2px solid #777;cursor:crosshair;max-height:70vh;touch-action:none}}
.row{{display:flex;gap:18px;align-items:flex-start}}.panel{{width:520px}}.zoomrow{{display:flex;gap:8px}}.zoom{{width:180px}}
.zoom canvas{{image-rendering:pixelated;border:1px solid #777;width:160px;height:160px}}pre{{white-space:pre-wrap;color:#bde;font-size:13px}}
#frameNav{{display:grid;grid-template-columns:repeat(10,1fr);gap:3px;margin-top:8px}}#frameNav button{{font-size:12px;margin:0;padding:4px;background:#444;color:#eee}}
#frameNav button.reviewed{{background:#19733a}}#frameNav button.current{{outline:3px solid #ffd54a}}.upper{{color:#55ff88}}.lower{{color:#55ddff}}#message{{color:#ffdb6e;font-weight:bold;min-height:24px}}</style>
<h1>{title} — frozen detector review</h1><p>Green = upper; cyan = lower. Inspect both physical virtual corners, then press <b>Enter</b> or <b>ACCEPT PREDICTIONS</b>. Drag a marker or use Mark Upper/Lower and click to correct it.</p>
<div><button class='primary' onclick='acceptAndNext()'>ACCEPT PREDICTIONS</button><button onclick='prev()'>Previous</button><button onclick='next()'>Next</button>
<button onclick='setMode("upper")'>Mark upper</button><button onclick='setMode("lower")'>Mark lower</button><button onclick='clearCurrent()'>Reset frame</button><button id='downloadButton' onclick='downloadCsv()' disabled>Download CSV</button></div>
<div id='message'></div><div class='row'><canvas id='canvas'></canvas><div class='panel'><h2 id='title'></h2><h3 id='progress'></h3><div id='status'></div>
<label><input id='upperVisible' type='checkbox' checked> upper visible</label> <span class='upper' id='upperSource'></span><br>
<label><input id='lowerVisible' type='checkbox' checked> lower visible</label> <span class='lower' id='lowerSource'></span><br>
<label>condition <select id='condition'><option>clean</option><option>dark</option><option>bright</option><option>dirty</option><option>damaged</option><option>fade</option><option>leader</option><option>image_content</option><option>other</option></select></label><br>
<label>notes<br><input id='notes' size='54'></label><div class='zoomrow'><div class='zoom'><b class='upper'>Upper detail</b><canvas id='upperZoom'></canvas></div><div class='zoom'><b class='lower'>Lower detail</b><canvas id='lowerZoom'></canvas></div></div>
<pre id='coords'></pre><div id='frameNav'></div></div></div>
<script>
const frames={payload}, predictions={prediction_payload}, scale=2, roiWidth=120;let index=0,mode='upper',dragging=null,dragMoved=false;
const byId=id=>document.getElementById(id),canvas=byId('canvas'),ctx=canvas.getContext('2d'),titleElement=byId('title'),progress=byId('progress'),statusElement=byId('status'),coordsElement=byId('coords'),upperVisible=byId('upperVisible'),lowerVisible=byId('lowerVisible'),condition=byId('condition'),notes=byId('notes'),message=byId('message'),downloadButton=byId('downloadButton'),upperSource=byId('upperSource'),lowerSource=byId('lowerSource'),frameNav=byId('frameNav');
let image=new Image(),labels={{}};try{{labels=JSON.parse(localStorage.getItem('{storage}')||'{{}}')}}catch(_){{labels={{}};localStorage.removeItem('{storage}')}}
function prediction(frame,region){{return (predictions[frame]||{{}})[region]||{{available:false,x:'',y:''}}}}
function fresh(frame){{let r={{upper_visible:true,upper_x:'',upper_y:'',lower_visible:true,lower_x:'',lower_y:'',film_condition:'clean',notes:'',upper_annotation_status:'manual_annotation',lower_annotation_status:'manual_annotation',reviewed:false}};for(const k of ['upper','lower']){{let p=prediction(frame,k);if(p.available){{r[k+'_x']=p.x;r[k+'_y']=p.y;r[k+'_annotation_status']='prediction_unreviewed'}}}}return r}}
function current(){{let frame=frames[index],r=labels[frame];if(!r){{r=fresh(frame);labels[frame]=r}}else{{for(const k of ['upper','lower']){{let p=prediction(frame,k);if(r[k+'_annotation_status']===undefined){{if(r[k+'_x']!=='')r[k+'_annotation_status']='manual_annotation';else if(p.available){{r[k+'_x']=p.x;r[k+'_y']=p.y;r[k+'_annotation_status']='prediction_unreviewed'}}else r[k+'_annotation_status']='manual_annotation'}}}}if(r.reviewed===undefined)r.reviewed=false}}return r}}
function save(){{localStorage.setItem('{storage}',JSON.stringify(labels))}}
function reviewedCount(){{return frames.filter(f=>labels[f]&&labels[f].reviewed===true).length}}
function markerSource(r,k){{let s=r[k+'_annotation_status'];return s==='prediction_unreviewed'?'frozen detector prediction':s==='accepted_prediction'?'accepted frozen prediction':s==='corrected_prediction'?'manual adjustment of prediction':s==='manual_annotation'?'manual placement':s==='not_visible'?'not visible':s}}
function saveForm(){{let r=current();r.film_condition=condition.value;r.notes=notes.value;for(const k of ['upper','lower']){{let visible=k==='upper'?upperVisible.checked:lowerVisible.checked;r[k+'_visible']=visible;if(!visible){{r[k+'_x']='';r[k+'_y']='';r[k+'_annotation_status']='not_visible'}}else if(r[k+'_x']===''){{let p=prediction(frames[index],k);if(p.available){{r[k+'_x']=p.x;r[k+'_y']=p.y;r[k+'_annotation_status']='prediction_unreviewed'}}else r[k+'_annotation_status']='manual_annotation'}}}}save()}}
function point(e){{let rect=canvas.getBoundingClientRect();return {{x:(e.clientX-rect.left)*canvas.width/rect.width/scale,y:(e.clientY-rect.top)*canvas.height/rect.height/scale}}}}
function place(k,p){{let r=current(),pred=prediction(frames[index],k);r[k+'_visible']=true;r[k+'_x']=Math.max(0,Math.min(119.999,p.x));r[k+'_y']=Math.max(0,Math.min(899.999,p.y));r[k+'_annotation_status']=pred.available?'corrected_prediction':'manual_annotation';r.reviewed=false;if(k==='upper')upperVisible.checked=true;else lowerVisible.checked=true;save();draw()}}
function drawMarker(r,k,color){{if(!r[k+'_visible']||r[k+'_x']==='')return;let x=r[k+'_x']*scale,y=r[k+'_y']*scale;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,11,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(x-16,y);ctx.lineTo(x+16,y);ctx.moveTo(x,y-16);ctx.lineTo(x,y+16);ctx.stroke();ctx.font='bold 18px sans-serif';ctx.fillText(k==='upper'?'U':'L',x+14,y-12)}}
function drawZoom(k,color){{let r=current(),z=byId(k+'Zoom'),zc=z.getContext('2d');z.width=z.height=160;zc.fillStyle='#111';zc.fillRect(0,0,160,160);if(!r[k+'_visible']||r[k+'_x']==='')return;let x=+r[k+'_x'],y=+r[k+'_y'],radius=20;zc.imageSmoothingEnabled=false;zc.drawImage(image,x-radius,y-radius,radius*2,radius*2,0,0,160,160);zc.strokeStyle=color;zc.lineWidth=2;zc.beginPath();zc.moveTo(60,80);zc.lineTo(100,80);zc.moveTo(80,60);zc.lineTo(80,100);zc.stroke()}}
function renderNav(){{frameNav.innerHTML='';frames.forEach((f,i)=>{{let b=document.createElement('button');b.textContent=f;b.className=(labels[f]&&labels[f].reviewed?'reviewed ':'')+(i===index?'current':'');b.onclick=()=>{{saveForm();index=i;load()}};frameNav.appendChild(b)}})}}
function draw(){{ctx.drawImage(image,0,0,canvas.width,canvas.height);let r=current();drawMarker(r,'upper','#39ff72');drawMarker(r,'lower','#31dfff');drawZoom('upper','#39ff72');drawZoom('lower','#31dfff');let n=reviewedCount();progress.textContent='Reviewed: '+n+' / '+frames.length;downloadButton.disabled=n!==frames.length;statusElement.textContent='Placement mode: '+mode+(r.reviewed?' — FRAME REVIEWED':' — confirmation required');upperSource.textContent=markerSource(r,'upper');lowerSource.textContent=markerSource(r,'lower');coordsElement.textContent=JSON.stringify(r,null,2);renderNav()}}
function load(){{let r=current();titleElement.textContent='Frame '+frames[index]+' ('+(index+1)+'/'+frames.length+')';upperVisible.checked=r.upper_visible;lowerVisible.checked=r.lower_visible;condition.value=r.film_condition;notes.value=r.notes;message.textContent='';image.onload=()=>{{canvas.width=roiWidth*scale;canvas.height=900*scale;draw()}};image.onerror=()=>message.textContent='IMAGE LOAD FAILED: '+image.src;image.src='roi/frame_'+String(frames[index]).padStart(6,'0')+'.png'}}
canvas.onpointerdown=e=>{{let p=point(e),r=current(),near=[];for(const k of ['upper','lower'])if(r[k+'_visible']&&r[k+'_x']!=='')near.push([Math.hypot(p.x-r[k+'_x'],p.y-r[k+'_y']),k]);near.sort((a,b)=>a[0]-b[0]);dragging=near.length&&near[0][0]<12?near[0][1]:mode;dragMoved=false;canvas.setPointerCapture(e.pointerId);if(!(near.length&&near[0][0]<12)){{place(dragging,p);mode=mode==='upper'?'lower':'upper'}}}};
canvas.onpointermove=e=>{{if(dragging&&e.buttons){{dragMoved=true;place(dragging,point(e))}}}};canvas.onpointerup=e=>{{if(dragging&&dragMoved)place(dragging,point(e));dragging=null}};
function setMode(k){{saveForm();mode=k;draw()}}function next(){{saveForm();index=Math.min(frames.length-1,index+1);load()}}function prev(){{saveForm();index=Math.max(0,index-1);load()}}
function clearCurrent(){{labels[frames[index]]=fresh(frames[index]);save();load()}}
function acceptAndNext(){{saveForm();let r=current();for(const k of ['upper','lower'])if(r[k+'_visible']&&r[k+'_x']===''){{message.textContent='Place the '+k+' marker or mark it not visible.';return}}for(const k of ['upper','lower']){{if(!r[k+'_visible'])r[k+'_annotation_status']='not_visible';else if(r[k+'_annotation_status']==='prediction_unreviewed')r[k+'_annotation_status']='accepted_prediction'}}r.reviewed=true;save();draw();if(index<frames.length-1){{index++;load()}}}}
function csvValue(v){{return '"'+String(v??'').replaceAll('"','""')+'"'}}function downloadCsv(){{if(reviewedCount()!==frames.length){{message.textContent='Review all 50 frames before downloading.';return}}saveForm();let fields={json.dumps(VALIDATION_FIELDS)},lines=[fields.join(',')];for(const f of frames){{let r=labels[f],row={{frame:f,...r}};for(const k of ['upper','lower']){{let p=prediction(f,k);row[k+'_prediction_available']=p.available;row[k+'_predicted_x']=p.available?p.x:'';row[k+'_predicted_y']=p.available?p.y:''}}lines.push(fields.map(k=>csvValue(row[k])).join(','))}}let a=document.createElement('a'),url=URL.createObjectURL(new Blob([lines.join('\\n')+'\\n'],{{type:'text/csv'}}));a.href=url;a.download='{download}';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}
for(const id of ['condition','notes'])byId(id).onchange=saveForm;upperVisible.onchange=()=>{{current().reviewed=false;saveForm();draw()}};lowerVisible.onchange=()=>{{current().reviewed=false;saveForm();draw()}};document.addEventListener('keydown',e=>{{if(e.key==='Enter'&&!e.repeat){{e.preventDefault();acceptAndNext()}}}});load();
</script>"""

def spaced(values,n):
 v=sorted(set(map(int,values)));return v if len(v)<=n else [v[i] for i in np.linspace(0,len(v)-1,n).round().astype(int)]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('dataset',choices=KNOWN);ap.add_argument('video',type=Path);ap.add_argument('results',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--count',type=int,default=50);args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 d=pd.read_csv(args.results);accepted=d[d.accepted.astype(str).str.lower().isin(['true','1'])];rejected=d[~d.index.isin(accepted.index)]
 selection_path=args.output/'selection.json'
 if selection_path.exists():
  existing=json.loads(selection_path.read_text());selected=set(map(int,existing['frames']));categories={int(k):v for k,v in existing.get('categories',{}).items()}
 else:selected=set(KNOWN[args.dataset]);categories={f:'known' for f in selected}
 groups=[('accepted_spread',spaced(accepted.frame,10)),('rejected_spread',spaced(rejected.frame,10)),
  ('highest_confidence',accepted.nlargest(6,['upper_confidence']).frame.tolist()),
  ('lowest_confidence_accepted',accepted.nsmallest(6,['upper_confidence']).frame.tolist()),
  ('largest_geometry_deviation',d.assign(dev=abs(d.geometry_error_x)+abs(d.geometry_error_y)).nlargest(8,'dev').frame.tolist())]
 if not selection_path.exists():
  for label,group_frames in groups:
   for f in group_frames:selected.add(int(f));categories.setdefault(int(f),label)
  allframes=set(map(int,d.frame));
  while len(selected)<args.count:
   f=max(allframes-selected,key=lambda x:min(abs(x-y) for y in selected));selected.add(f);categories[f]='coverage_fill'
  if len(selected)>args.count:
   required=set(KNOWN[args.dataset]);others=spaced(selected-required,args.count-len(required));selected=required|set(others)
 frames=sorted(selected);roi=args.output/'roi';review=args.output/'review_images';roi.mkdir(exist_ok=True);review.mkdir(exist_ok=True);wanted=set(frames)
 with av.open(str(args.video)) as container:
  for i,vf in enumerate(container.decode(video=0),1):
   if i not in wanted:continue
   bgr=vf.to_ndarray(format='bgr24');cv2.imwrite(str(roi/f'frame_{i:06d}.png'),bgr[:,:120]);cv2.imwrite(str(review/f'frame_{i:06d}.jpg'),annotate_review(bgr,i,120),[cv2.IMWRITE_JPEG_QUALITY,94])
 rows=[{'frame':f,'upper_visible':'','upper_x':'','upper_y':'','lower_visible':'','lower_x':'','lower_y':'','film_condition':'','notes':''} for f in frames]
 with (args.output/f'{args.dataset}_ground_truth_template.csv').open('w',newline='') as h:w=csv.DictWriter(h,FIELDS);w.writeheader();w.writerows(rows)
 prediction_rows=d.set_index('frame');predictions={}
 for frame in frames:
  row=prediction_rows.loc[frame];predictions[str(frame)]={}
  for region in ('upper','lower'):
   x=row[f'{region}_x'];y=row[f'{region}_y'];available=bool(pd.notna(x) and pd.notna(y))
   predictions[str(frame)][region]={'available':available,'x':float(x) if available else '',
     'y':float(y) if available else '','frozen_pair_accepted':bool(row['accepted'])}
 (args.output/'annotate.html').write_text(validation_annotation_html(frames,predictions,args.dataset))
 (args.output/'selection.json').write_text(json.dumps({'dataset':args.dataset,'frames':frames,'categories':{str(f):categories.get(f,'sampled') for f in frames},'frozen_detector_results':str(args.results)},indent=2)+'\n')
 print(json.dumps({'dataset':args.dataset,'frames':len(frames),'first':frames[0],'last':frames[-1],'output':str(args.output)},indent=2))
if __name__=='__main__':main()
