import cv2,numpy as np
from research.p05_rigid_consensus_partial_hole_poc import fit_fixed
from pathlib import Path
import json
CFG=json.loads(Path('research/p05_rigid_consensus_partial_hole_blue_frozen.json').read_text())
def test_fixed_geometry_never_follows_torn_contour_dimensions():
 im=np.full((900,1000,3),20,np.uint8);cv2.rectangle(im,(300,300),(682,572),(240,240,240),-1);cv2.rectangle(im,(430,530),(650,620),(20,20,20),-1)
 model,detail,_=fit_fixed(im,(491,436),CFG);assert model is not None;assert model.width==CFG['hole_width'];assert model.height==CFG['hole_height']
def test_geometry_alone_cannot_detect_blank_partner():
 im=np.full((900,1000,3),20,np.uint8);model,_,_=fit_fixed(im,(491,436),CFG);assert model is None
def test_single_false_wall_is_an_outlier_not_an_anchor():
 im=np.full((900,1000,3),20,np.uint8);cv2.rectangle(im,(300,300),(682,572),(240,240,240),-1);cv2.rectangle(im,(430,530),(650,620),(20,20,20),-1)
 cv2.line(im,(730,300),(730,572),(255,255,255),8)
 model,detail,_=fit_fixed(im,(491,436),CFG);assert model is not None;assert abs(model.cx-491)<2;assert any(not a['inlier'] and a['kind']=='vertical' and a['x']>700 for a in detail['assignments'])
