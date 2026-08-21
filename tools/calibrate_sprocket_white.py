#!/usr/bin/env python3
"""Derive a candidate RAW white-balance correction from empty sprocket illumination."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, platform, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

BLACK,WHITE=256,4095; USABLE=WHITE-BLACK
GROUPS=[1400,1598,1798,2198,2798,3398]
FRAMES=[b+i for b in GROUPS for i in range(4)]
ASN=np.array([.3982635708,1,.603646022]); ASN_GAIN=np.array([1/ASN[0],1,1/ASN[2]])
CM=np.array([[.5303,-.0342,-.0657],[-.3287,1.2062,.0975],[-.0479,.223,.3913]])
XYZ2RGB=np.array([[3.2406,-1.5372,-.4986],[-.9689,1.8758,.0415],[.0557,-.204,1.057]])

def run(c,env=None):
 p=subprocess.run([str(x) for x in c],text=True,capture_output=True,env=env)
 if p.returncode: raise RuntimeError(' '.join(map(str,c))+'\n'+p.stderr)
 return p.stdout
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(1048576): h.update(b)
 return h.hexdigest()
def raw12(path):
 # ExifTool verified one uncompressed 12-bit tile at byte 760, 2028x1520.
 with path.open('rb') as f: f.seek(760); b=f.read(4623840)
 a=np.frombuffer(b,np.uint8).reshape(-1,3); x=(a[:,0].astype(np.uint16)<<4)|(a[:,1]>>4); y=((a[:,1]&15).astype(np.uint16)<<8)|a[:,2]
 out=np.empty(3082560,np.uint16); out[0::2]=x; out[1::2]=y
 return out.reshape(1520,2028)
def runs(mask):
 out=[]; start=None
 for i,v in enumerate(mask):
  if v and start is None:start=i
  if start is not None and (not v or i==len(mask)-1):out.append((start,i if not v else i+1));start=None
 return out
def holes(raw):
 # Average each BGGR cell for geometry only, then locate the two bright bands.
 cell=raw.reshape(760,2,1014,2).mean((1,3)); lum=np.repeat(np.repeat(cell,2,0),2,1)
 q=lum[:,100:570]; bright=q>np.percentile(q,99)*.90
 bands=[x for x in runs(bright.sum(1)>130) if 180<=x[1]-x[0]<=330]
 cand=[]
 for u,l in zip(bands,bands[1:]):
  uy,ly=sum(u)/2,sum(l)/2
  if abs((ly-uy)-785)>100:continue
  hs=[]
  for top,bot in (u,l):
   cols=np.flatnonzero(bright[top:bot].sum(0)>(bot-top)*.55)
   if len(cols)<200:break
   hs.append({'cx':float((cols[0]+cols[-1])/2+100),'cy':float((top+bot)/2),'bounds':[int(cols[0]+100),int(top),int(cols[-1]+101),int(bot)]})
  if len(hs)==2:cand.append((abs((ly-uy)-785),hs))
 if not cand: raise ValueError('no reliable sprocket pair')
 return min(cand,key=lambda x:x[0])[1]
def populations(raw,hole):
 cx,cy=int(round(hole['cx']/2)*2),int(round(hole['cy']/2)*2); x0,x1=cx-100,cx+100; y0,y1=cy-70,cy+70
 patch=raw[y0:y1,x0:x1]; cells=patch.reshape(70,2,100,2)
 vals={'B':cells[:,0,:,0].ravel(),'G1':cells[:,0,:,1].ravel(),'G2':cells[:,1,:,0].ravel(),'R':cells[:,1,:,1].ravel()}
 corrected={k:np.clip(v.astype(float)-BLACK,0,None) for k,v in vals.items()}
 cell_l=np.mean(np.stack([corrected[k].reshape(70,100) for k in ('R','G1','G2','B')]),0)
 med=np.median(cell_l); keep=(cell_l>med*.82)&(cell_l<med*1.12)
 result={}; near=USABLE*.98
 for k,v in corrected.items():
  allv=v; v=v.reshape(70,100)[keep]
  result[k]={'n':int(v.size),'median':float(np.median(v)),'p05':float(np.percentile(v,5)),'p25':float(np.percentile(v,25)),'p75':float(np.percentile(v,75)),'p95':float(np.percentile(v,95)),
   'near_clip_fraction':float(np.mean(allv>=near)),'clip_fraction':float(np.mean(allv>=USABLE)),'usable_fraction_of_range':float(np.median(v)/USABLE)}
 contamination=1-float(keep.mean()); worst=max(x['near_clip_fraction'] for x in result.values())
 if worst>=.05: status='unusable_clipping'; reason='at least one CFA population has >=5% near-clipped samples'
 elif contamination>.35: status='unusable_contamination_geometry'; reason='central rectangle required rejection of >35% of 2x2 cells'
 elif worst>=.01 or contamination>.20: status='marginal'; reason='minor near-clipping or spatial contamination'
 else: status='usable'; reason='central eroded region has low clipping and contamination'
 return result,keep,{'rect':[x0,y0,x1,y1],'contamination_fraction':contamination,'classification':status,'reason':reason}
def demosaic(raw,gain):
 x=np.clip((raw.astype(float)-BLACK)/USABLE,0,1); b=x[0::2,0::2]; g=(x[0::2,1::2]+x[1::2,0::2])/2; r=x[1::2,1::2]
 chans=[]
 for a in (r,g,b): chans.append(np.asarray(Image.fromarray(a.astype(np.float32),mode='F').resize((2028,1520),Image.Resampling.BILINEAR)))
 cam=np.stack(chans,-1)*gain; xyz=cam@np.linalg.inv(CM).T; rgb=xyz@XYZ2RGB.T
 return np.clip(rgb,0,None)
def render(rgb,exposure):
 x=rgb*exposure; x=x/(1+x); x=np.where(x<=.0031308,12.92*x,1.055*np.power(x,1/2.4)-.055)
 return np.uint8(np.clip(x,0,1)*255+.5)
def overlay(preview,hs,keeps,out):
 im=preview.copy(); d=ImageDraw.Draw(im,'RGBA')
 for h,k in zip(hs,keeps):
  x0,y0,x1,y1=h['measure']['rect']; d.rectangle((x0,y0,x1,y1),outline=(255,0,255,255),width=4)
  small=Image.fromarray(np.uint8(k)*150,'L').resize((x1-x0,y1-y0),Image.Resampling.NEAREST); layer=Image.new('RGBA',im.size); layer.paste((0,255,0,100),(x0,y0),small); im=Image.alpha_composite(im.convert('RGBA'),layer); d=ImageDraw.Draw(im,'RGBA')
  bx=h['bounds']; d.rectangle(bx,outline=(255,180,0,230),width=3)
 im.convert('RGB').save(out,quality=94)
def histogram(rows,out):
 w,h=900,480; im=Image.new('RGB',(w,h),'white'); d=ImageDraw.Draw(im); colors={'R':'red','G1':(0,150,0),'G2':(0,220,80),'B':'blue'}
 d.text((10,8),'Usable RAW sprocket medians; dashed line = 98% near-clip',fill='black'); d.line((60,430,860,430),fill='black'); d.line((60,40,60,430),fill='black'); d.line((60+800*.98,40,60+800*.98,430),fill='gray',width=2)
 for ci,k in enumerate(('R','G1','G2','B')):
  vals=[r['channels'][k]['median']/USABLE for r in rows if r['classification']=='usable'];
  for i,v in enumerate(vals): d.ellipse((60+800*v-3,65+ci*85+i%5*7,60+800*v+3,71+ci*85+i%5*7),fill=colors[k])
  d.text((10,65+ci*85),k,fill=colors[k])
 im.save(out)
def contact(paths,out):
 ims=[]
 for p in paths:
  im=Image.open(p).convert('RGB'); im.thumbnail((1200,350)); tile=Image.new('RGB',(1200,385),'black');tile.paste(im,(0,35));ImageDraw.Draw(tile).text((8,10),p.stem,fill='white');ims.append(tile)
 c=Image.new('RGB',(1200,len(ims)*385),(25,25,25))
 for i,im in enumerate(ims):c.paste(im,(0,i*385))
 c.save(out,quality=92)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--raw-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/raw'));ap.add_argument('--work-dir',type=Path,default=Path('work/sprocket-white-poc'));ap.add_argument('--output-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/outputs/sprocket-white-poc'));a=ap.parse_args();a.work_dir=a.work_dir.resolve();a.output_dir=a.output_dir.resolve()
 for p in (a.work_dir,a.output_dir):p.mkdir(parents=True,exist_ok=True)
 for n in ('overlays','sprocket-crops','raw-visualizations','comparisons'): (a.output_dir/n).mkdir(exist_ok=True)
 cache=a.work_dir/'cache';(cache/'gmic').mkdir(parents=True,exist_ok=True);env=os.environ.copy();env['XDG_CACHE_HOME']=str(cache)
 measurements=[]; rawmap={}; hsmap={}; commands=[]
 for n in FRAMES:
  src=a.raw_dir/f'frame_{n:06d}.dng';raw=raw12(src);rawmap[n]=raw;hs=holes(raw);keeps=[]
  for i,h in enumerate(hs):
   ch,keep,m=populations(raw,h);h['measure']=m;keeps.append(keep);measurements.append({'frame':n,'hole':i+1,'source':str(src),'classification':m['classification'],'reason':m['reason'],'geometry':h,'channels':ch})
  hsmap[n]=hs
  prev=a.work_dir/f'frame_{n:06d}.jpg';cfg=a.work_dir/'dt'/str(n);cfg.mkdir(parents=True,exist_ok=True);cmd=['darktable-cli',src,prev,'--core','--configdir',cfg];commands.append(' '.join(map(str,cmd)))
  run(cmd,env);overlay(Image.open(prev).convert('RGB'),hs,keeps,a.output_dir/'overlays'/f'frame_{n:06d}.jpg')
  for i,h in enumerate(hs):
   x0,y0,x1,y1=h['measure']['rect'];Image.open(prev).crop((x0-60,y0-60,x1+60,y1+60)).save(a.output_dir/'sprocket-crops'/f'frame_{n:06d}_hole{i+1}.jpg')
   p=raw[y0:y1,x0:x1];v=np.uint8(np.clip((p-BLACK)/USABLE,0,1)*255);Image.fromarray(v).resize((800,560)).save(a.output_dir/'raw-visualizations'/f'frame_{n:06d}_hole{i+1}.png')
 usable=[r for r in measurements if r['classification']=='usable']; ratios=[]
 for r in usable:
  med={k:r['channels'][k]['median'] for k in ('R','G1','G2','B')};g=(med['G1']+med['G2'])/2;ratios.append([med['R']/g,med['G1']/g,med['G2']/g,med['B']/g])
 ratios=np.array(ratios);ratio=np.median(ratios,0);fixed=np.array([1/ratio[0],1,1/ratio[3]])
 # Conventional gains neutralize the measured illuminant. For DNG rendering,
 # ColorMatrix1 already maps its D65 camera-neutral vector (AsShotNeutral) to
 # D65 XYZ, so the required pre-matrix correction is ASN/measured_response.
 render_correction=np.array([ASN[0]/ratio[0],1,ASN[2]/ratio[3]])
 principal=[]
 for n in GROUPS:
  raw=rawmap[n];embedded=demosaic(raw,np.ones(3));fixedrgb=demosaic(raw,render_correction);q=np.percentile(embedded[200:1320,600:1750],75);exp=.40/max(q,.01)
  e=Image.fromarray(render(embedded,exp));f=Image.fromarray(render(fixedrgb,exp));d=Image.open(a.work_dir/f'frame_{n:06d}.jpg').convert('RGB')
  canvas=Image.new('RGB',(2028*3,1560),'black');draw=ImageDraw.Draw(canvas)
  for i,(name,im) in enumerate((('embedded_AsShotNeutral',e),('Darktable_default_reference',d),('fixed_sprocket_WB',f))):canvas.paste(im,(i*2028,40));draw.text((i*2028+10,12),f'{name} | frame {n}',fill='white')
  dst=a.output_dir/'comparisons'/f'frame_{n:06d}.jpg';canvas.resize((1825,468)).save(dst,quality=94);principal.append(dst)
 histogram(usable,a.output_dir/'raw-channel-summary.png');contact(principal,a.output_dir/'controlled-comparisons-contact-sheet.jpg')
 table=a.output_dir/'measurements.csv'
 with table.open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['frame','hole','classification','contamination','R_median','G1_median','G2_median','B_median','R_nearclip','G1_nearclip','G2_nearclip','B_nearclip'])
  for r in measurements:w.writerow([r['frame'],r['hole'],r['classification'],r['geometry']['measure']['contamination_fraction']]+[r['channels'][k]['median'] for k in ('R','G1','G2','B')]+[r['channels'][k]['near_clip_fraction'] for k in ('R','G1','G2','B')])
 report={'poc':'sprocket-white-poc','created':now(),'source_policy':'read_only','packing':'TIFF uncompressed 12-bit, two big-endian packed samples per three bytes','dimensions':[2028,1520],'cfa':'BGGR','black_level':BLACK,'white_level':WHITE,'near_clip_threshold':BLACK+.98*USABLE,'frames':FRAMES,'measurements':measurements,
  'usable_holes':len(usable),'total_holes':len(measurements),'median_raw_ratios_R_G1_G2_B_relative_mean_green':ratio.tolist(),'ratio_robust_sigma_mad':[float(1.4826*np.median(np.abs(ratios[:,i]-np.median(ratios[:,i])))) for i in range(4)],'fixed_gains_RGB_relative_green':fixed.tolist(),'render_correction_RGB_relative_to_embedded_D65':render_correction.tolist(),'AsShotNeutral':ASN.tolist(),'AsShotNeutral_implied_gains_RGB':ASN_GAIN.tolist(),'ColorMatrix1':CM.tolist(),
  'render_note':'Custom embedded/fixed columns use identical simple bilinear demosaic, DNG ColorMatrix1 inversion, exposure and tone. Darktable default is a reference column and necessarily includes its documented default RAW pipeline; it is not used for gain derivation.',
  'commands':commands,'tools':{'python':platform.python_version(),'numpy':np.__version__,'pillow':Image.__version__,'darktable':run(['darktable-cli','--version']).splitlines()[0],'exiftool':run(['exiftool','-ver']).strip()},'output':str(a.output_dir)}
 (a.output_dir/'poc-report.json').write_text(json.dumps(report,indent=2)+'\n')
 idx=['# Sprocket-hole white-reference POC','',f'{len(usable)} of {len(measurements)} hole measurements classified usable.','',f'Fixed RGB gains relative to green: `{fixed.tolist()}`.','',
  'The green/yellow cast is assessed only as capture-system calibration here; no scene gray-world or luminance normalization is applied.','',
  '- [Controlled comparison contact sheet](controlled-comparisons-contact-sheet.jpg)','- [RAW channel summary](raw-channel-summary.png)','- [Measurement table](measurements.csv)','- [Machine report](poc-report.json)','',
  'Individual [mask overlays](overlays/), [sprocket crops](sprocket-crops/), [linear RAW visualizations](raw-visualizations/), and [comparisons](comparisons/) are in their respective directories.','']
 (a.output_dir/'index.md').write_text('\n'.join(idx))
 print(json.dumps({'usable':len(usable),'total':len(measurements),'ratio':ratio.tolist(),'gains':fixed.tolist()}))
if __name__=='__main__':main()
