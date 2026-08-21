#!/usr/bin/env python3
"""Representative-frame, scene-aware color POC; never writes beside source DNGs."""

from __future__ import annotations

import argparse, hashlib, json, os, platform, shutil, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from research._legacy_geometry import PRESETS, detect_anchor, subpixel_crop

VERSION = "0.1.0"
GROUPS = [
    ("early_experiment", range(120,124), "early capture experiment; pale outdoor scene and unstable exposure"),
    ("landscape", range(1000,1004), "bright landscape with sky/water-like distant blue and foliage"),
    ("indoor_transition", range(1400,1404), "green-cast indoor scene near a tonal/color transition"),
    ("child_warm", range(1598,1602), "person/skin tone, white clothing, wood and mixed warm neutrals"),
    ("people_green", range(1798,1802), "people and skin tones under severe green cast"),
    ("bright_skin", range(2198,2202), "bright clothing/skin, dark background and sprocket highlights"),
    ("color_objects", range(2798,2802), "saturated blue/red objects with shadow detail"),
    ("dark_holiday", range(3398,3402), "dark indoor scene, people, colored lights and difficult highlights"),
]
APPROACHES = ["baseline", "conservative_global", "film_aware", "scene_aware"]
ROI = {"x": [0.10, 0.90], "y": [0.10, 0.90]}

def run(cmd):
    p=subprocess.run([str(x) for x in cmd], text=True, capture_output=True)
    if p.returncode: raise RuntimeError(f"command failed: {' '.join(map(str,cmd))}\n{p.stderr}")
    return p.stdout

def version(cmd): return (run(cmd).splitlines() or [""])[0]
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1024*1024): h.update(b)
    return h.hexdigest()
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def roi_pixels(a):
    h,w=a.shape[:2]; return a[int(h*.10):int(h*.90),int(w*.10):int(w*.90)].reshape(-1,3)
def stats(a):
    p=roi_pixels(a); l=p@np.array([.2126,.7152,.0722]); usable=p[(l>.025)&(l<.975)]
    if len(usable)<100: usable=p
    lum=usable@np.array([.2126,.7152,.0722]); ch=np.median(usable,axis=0)
    return {"median_luma":float(np.median(lum)),"channel_median_rgb":ch.tolist(),
            "channel_balance_log_std":float(np.std(np.log(np.maximum(ch,.001)))),
            "shadow_fraction":float(np.mean(np.max(p,axis=1)<.01)),
            "highlight_fraction":float(np.mean(np.max(p,axis=1)>.99)),
            "channel_clip_fraction_rgb":[float(np.mean(p[:,i]>.995)) for i in range(3)]}
def params_from_arrays(arrays, strength, exposure_strength, target=.52):
    pooled=np.concatenate([roi_pixels(a)[::16] for a in arrays]); lum=pooled@np.array([.2126,.7152,.0722])
    usable=pooled[(lum>.04)&(lum<.92)]; ch=np.median(usable,axis=0)
    neutral=float(np.exp(np.mean(np.log(np.maximum(ch,.02)))))
    gains=np.clip(neutral/np.maximum(ch,.02),.68,1.38); gains=1+(gains-1)*strength
    med=float(np.median(usable@np.array([.2126,.7152,.0722])))
    exp=float(np.clip((target/max(med,.05))**exposure_strength,2**-.45,2**.45))
    return exp,gains
def apply(a, exp, gains):
    x=a*exp*gains.reshape(1,1,3)
    # Smooth, channel-preserving shoulder; avoids hard clipping sprockets/highlights.
    x=x/(1+.10*np.maximum(x-0.70,0))
    return np.clip(x,0,1)
def label(im,text):
    out=Image.new('RGB',(im.width,im.height+38),'black'); out.paste(im,(0,38))
    ImageDraw.Draw(out).text((8,10),text,fill='white'); return out
def sheet(paths,out,title,cols=4):
    ims=[Image.open(p).convert('RGB') for p in paths]; thumb=(360,286)
    tiles=[]
    for p,im in zip(paths,ims):
        im.thumbnail(thumb,Image.Resampling.LANCZOS); tiles.append(label(im,f"{p.parent.name} | {p.stem}"))
    rows=(len(tiles)+cols-1)//cols; canvas=Image.new('RGB',(cols*thumb[0],rows*324+42),(28,28,28))
    ImageDraw.Draw(canvas).text((10,12),title,fill='white')
    for i,im in enumerate(tiles): canvas.paste(im,((i%cols)*thumb[0],42+(i//cols)*324))
    canvas.save(out,quality=92)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--raw-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/raw'))
    ap.add_argument('--work-dir',type=Path,default=Path('work/color-poc')); ap.add_argument('--output-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/outputs/color-poc'))
    ap.add_argument('--keep-tiffs',action='store_true'); args=ap.parse_args(); args.work_dir=args.work_dir.resolve(); args.output_dir=args.output_dir.resolve()
    for p in (args.work_dir,args.output_dir): p.mkdir(parents=True,exist_ok=True)
    cache=args.work_dir/'cache'; (cache/'gmic').mkdir(parents=True,exist_ok=True)
    tiffs=args.work_dir/'tiff'; reg=args.work_dir/'registered'; tiffs.mkdir(exist_ok=True); reg.mkdir(exist_ok=True)
    env=os.environ.copy(); env['XDG_CACHE_HOME']=str(cache)
    selected=[]; arrays={}; anchors={}; commands=[]
    for group,numbers,reason in GROUPS:
      for n in numbers:
        dng=args.raw_dir/f'frame_{n:06d}.dng'; tif=tiffs/f'frame_{n:06d}.tif'; cfg=args.work_dir/'dt-config'/f'{n:06d}'; cfg.mkdir(parents=True,exist_ok=True)
        cmd=['darktable-cli',dng,tif,'--core','--configdir',cfg,'--conf','plugins/imageio/format/tiff/bpp=16','--conf','plugins/imageio/format/tiff/compress=1']
        commands.append(' '.join(map(str,cmd)))
        if not tif.exists():
            p=subprocess.run([str(x) for x in cmd],text=True,capture_output=True,env=env)
            if p.returncode or not tif.exists(): raise RuntimeError(p.stderr)
        with Image.open(tif) as im:
            score,x,y=detect_anchor(im); c=PRESETS['loose']; crop=subpixel_crop(im.convert('RGB'),x+c['x_offset'],y+c['y_offset'],c['width'],c['height'])
        crop=crop.rotate(180,expand=False).transpose(Image.Transpose.FLIP_LEFT_RIGHT); crop=ImageEnhance.Contrast(crop).enhance(1.04)
        crop.save(reg/f'frame_{n:06d}.png'); arrays[n]=np.asarray(crop,dtype=np.float32)/255.; anchors[n]={'x':x,'y':y,'score':score}
        selected.append({'frame':n,'source':str(dng),'group':group,'reason':reason})
    all_arrays=list(arrays.values()); global_exp,global_gain=params_from_arrays(all_arrays,.45,.25,.50)
    corrections={a:{} for a in APPROACHES}; measurements={a:{} for a in APPROACHES}
    for group,numbers,reason in GROUPS:
        nums=list(numbers); scene_exp,scene_gain=params_from_arrays([arrays[n] for n in nums],.72,.35,.50)
        # Exact production normalization, with its radius-4 rolling median. In a
        # four-frame POC group the rolling window resolves to one stable group value.
        raw_base=[]
        for n in nums:
            s=stats(arrays[n]); ch=np.array(s['channel_median_rgb']); neutral=np.exp(np.mean(np.log(np.maximum(ch,.02))))
            bg=np.clip(neutral/np.maximum(ch,.02),.78,1.28); bg=1+(bg-1)*.25
            be=float(np.clip(.801/max(s['median_luma'],.03),2**-.65,2**.65)); raw_base.append((be,bg))
        base_exp=float(np.median([x[0] for x in raw_base])); base_gain=np.median(np.array([x[1] for x in raw_base]),axis=0)
        for n in nums:
            a=arrays[n]
            frame_exp,frame_gain=params_from_arrays([a],.72,.35,.50)
            ps={'baseline':(base_exp,base_gain),'conservative_global':(global_exp,global_gain),'film_aware':(frame_exp,frame_gain),'scene_aware':(scene_exp,scene_gain)}
            for approach,(exp,gain) in ps.items():
                dst=args.output_dir/'frames'/approach/f'frame_{n:06d}.jpg'; dst.parent.mkdir(parents=True,exist_ok=True)
                if approach=='baseline':
                    x=a*exp*gain.reshape(1,1,3); out=np.clip(x/(1+.12*x),0,1)
                else: out=apply(a,exp,gain)
                corrections[approach][str(n)]={'exposure_gain':exp,'channel_gains_rgb':gain.tolist()}; measurements[approach][str(n)]=stats(out)
    contacts=args.output_dir/'contact-sheets'; contacts.mkdir(exist_ok=True)
    for approach in APPROACHES: sheet(sorted((args.output_dir/'frames'/approach).glob('*.jpg')),contacts/f'{approach}.jpg',approach)
    comps=args.output_dir/'enlarged-comparisons'; comps.mkdir(exist_ok=True)
    for n in (1000,1400,1800,2200,2800,3400):
        paths=[args.output_dir/'frames'/a/f'frame_{n:06d}.jpg' for a in APPROACHES]; sheet(paths,comps/f'frame_{n:06d}.jpg',f'frame {n}',4)
    clips=args.output_dir/'clips'; clips.mkdir(exist_ok=True)
    for group,numbers,_ in GROUPS:
      nums=list(numbers); tmp=args.work_dir/'clip'; tmp.mkdir(exist_ok=True)
      for i,n in enumerate(nums):
        ims=[Image.open(args.output_dir/'frames'/a/f'frame_{n:06d}.jpg').resize((566,450)) for a in APPROACHES]
        c=Image.new('RGB',(1132,976),'black'); d=ImageDraw.Draw(c)
        for j,(a,im) in enumerate(zip(APPROACHES,ims)): c.paste(im,((j%2)*566,38+(j//2)*488)); d.text(((j%2)*566+8,(j//2)*488+10),f'{a} | frame {n}',fill='white')
        c.save(tmp/f'{i:06d}.jpg',quality=93)
      clip=clips/f'{group}_16fps.mp4'; run(['ffmpeg','-y','-hide_banner','-loglevel','error','-framerate','16','-i',tmp/'%06d.jpg','-frames:v',len(nums),'-c:v','libx264','-crf','15','-pix_fmt','yuv420p',clip])
      for p in tmp.glob('*.jpg'): p.unlink()
    temporal={}
    for approach in APPROACHES:
      temporal[approach]={}
      for group,numbers,_ in GROUPS:
        rows=[measurements[approach][str(n)] for n in numbers]; l=np.array([r['median_luma'] for r in rows]); b=np.array([r['channel_balance_log_std'] for r in rows])
        temporal[approach][group]={'luma_std':float(l.std()),'luma_max_step':float(np.max(np.abs(np.diff(l)))),'channel_balance_std':float(b.std()),'max_highlight_fraction':max(r['highlight_fraction'] for r in rows)}
    report={'poc':'grokcam_color_poc','version':VERSION,'created':now(),'source_policy':'read_only','selected_frames':selected,'crop':PRESETS['loose'],'analysis_roi':ROI,
      'approaches':{'baseline':'exact production normalization: target 0.801, bounded gray balance at 25%, radius-4 median represented by one stable value per four-frame group, and x/(1+0.12x) compression','conservative_global':'one pooled global correction, 45% gray-balance strength','film_aware':'per-frame picture-aperture correction; diagnostic for pumping risk','scene_aware':'one correction per four-frame scene group, 72% gray-balance strength'},
      'global_parameters':{'exposure_gain':global_exp,'channel_gains_rgb':global_gain.tolist()},'corrections':corrections,'measurements':measurements,'temporal':temporal,'anchors':anchors,
      'commands':commands,'tools':{'python':platform.python_version(),'numpy':np.__version__,'pillow':Image.__version__,'darktable':version(['darktable-cli','--version']),'ffmpeg':version(['ffmpeg','-version']),'exiftool':version(['exiftool','-ver'])},'outputs':str(args.output_dir)}
    (args.output_dir/'poc-report.json').write_text(json.dumps(report,indent=2)+'\n')
    index=['# GrokCam color POC review','',f'Generated {report["created"]}. Frames are registered with the production loose crop; color statistics use only the inset picture area.','', '## Contact sheets','']
    index += [f'- [{a}](contact-sheets/{a}.jpg)' for a in APPROACHES]; index += ['', '## Difficult-frame comparisons','']+[f'- [frame {n}](enlarged-comparisons/frame_{n:06d}.jpg)' for n in (1000,1400,1800,2200,2800,3400)]
    index += ['', '## Adjacent-frame clips (16 fps)','']+[f'- [{g}](clips/{g}_16fps.mp4)' for g,_,_ in GROUPS]; index += ['', '- [Machine-readable report](poc-report.json)','']
    (args.output_dir/'index.md').write_text('\n'.join(index))
    for p in args.output_dir.rglob('*'):
        if p.is_file(): report.setdefault('verification',{})[str(p.relative_to(args.output_dir))]={'bytes':p.stat().st_size,'sha256':sha(p)}
    (args.output_dir/'poc-report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not args.keep_tiffs:
        shutil.rmtree(tiffs); shutil.rmtree(args.work_dir/'dt-config',ignore_errors=True)
    print(args.output_dir/'index.md')

if __name__=='__main__': main()
