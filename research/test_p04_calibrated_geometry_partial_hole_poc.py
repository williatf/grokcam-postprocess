import cv2,numpy as np
from research.p04_calibrated_geometry_partial_hole_poc import fit_fixed
from pathlib import Path
import json
CFG=json.loads(Path('research/p04_calibrated_geometry_partial_hole_blue_frozen.json').read_text())
def test_fixed_geometry_never_follows_torn_contour_dimensions():
 im=np.full((900,1000,3),20,np.uint8);cv2.rectangle(im,(300,300),(682,572),(240,240,240),-1);cv2.rectangle(im,(430,530),(650,620),(20,20,20),-1)
 model,detail,_=fit_fixed(im,(491,436),CFG);assert model is not None;assert model.width==CFG['hole_width'];assert model.height==CFG['hole_height']
def test_geometry_alone_cannot_detect_blank_partner():
 im=np.full((900,1000,3),20,np.uint8);model,_,_=fit_fixed(im,(491,436),CFG);assert model is None
