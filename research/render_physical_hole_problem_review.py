#!/usr/bin/env python3
"""Render unresolved physical-hole POC frames without changing detector decisions."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.image_processing import registered_frame
from grokcam.models import CropGeometry
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS, load_capture, load_manifest, transform_boxes
from research.p02_physical_hole_capture_prior_poc import physical_hole

POC = ROOT / "research/output/sprocket_xy/physical_hole_capture_prior_poc"
DEFAULT_OUTPUT = POC / "Reel_46335/problem_frame_review"
FROZEN = ROOT / "research/p02_physical_hole_capture_prior_blue_frozen.json"
ORDER = ["size_shape", "roi_edge_escape", "ineligible", "pitch", "solidity", "x_agreement", "other"]
LABELS = {
    "size_shape": "SIZE / SHAPE",
    "roi_edge_escape": "ROI-EDGE ESCAPE",
    "ineligible": "INELIGIBLE CAPTURE EVIDENCE",
    "pitch": "PITCH",
    "solidity": "SOLIDITY",
    "x_agreement": "X AGREEMENT",
    "other": "OTHER / BROAD DISAGREEMENT",
}


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except ValueError:
        return None


def classify(row: dict) -> str:
    reason = row["physical_failure_reason"]
    if reason in ORDER and reason != "success":
        return reason
    return "other"


def any_capture_boxes(item: dict) -> list[tuple[float, float, float, float]]:
    eligible = transform_boxes(item)
    if eligible:
        return eligible
    values = item.get("sprockets") or []
    if not values:
        return []
    sx = float(item["raw_width"]) / float(item["preview_width"])
    sy = float(item["raw_height"]) / float(item["preview_height"])
    return [(float(v[0]) * sx, float(v[1]) * sy, float(v[2]) * sx, float(v[3]) * sy)
            for v in sorted(values, key=lambda value: float(value[1]))[:2]]


def roi_bounds(box, width, height, margin):
    px, py, pw, ph = box
    return (max(0, int(math.floor(px - pw * (.5 + margin)))),
            max(0, int(math.floor(py - ph * (.5 + margin)))),
            min(width, int(math.ceil(px + pw * (.5 + margin)))),
            min(height, int(math.ceil(py + ph * (.5 + margin)))))


def draw_cross(draw, x, y, color, radius=16, width=5):
    draw.line((x-radius, y, x+radius, y), fill=color, width=width)
    draw.line((x, y-radius, x, y+radius), fill=color, width=width)


def roi_panel(image, box, candidate, title, margin, size=(650, 330)):
    x0, y0, x1, y1 = roi_bounds(box, image.width, image.height, margin)
    if x1 <= x0 or y1 <= y0:
        panel = Image.new("RGB", size, "#171717")
        ImageDraw.Draw(panel).text((18, 18), f"{title}: ROI outside image", fill="white")
        return panel
    crop = image.crop((x0, y0, x1, y1)).convert("RGB")
    draw = ImageDraw.Draw(crop)
    px, py, pw, ph = box
    draw.rectangle((px-pw/2-x0, py-ph/2-y0, px+pw/2-x0, py+ph/2-y0),
                   outline="#00ffff", width=7)
    if candidate is not None:
        draw.rectangle((candidate.cx-candidate.width/2-x0, candidate.cy-candidate.height/2-y0,
                        candidate.cx+candidate.width/2-x0, candidate.cy+candidate.height/2-y0),
                       outline="#3cff3c", width=7)
        draw_cross(draw, candidate.cx-x0, candidate.cy-y0, "#3cff3c")
    crop.thumbnail((size[0], size[1]-42), Image.Resampling.LANCZOS)
    panel = Image.new("RGB", size, "#101010")
    panel.paste(crop, ((size[0]-crop.width)//2, 40+(size[1]-42-crop.height)//2))
    d = ImageDraw.Draw(panel)
    status = "candidate" if candidate is not None else "no accepted candidate"
    d.text((10, 10), f"{title} — {status}  cyan=capture  green=candidate", fill="white")
    return panel


def make_panel(image: Image.Image, row: dict, capture: dict, record: dict, frozen: dict) -> Image.Image:
    width, height = 1400, 850
    panel = Image.new("RGB", (width, height), "#0c0c0c")
    draw = ImageDraw.Draw(panel)
    group = classify(row)
    detail = json.loads(row.get("physical_detail") or "{}")
    source = row["hybrid_source"]
    draw.rectangle((0, 0, width, 74), fill="#000000")
    draw.text((16, 12), f"FRAME {int(row['frame']):06d}   {LABELS[group]}", fill="white")
    draw.text((16, 40), f"final={source}   raw reason={row['physical_failure_reason']}   detail={str(detail)[:150]}",
              fill="#dddddd")

    boxes = any_capture_boxes(capture)
    candidates = []
    for box in boxes:
        candidate, _, _ = physical_hole(__import__('numpy').asarray(image.convert("RGB")), box,
                                        float(frozen["roi_margin_fraction"]))
        candidates.append(candidate)
    for index in range(2):
        title = "UPPER ROI" if index == 0 else "LOWER ROI"
        if index < len(boxes):
            rp = roi_panel(image, boxes[index], candidates[index], title,
                           float(frozen["roi_margin_fraction"]))
        else:
            rp = Image.new("RGB", (650, 330), "#171717")
            ImageDraw.Draw(rp).text((18, 18), f"{title}: no capture box", fill="white")
        panel.paste(rp, (10, 82 + index * 376))

    final_x = float(row["hybrid_final_x"]); final_y = float(row["hybrid_final_y"])
    crop = CropGeometry(final_x + 159.0, final_y - 413.0, 1133, 900)
    context = registered_frame(image, crop, load_calibration().contrast)
    context.thumbnail((720, 690), Image.Resampling.LANCZOS)
    context_x = 670 + (720-context.width)//2
    context_y = 112 + (690-context.height)//2
    panel.paste(context, (context_x, context_y))
    draw.rectangle((670, 82, 1390, 112), fill="#181818")
    draw.text((682, 88), "PROVISIONAL REGISTERED FRAME (final interpolated/held anchor)", fill="white")
    eligibility = row["capture_pair_seed_eligible"] == "True"
    draw.text((682, 815), f"capture mode={capture.get('raw_registration_mode')}  source={capture.get('selected_source')}  "
              f"eligible_pair={eligibility}  boxes={len(boxes)}", fill="#dddddd")
    return panel


def sheet(paths, destination, title, columns=2, thumb=(700, 425)):
    if not paths:
        return
    rows = math.ceil(len(paths)/columns)
    canvas = Image.new("RGB", (columns*thumb[0], 58+rows*thumb[1]), "black")
    ImageDraw.Draw(canvas).text((14, 18), title, fill="white")
    for index, path in enumerate(paths):
        with Image.open(path) as im:
            item = im.convert("RGB").resize(thumb, Image.Resampling.LANCZOS)
        canvas.paste(item, ((index%columns)*thumb[0], 58+(index//columns)*thumb[1]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=91, subsampling=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    diag = POC / "Reel_46335/diagnostics.csv"
    unresolved = [r for r in csv.DictReader(diag.open()) if r["hybrid_interpolated"] == "True"]
    assert len(unresolved) == 198, f"expected frozen population of 198, found {len(unresolved)}"
    by_frame = {int(r["frame"]): r for r in unresolved}
    spec = REELS["Reel_46335"]
    capture = load_capture(spec["project"])
    _, records, _ = load_manifest(spec["manifest"])
    frozen = json.loads(FROZEN.read_text())
    calibration = load_calibration()
    developer = DarktableMatchedDeveloper(calibration.match.report)
    panels = args.output_dir / "panels"
    panels.mkdir(parents=True, exist_ok=True)
    dngs = [spec["project"] / "raw" / f"frame_{n:06d}.dng" for n in sorted(by_frame)]
    for start in range(0, len(dngs), 24):
        batch = dngs[start:start+24]
        temporary = Path(tempfile.mkdtemp(prefix="problem_review_", dir=ROOT/"work"))
        try:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = {pool.submit(developer.develop, dng, temporary/f"{dng.stem}.tif"): dng for dng in batch}
                for future in as_completed(futures):
                    future.result()
            for dng in batch:
                n = int(dng.stem.rsplit("_", 1)[1])
                with Image.open(temporary/f"{dng.stem}.tif") as image:
                    result = make_panel(image, by_frame[n], capture[n], records[n], frozen)
                result.save(panels/f"frame_{n:06d}.jpg", quality=91, subsampling=0)
        finally:
            shutil.rmtree(temporary)
        print(f"rendered {min(start+len(batch), len(dngs))}/{len(dngs)}", flush=True)

    grouped = defaultdict(list)
    for row in unresolved:
        grouped[classify(row)].append(panels/f"frame_{int(row['frame']):06d}.jpg")
    for group in ORDER:
        if grouped[group]:
            sheet(grouped[group], args.output_dir/f"all_{group}.jpg",
                  f"Reel_46335 unresolved — {LABELS[group]} — {len(grouped[group])} frames")
    representatives = []
    for group in ORDER:
        items = grouped[group]
        if not items:
            continue
        count = min(6, len(items))
        indices = sorted({round(i*(len(items)-1)/max(1, count-1)) for i in range(count)})
        representatives.extend(items[i] for i in indices)
    sheet(representatives, args.output_dir/"condensed_representative_examples.jpg",
          "Reel_46335 unresolved — representative examples by failure class", columns=2)
    summary = {
        "source_diagnostics": str(diag), "frames": len(unresolved),
        "final_sources": dict(Counter(r["hybrid_source"] for r in unresolved)),
        "groups": {group: len(grouped[group]) for group in ORDER},
        "detector_parameters_changed": False,
        "render_note": "Candidate overlays rerun the frozen per-hole evidence function for visualization only; frozen diagnostics define population, classifications, and final decisions.",
    }
    (args.output_dir/"review_index.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
