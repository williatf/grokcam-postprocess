#!/usr/bin/env python3
"""Prepare a sealed, anonymized P13 lower-top landmark review package."""
from __future__ import annotations

import argparse,csv,hashlib,json,random
from pathlib import Path

from PIL import Image

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper


def truth(value):return str(value).lower()=="true"
def bucket(value):
    return "lt1" if value<1 else "1to2" if value<2 else "2to3" if value<3 else "3to5" if value<=5 else "gt5"


def eligible(csv_path):
    rows=list(csv.DictReader(Path(csv_path).open()));by={int(r["frame"]):r for r in rows};pairs=[]
    for frame in sorted(by):
        if frame+1 not in by:continue
        a,b=by[frame],by[frame+1]
        if not truth(a["lower_top_valid"]) or not truth(b["lower_top_valid"]):continue
        ad=float(b["trusted_anchor_y"])-float(a["trusted_anchor_y"]);ld=float(b["lower_top_y"])-float(a["lower_top_y"]);difference=ad-ld
        pairs.append({"frame_a":frame,"frame_b":frame+1,"pair_type":"transition" if a["source"]!=b["source"] else "same_source","stratum":bucket(abs(difference)),"source_a":a["source"],"source_b":b["source"],"anchor_delta":ad,"p11_delta":ld,"difference":difference})
    return by,pairs


def sample_pairs(pairs,seed):
    rng=random.Random(seed);chosen=[]
    transitions=[p for p in pairs if p["pair_type"]=="transition"];chosen.extend(transitions)
    same=[p for p in pairs if p["pair_type"]=="same_source"]
    targets={"lt1":20,"1to2":10,"2to3":10,"3to5":10,"gt5":10}
    for name,target in targets.items():
        population=[p for p in same if p["stratum"]==name];rng.shuffle(population);chosen.extend(population[:target])
    return chosen


HTML=r'''<!doctype html><meta charset="utf-8"><title>P13 blind lower-top review</title>
<style>body{font:18px system-ui;background:#151515;color:#eee;margin:18px}button{font-size:17px;padding:9px;margin:4px}#wrap{position:relative;display:inline-block;border:2px solid #777}#img{display:block;image-rendering:auto}#line{position:absolute;left:0;right:0;height:2px;background:#00e5ff;pointer-events:none;display:none}#status{font-weight:bold;color:#7ee787}.muted{color:#aaa}</style>
<h1>P13 blind physical-landmark review</h1><p>Click the visible <b>top boundary of the lower sprocket hole</b>. No frame number, registration source, anchor, prior measurement, or disagreement is shown.</p>
<p>Use <b>Unmeasurable</b> only when the physical boundary cannot be located confidently. Every item requires explicit submission.</p>
<div><button id="prev">Previous</button><button id="submit">Submit & next</button><button id="unmeas">Unmeasurable & next</button><button id="next">Next</button><button id="download">Download completed CSV</button></div>
<p id="status"></p><div id="wrap"><img id="img"><div id="line"></div></div><p class="muted" id="position"></p>
<script>
let items=[],i=0,key='p13-blind-anchor-v1',data=JSON.parse(localStorage.getItem(key)||'{}');const $=x=>document.getElementById(x);
fetch('items.json').then(r=>r.json()).then(x=>{items=x;show()});function rec(){return data[items[i].item_id]||{}}
function show(){let x=items[i],r=rec();$('img').src=x.image;$('line').style.display=r.status==='measured'?'block':'none';if(r.status==='measured')$('line').style.top=r.crop_y+'px';$('position').textContent=r.status==='measured'?'Marker placed. Submit to freeze this item.':r.status==='unmeasurable'?'Marked unmeasurable and submitted.':'No submitted landmark.';let done=Object.values(data).filter(v=>v.submitted).length;$('status').textContent=`Blind item ${i+1} / ${items.length} — Submitted: ${done} / ${items.length}`}
$('wrap').onclick=e=>{let r=rec();if(r.submitted)return;let box=$('img').getBoundingClientRect(),y=(e.clientY-box.top)*$('img').naturalHeight/box.height;r={status:'measured',crop_y:y,image_y:y+items[i].crop_top,submitted:false};data[items[i].item_id]=r;save();show()};
function save(){localStorage.setItem(key,JSON.stringify(data))}function finish(status){let r=rec();if(status==='measured'&&r.status!=='measured'){alert('Click the landmark first.');return}if(status==='unmeasurable')r={status:'unmeasurable',crop_y:'',image_y:'',submitted:false};r.submitted=true;data[items[i].item_id]=r;save();if(i<items.length-1)i++;show()}
$('submit').onclick=()=>finish('measured');$('unmeas').onclick=()=>finish('unmeasurable');$('prev').onclick=()=>{if(i)i--;show()};$('next').onclick=()=>{if(i<items.length-1)i++;show()};
$('download').onclick=()=>{if(Object.values(data).filter(v=>v.submitted).length!==items.length){alert('Complete every item before download.');return}let out=['item_id,status,crop_y,image_y'];for(let x of items){let r=data[x.item_id];out.push([x.item_id,r.status,r.crop_y,r.image_y].join(','))}let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([out.join('\n')+'\n'],{type:'text/csv'}));a.download='p13_blind_measurements.csv';a.click()};
</script>'''


def main():
    p=argparse.ArgumentParser();p.add_argument("--p09-csv",required=True);p.add_argument("--raw-dir",required=True);p.add_argument("--output-dir",required=True);p.add_argument("--seed",type=int,default=130913);a=p.parse_args();root=Path(a.output_dir);blind=root/"blind_review";images=blind/"images";sealed=root/"sealed";images.mkdir(parents=True,exist_ok=True);sealed.mkdir(parents=True,exist_ok=True)
    rows,population=eligible(a.p09_csv);pairs=sample_pairs(population,a.seed);frames=sorted({p[k] for p in pairs for k in ("frame_a","frame_b")});rng=random.Random(a.seed+1);rng.shuffle(frames)
    calibration=load_calibration();developer=DarktableMatchedDeveloper(calibration.match.report);mapping=[];items=[];working=root/"developed_working.tif";crop=(100,950,700,1200)
    for index,frame in enumerate(frames,1):
        item=f"item_{index:03d}";developer.develop(Path(a.raw_dir)/f"frame_{frame:06d}.dng",working)
        with Image.open(working) as image:image.crop(crop).convert("RGB").save(images/f"{item}.png",compress_level=3)
        working.unlink(missing_ok=True);mapping.append({"item_id":item,"frame":frame});items.append({"item_id":item,"image":f"images/{item}.png","crop_top":crop[1]})
        if index==1 or index%25==0 or index==len(frames):print(f"P13 {index}/{len(frames)}",flush=True)
    frame_to_item={m["frame"]:m["item_id"] for m in mapping}
    pair_records=[]
    counts={}
    for pair in pairs:
        key=(pair["pair_type"],pair["stratum"]);counts[key]=counts.get(key,0)+1;pair_records.append({**pair,"item_a":frame_to_item[pair["frame_a"]],"item_b":frame_to_item[pair["frame_b"]]})
    population_counts={}
    for pair in population:
        key=f'{pair["pair_type"]}:{pair["stratum"]}';population_counts[key]=population_counts.get(key,0)+1
    sealed_data={"version":"p13-blind-v1","seed":a.seed,"crop":{"left":crop[0],"top":crop[1],"right":crop[2],"bottom":crop[3]},"eligible_population_pairs":len(population),"sample_pairs":len(pairs),"unique_frames":len(frames),"population_counts":population_counts,"sample_counts":{f"{k[0]}:{k[1]}":v for k,v in counts.items()},"mapping":mapping,"pairs":pair_records,"p09_csv":str(Path(a.p09_csv).resolve())}
    (sealed/"sample_mapping.json").write_text(json.dumps(sealed_data,indent=2)+"\n");(blind/"items.json").write_text(json.dumps(items,indent=2)+"\n");(blind/"annotate.html").write_text(HTML);print(json.dumps({k:sealed_data[k] for k in ("eligible_population_pairs","sample_pairs","unique_frames","population_counts","sample_counts")},indent=2))


if __name__=="__main__":main()
