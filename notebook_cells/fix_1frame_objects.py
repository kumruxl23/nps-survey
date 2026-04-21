# ============================================================
# FIX: Propagate 1-frame objects via SAM2
# ============================================================
# Reads the final output JSON, finds objects with only 1 frame,
# gets their bbox from that frame, runs SAM2 to propagate,
# and injects into the COCO file.
#
# Run on SageMaker notebook (needs GPU).
# ============================================================

import boto3, json, os, sys, shutil, time
import numpy as np
import cv2
import torch, gc

AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
SOURCE_PREFIX = "area-organization-science/prod/BFI1/March-26-usecase-simulation/events/object_fall"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"

SAM2_DIR        = os.path.expanduser("~/SageMaker/sam2")
SAM2_CHECKPOINT = os.path.join(SAM2_DIR, "checkpoints", "sam2.1_hiera_small.pt")
SAM2_CONFIG     = "configs/sam2.1/sam2.1_hiera_s.yaml"
RESIZE_FACTOR   = 0.5

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

s3  = boto3.client("s3", region_name=AWS_REGION)
pag = s3.get_paginator("list_objects_v2")

def list_s3_image_keys(prefix):
    keys = []
    for page in pag.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if os.path.splitext(obj["Key"])[1].lower() in IMAGE_EXTENSIONS:
                keys.append(obj["Key"])
    return sorted(keys)

def s3_read_json(key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8"))

def mask_to_bbox(m):
    r = np.any(m, axis=1)
    c = np.any(m, axis=0)
    if not r.any(): return None
    y0, y1 = np.where(r)[0][[0, -1]]
    x0, x1 = np.where(c)[0][[0, -1]]
    return [int(x0), int(y0), int(x1-x0+1), int(y1-y0+1)]

# ═══ FIND 1-FRAME OBJECTS FROM FINAL OUTPUT ═══
local_path = os.path.expanduser("~/SageMaker/final_output.json")
with open(local_path) as f:
    final = json.load(f)

to_fix = []
for iid, inst in final["instances"].items():
    for cid, cd in inst.get("cameras", {}).items():
        for obj in cd.get("objects", []):
            fa = obj.get("frame_annotations", {})
            if len(fa) <= 1 and fa:
                frame_key = list(fa.keys())[0]
                bbox = fa[frame_key].get("bbox")
                if bbox and len(bbox) == 4:
                    to_fix.append({
                        "instance_id": iid,
                        "camera_id": cid,
                        "label": obj["label"],
                        "tracking_id": obj["tracking_id"],
                        "prompt_frame": int(frame_key),
                        "bbox": bbox,
                        "metadata": fa[frame_key].get("metadata", {}),
                        "total_frames": cd.get("total_frames", 0),
                    })

print(f"Found {len(to_fix)} objects to fix:")
for t in to_fix:
    print(f"  {t['instance_id'][-25:]} / {t['camera_id']} / {t['tracking_id']} "
          f"bbox={t['bbox']} frame={t['prompt_frame']}")

if not to_fix:
    print("Nothing to fix!")
    raise SystemExit()

# ═══ LOAD SAM2 ═══
os.chdir(SAM2_DIR)
if SAM2_DIR not in sys.path:
    sys.path.insert(0, SAM2_DIR)
from sam2.build_sam import build_sam2_video_predictor

gc.collect(); torch.cuda.empty_cache()
predictor = build_sam2_video_predictor(SAM2_CONFIG, SAM2_CHECKPOINT, device="cuda")
print(f"SAM2 loaded")

LOCAL_WORK = "/tmp/fix_1frame"

# Group by instance+camera to avoid re-downloading frames
groups = {}
for t in to_fix:
    key = (t["instance_id"], t["camera_id"])
    if key not in groups:
        groups[key] = []
    groups[key].append(t)

print(f"\n{len(groups)} unique instance+camera combos to process")

for (iid, cid), items in groups.items():
    print(f"\n{'='*60}")
    print(f"Processing {iid}/{cid} ({len(items)} objects)")

    # Download + resize frames
    source_prefix = f"{SOURCE_PREFIX}/{iid}/{cid}/"
    all_keys = list_s3_image_keys(source_prefix)
    nf = len(all_keys)
    if nf == 0:
        print(f"  No source frames found, skipping")
        continue

    raw_dir = os.path.join(LOCAL_WORK, "raw")
    resized_dir = os.path.join(LOCAL_WORK, "resized")
    for d in [raw_dir, resized_dir]:
        if os.path.exists(d): shutil.rmtree(d)
        os.makedirs(d)

    print(f"  Downloading {nf} frames...", end=" ", flush=True)
    ORIG_W, ORIG_H = 0, 0
    for idx, key in enumerate(all_keys):
        ext = os.path.splitext(key)[1].lower() or '.jpg'
        raw_p = os.path.join(raw_dir, f"{idx:04d}{ext}")
        res_p = os.path.join(resized_dir, f"{idx:04d}.jpg")
        s3.download_file(BUCKET, key, raw_p)
        img = cv2.imread(raw_p)
        if img is not None:
            if ORIG_W == 0:
                ORIG_H, ORIG_W = img.shape[:2]
            rw, rh = int(ORIG_W * RESIZE_FACTOR), int(ORIG_H * RESIZE_FACTOR)
            cv2.imwrite(res_p, cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA))
    RW, RH = int(ORIG_W * RESIZE_FACTOR), int(ORIG_H * RESIZE_FACTOR)
    print(f"done ({ORIG_W}x{ORIG_H})")

    # Load COCO file
    coco_key = f"{STAGE2_PREFIX}/coco/{iid}/annotations.json"
    try:
        coco_data = s3_read_json(coco_key)
    except:
        coco_data = {"instance_id": iid, "cameras": {}}

    if "cameras" not in coco_data:
        coco_data["cameras"] = {}
    if cid not in coco_data["cameras"]:
        coco_data["cameras"][cid] = {"camera_id": cid, "objects": []}

    cam_coco = coco_data["cameras"][cid]
    if "objects" not in cam_coco:
        cam_coco["objects"] = []

    # Process each object
    for item in items:
        tid = item["tracking_id"]
        label = item["label"]
        bbox = item["bbox"]
        prompt_frame = item["prompt_frame"]
        metadata = item["metadata"]

        print(f"\n  {tid}: bbox={bbox} frame={prompt_frame}")

        # Check if already in COCO with >1 frame
        existing = [o for o in cam_coco["objects"] if o.get("tracking_id") == tid]
        if existing and len(existing[0].get("frame_annotations", {})) > 1:
            print(f"    Already propagated ({len(existing[0]['frame_annotations'])} frames), skipping")
            continue

        # Scale bbox
        scaled_box = np.array([
            bbox[0] * RESIZE_FACTOR,
            bbox[1] * RESIZE_FACTOR,
            (bbox[0] + bbox[2]) * RESIZE_FACTOR,
            (bbox[1] + bbox[3]) * RESIZE_FACTOR,
        ], dtype=np.float32)

        gc.collect(); torch.cuda.empty_cache()

        try:
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                state = predictor.init_state(
                    video_path=resized_dir,
                    offload_video_to_cpu=True,
                    offload_state_to_cpu=True,
                )
                predictor.add_new_points_or_box(
                    inference_state=state, frame_idx=prompt_frame,
                    obj_id=1, box=scaled_box,
                )
                segs = {}
                for of, ooids, oml in predictor.propagate_in_video(state):
                    segs[of] = {1: (oml[0] > 0.0).cpu().numpy().squeeze()}
                for of, ooids, oml in predictor.propagate_in_video(state, reverse=True):
                    if of not in segs:
                        segs[of] = {1: (oml[0] > 0.0).cpu().numpy().squeeze()}
                predictor.reset_state(state)
                del state
        except Exception as e:
            print(f"    SAM2 error: {e}")
            continue

        # Build frame annotations + upload masks
        frame_anns = {}
        masks_uploaded = 0
        for fidx in range(nf):
            if fidx not in segs or 1 not in segs[fidx]:
                continue
            mask_small = segs[fidx][1]
            if not mask_small.any():
                continue
            mask_orig = cv2.resize(mask_small.astype(np.uint8), (ORIG_W, ORIG_H),
                                   interpolation=cv2.INTER_NEAREST).astype(bool)
            if not mask_orig.any():
                continue
            bb = mask_to_bbox(mask_orig)
            if not bb:
                continue
            frame_anns[str(fidx)] = {
                "bbox": bb, "area": int(mask_orig.sum()),
                "has_mask": True, "metadata": metadata.copy(),
            }
            _, buf = cv2.imencode('.png', mask_orig.astype(np.uint8) * 255)
            mk = f"{STAGE2_PREFIX}/masks/{iid}/{cid}/{label}_{tid}/frame_{fidx:04d}.png"
            s3.put_object(Bucket=BUCKET, Key=mk, Body=buf.tobytes(), ContentType='image/png')
            masks_uploaded += 1

        print(f"    Propagated to {len(frame_anns)} frames, {masks_uploaded} masks")

        # Remove old entry if exists
        cam_coco["objects"] = [o for o in cam_coco["objects"] if o.get("tracking_id") != tid]

        # Add new entry
        cam_coco["objects"].append({
            "label": label, "tracking_id": tid,
            "source": "manual_injection", "status": "pending",
            "tracked_frames": len(frame_anns), "total_frames": nf,
            "masks_s3_prefix": f"s3://{BUCKET}/{STAGE2_PREFIX}/masks/{iid}/{cid}/{label}_{tid}/",
            "metadata": metadata, "frame_annotations": frame_anns,
        })

        del segs
        gc.collect(); torch.cuda.empty_cache()

    # Save updated COCO
    s3.put_object(Bucket=BUCKET, Key=coco_key,
                  Body=json.dumps(coco_data, indent=2).encode("utf-8"),
                  ContentType="application/json")
    print(f"\n  Saved COCO: {coco_key}")

    # Cleanup
    shutil.rmtree(LOCAL_WORK, ignore_errors=True)

print(f"\n{'='*60}")
print(f"DONE — Re-run Cell 10 to regenerate final output")
print(f"{'='*60}")
