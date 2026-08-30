import json
import unittest

from PIL import Image, ImageDraw

from research.p09_sprocket_y_landmark_metrology import DEFAULT_CONFIG, HEIGHT, LOWER_X, PITCH, WIDTH, measure_frame


class P09Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.cfg=json.loads(DEFAULT_CONFIG.read_text())

    def image(self,shift=0):
        image=Image.new("RGB",(1000,1800),(10,10,10));draw=ImageDraw.Draw(image);ax,ay=400.,800.;ux=ax+17.125-LOWER_X/2;uy=ay-PITCH/2
        for cx,cy in ((ux,uy),(ux+LOWER_X,uy+PITCH)):draw.rectangle((cx-WIDTH/2,cy+shift-HEIGHT/2,cx+WIDTH/2,cy+shift+HEIGHT/2),fill="white")
        return image

    def test_four_independent_boundaries_follow_shift(self):
        result=measure_frame(self.image(3),400.,800.,self.cfg)
        self.assertEqual(set(k for k in result if k!="runtime_ms"),{"upper_top","upper_bottom","lower_top","lower_bottom"})
        for value in result.values():
            if isinstance(value,dict):self.assertTrue(value["valid"]);self.assertLess(abs(value["offset"]-3),1.5)

    def test_flat_image_fails_all_boundaries(self):
        result=measure_frame(Image.new("RGB",(1000,1800),"gray"),400.,800.,self.cfg)
        self.assertFalse(any(value["valid"] for value in result.values() if isinstance(value,dict)))


if __name__=="__main__":unittest.main()
