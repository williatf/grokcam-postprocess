import json
from pathlib import Path
import cv2,numpy as np
from research.p07_joint_rigid_sprocket_pair_evidence_poc import _prefer_direct_support,fit_pair
CFG=json.loads(Path('research/p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json').read_text())
def pair_image(bridge=False,only_upper=False):
 im=np.full((1800,1100,3),20,np.uint8);w=round(CFG['hole_width']);h=round(CFG['hole_height']);ux,uy=400,350;lx=round(ux+CFG['lower_minus_upper_x']);ly=round(uy+CFG['pitch'])
 cv2.rectangle(im,(ux-w//2,uy-h//2),(ux+w//2,uy+h//2),(240,240,240),-1)
 if not only_upper:cv2.rectangle(im,(lx-w//2,ly-h//2),(lx+w//2,ly+h//2),(240,240,240),-1)
 if bridge and not only_upper:cv2.rectangle(im,(390,uy+h//2-4),(430,ly-h//2+4),(240,240,240),-1)
 return im
def test_joint_pair_detects_without_normal_seed():
 best=fit_pair(pair_image(),[],[],None,CFG);assert best['safe'];assert abs(best['upper_x']-400)<=4;assert abs(best['upper_y']-350)<=4;assert best['upper_supported']>=4;assert best['lower_supported']>=4
def test_bridge_is_missing_damage_not_shape_fit():
 best=fit_pair(pair_image(True),[],[],None,CFG);assert best['safe'];assert best['lower_y']-best['upper_y']==CFG['pitch'];assert best['lower_x']-best['upper_x']==CFG['lower_minus_upper_x']
def test_one_hole_cannot_manufacture_rigid_pair():
 best=fit_pair(pair_image(only_upper=True),[],[],None,CFG);assert not best['safe'];assert best['lower_supported']<CFG['minimum_weaker_hole_supported'] or best['supported']<CFG['minimum_total_supported']
def test_blank_image_rejected():
 best=fit_pair(np.full((1800,1100,3),20,np.uint8),[],[],None,CFG);assert not best['safe'];assert best['supported']==0
def test_supported_modeled_wall_is_not_overridden_by_nearby_parallel_edge():
 im=pair_image();x=400+round(CFG['hole_width'])//2+16;cv2.line(im,(x,240),(x,460),(255,255,255),8)
 best=fit_pair(im,[],[],None,CFG);assert best['safe'];assert best['upper']['states']['right_wall']=='supported'
def test_displaced_same_polarity_edge_is_missing_not_contradictory():
 ev={'states':{'top_edge':'contradicted'},'strengths':{'top_edge':.1},'contradictions':{'top_edge':.9},'residuals':{'top_edge':12},'score':0.,'supported':0,'missing':0,'contradicted':1,'strongest_contradiction':.9}
 out=_prefer_direct_support(ev,CFG);assert out['states']['top_edge']=='missing';assert out['contradicted']==0;assert out['residuals']['top_edge']==12
