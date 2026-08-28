import cv2
import numpy as np

from research.p03_partner_assisted_partial_hole_poc import fit_partial_partner


def synthetic(missing="none"):
    image=np.full((700,900,3),25,np.uint8)
    cv2.rectangle(image,(280,210),(620,490),(235,235,235),-1)
    if missing=="bottom":cv2.rectangle(image,(350,460),(550,510),(25,25,25),-1)
    return image


def test_intact_or_partially_torn_partner_has_pixel_fit():
    fit,detail=fit_partial_partner(synthetic("bottom"),(450,350,340,280),(340,280))
    assert fit is not None
    assert len(detail["accepted_features"])>=4


def test_no_hole_cannot_be_inferred_from_geometry_alone():
    image=np.full((700,900,3),25,np.uint8)
    fit,detail=fit_partial_partner(image,(450,350,340,280),(340,280))
    assert fit is None
