# ============================================================
# DEBUG: Read verification annotation data for a specific chunk
# ============================================================
# Paste in notebook. Edit INSTANCE_ID, run.
# Shows exactly what labels + tracking IDs exist per camera per frame.
# ============================================================

import boto3, json

AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
STAGE3_PREFIX = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX = f"{OUTPUT_PREFIX}/stage4_verification"

# ═══ EDIT THIS — the chunk you want to inspect ═══
INSTANCE_ID = "chunk_1774559940-1774559950s"
# ══════════════════════════════════════════════════

s3 = boto3.client("s3", region_name=AWS_REGION)

# Try loading from stage3 annotations (validator output)
ann_data = None
for prefix in [VERIFY_PREFIX, STAGE3_PREFIX]:
    ann_key = f"{prefix}/annotations/{INSTANCE_ID}.json"
    try:
        resp = s3.get_object(Bucket=BUCKET, Key=ann_key)
        raw = resp["Body"].read().decode("utf-8")
        # Handle double-serialised JSON
        parsed = raw
        for _ in range(5):
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except:
                    break
            else:
                break
        if isinstance(parsed, dict):
            ann_data = parsed
            print(f"Loaded from: s3://{BUCKET}/{ann_key}")
            print(f"Top-level keys: {list(ann_data.keys())[:20]}")
            break
    except Exception as e:
        print(f"Not found at {ann_key}: {e}")

if not ann_data:
    print("No annotation data found for this instance!")
    raise SystemExit()

# ═══ PARSE AND DISPLAY ═══════════════════════════

print(f"\n{'='*70}")
print(f" ANNOTATION DATA FOR: {INSTANCE_ID}")
print(f"{'='*70}")

# Count frame keys
frame_keys = sorted([k for k in ann_data if k.startswith("frame_")])
print(f"\nFrame keys found: {len(frame_keys)}")
if frame_keys:
    print(f"  First: {frame_keys[0]}, Last: {frame_keys[-1]}")

# Per-frame breakdown
for fk in frame_keys:
    fd = ann_data[fk]
    if not isinstance(fd, dict):
        print(f"\n  {fk}: NOT A DICT — type={type(fd)}")
        continue

    # Try both validated_annotations and cameras formats
    cameras = []
    if "validated_annotations" in fd and isinstance(fd["validated_annotations"], dict):
        cameras = fd["validated_annotations"].get("cameras", [])
    elif "cameras" in fd:
        cameras = fd["cameras"]

    if not cameras:
        print(f"\n  {fk}: no cameras data")
        continue

    total_anns = sum(len(c.get("annotations", [])) for c in cameras)
    print(f"\n  {fk}: {len(cameras)} cameras, {total_anns} total annotations")

    for ci, cam in enumerate(cameras):
        cam_id = cam.get("camera_id", f"cam_{ci}")
        anns = cam.get("annotations", [])
        if not anns:
            continue

        print(f"    Camera {cam_id} ({len(anns)} annotations):")
        for ai, ann in enumerate(anns):
            label = ann.get("label", "?")
            tid   = ann.get("tracking_id", "?")
            tool  = ann.get("tool", "?")
            meta  = ann.get("metadata", {})

            # Check if data exists
            data = ann.get("data", None)
            has_data = data is not None and (
                (isinstance(data, dict) and data.get("w", 0) > 0) or
                (isinstance(data, list) and len(data) >= 3)
            )

            # Show metadata values that are True
            true_meta = [k for k, v in meta.items() if v == "True"]

            print(f"      [{ai}] {label} | {tid} | {tool} | "
                  f"has_shape={'Y' if has_data else 'N'} | "
                  f"true_meta={true_meta if true_meta else 'all False'}")

# ═══ TRACKING ID SUMMARY ═══════════════════════════

print(f"\n{'='*70}")
print(f" TRACKING ID SUMMARY (across all frames)")
print(f"{'='*70}")

tid_info = {}  # tid → {label, cameras: set, frames: set}
for fk in frame_keys:
    fd = ann_data[fk]
    if not isinstance(fd, dict):
        continue
    fp = int(fk.replace("frame_", ""))

    cameras = []
    if "validated_annotations" in fd and isinstance(fd["validated_annotations"], dict):
        cameras = fd["validated_annotations"].get("cameras", [])
    elif "cameras" in fd:
        cameras = fd["cameras"]

    for ci, cam in enumerate(cameras):
        cam_id = cam.get("camera_id", f"cam_{ci}")
        for ann in cam.get("annotations", []):
            tid = ann.get("tracking_id", "")
            if not tid:
                continue
            if tid not in tid_info:
                tid_info[tid] = {"label": ann.get("label", "?"), "cameras": set(), "frames": set()}
            tid_info[tid]["cameras"].add(cam_id)
            tid_info[tid]["frames"].add(fp)

for tid in sorted(tid_info.keys()):
    info = tid_info[tid]
    print(f"  {tid:<35} label={info['label']:<20} "
          f"cameras={sorted(info['cameras'])} "
          f"frames={len(info['frames'])}f "
          f"({min(info['frames'])}-{max(info['frames'])})")

# ═══ CHECK FOR MISMATCHES ═══════════════════════════

print(f"\n{'='*70}")
print(f" MISMATCH CHECK: tracking_id label vs actual label")
print(f"{'='*70}")

mismatches = []
for tid, info in tid_info.items():
    # tracking_id format is "label#N" — extract expected label
    parts = tid.split("#")
    if len(parts) == 2:
        expected_label = parts[0]
        actual_label = info["label"]
        if expected_label != actual_label:
            mismatches.append((tid, expected_label, actual_label))

if mismatches:
    print(f"\n  FOUND {len(mismatches)} MISMATCHES:")
    for tid, expected, actual in mismatches:
        print(f"    {tid}: expected '{expected}' but annotation says '{actual}'")
else:
    print(f"\n  No mismatches found — all tracking IDs match their labels.")

# ═══ CHECK _object_statuses and _tracking ═══════════

print(f"\n{'='*70}")
print(f" INTERNAL KEYS")
print(f"{'='*70}")

for key in ["_meta", "_tracking", "_object_statuses", "_variance_types", "_camera_settings"]:
    if key in ann_data:
        val = ann_data[key]
        if isinstance(val, dict):
            print(f"\n  {key}: {len(val)} entries")
            for k2, v2 in list(val.items())[:5]:
                print(f"    {k2}: {json.dumps(v2)[:100]}")
            if len(val) > 5:
                print(f"    ... and {len(val)-5} more")
        else:
            print(f"\n  {key}: {str(val)[:200]}")
    else:
        print(f"\n  {key}: NOT PRESENT")

print(f"\n{'='*70}")
print(f" DONE")
print(f"{'='*70}")
