#!/usr/bin/env python3
"""Focused residual-cast still-image POC using fixed sprocket calibration."""
from __future__ import annotations
import argparse,json,platform,subprocess
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from grokcam_sprocket_white_poc import raw12,demosaic
from grokcam_raw_production import PRESETS,subpixel_crop

FRAMES=[1400,1598,1798,2198,2798,3398]; FIXED=np.array([1.06984,1,1.09921])
SRGB2XYZ=np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.072175],[.0193339,.119192,.9503041]])
REGIONS={
1400:[('pale_papers',(360,100,720,280),'pale paper/card; likely low saturation but printed and possibly warm'),('white_bowl',(250,250,470,420),'white serving bowl; specular and aged'),('wood',(330,470,760,700),'wood cabinet; known warm control'),('dark_gate',(930,250,1080,650),'dark gate/edge; not a scene neutral')],
1598:[('white_clothing',(500,430,850,720),'white child clothing; plausible neutral but warm indoor illumination'),('skin',(610,250,790,410),'skin/hair region; mixed pixels and highlights'),('wood',(260,250,620,500),'wood floor/cabinet; warm control'),('blue_pot',(180,380,330,560),'known saturated blue object')],
1798:[('pale_clothing',(560,340,820,650),'pale patterned clothing; plausible low saturation'),('skin',(570,220,790,370),'skin/hair; mixed and shadowed'),('striped_shirt',(300,300,520,620),'nominal black/white stripes; mixed neutral/color detail'),('dark_seat',(760,320,1000,650),'dark upholstery; uncertain neutrality')],
2198:[('white_shirt',(380,180,690,450),'white shirt; plausible neutral with skin spill'),('skin_arm',(300,390,520,670),'skin; mixed illumination'),('gray_trousers',(430,500,720,770),'gray trousers; plausible neutral'),('green_floor',(120,480,360,760),'green floor/carpet; known colored control')],
2798:[('white_box',(100,520,390,770),'white printed box; plausible neutral with orange printing'),('blue_plush',(500,260,850,700),'known saturated blue control'),('red_trim',(620,430,800,570),'known saturated red control'),('dark_upholstery',(300,150,520,400),'dark upholstery; uncertain neutral')],
3398:[('pale_blouse',(260,280,510,620),'pale blouse; plausible neutral but warm interior'),('skin',(330,190,500,330),'skin/hair boundary; mixed pixels'),('wall',(110,180,300,430),'painted wall; low saturation but unknown hue'),('tree_dark',(600,180,970,650),'dark green tree and colored lights; known colored control')],}
WB={'wb_none':[1,1,1],'wb_mild':[1.05,.94,1.03],'wb_medium':[1.10,.88,1.06],'wb_strong':[1.16,.82,1.10],'wb_blue':[1.10,.88,1.12],'wb_red':[1.16,.88,1.05]}
MATRIX=np.array([[1.04,-.03,-.01],[-.025,1.045,-.02],[-.01,-.035,1.045]])
RECOMMENDED={1400:'combined_strong',1598:'combined_mild',1798:'combined_strong',2198:'combined_strong',2798:'combined_mild',3398:'wb_none'}

def tone(x):
 x=np.clip(x,0,None);x=x/(1+x);return np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)
def u8(x):return np.uint8(np.clip(tone(x),0,1)*255+.5)
def regcrop(rgb,anchor):
 c=PRESETS['loose']; chans=[]
 for i in range(3):
  im=Image.fromarray(rgb[:,:,i].astype(np.float32),mode='F');q=subpixel_crop(im,anchor['x']+c['x_offset'],anchor['y']+c['y_offset'],c['width'],c['height']);q=q.rotate(180).transpose(Image.Transpose.FLIP_LEFT_RIGHT);chans.append(np.asarray(q))
 return np.stack(chans,-1)
def curve(rgb,strength=1):
 l=rgb@np.array([.2126,.7152,.0722]); # smooth density-dependent multipliers
 mid=np.exp(-((l-.28)/.24)**2); shadow=np.exp(-((l-.07)/.09)**2)
 gains=np.stack([1+strength*(.13*mid+.04*shadow),1-strength*(.11*mid+.03*shadow),1+strength*(.10*mid+.03*shadow)],-1)
 return rgb*gains
def candidate(base,name):
 if name in WB:return base*np.array(WB[name])
 if name=='curve':return curve(base,1)
 if name=='matrix':return np.clip(base@MATRIX.T,0,None)
 if name=='combined_mild':return curve(base*np.array(WB['wb_mild']),.55)
 if name=='combined_strong':return curve(base*np.array(WB['wb_medium']),.75)
 raise KeyError(name)
def patchstats(a,box):
 x0,y0,x1,y1=box;p=a[y0:y1,x0:x1].reshape(-1,3);med=np.median(p,0);disp=tone(med);xyz=SRGB2XYZ@med;s=xyz.sum();xy=[float(xyz[0]/s),float(xyz[1]/s)] if s else [0,0];lum=p@np.array([.2126,.7152,.0722]);cuts=np.percentile(lum,[33.333,66.667]);bins=[]
 for name,mask in [('shadow',lum<=cuts[0]),('midtone',(lum>cuts[0])&(lum<=cuts[1])),('highlight',lum>cuts[1])]:
  m=np.median(p[mask],0);z=SRGB2XYZ@m;ss=z.sum();bins.append({'density_bin':name,'linear_median_rgb':m.tolist(),'linear_luminance':float(m@np.array([.2126,.7152,.0722])),'xy_chromaticity':[float(z[0]/ss),float(z[1]/ss)] if ss else [0,0]})
 return {'linear_median_rgb':med.tolist(),'linear_std_rgb':np.std(p,0).tolist(),'display_median_rgb':disp.tolist(),'linear_luminance':float(med@np.array([.2126,.7152,.0722])),'xy_chromaticity':xy,'linear_clip_fraction_rgb':[float(np.mean(p[:,i]>=1)) for i in range(3)],'density_bins':bins}
def labeled(arr,text,width=700):
 im=Image.fromarray(u8(arr));im.thumbnail((width,560));out=Image.new('RGB',(im.width,im.height+34),'black');out.paste(im,(0,34));ImageDraw.Draw(out).text((8,10),text,fill='white');return out
def row(items,out,title):
 ims=[labeled(a,t,560) for t,a in items];w=sum(i.width for i in ims);h=max(i.height for i in ims)+38;c=Image.new('RGB',(w,h),(25,25,25));ImageDraw.Draw(c).text((8,10),title,fill='white');x=0
 for im in ims:c.paste(im,(x,38));x+=im.width
 c.save(out,quality=94)
def overlay(base,regions,out,n):
 im=Image.fromarray(u8(base));d=ImageDraw.Draw(im,'RGBA');colors=['red','cyan','magenta','orange','yellow']
 for i,(name,b,why) in enumerate(regions):d.rectangle(b,outline=colors[i],width=4);d.text((b[0]+4,b[1]+4),name,fill=colors[i])
 im.save(out,quality=94)
def chromaplot(rows,out):
 im=Image.new('RGB',(900,600),'white');d=ImageDraw.Draw(im);d.text((10,8),'Base neutral-candidate chromaticity vs linear luminance (labels: frame/region)',fill='black');d.line((70,540,860,540),fill='black');d.line((70,40,70,540),fill='black')
 for r in rows:
  x,y=r['base']['xy_chromaticity'];lum=r['base']['linear_luminance'];px=70+min(lum,1)*790;py=540-min(max((x-y)+.2,0),.4)/.4*500;d.ellipse((px-4,py-4,px+4,py+4),fill='green');d.text((px+5,py-5),f"{r['frame']}/{r['name']}",fill='black')
 d.text((720,560),'luminance →',fill='black');d.text((5,40),'red-minus-green chroma ↑',fill='black');im.save(out)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--raw-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/raw'));ap.add_argument('--sprocket-report',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/outputs/sprocket-white-poc/poc-report.json'));ap.add_argument('--work-dir',type=Path,default=Path('work/residual-cast-poc'));ap.add_argument('--output-dir',type=Path,default=Path('/mnt/GrokCam/projects/RAW_Test/outputs/residual-cast-poc'));a=ap.parse_args();a.work_dir=a.work_dir.resolve();a.output_dir=a.output_dir.resolve()
 for p in (a.work_dir,a.output_dir):p.mkdir(parents=True,exist_ok=True)
 for n in ('base','overlays','wb-grids','family-comparisons','zooms','plots'): (a.output_dir/n).mkdir(exist_ok=True)
 sprocket=json.loads(a.sprocket_report.read_text()); anchors={}
 for n in FRAMES:
  hs=[r['geometry'] for r in sprocket['measurements'] if int(r['frame'])==n]
  anchors[n]={'x':float(np.mean([h['cx'] for h in hs])),'y':float(np.mean([h['cy'] for h in hs]))}
 bases={}; measurements=[]
 for n in FRAMES:
  raw=raw12(a.raw_dir/f'frame_{n:06d}.dng');full=demosaic(raw,FIXED);base=regcrop(full,anchors[n]);bases[n]=base;np.save(a.work_dir/f'base_{n:06d}.npy',base)
  Image.fromarray(u8(base)).save(a.output_dir/'base'/f'frame_{n:06d}.jpg',quality=95);overlay(base,REGIONS[n],a.output_dir/'overlays'/f'frame_{n:06d}.jpg',n)
  for name,box,why in REGIONS[n]:measurements.append({'frame':n,'name':name,'box_xyxy':box,'reason_and_limitation':why,'base':patchstats(base,box)})
  row([(k,candidate(base,k)) for k in WB],a.output_dir/'wb-grids'/f'frame_{n:06d}.jpg',f'frame {n} | fixed exposure/tone | WB/tint-only sweep')
  fam=[('base',base),('wb_medium',candidate(base,'wb_medium')),('curve',candidate(base,'curve')),('matrix',candidate(base,'matrix')),('recommended_'+RECOMMENDED[n],candidate(base,RECOMMENDED[n]))]
  row(fam,a.output_dir/'family-comparisons'/f'frame_{n:06d}.jpg',f'frame {n} | matched correction families')
  # A representative central zoom; region-specific boxes remain in JSON/overlays.
  x0,y0,x1,y1=REGIONS[n][0][1];pad=60;crop=lambda z:z[max(0,y0-pad):min(900,y1+pad),max(0,x0-pad):min(1133,x1+pad)]
  row([('base',crop(base)),('wb',crop(candidate(base,'wb_medium'))),('curve',crop(candidate(base,'curve'))),('recommended',crop(candidate(base,RECOMMENDED[n])))],a.output_dir/'zooms'/f'frame_{n:06d}.jpg',f'frame {n} | {REGIONS[n][0][0]} zoom')
 chromaplot([r for r in measurements if any(x in r['name'] for x in ('pale','white','gray','dark','wall'))],a.output_dir/'plots'/'neutral_chromaticity_vs_luminance.png')
 findings={1400:{'cast':'strong yellow-green mixture; pale highlights and wood both affected','wb_sufficient':False,'crossover':True,'curves_help':True,'matrix_justified':False,'least_aggressive':'combined_strong','uncertainty':'pale papers are printed/aged and original illumination unknown'},1598:{'cast':'warm yellow with moderate green component','wb_sufficient':False,'crossover':True,'curves_help':True,'matrix_justified':False,'least_aggressive':'combined_mild','uncertainty':'white clothing likely reflects warm indoor light'},1798:{'cast':'severe green across pale clothing, skin, and midtones','wb_sufficient':False,'crossover':True,'curves_help':True,'matrix_justified':False,'least_aggressive':'combined_strong','uncertainty':'skin and patterned clothing are mixed samples'},2198:{'cast':'strong green/cyan, most visible in shirt and gray trousers','wb_sufficient':False,'crossover':True,'curves_help':True,'matrix_justified':False,'least_aggressive':'combined_strong','uncertainty':'floor is genuinely green and must not be neutralized'},2798:{'cast':'moderate yellow-green; saturated red/blue controls remain plausible','wb_sufficient':True,'crossover':False,'curves_help':False,'matrix_justified':False,'least_aggressive':'combined_mild','uncertainty':'white box includes orange printing'},3398:{'cast':'relatively plausible warm interior control','wb_sufficient':True,'crossover':False,'curves_help':False,'matrix_justified':False,'least_aggressive':'wb_none','uncertainty':'holiday lighting and wall color are unknown'}}
 report={'poc':'residual-cast-poc','created':datetime.now(timezone.utc).isoformat(timespec='seconds'),'source_policy':'read_only','frames':FRAMES,'source_paths':[str(a.raw_dir/f'frame_{n:06d}.dng') for n in FRAMES],'base_pipeline':{'black':256,'white':4095,'cfa':'BGGR','precision':'float32/float64 measurement and processing; lossless float NPY work bases; 8-bit final review JPEG','fixed_capture_correction_RGB':FIXED.tolist(),'ColorMatrix1':sprocket['ColorMatrix1'],'demosaic':'bilinear from separated BGGR planes','crop':PRESETS['loose'],'tone':'x/(1+x), then sRGB; identical within comparisons','automatic_WB':False,'gray_world':False},'regions':measurements,'candidates':{'wb_rgb_gains':WB,'curve':'luminance-dependent smooth RGB gains: R +13% mid/+4% shadow; G -11% mid/-3% shadow; B +10% mid/+3% shadow','matrix':MATRIX.tolist(),'combined_mild':'wb_mild plus 55% curve','combined_strong':'wb_medium plus 75% curve'},'per_frame_findings':findings,'cross_frame_conclusion':'1400, 1798, and 2198 can share combined_strong as a diagnostic model; 1598 benefits from a milder version, while 2798 and especially 3398 should not receive the strong grade. This is restoration judgment, not capture calibration.','objective_vs_subjective':{'objective':'fixed sprocket correction is held constant','measured_neutralization':'candidate patches quantify residual chroma but are not forced to gray','subjective':'recommended candidates preserve plausible skin, wood, saturated controls, and warm illumination','fading':'brightness-dependent residuals support dye crossover/fading as part of the cast'},'command':f'{Path(__file__).resolve()} --raw-dir {a.raw_dir} --sprocket-report {a.sprocket_report} --work-dir {a.work_dir} --output-dir {a.output_dir}','tools':{'python':platform.python_version(),'numpy':np.__version__,'pillow':Image.__version__},'outputs':str(a.output_dir)}
 (a.output_dir/'poc-report.json').write_text(json.dumps(report,indent=2)+'\n')
 idx=['# Residual-cast POC review','', 'Fixed capture correction in every image: `R×1.06984, G×1, B×1.09921`. No automatic WB, gray-world, or luminance normalization.','', 'Review order:','', '1. [Neutral chromaticity versus luminance](plots/neutral_chromaticity_vs_luminance.png)','2. WB/tint-only grids by frame','3. Matched family comparisons','4. Reference overlays and zooms','', '## Frames','']
 for n in FRAMES:idx += [f'### {n}','',f'- [Base](base/frame_{n:06d}.jpg) · [regions](overlays/frame_{n:06d}.jpg) · [WB grid](wb-grids/frame_{n:06d}.jpg) · [families](family-comparisons/frame_{n:06d}.jpg) · [zoom](zooms/frame_{n:06d}.jpg)','']
 idx += ['- [Machine-readable report](poc-report.json)',''];(a.output_dir/'index.md').write_text('\n'.join(idx))
 print(a.output_dir/'index.md')
if __name__=='__main__':main()
