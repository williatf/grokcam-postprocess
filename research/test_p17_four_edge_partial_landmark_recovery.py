import unittest
from research.p17_four_edge_partial_landmark_recovery import canonical_consensus

class P17Tests(unittest.TestCase):
    def test_single_and_consensus_and_disagreement(self):
        cfg={"cross_edge_consensus_tolerance_px":2}
        offsets={"a":10,"b":20}
        value,reason,_=canonical_consensus({"a":{"accepted":True,"y":100},"b":{"accepted":False,"y":None}},offsets,cfg)
        self.assertEqual(value,110);self.assertIsNone(reason)
        value,reason,_=canonical_consensus({"a":{"accepted":True,"y":100},"b":{"accepted":True,"y":91}},offsets,cfg)
        self.assertEqual(value,110.5);self.assertIsNone(reason)
        value,reason,_=canonical_consensus({"a":{"accepted":True,"y":100},"b":{"accepted":True,"y":95}},offsets,cfg)
        self.assertIsNone(value);self.assertEqual(reason,"cross_edge_disagreement")

if __name__=="__main__":unittest.main()
