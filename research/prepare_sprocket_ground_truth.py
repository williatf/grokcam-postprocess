#!/usr/bin/env python3
"""Prepare stratified frames and a browser annotation workflow for sprocket XY."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import av
import cv2
import numpy as np


BLUE_REQUIRED = {3260, 3451, 3487, 3615, 3676, 3754, 3846, 3882}
FIELDS = ["frame", "upper_visible", "upper_x", "upper_y", "lower_visible",
          "lower_x", "lower_y", "film_condition", "notes"]


def stratified_frames(first: int, last: int, count: int, required: set[int]) -> list[int]:
    if count < len(required):
        raise ValueError("count is smaller than the required frame set")
    selected = {frame for frame in required if first <= frame <= last}
    ordinary_count = count - len(selected)
    selected.update(int(round(value)) for value in np.linspace(first, last, ordinary_count))
    # A required event can coincide with an evenly spaced sample. Fill any
    # resulting shortfall at the point farthest from all current selections.
    if len(selected) < count:
        available=set(range(first,last+1))-selected
        while len(selected)<count:
            frame=max(available,key=lambda candidate:min(abs(candidate-other) for other in selected))
            selected.add(frame);available.remove(frame)
    return sorted(selected)


def annotate_review(frame: np.ndarray, source_frame: int, roi_width: int) -> np.ndarray:
    roi = frame[:, :roi_width]
    enlarged = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    canvas = cv2.copyMakeBorder(enlarged, 70, 30, 20, 20, cv2.BORDER_CONSTANT,
                                value=(20, 20, 20))
    cv2.putText(canvas, f"FRAME {source_frame} - LEFT SPROCKET ROI (3x)", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "Mark film-side corner: upper lower-right; lower upper-right",
                (20, 62), cv2.FONT_HERSHEY_SIMPLEX, .48, (190, 220, 255), 1, cv2.LINE_AA)
    return canvas


def annotation_html(frames: list[int], roi_width: int, dataset: str = "blue",
                    download_name: str | None = None) -> str:
    payload = json.dumps(frames)
    storage_key=f"grokcam_sprocket_xy_{dataset}"
    output_name=download_name or f"{dataset}_ground_truth.csv"
    title=dataset.replace('_',' ').title()
    return f"""<!doctype html><meta charset='utf-8'><title>Sprocket XY annotation</title>
<style>body{{font:16px sans-serif;background:#171717;color:#eee;margin:20px}}button,select,input{{font-size:15px;margin:4px}}
#canvas{{image-rendering:pixelated;border:1px solid #777;cursor:crosshair;max-height:76vh}}
.row{{display:flex;gap:20px;align-items:flex-start}}.panel{{max-width:520px}}pre{{white-space:pre-wrap;color:#bde}}</style>
<h1>{title} sprocket XY ground truth</h1>
<p>Click the physical film-side corner, not a centroid: <b>upper opening lower-right corner</b>, then
<b>lower opening upper-right corner</b>. Coordinates are in the original 120x900 ROI.</p>
<div><button onclick='prev()'>Previous</button><button onclick='next()'>Next</button>
<button onclick='setMode("upper")'>Mark upper</button><button onclick='setMode("lower")'>Mark lower</button>
<button onclick='clearCurrent()'>Clear frame</button><button onclick='downloadCsv()'>Download CSV</button></div>
<div class='row'><canvas id='canvas'></canvas><div class='panel'>
<h2 id='title'></h2><div id='status'></div>
<label><input id='upperVisible' type='checkbox' checked> upper visible</label><br>
<label><input id='lowerVisible' type='checkbox' checked> lower visible</label><br>
<label>condition <select id='condition'><option>clean</option><option>dark</option><option>bright</option>
<option>dirty</option><option>damaged</option><option>fade</option><option>leader</option><option>image_content</option><option>other</option></select></label><br>
<label>notes<br><input id='notes' size='50'></label>
<pre id='coords'></pre></div></div>
<script>
const frames={payload}, scale=2, roiWidth={roi_width}; let index=0, mode='upper';
const canvas=document.getElementById('canvas'), ctx=canvas.getContext('2d');
const titleElement=document.getElementById('title'), statusElement=document.getElementById('status');
const coordsElement=document.getElementById('coords'), upperVisible=document.getElementById('upperVisible');
const lowerVisible=document.getElementById('lowerVisible'), condition=document.getElementById('condition');
const notes=document.getElementById('notes'); let image=new Image(), labels={{}};
try {{ labels=JSON.parse(localStorage.getItem('{storage_key}')||'{{}}'); }}
catch (_) {{ labels={{}}; localStorage.removeItem('{storage_key}'); }}
function blank(){{return {{upper_visible:true,lower_visible:true,upper_x:'',upper_y:'',lower_x:'',lower_y:'',film_condition:'clean',notes:''}}}}
function current(){{return labels[frames[index]]||blank()}}
function saveForm(){{let r=current();r.upper_visible=upperVisible.checked;r.lower_visible=lowerVisible.checked;
r.film_condition=condition.value;r.notes=notes.value;labels[frames[index]]=r;localStorage.setItem('{storage_key}',JSON.stringify(labels));}}
function draw(){{ctx.drawImage(image,0,0,canvas.width,canvas.height);let r=current();ctx.lineWidth=2;
for(const k of ['upper','lower'])if(r[k+'_x']!==''){{ctx.strokeStyle=k==='upper'?'#00ff66':'#00ccff';ctx.beginPath();ctx.arc(r[k+'_x']*scale,r[k+'_y']*scale,8,0,Math.PI*2);ctx.stroke();}}
coordsElement.textContent=JSON.stringify(r,null,2);statusElement.textContent='Mode: '+mode+' | completed '+Object.values(labels).filter(x=>x.upper_x!==''||!x.upper_visible).length+'/'+frames.length;}}
function load(){{let r=current();titleElement.textContent='Frame '+frames[index]+' ('+(index+1)+'/'+frames.length+')';
upperVisible.checked=r.upper_visible;lowerVisible.checked=r.lower_visible;condition.value=r.film_condition;notes.value=r.notes;
image.onload=()=>{{canvas.width=roiWidth*scale;canvas.height=900*scale;draw()}};
image.onerror=()=>{{statusElement.textContent='IMAGE LOAD FAILED: '+image.src}};
image.src='roi/frame_'+String(frames[index]).padStart(6,'0')+'.png';}}
canvas.onclick=e=>{{let rect=canvas.getBoundingClientRect(),r=current();r[mode+'_x']=(e.clientX-rect.left)*canvas.width/rect.width/scale;
r[mode+'_y']=(e.clientY-rect.top)*canvas.height/rect.height/scale;labels[frames[index]]=r;saveForm();mode=mode==='upper'?'lower':'upper';draw()}};
function setMode(x){{saveForm();mode=x;draw()}} function next(){{saveForm();index=Math.min(frames.length-1,index+1);load()}}
function prev(){{saveForm();index=Math.max(0,index-1);load()}} function clearCurrent(){{labels[frames[index]]=undefined;delete labels[frames[index]];saveForm();load()}}
function downloadCsv(){{saveForm();let fields={json.dumps(FIELDS)},lines=[fields.join(',')];for(const f of frames){{let r=labels[f]||blank();
let vals=[f,...fields.slice(1).map(k=>r[k]??'')].map(v=>'"'+String(v).replaceAll('"','""')+'"');lines.push(vals.join(','));}}
let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([lines.join('\\n')+'\\n'],{{type:'text/csv'}}));a.download='{output_name}';a.click();}}
for(const id of ['upperVisible','lowerVisible','condition','notes'])document.getElementById(id).onchange=saveForm;load();
</script>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--first-frame", type=int, required=True)
    parser.add_argument("--last-frame", type=int, required=True)
    parser.add_argument("--count", type=int, default=75)
    parser.add_argument("--roi-width", type=int, default=120)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    roi_dir=args.output/"roi"; review_dir=args.output/"review_images"
    roi_dir.mkdir(exist_ok=True); review_dir.mkdir(exist_ok=True)
    required = BLUE_REQUIRED if args.first_frame == 3000 and args.last_frame == 3999 else set()
    selected = stratified_frames(args.first_frame, args.last_frame, args.count, required)
    wanted=set(selected)
    with av.open(str(args.video)) as container:
        for index, video_frame in enumerate(container.decode(video=0)):
            source_frame=args.first_frame+index
            if source_frame not in wanted: continue
            bgr=video_frame.to_ndarray(format="bgr24")
            cv2.imwrite(str(roi_dir/f"frame_{source_frame:06d}.png"),bgr[:,:args.roi_width])
            cv2.imwrite(str(review_dir/f"frame_{source_frame:06d}.jpg"),
                        annotate_review(bgr,source_frame,args.roi_width),[cv2.IMWRITE_JPEG_QUALITY,94])
    rows=[{"frame":f,"upper_visible":"","upper_x":"","upper_y":"","lower_visible":"",
           "lower_x":"","lower_y":"","film_condition":"","notes":""} for f in selected]
    with (args.output/"blue_ground_truth_template.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,FIELDS);writer.writeheader();writer.writerows(rows)
    (args.output/"annotate.html").write_text(annotation_html(selected,args.roi_width,"blue"))
    (args.output/"selection.json").write_text(json.dumps({"video":str(args.video),"frames":selected,
      "required_frames":sorted(required),"feature_definition":
      "upper lower-right and lower upper-right physical sprocket-opening corners"},indent=2)+"\n")
    print(json.dumps({"frames":len(selected),"output":str(args.output)},indent=2))


if __name__ == "__main__": main()
