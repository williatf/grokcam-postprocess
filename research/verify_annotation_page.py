#!/usr/bin/env python3
"""Verify the served annotation page and every relative image resource."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

import cv2
import numpy as np


def fetch(url: str) -> tuple[bytes, str]:
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read(), response.headers.get_content_type()


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("base_url")
    parser.add_argument("selection",type=Path);args=parser.parse_args()
    base=args.base_url.rstrip("/")+"/"; selection=json.loads(args.selection.read_text())
    page,page_type=fetch(urljoin(base,"annotate.html"));html=page.decode("utf-8")
    required=["function load()", "image.onload", "localStorage.getItem",
              "function downloadCsv()", r"lines.join('\n')+'\n'", "load();"]
    missing=[token for token in required if token not in html]
    if missing: raise RuntimeError(f"annotation page is missing required JavaScript: {missing}")
    checked=[]
    for frame in selection["frames"]:
        relative=f"roi/frame_{frame:06d}.png";body,content_type=fetch(urljoin(base,relative))
        image=cv2.imdecode(np.frombuffer(body,dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[:2]!=(900,120):
            raise RuntimeError(f"{relative}: expected 120x900 image")
        checked.append(relative)
    print(json.dumps({"page_status":200,"page_content_type":page_type,
      "first_image":checked[0],"last_image":checked[-1],"images_verified":len(checked)},indent=2))


if __name__=="__main__":main()

