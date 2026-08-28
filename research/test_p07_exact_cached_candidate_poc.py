import json
from pathlib import Path
import cv2,numpy as np
from research.p07_joint_rigid_sprocket_pair_evidence_poc import fit_pair
from research.p07_exact_cached_candidate_poc import fit_pair_cached
CFG=json.loads(Path('research/p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json').read_text())
def image():
 im=np.full((1800,1100,3),20,np.uint8);w=round(CFG['hole_width']);h=round(CFG['hole_height']);cv2.rectangle(im,(400-w//2,350-h//2),(400+w//2,350+h//2),(240,240,240),-1);x=round(400+CFG['lower_minus_upper_x']);y=round(350+CFG['pitch']);cv2.rectangle(im,(x-w//2,y-h//2),(x+w//2,y+h//2),(240,240,240),-1);return im
def test_cached_variant_is_exact_on_synthetic_pair():
 im=image();a=fit_pair(im,[],[],None,CFG);m={};b=fit_pair_cached(im,[],[],None,CFG,m);assert a==b;assert m['candidate_cache_hits']>0;assert m['percentile_calls_avoided']==m['candidate_cache_hits']*4
def test_cached_variant_preserves_rejection():
 im=np.full((1800,1100,3),20,np.uint8);assert fit_pair(im,[],[],None,CFG)==fit_pair_cached(im,[],[],None,CFG,{})
