import json,unittest
from PIL import Image,ImageDraw
from research.p14_detector_guided_edge_registration import DEFAULT_CONFIG,HEIGHT,LOWER_X,PITCH,WIDTH,measure_frame

class P14Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.cfg=json.loads(DEFAULT_CONFIG.read_text())
 def image(self,shift=0):
  im=Image.new('RGB',(1000,1800),(10,10,10));d=ImageDraw.Draw(im);ax,ay=400.,800.;ux=ax+17.125-LOWER_X/2;uy=ay-PITCH/2
  for x,y in ((ux,uy),(ux+LOWER_X,uy+PITCH)):d.rectangle((x-WIDTH/2,y+shift-HEIGHT/2,x+WIDTH/2,y+shift+HEIGHT/2),fill='white')
  return im
 def test_edges_follow_known_shift(self):
  r=measure_frame(self.image(3),400,800,self.cfg)
  for name in ('upper_bottom','lower_top'):self.assertTrue(r[name]['valid']);self.assertLess(abs(r[name]['offset']-3),1.5)
 def test_flat_image_rejects(self):
  r=measure_frame(Image.new('RGB',(1000,1800),'gray'),400,800,self.cfg)
  self.assertFalse(r['upper_bottom']['valid']);self.assertFalse(r['lower_top']['valid'])

if __name__=='__main__':unittest.main()
