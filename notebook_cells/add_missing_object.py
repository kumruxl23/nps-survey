# ============================================================
# ADD MISSING OBJECT — Single-object SAM2 propagation
# ============================================================
# Use when verification reveals a completely missing object.
# You provide: instance_id, camera, label, tracking_id, and
# a bounding box on ONE frame. This script:
#   1. Downloads all source frames for that camera
#   2. Runs SAM2 with your bbox as the prompt
#   3. Gets bbox + mask for all frames
#   4. Injects the new object into the validation JSON
#   5. Uploads updated JSON to S3
#
# Run on SageMaker notebook (needs GPU for SAM2).
# ============================================================

import boto3, json, os, sys, shutil, time
import numpy as np
import cv2
import torch, gc

# ═══════════════════ EDIT THESE ═══════════════════
AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
SOURCE_PREFIX = "area-organization-science/prod/BFI1/March-26-usecase-simulation/events/object_fall"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"
STAGE3_PREFIX = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX = f"{OUTPUT_PREFIX}/stage4_verification"

SAM2_DIR        = os.path.expanduser("~/SageMaker/sam2")
SAM2_CHECKPOINT = os.path.join(SAM2_DIR, "checkpoints", "sam2.1_hiera_small.pt")
SAM2_CONFIG     = "configs/sam2.1/sam2.1_hiera_s.yaml"
RESIZE_FACTOR   = 0.5

# ═══ WHAT TO ADD ═══
INSTANCE_ID   = "chunk_1774560020-1774560030s"  # ← edit
CAMERA_ID     = "0007"                           # ← edit
LABEL         = "tote"                           # ← edit
TRACKING_ID   = "tote#6"                         # ← edit
PROMPT_FRAME  = 0                                # ← which source frame to prompt on
PROMPT_BBOX   = [400, 300, 80, 60]               # ← [x, y, width, height] on ORIGINAL resolution

# Metadata defaults (all False, edit if needed)
METADATA = {
    "is_tote_on_ground": "True",
    "is_tote_overfilled": "False",
    "is_tote_on_shelf": "False",
    "stacked_totes": "False",
}
# ══════════════════════════════════════════════════

s3  = boto3.client("s3", region_name=AWS_REGION)
pag = s3.get_paginator("list_objects_v2")

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

def list_s3_image_keys(prefix):
    keys = []
    for page in pag.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if os.path.splitext(obj["Key"])[1].lower() in IMAGE_EXTENSIONS:
                keys.append(obj["Key"])
    return sorted(keys)

def mask_to_bbox(m):
    r = np.any(m, axis=1)
    c = np.any(m, axis=0)
    if not r.any():
        return None
    y0, y1 = np.where(r)[0][[0, -1]]
    x0, x1 = np.where(c)[0][[0, -1]]
    return [int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)]

print("=" * 70)
print(f" ADDING: {TRACKING_ID} to {INSTANCE_ID}/{CAMERA_ID}")
print("=" * 70)

# ═══ 1. DOWNLOAD FRAMES ═════════════════════════════════════

source_prefix = f"{SOURCE_PREFIX}/{INSTANCE_ID}/{CAMERA_ID}/"
all_keys = list_s3_image_keys(source_prefix)
nf = len(all_keys)
print(f"\n[1/5] Found {nf} source frames")

LOCAL_WORK = "/tmp/add_object_work"
raw_dir = os.path.join(LOCAL_WORK, "raw")
resized_dir = os.path.join(LOCAL_WORK, "resized")
for d in [raw_dir, resized_dir]:
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)

print(f"[2/5] Downloading + resizing {nf} frames...")
for idx, key in enumerate(all_keys):
    ext = os.path.splitext(key)[1].lower() or '.jpg'
    raw_p = os.path.join(raw_dir, f"{idx:04d}{ext}")
    res_p = os.path.join(resized_dir, f"{idx:04d}.jpg")
    s3.download_file(BUCKET, key, raw_p)
    img = cv2.imread(raw_p)
    if img is not None:
        h, w = img.shape[:2]
        rw, rh = int(w * RESIZE_FACTOR), int(h * RESIZE_FACTOR)
        resized = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA)
        cv2.imwrite(res_p, resized)
    if idx % 20 == 0:
        print(f"  {idx}/{nf}...", end=" ", flush=True)

# Get dimensions
sample = cv2.imread(os.path.join(raw_dir, f"0000{ext}"))
ORIG_H, ORIG_W = sample.shape[:2]
RW, RH = int(ORIG_W * RESIZE_FACTOR), int(ORIG_H * RESIZE_FACTOR)
print(f"\n  Original: {ORIG_W}x{ORIG_H}, Resized: {RW}x{RH}")

# ═══ 3. RUN SAM2 ════════════════════════════════════════════

print(f"\n[3/5] Running SAM2 propagation...")

os.chdir(SAM2_DIR)
if SAM2_DIR not in sys.path:
    sys.path.insert(0, SAM2_DIR)
from sam2.build_sam import build_sam2_video_predictor

gc.collect()
torch.cuda.empty_cache()
predictor = build_sam2_video_predictor(SAM2_CONFIG, SAM2_CHECKPOINT, device="cuda")

# Scale bbox to resized resolution
bx, by, bw, bh = PROMPT_BBOX
scaled_box = np.array([
    bx * RESIZE_FACTOR,
    by * RESIZE_FACTOR,
    (bx + bw) * RESIZE_FACTOR,
    (by + bh) * RESIZE_FACTOR,
], dtype=np.float32)

with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
    state = predictor.init_state(
        video_path=resized_dir,
        offload_video_to_cpu=True,
        offload_state_to_cpu=True,
    )

    predictor.add_new_points_or_box(
        inference_state=state,
        frame_idx=PROMPT_FRAME,
        obj_id=1,
        box=scaled_box,
    )

    # Forward propagation
    video_segments = {}
    for of, ooids, oml in predictor.propagate_in_video(state):
        if of not in video_segments:
            video_segments[of] = {}
        for i, oid in enumerate(ooids):
            video_segments[of][oid] = (oml[i] > 0.0).cpu().numpy().squeeze()

    # Reverse propagation
    for of, ooids, oml in predictor.propagate_in_video(state, reverse=True):
        if of not in video_segments:
            video_segments[of] = {}
        for i, oid in enumerate(ooids):
            if oid not in video_segments[of]:
                video_segments[of][oid] = (oml[i] > 0.0).cpu().numpy().squeeze()

    predictor.reset_state(state)

del state, predictor
gc.collect()
torch.cuda.empty_cache()

print(f"  Propagated to {len(video_segments)} frames")

# ═══ 4. BUILD FRAME ANNOTATIONS ═════════════════════════════

print(f"\n[4/5] Building frame annotations...")

frame_annotations = {}
masks_uploaded = 0

for fidx in range(nf):
    if fidx not in video_segments or 1 not in video_segments[fidx]:
        continue

    mask_small = video_segments[fidx][1]
    if not mask_small.any():
        continue

    # Scale mask back to original resolution
    mask_orig = cv2.resize(
        mask_small.astype(np.uint8),
        (ORIG_W, ORIG_H),
        interpolation=cv2.INTER_NEAREST
    ).astype(bool)

    if not mask_orig.any():
        continue

    bbox = mask_to_bbox(mask_orig)
    if not bbox:
        continue

    area = int(mask_orig.sum())

    frame_annotations[str(fidx)] = {
        "bbox": bbox,
        "area": area,
        "has_mask": True,
        "metadata": METADATA.copy(),
    }

    # Upload mask
    _, buf = cv2.imencode('.png', mask_orig.astype(np.uint8) * 255)
    mask_key = (
        f"{STAGE2_PREFIX}/masks/{INSTANCE_ID}"
        f"/{CAMERA_ID}/{LABEL}_{TRACKING_ID}"
        f"/frame_{fidx:04d}.png"
    )
    s3.put_object(Bucket=BUCKET, Key=mask_key,
                  Body=buf.tobytes(), ContentType='image/png')
    masks_uploaded += 1

print(f"  {len(frame_annotations)} frame annotations created")
print(f"  {masks_uploaded} masks uploaded")

# ═══ 5. INJECT INTO VALIDATION JSON ═════════════════════════

print(f"\n[5/5] Injecting into validation data...")

# Load existing validation data
ann_key = f"{STAGE3_PREFIX}/annotations/{INSTANCE_ID}.json"
try:
    resp = s3.get_object(Bucket=BUCKET, Key=ann_key)
    val_data = json.loads(resp["Body"].read().decode("utf-8"))
    for _ in range(5):
        if isinstance(val_data, str):
            try: val_data = json.loads(val_data)
            except: break
        else: break
    print(f"  Loaded existing validation data")
except:
    val_data = {}
    print(f"  No existing validation data, creating new")

# Load frame mapping to get sampled indices
mapping_key = f"{OUTPUT_PREFIX}/frame_mapping.json"
frame_mapping = json.loads(
    s3.get_object(Bucket=BUCKET, Key=mapping_key)["Body"].read().decode("utf-8")
)
cam_map = frame_mapping.get(INSTANCE_ID, {}).get(CAMERA_ID, {})
sampled_indices = cam_map.get("sampled_indices", [])

# Find camera index
cam_names = list(frame_mapping.get(INSTANCE_ID, {}).keys())
cam_idx = cam_names.index(CAMERA_ID) if CAMERA_ID in cam_names else 0

# Inject into each sampled frame (validation JSON)
injected = 0
for fi, src_idx in enumerate(sampled_indices):
    fk = f"frame_{fi:02d}"

    if fk not in val_data:
        val_data[fk] = {"cameras": []}

    fd = val_data[fk]
    cameras = fd.get("cameras", [])
    if "validated_annotations" in fd:
        cameras = fd["validated_annotations"].get("cameras", cameras)

    # Ensure camera entry exists
    while len(cameras) <= cam_idx:
        cameras.append({"camera_id": cam_names[len(cameras)] if len(cameras) < len(cam_names) else f"cam_{len(cameras)}", "annotations": []})

    cam_entry = cameras[cam_idx]
    if "annotations" not in cam_entry:
        cam_entry["annotations"] = []

    # Check if this tracking ID already exists
    already = any(a.get("tracking_id") == TRACKING_ID for a in cam_entry["annotations"])
    if already:
        continue

    # Get frame annotation for this source frame
    fa = frame_annotations.get(str(src_idx), None)
    if not fa:
        continue

    cam_entry["annotations"].append({
        "label": LABEL,
        "label_name": LABEL.replace("_", " ").title(),
        "color": "#999",
        "tool": "bbox",
        "data": {"x": fa["bbox"][0], "y": fa["bbox"][1],
                 "w": fa["bbox"][2], "h": fa["bbox"][3]},
        "tracking_id": TRACKING_ID,
        "metadata": fa["metadata"],
    })
    injected += 1

print(f"  Injected into {injected} sampled frames")

# Also inject into SAM2 COCO file (all frames, for Cell 10)
coco_key = f"{STAGE2_PREFIX}/coco/{INSTANCE_ID}/annotations.json"
try:
    coco_data = json.loads(s3.get_object(Bucket=BUCKET, Key=coco_key)["Body"].read().decode("utf-8"))
    print(f"  Loaded COCO: {coco_key}")
except Exception:
    coco_data = {"instance_id": INSTANCE_ID, "cameras": {}}
    print(f"  Created new COCO")

if "cameras" not in coco_data:
    coco_data["cameras"] = {}
if CAMERA_ID not in coco_data["cameras"]:
    coco_data["cameras"][CAMERA_ID] = {"camera_id": CAMERA_ID, "objects": []}

cam_coco = coco_data["cameras"][CAMERA_ID]
if "objects" not in cam_coco:
    cam_coco["objects"] = []

# Check if already exists in COCO
coco_exists = any(o.get("tracking_id") == TRACKING_ID for o in cam_coco["objects"])
if not coco_exists:
    coco_obj = {
        "label": LABEL,
        "tracking_id": TRACKING_ID,
        "source": "manual_injection",
        "status": "pending",
        "tracked_frames": len(frame_annotations),
        "total_frames": nf,
        "masks_s3_prefix": f"s3://{BUCKET}/{STAGE2_PREFIX}/masks/{INSTANCE_ID}/{CAMERA_ID}/{LABEL}_{TRACKING_ID}/",
        "metadata": METADATA.copy(),
        "frame_annotations": {},
    }
    for fidx_str, fa_data in frame_annotations.items():
        coco_obj["frame_annotations"][fidx_str] = {
            "bbox": fa_data["bbox"],
            "area": fa_data["area"],
            "has_mask": True,
            "metadata": fa_data["metadata"],
        }
    cam_coco["objects"].append(coco_obj)
    s3.put_object(Bucket=BUCKET, Key=coco_key,
                  Body=json.dumps(coco_data, indent=2).encode("utf-8"),
                  ContentType="application/json")
    print(f"  Injected {TRACKING_ID} into COCO ({len(frame_annotations)} frames)")
else:
    print(f"  {TRACKING_ID} already in COCO, skipping")

# Backup + save
backup_key = f"{STAGE3_PREFIX}/annotations/{INSTANCE_ID}_backup_{int(time.time())}.json"
s3.put_object(Bucket=BUCKET, Key=backup_key,
              Body=json.dumps(val_data, indent=2).encode("utf-8"))
print(f"  Backup: s3://{BUCKET}/{backup_key}")

# Save to both stage3 and verify
for prefix in [STAGE3_PREFIX, VERIFY_PREFIX]:
    save_key = f"{prefix}/annotations/{INSTANCE_ID}.json"
    s3.put_object(Bucket=BUCKET, Key=save_key,
                  Body=json.dumps(val_data, indent=2).encode("utf-8"),
                  ContentType="application/json")
    print(f"  Saved: s3://{BUCKET}/{save_key}")

# Cleanup
shutil.rmtree(LOCAL_WORK, ignore_errors=True)

print(f"\n{'=' * 70}")
print(f"  DONE — {TRACKING_ID} added to {INSTANCE_ID}/{CAMERA_ID}")
print(f"  {len(frame_annotations)} total frames propagated")
print(f"  {injected} sampled frames injected into validation JSON")
print(f"  {masks_uploaded} masks uploaded to S3")
print(f"{'=' * 70}")
print(f"\n  The object will now appear in the verification template")
print(f"  and in Cell 10's final output.")
