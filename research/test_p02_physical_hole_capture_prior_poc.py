import numpy as np
from research.p02_physical_hole_capture_prior_poc import physical_hole


def test_rectangular_physical_hole_is_identified():
    image=np.full((800,800,3),25,dtype=np.uint8);image[270:430,220:480]=245
    hole,reason,_=physical_hole(image,(350,350,260,160),.25)
    assert reason=="success";assert hole is not None
    assert abs(hole.cx-350)<3 and abs(hole.cy-350)<3


def test_arbitrary_thin_edge_is_not_a_hole():
    image=np.full((800,800,3),25,dtype=np.uint8);image[340:355,150:550]=245
    hole,reason,_=physical_hole(image,(350,350,260,160),.35)
    assert hole is None


def test_picture_highlight_outside_predicted_gate_is_rejected():
    image=np.full((800,800,3),25,dtype=np.uint8);image[220:500,500:780]=245
    hole,reason,_=physical_hole(image,(250,350,260,160),.35)
    assert hole is None
