#!/usr/bin/env python3
"""Run frozen P07 on the reserved blind population and lock outputs pre-unblind."""
from __future__ import annotations

import argparse, csv, hashlib, json, shutil, sys, tempfile, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grokcam.config import load_calibration
from grokcam.raw_development import DarktableMatchedDeveloper
from research.p01_hybrid_capture_prior_poc import REELS, load_capture
from research.p07_joint_rigid_sprocket_pair_evidence_poc import (
    BASE, CONFIG, P06, _summary, evaluate, panel,
)
from research.prepare_partner_partial_blind_validation import html

SOURCE_PACKAGE = ROOT / "research/output/sprocket_xy/partner_partial_hole_blind_validation"
DEFAULT_OUTPUT = ROOT / "research/output/sprocket_xy/p07_frozen_blind_validation"
FROZEN = [
    ROOT / "research/p07_joint_rigid_sprocket_pair_evidence_poc.py",
    ROOT / "research/p07_joint_rigid_sprocket_pair_evidence_blue_frozen.json",
    ROOT / "research/test_p07_joint_rigid_sprocket_pair_evidence_poc.py",
]
EXPECTED = {
    FROZEN[0]: "d78bc8478308451af69d37dc7485cb5c0a15cd7a59ccdb75ec86932a498fd13d",
    FROZEN[1]: "334abf89ee43a0eb18c7f33e68eb8afb9f38556ff981136ac16f5d30b646a1c6",
    FROZEN[2]: "82bc6487ffd3d9bc8c9dc86a206355f4973202ed19b79f9c59a8cb1438558e4d",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root: Path, excluded=frozenset()) -> tuple[str, dict[str, str]]:
    hashes = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in excluded:
            hashes[rel] = sha(path)
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return digest, hashes


def flatten(frame, row, result, p06row, cfg, timings):
    b = result["best"]
    return {
        "frame": frame, "classification": result["classification"],
        "accepted": result["accepted"],
        "normal_detector_count": result["normal_detected_count"],
        "p06_accepted": p06row["accepted"], "p06_classification": p06row["classification"],
        "upper_x": b["upper_x"], "upper_y": b["upper_y"],
        "lower_x": b["lower_x"], "lower_y": b["lower_y"],
        "fixed_width": cfg["hole_width"], "fixed_height": cfg["hole_height"],
        "fixed_pitch": cfg["pitch"], "fixed_x_offset": cfg["lower_minus_upper_x"],
        "upper_states_json": json.dumps(b["upper"]["states"], sort_keys=True),
        "lower_states_json": json.dumps(b["lower"]["states"], sort_keys=True),
        "upper_strengths_json": json.dumps(b["upper"]["strengths"], sort_keys=True),
        "lower_strengths_json": json.dumps(b["lower"]["strengths"], sort_keys=True),
        "upper_residuals_json": json.dumps(b["upper"]["residuals"], sort_keys=True),
        "lower_residuals_json": json.dumps(b["lower"]["residuals"], sort_keys=True),
        "upper_supported": b["upper_supported"], "lower_supported": b["lower_supported"],
        "total_supported": b["supported"], "missing_count": b["missing"],
        "contradicted_count": b["contradicted"],
        "strongest_contradiction": b["strongest_contradiction"],
        "upper_score": b["upper_score"], "lower_score": b["lower_score"],
        "geometric_contribution": b["geometric_contribution"],
        "geometric_residual": b["geometric_residual"], "joint_score": b["score"],
        "contradiction_penalty": b["contradiction_penalty"],
        "competitor_score": b["score"] - b["margin"], "competitor_margin": b["margin"],
        "competitors_json": json.dumps(b["competitors"], sort_keys=True),
        "capture_pair_distance": result["capture_distance"], "p06_distance": result["p06_distance"],
        "final_anchor_x": result["anchor_x"], "final_anchor_y": result["anchor_y"],
        "accepted_without_normal_seed": result["accepted"] and result["normal_detected_count"] == 0,
        "detector_seconds": timings["detector"], "overlay_seconds": timings["overlay"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()
    mismatches = {str(p): (EXPECTED[p], sha(p)) for p in FROZEN if sha(p) != EXPECTED[p]}
    if mismatches:
        raise SystemExit("FROZEN HASH MISMATCH: " + json.dumps(mismatches, indent=2))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty blind package: {args.output_dir}")

    started = time.perf_counter(); args.output_dir.mkdir(parents=True)
    frozen_dir = args.output_dir / "frozen"; frozen_dir.mkdir()
    for src in FROZEN: shutil.copy2(src, frozen_dir / src.name)
    selection = json.loads((SOURCE_PACKAGE / "selection_private.json").read_text())
    frames = [int(x) for x in selection["frames"]]
    if len(frames) != 68 or len(set(frames)) != 68 or 3341 not in frames:
        raise SystemExit("reserved blind population invariant failed")
    (args.output_dir / "population_manifest.json").write_text(json.dumps({
        "source_package": str(SOURCE_PACKAGE.relative_to(ROOT)),
        "frames_in_blind_order": frames,
        "selection": selection["selection"],
        "feature_definition": selection["feature_definition"],
        "source_selection_freeze_id": selection["freeze_id"],
    }, indent=2) + "\n")

    baseline_rows = {int(r["frame"]): r for r in csv.DictReader((BASE / "diagnostics.csv").open())}
    p06_rows = {int(r["frame"]): r for r in csv.DictReader((P06 / "diagnostics.csv").open())}
    missing = [f for f in frames if f not in baseline_rows or f not in p06_rows]
    if missing: raise SystemExit(f"blind frames absent from frozen inputs: {missing}")
    cfg = json.loads(CONFIG.read_text()); spec = REELS["Reel_46335"]
    capture = load_capture(spec["project"]); cal = load_calibration()
    developer = DarktableMatchedDeveloper(cal.match.report)
    panels = args.output_dir / "panels"; panels.mkdir()
    results, prep_seconds = [], 0.0
    dngs = [spec["project"] / "raw" / f"frame_{n:06d}.dng" for n in sorted(frames)]
    for start in range(0, len(dngs), 24):
        batch = dngs[start:start + 24]
        tmp = Path(tempfile.mkdtemp(prefix="p07_blind_", dir=ROOT / "work"))
        try:
            t = time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = [pool.submit(developer.develop, d, tmp / f"{d.stem}.tif") for d in batch]
                for future in as_completed(futures): future.result()
            prep_seconds += time.perf_counter() - t

            def process(dng):
                n = int(dng.stem.rsplit("_", 1)[1]); row = baseline_rows[n]
                with Image.open(tmp / f"{dng.stem}.tif") as image:
                    t0 = time.perf_counter(); result = evaluate(image, row, capture[n], p06_rows[n], cfg)
                    detector = time.perf_counter() - t0
                    t0 = time.perf_counter(); panel(image, row, result, cal, cfg).save(panels / f"frame_{n:06d}.jpg", quality=91)
                    overlay = time.perf_counter() - t0
                return flatten(n, row, result, p06_rows[n], cfg, {"detector": detector, "overlay": overlay})

            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                results.extend(f.result() for f in as_completed([pool.submit(process, d) for d in batch]))
        finally:
            shutil.rmtree(tmp)
        print(f"processed {min(start + len(batch), len(dngs))}/{len(dngs)}", flush=True)

    results.sort(key=lambda r: r["frame"])
    fields = sorted({k for row in results for k in row})
    with (args.output_dir / "diagnostics.csv").open("w", newline="") as h:
        writer = csv.DictWriter(h, fields); writer.writeheader(); writer.writerows(results)
    (args.output_dir / "diagnostics.json").write_text(json.dumps(results, indent=2) + "\n")
    accepted = [r for r in results if r["accepted"]]; rejected = [r for r in results if not r["accepted"]]
    report = {
        "state": "LOCKED_PRE_UNBLIND", "ground_truth_opened": False,
        "frames": len(results), "accepted": len(accepted), "rejected": len(rejected),
        "classifications": dict(Counter(r["classification"] for r in results)),
        "accepted_without_normal_seed": sum(bool(r["accepted_without_normal_seed"]) for r in results),
        "competitor_margin": _summary([float(r["competitor_margin"]) for r in accepted]),
        "support_distribution": dict(Counter(f'{r["upper_supported"]}+{r["lower_supported"]}' for r in accepted)),
        "contradiction_distribution": dict(Counter(int(r["contradicted_count"]) for r in accepted)),
        "geometry_residual": _summary([float(r["geometric_residual"]) for r in accepted]),
        "timing_seconds": {
            "dng_preparation_wall": prep_seconds,
            "incremental_detector_sum": sum(float(r["detector_seconds"]) for r in results),
            "incremental_detector_median_per_frame": float(sorted(float(r["detector_seconds"]) for r in results)[len(results)//2]),
            "overlay_sum": sum(float(r["overlay_seconds"]) for r in results),
            "total_isolated_wall": time.perf_counter() - started,
        },
        "frozen_hashes": {str(p.relative_to(ROOT)): EXPECTED[p] for p in FROZEN},
    }
    (args.output_dir / "pre_unblind_summary.json").write_text(json.dumps(report, indent=2) + "\n")

    # The old package supplies only answer-free ROI pixels and coordinate origins.
    roi = args.output_dir / "roi"; roi.mkdir()
    for frame in frames:
        for region in ("upper", "lower"):
            shutil.copy2(SOURCE_PACKAGE / "roi" / f"frame_{frame:06d}_{region}.png", roi)
    origins = {str(f): selection["origins"][str(f)] for f in frames}
    freeze_id = hashlib.sha256(json.dumps(list(EXPECTED.values()), sort_keys=True).encode()).hexdigest()
    (args.output_dir / "annotate.html").write_text(html(frames, origins, "p07_" + freeze_id))
    reveal = args.output_dir / "reveal"; reveal.mkdir()
    for frame in frames: shutil.copy2(panels / f"frame_{frame:06d}.jpg", reveal)

    package_hash, file_hashes = tree_hash(args.output_dir, {"lock_manifest.json"})
    lock = {
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "state": "LOCKED_PRE_UNBLIND", "ground_truth_opened": False,
        "package_sha256": package_hash, "files": file_hashes,
        "frozen_hashes_verified": True,
        "protected_answer_files_read": [],
    }
    (args.output_dir / "lock_manifest.json").write_text(json.dumps(lock, indent=2) + "\n")
    print(json.dumps({**report, "package_sha256": package_hash}, indent=2))


if __name__ == "__main__": main()
