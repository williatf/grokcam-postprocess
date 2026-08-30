import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from research.p08_same_frame_y_refinement import DEFAULT_CONFIG, GEOMETRY, refine


class P08Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads(DEFAULT_CONFIG.read_text())

    def image(self, shift=0):
        image=Image.new("RGB",(1000,1800),(15,15,15));draw=ImageDraw.Draw(image)
        anchor_x,anchor_y=400.,800.;ux=anchor_x+17.125-GEOMETRY["lower_minus_upper_x"]/2;uy=anchor_y-GEOMETRY["pitch"]/2
        for cx,cy in ((ux,uy),(ux+GEOMETRY["lower_minus_upper_x"],uy+GEOMETRY["pitch"])):
            draw.rectangle((cx-GEOMETRY["width"]/2,cy+shift-GEOMETRY["height"]/2,cx+GEOMETRY["width"]/2,cy+shift+GEOMETRY["height"]/2),fill=(245,245,245))
        return image

    def test_recovers_bounded_same_frame_shift(self):
        result=refine(self.image(3),400.,800.,self.cfg)
        self.assertTrue(result.integer_accepted)
        self.assertLessEqual(abs(result.integer_offset-3),1)
        self.assertLessEqual(abs(result.subpixel_offset),self.cfg["bound_px"])

    def test_no_trusted_anchor_cannot_be_rescued(self):
        result=refine(self.image(),None,None,self.cfg)
        self.assertFalse(result.trusted);self.assertFalse(result.integer_accepted)
        self.assertEqual(result.rejection_reason,"no_trusted_anchor")

    def test_weak_image_does_no_harm(self):
        result=refine(Image.new("RGB",(1000,1800),(40,40,40)),400.,800.,self.cfg)
        self.assertFalse(result.integer_accepted);self.assertEqual(result.integer_offset,0)
        self.assertEqual(result.subpixel_offset,0)

    def test_search_boundary_peak_does_no_harm(self):
        result=refine(self.image(12),400.,800.,self.cfg)
        self.assertFalse(result.integer_accepted)
        self.assertEqual(result.integer_offset,0)


if __name__=="__main__":unittest.main()
