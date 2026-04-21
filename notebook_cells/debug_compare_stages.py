# ============================================================
# DEBUG: Compare SAM2 output vs Validation output for a chunk
# ============================================================
# Shows what SAM2 detected vs what the validator kept/deleted.
# Paste in notebook, edit INSTANCE_ID, run.
# ============================================================

import boto3, json

AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"
STAGE3_PREFIX = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX = f"{OUTPUT_PREFIX}/stage4_verification"
GT_JOB_NAME   = "obejct-fall-annotation-prod"  # Stage 1 GT job name (with typo)

# ═══ EDIT THIS ═══
INSTANCE_ID = "chunk_1774559940-1774559950s"
# ══════════════════

s3  = boto3.client("s3", region_name=AWS_REGION)
pag = s3.get_paginator("list_objects_v2")

def s3_read_json(key):
    resp = s3.get_object(Bucket=BUCKET, Key=key)
    return json.loads(resp["Body"].read().decode("utf-8"))

def deep_parse(raw):
    for _ in range(5):
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except: break
        else: break
    return raw

# ═══ 1. SAM2 RESULTS (what SAM2 propagated) ═══════════════

print("=" * 70)
print(" STAGE 2: SAM2 RESULTS")
print("=" * 70)

sam2_data = None
try:
    raw = s3_read_json(f"{STAGE2_PREFIX}/full_results.json")
    if "instances" in raw:
        raw = raw["instances"]
    sam2_data = raw.get(INSTANCE_ID, {})
except Exception as e:
    print(f"  Could not load SAM2 results: {e}")

if sam2_data:
    for cam_id, cam_data in sam2_data.items():
        if not isinstance(cam_data, dict):
            continue
        objects = cam_data.get("objects", [])
        print(f"\n  Camera {cam_id}: {len(objects)} objects")
        for obj in objects:
            label = obj.get("label", "?")
            tid   = obj.get("tracking_id", "?")
            tf    = obj.get("tracked_frames", 0)
            total = obj.get("total_frames", 0)
            print(f"    {tid:<35} label={label:<20} tracked={tf}/{total}f")
else:
    print("  No SAM2 data found for this instance")

# ═══ 2. STAGE 1 ANNOTATION (what annotator drew) ══════════

print(f"\n{'=' * 70}")
print(" STAGE 1: ORIGINAL ANNOTATION (GT worker output)")
print("=" * 70)

# Try to find parsed annotations
stage1_data = None
try:
    import os
    parsed_path = os.path.expanduser("~/SageMaker/parsed_annotations.json")
    if os.path.exists(parsed_path):
        with open(parsed_path) as f:
            all_parsed = json.load(f)
        for task in all_parsed:
            if task.get("instance_id") == INSTANCE_ID:
                stage1_data = task.get("annotation_data", {})
                break
except Exception as e:
    print(f"  Could not load parsed annotations: {e}")

if stage1_data:
    # Collect all tracking IDs from stage 1
    s1_tids = {}
    frame_keys = sorted([k for k in stage1_data if k.startswith("frame_")])
    for fk in frame_keys:
        fd = stage1_data[fk]
        if not isinstance(fd, dict):
            continue
        cameras = fd.get("cameras", [])
        for ci, cam in enumerate(cameras):
            cam_id = cam.get("camera_id", f"cam_{ci}")
            for ann in cam.get("annotations", []):
                tid = ann.get("tracking_id", "")
                label = ann.get("label", "?")
                if tid:
                    if tid not in s1_tids:
                        s1_tids[tid] = {"label": label, "cameras": set(), "frames": set()}
                    s1_tids[tid]["cameras"].add(cam_id)
                    s1_tids[tid]["frames"].add(fk)

    print(f"  Found {len(s1_tids)} tracking IDs across {len(frame_keys)} frames:")
    for tid in sorted(s1_tids):
        info = s1_tids[tid]
        print(f"    {tid:<35} label={info['label']:<20} "
              f"cameras={sorted(info['cameras'])} frames={len(info['frames'])}f")
else:
    print("  No parsed annotations found (~/SageMaker/parsed_annotations.json)")
    print("  Trying to scan worker-response files...")

    # Try scanning worker responses directly
    wr_prefix = f"{OUTPUT_PREFIX}/gt-output/{GT_JOB_NAME}/annotations/worker-response/"
    try:
        found = False
        for page in pag.paginate(Bucket=BUCKET, Prefix=wr_prefix):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".json"):
                    continue
                # Read manifest to match task index to instance
                # Just list what's available
                if not found:
                    print(f"  Worker response files exist at: {wr_prefix}")
                    found = True
                    break
            if found:
                break
        if not found:
            print(f"  No worker responses found at {wr_prefix}")
    except Exception as e:
        print(f"  Error scanning: {e}")

# ═══ 3. VALIDATION OUTPUT (what validator approved) ════════

print(f"\n{'=' * 70}")
print(" STAGE 3: VALIDATION OUTPUT (validator decisions)")
print("=" * 70)

val_data = None
for prefix in [STAGE3_PREFIX, VERIFY_PREFIX]:
    ann_key = f"{prefix}/annotations/{INSTANCE_ID}.json"
    try:
        raw = s3_read_json(ann_key)
        val_data = deep_parse(raw)
        print(f"  Loaded from: {ann_key}")
        break
    except:
        pass

if val_data and isinstance(val_data, dict):
    # Object statuses
    obj_statuses = val_data.get("_object_statuses", {})
    variance_types = val_data.get("_variance_types", {})

    if obj_statuses:
        print(f"\n  Object statuses ({len(obj_statuses)}):")
        for tid, status in sorted(obj_statuses.items()):
            var_type = variance_types.get(tid, "")
            var_str = f" [{var_type}]" if var_type else ""
            print(f"    {tid:<35} status={status}{var_str}")

    # Collect validated tracking IDs
    v_tids = {}
    frame_keys = sorted([k for k in val_data if k.startswith("frame_")])
    for fk in frame_keys:
        fd = val_data[fk]
        if not isinstance(fd, dict):
            continue
        # Handle both formats
        cameras = []
        if "validated_annotations" in fd:
            cameras = fd["validated_annotations"].get("cameras", [])
        elif "cameras" in fd:
            cameras = fd["cameras"]

        for ci, cam in enumerate(cameras):
            cam_id = cam.get("camera_id", f"cam_{ci}")
            for ann in cam.get("annotations", []):
                tid = ann.get("tracking_id", "")
                label = ann.get("label", "?")
                if tid:
                    if tid not in v_tids:
                        v_tids[tid] = {"label": label, "cameras": set(), "frames": set()}
                    v_tids[tid]["cameras"].add(cam_id)
                    v_tids[tid]["frames"].add(fk)

    print(f"\n  Validated tracking IDs ({len(v_tids)}):")
    for tid in sorted(v_tids):
        info = v_tids[tid]
        status = obj_statuses.get(tid, "?")
        print(f"    {tid:<35} label={info['label']:<20} "
              f"status={status:<10} cameras={sorted(info['cameras'])} "
              f"frames={len(info['frames'])}f")
else:
    print("  No validation data found")

# ═══ 4. COMPARISON ═════════════════════════════════════════

print(f"\n{'=' * 70}")
print(" COMPARISON: SAM2 vs Validation")
print("=" * 70)

if sam2_data:
    sam2_tids = set()
    for cam_id, cam_data in sam2_data.items():
        if not isinstance(cam_data, dict):
            continue
        for obj in cam_data.get("objects", []):
            sam2_tids.add(obj.get("tracking_id", ""))
    sam2_tids.discard("")

    val_tids_set = set(v_tids.keys()) if val_data else set()

    in_sam2_only = sam2_tids - val_tids_set
    in_val_only  = val_tids_set - sam2_tids
    in_both      = sam2_tids & val_tids_set

    print(f"\n  SAM2 objects:       {len(sam2_tids)}")
    print(f"  Validated objects:  {len(val_tids_set)}")
    print(f"  In both:            {len(in_both)}")
    print(f"  SAM2 only (removed by validator): {len(in_sam2_only)}")
    print(f"  Validation only (added by validator): {len(in_val_only)}")

    if in_sam2_only:
        print(f"\n  REMOVED BY VALIDATOR (in SAM2 overlay but not in validated data):")
        for tid in sorted(in_sam2_only):
            # Find label from SAM2
            label = "?"
            for cam_id, cam_data in sam2_data.items():
                if not isinstance(cam_data, dict):
                    continue
                for obj in cam_data.get("objects", []):
                    if obj.get("tracking_id") == tid:
                        label = obj.get("label", "?")
                        break
            status = obj_statuses.get(tid, "not in statuses")
            print(f"    {tid:<35} label={label:<20} status={status}")

    if in_val_only:
        print(f"\n  ADDED BY VALIDATOR (not in SAM2, added during validation):")
        for tid in sorted(in_val_only):
            info = v_tids.get(tid, {})
            print(f"    {tid:<35} label={info.get('label','?')}")

    if in_both:
        print(f"\n  KEPT (in both SAM2 and validation):")
        for tid in sorted(in_both):
            status = obj_statuses.get(tid, "?")
            print(f"    {tid:<35} status={status}")
else:
    print("  Cannot compare — SAM2 data not loaded")

print(f"\n{'=' * 70}")
print(" CONCLUSION")
print("=" * 70)
print("""
If you see objects in the SAM2 overlay image that are NOT in the
validated data, it means the validator DELETED them during Stage 3.

The overlay video/frames were generated BEFORE validation, so they
still show the deleted objects. This is expected behavior.

The metadata sidebar correctly shows only what the validator approved.
""")
