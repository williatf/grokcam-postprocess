#!/usr/bin/env python3
"""Validate completeness and coordinate sanity of manual sprocket XY labels."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


TRUE = {"true", "1", "yes", "y"}
FALSE = {"false", "0", "no", "n"}


def parse_visible(value: str, frame: int, region: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE: return True
    if normalized in FALSE: return False
    raise ValueError(f"frame {frame}: {region}_visible must be true or false")


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("csv",type=Path)
    parser.add_argument("--expected-count",type=int);args=parser.parse_args()
    rows=list(csv.DictReader(args.csv.open()))
    errors=[];frames=[];visible={"upper":0,"lower":0}
    if args.expected_count is not None and len(rows)!=args.expected_count:
        errors.append(f"expected {args.expected_count} rows, found {len(rows)}")
    for row in rows:
        try: frame=int(row["frame"]);frames.append(frame)
        except Exception: errors.append(f"invalid frame: {row.get('frame')!r}");continue
        for region in ("upper","lower"):
            try: is_visible=parse_visible(row[f"{region}_visible"],frame,region)
            except ValueError as exc: errors.append(str(exc));continue
            if not is_visible: continue
            visible[region]+=1
            for axis,limit in (("x",120),("y",900)):
                try: value=float(row[f"{region}_{axis}"])
                except Exception: errors.append(f"frame {frame}: missing {region}_{axis}");continue
                if not math.isfinite(value) or not 0<=value<limit:
                    errors.append(f"frame {frame}: {region}_{axis}={value} outside [0,{limit})")
        if not row.get("film_condition","").strip():
            errors.append(f"frame {frame}: missing film_condition")
    if len(frames)!=len(set(frames)): errors.append("duplicate frame rows")
    summary={"rows":len(rows),"visible":visible,"errors":errors}
    print(json.dumps(summary,indent=2))
    if errors: raise SystemExit(1)


if __name__=="__main__":main()

