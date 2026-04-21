# ============================================================
# FIX VALIDATION DATA — Add / Delete / Modify / Relabel
# ============================================================
# Directly edits the stage3 validation JSON in S3.
# Run after debug_compare_stages to understand what needs fixing.
#
# Operations:
#   1. RELABEL  — change tracking_id label (e.g. package_asin → tissue_roll)
#   2. DELETE   — remove a tracking_id from all frames
#   3. ADD      — copy an object from SAM2 results into validation data
#   4. MODIFY METADATA — change metadata values for a tracking_id
#
# All changes are frame-level aware and logged.
# ============================================================

import boto3, json, copy, os
from datetime import datetime, timezone

AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"
STAGE3_PREFIX = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX = f"{OUTPUT_PREFIX}/stage4_verification"

s3 = boto3.client("s3", region_name=AWS_REGION)

# ═══════════════════ EDIT THIS SECTION ═══════════════════

INSTANCE_ID = "chunk_1774559940-1774559950s"

# Define your fixes here. Each fix is a dict with "action" + params.
# Uncomment/edit the ones you need.

FIXES = [

    # ── RELABEL: Change package_asin#1 → tissue_roll#1 ──────
    # This renames the tracking_id AND changes the label field
    # on ALL frames where this object exists.
    #
    # {
    #     "action": "relabel",
    #     "old_tracking_id": "package_asin#1",
    #     "new_tracking_id": "tissue_roll#1",
    #     "new_label": "tissue_roll",
    #     "new_label_name": "Tissue Roll",
    #     "new_color": "#1DE9B6",
    # },
    # {
    #     "action": "relabel",
    #     "old_tracking_id": "package_asin#2",
    #     "new_tracking_id": "tissue_roll#2",
    #     "new_label": "tissue_roll",
    #     "new_label_name": "Tissue Roll",
    #     "new_color": "#1DE9B6",
    # },

    # ── DELETE: Remove a tracking_id from all frames ────────
    # {
    #     "action": "delete",
    #     "tracking_id": "package_asin#3",
    # },

    # ── ADD FROM SAM2: Pull an object from SAM2 results ─────
    # Copies the object's shape data from SAM2 into validation
    # data for the specified frames. If frames=None, copies all.
    # {
    #     "action": "add_from_sam2",
    #     "tracking_id": "package_asin#1",
    #     "frames": None,  # None = all frames, or [0, 1, 2] for specific
    # },

    # ── MODIFY METADATA: Change metadata for a tracking_id ──
    # Changes apply from start_frame forward (propagation logic).
    # If start_frame=0, it applies to all frames.
    # {
    #     "action": "modify_metadata",
    #     "tracking_id": "tissue_roll#1",
    #     "start_frame": 0,
    #     "metadata_changes": {
    #         "is_tissue_roll_in_tote": "True",
    #         "is_tissue_roll_on_ground": "False",
    #     },
    # },

    # ── SET STATUS: Change object status ─────────────────────
    # {
    #     "action": "set_status",
    #     "tracking_id": "stepladder#1",
    #     "status": "pending",  # pending, fixing, deleted
    # },

]

# ═══════════════════ END EDIT SECTION ════════════════════

def deep_parse(raw):
    for _ in range(5):
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except: break
        else: break
    return raw

def s3_read_json(key):
    resp = s3.get_object(Bucket=BUCKET, Key=key)
    return json.loads(resp["Body"].read().decode("utf-8"))

# ═══ LOAD CURRENT VALIDATION DATA ═══════════════════════

print("=" * 70)
print(f" FIXING: {INSTANCE_ID}")
print("=" * 70)

ann_key = f"{STAGE3_PREFIX}/annotations/{INSTANCE_ID}.json"
try:
    val_data = deep_parse(s3_read_json(ann_key))
    source = "stage3"
    print(f"  Loaded from stage3: {ann_key}")
except:
    ann_key = f"{VERIFY_PREFIX}/annotations/{INSTANCE_ID}.json"
    val_data = deep_parse(s3_read_json(ann_key))
    source = "verify"
    print(f"  Loaded from verify: {ann_key}")

if not isinstance(val_data, dict):
    raise ValueError("Could not parse validation data")

frame_keys = sorted([k for k in val_data if k.startswith("frame_")])
print(f"  Frames: {len(frame_keys)}")

# Load SAM2 data (needed for add_from_sam2)
sam2_data = None
try:
    raw = s3_read_json(f"{STAGE2_PREFIX}/full_results.json")
    if "instances" in raw:
        raw = raw["instances"]
    sam2_data = raw.get(INSTANCE_ID, {})
except:
    pass

# ═══ BACKUP BEFORE CHANGES ═══════════════════════════════

backup_key = f"{STAGE3_PREFIX}/annotations/{INSTANCE_ID}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
s3.put_object(
    Bucket=BUCKET, Key=backup_key,
    Body=json.dumps(val_data, indent=2).encode("utf-8"),
    ContentType="application/json"
)
print(f"  Backup saved: s3://{BUCKET}/{backup_key}")

# ═══ APPLY FIXES ═════════════════════════════════════════

change_log = []

for fix_idx, fix in enumerate(FIXES):
    action = fix["action"]
    print(f"\n  [{fix_idx+1}] Action: {action}")

    # ── RELABEL ──────────────────────────────────────────
    if action == "relabel":
        old_tid = fix["old_tracking_id"]
        new_tid = fix["new_tracking_id"]
        new_label = fix["new_label"]
        new_label_name = fix.get("new_label_name", new_label)
        new_color = fix.get("new_color", "#999")
        count = 0

        for fk in frame_keys:
            fd = val_data[fk]
            if not isinstance(fd, dict):
                continue

            # Handle both formats
            cam_lists = []
            if "validated_annotations" in fd:
                cam_lists.append(fd["validated_annotations"].get("cameras", []))
            if "cameras" in fd:
                cam_lists.append(fd["cameras"])

            for cameras in cam_lists:
                for cam in cameras:
                    for ann in cam.get("annotations", []):
                        if ann.get("tracking_id") == old_tid:
                            ann["tracking_id"] = new_tid
                            ann["label"] = new_label
                            ann["label_name"] = new_label_name
                            ann["color"] = new_color
                            # Reset metadata to defaults for new label
                            # (caller can modify_metadata after)
                            count += 1

        # Fix _object_statuses
        if "_object_statuses" in val_data:
            if old_tid in val_data["_object_statuses"]:
                val_data["_object_statuses"][new_tid] = val_data["_object_statuses"].pop(old_tid)

        # Fix _tracking
        if "_tracking" in val_data and "objects" in val_data["_tracking"]:
            if old_tid in val_data["_tracking"]["objects"]:
                obj_info = val_data["_tracking"]["objects"].pop(old_tid)
                obj_info["label"] = new_label
                obj_info["label_name"] = new_label_name
                val_data["_tracking"]["objects"][new_tid] = obj_info

        # Fix _variance_types
        if "_variance_types" in val_data:
            if old_tid in val_data["_variance_types"]:
                val_data["_variance_types"][new_tid] = val_data["_variance_types"].pop(old_tid)

        print(f"    Relabeled {old_tid} → {new_tid} ({count} annotations)")
        change_log.append({"action": "relabel", "old": old_tid, "new": new_tid, "count": count})

    # ── DELETE ───────────────────────────────────────────
    elif action == "delete":
        tid = fix["tracking_id"]
        count = 0

        for fk in frame_keys:
            fd = val_data[fk]
            if not isinstance(fd, dict):
                continue

            cam_lists = []
            if "validated_annotations" in fd:
                cam_lists.append(("validated_annotations", fd["validated_annotations"].get("cameras", [])))
            if "cameras" in fd:
                cam_lists.append(("cameras", fd["cameras"]))

            for list_key, cameras in cam_lists:
                for cam in cameras:
                    before = len(cam.get("annotations", []))
                    cam["annotations"] = [a for a in cam.get("annotations", []) if a.get("tracking_id") != tid]
                    count += before - len(cam["annotations"])

        # Remove from internal keys
        for ikey in ["_object_statuses", "_variance_types"]:
            if ikey in val_data and tid in val_data[ikey]:
                del val_data[ikey][tid]

        if "_tracking" in val_data and "objects" in val_data["_tracking"]:
            if tid in val_data["_tracking"]["objects"]:
                del val_data["_tracking"]["objects"][tid]

        print(f"    Deleted {tid} ({count} annotations removed)")
        change_log.append({"action": "delete", "tid": tid, "count": count})

    # ── ADD FROM SAM2 ────────────────────────────────────
    elif action == "add_from_sam2":
        tid = fix["tracking_id"]
        target_frames = fix.get("frames", None)

        if not sam2_data:
            print(f"    ERROR: SAM2 data not loaded, cannot add {tid}")
            continue

        # Find this object in SAM2 results
        sam2_obj = None
        sam2_cam_id = None
        for cam_id, cam_data in sam2_data.items():
            if not isinstance(cam_data, dict):
                continue
            for obj in cam_data.get("objects", []):
                if obj.get("tracking_id") == tid:
                    sam2_obj = obj
                    sam2_cam_id = cam_id
                    break
            if sam2_obj:
                break

        if not sam2_obj:
            print(f"    ERROR: {tid} not found in SAM2 results")
            continue

        label = sam2_obj.get("label", "")
        label_name = sam2_obj.get("label_name", label)
        color = sam2_obj.get("color", "#999")
        frame_anns = sam2_obj.get("frame_annotations", {})
        count = 0

        for frame_str, fa_data in frame_anns.items():
            fi = int(frame_str)
            if target_frames is not None and fi not in target_frames:
                continue

            fk = f"frame_{fi:02d}"
            if fk not in val_data:
                continue

            fd = val_data[fk]
            if not isinstance(fd, dict):
                continue

            # Find the right camera in validation data
            cameras = []
            if "validated_annotations" in fd:
                cameras = fd["validated_annotations"].get("cameras", [])
            elif "cameras" in fd:
                cameras = fd["cameras"]

            # Find matching camera
            target_cam = None
            for cam in cameras:
                if cam.get("camera_id") == sam2_cam_id:
                    target_cam = cam
                    break

            if not target_cam:
                # Camera not in this frame's data, skip
                continue

            # Check if already exists
            already = any(a.get("tracking_id") == tid for a in target_cam.get("annotations", []))
            if already:
                continue

            # Build annotation from SAM2 bbox
            bbox = fa_data.get("bbox", None)
            if not bbox:
                continue

            new_ann = {
                "label": label,
                "label_name": label_name,
                "color": color,
                "tool": "bbox",
                "data": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
                "tracking_id": tid,
                "metadata": {},
            }

            if "annotations" not in target_cam:
                target_cam["annotations"] = []
            target_cam["annotations"].append(new_ann)
            count += 1

        # Add to _object_statuses
        if "_object_statuses" in val_data:
            val_data["_object_statuses"][tid] = "pending"

        print(f"    Added {tid} from SAM2 ({count} frame-camera entries)")
        change_log.append({"action": "add_from_sam2", "tid": tid, "count": count})

    # ── MODIFY METADATA ──────────────────────────────────
    elif action == "modify_metadata":
        tid = fix["tracking_id"]
        start_frame = fix.get("start_frame", 0)
        meta_changes = fix.get("metadata_changes", {})
        count = 0

        for fk in frame_keys:
            fi = int(fk.replace("frame_", ""))
            if fi < start_frame:
                continue

            fd = val_data[fk]
            if not isinstance(fd, dict):
                continue

            cam_lists = []
            if "validated_annotations" in fd:
                cam_lists.append(fd["validated_annotations"].get("cameras", []))
            if "cameras" in fd:
                cam_lists.append(fd["cameras"])

            for cameras in cam_lists:
                for cam in cameras:
                    for ann in cam.get("annotations", []):
                        if ann.get("tracking_id") == tid:
                            if "metadata" not in ann:
                                ann["metadata"] = {}
                            for mk, mv in meta_changes.items():
                                ann["metadata"][mk] = mv
                            count += 1

        print(f"    Modified metadata for {tid} from frame {start_frame} ({count} annotations updated)")
        print(f"    Changes: {meta_changes}")
        change_log.append({"action": "modify_metadata", "tid": tid, "start_frame": start_frame, "changes": meta_changes, "count": count})

    # ── SET STATUS ───────────────────────────────────────
    elif action == "set_status":
        tid = fix["tracking_id"]
        status = fix["status"]
        if "_object_statuses" not in val_data:
            val_data["_object_statuses"] = {}
        old_status = val_data["_object_statuses"].get(tid, "unknown")
        val_data["_object_statuses"][tid] = status
        print(f"    {tid}: {old_status} → {status}")
        change_log.append({"action": "set_status", "tid": tid, "old": old_status, "new": status})

    else:
        print(f"    Unknown action: {action}")

# ═══ SAVE FIXED DATA ═════════════════════════════════════

if not FIXES:
    print("\n  No fixes defined — edit the FIXES list and re-run.")
    print("  Examples are commented out in the code above.")
else:
    # Add change log
    if "_fix_log" not in val_data:
        val_data["_fix_log"] = []
    val_data["_fix_log"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fixes_applied": len(FIXES),
        "changes": change_log,
    })

    # Save to both stage3 and verify locations
    fixed_body = json.dumps(val_data, indent=2).encode("utf-8")

    for prefix in [STAGE3_PREFIX, VERIFY_PREFIX]:
        save_key = f"{prefix}/annotations/{INSTANCE_ID}.json"
        s3.put_object(
            Bucket=BUCKET, Key=save_key,
            Body=fixed_body,
            ContentType="application/json"
        )
        print(f"\n  Saved: s3://{BUCKET}/{save_key}")

    print(f"\n  Size: {len(fixed_body):,} bytes")
    print(f"  Changes: {len(change_log)}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f" CHANGE LOG")
    print(f"{'=' * 70}")
    for cl in change_log:
        print(f"  {cl}")

print(f"\n{'=' * 70}")
print(f" DONE — Re-run debug_compare_stages.py to verify")
print(f"{'=' * 70}")
