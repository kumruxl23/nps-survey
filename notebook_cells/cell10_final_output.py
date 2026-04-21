# ============================================================
# CELL 10 — FINAL OUTPUT GENERATOR
# ============================================================
import boto3, json, os, sys, time
from datetime import datetime, timezone

AWS_REGION        = "ap-south-1"
BUCKET            = "drishti-lab"
OUTPUT_PREFIX     = "area-organization-science/output/object_fall"
SOURCE_PREFIX     = "area-organization-science/prod/BFI1/March-26-usecase-simulation/events/object_fall"
STAGE0_PREFIX     = f"{OUTPUT_PREFIX}/stage0_frames"
STAGE2_PREFIX     = f"{OUTPUT_PREFIX}/stage2_sam2"
STAGE3_PREFIX     = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX     = f"{OUTPUT_PREFIX}/stage4_verification"
VERIFY_JOB_NAME   = "object-fall-verification-v1"
PIPELINE_VERSION  = "2.0"
NUM_FRAMES        = 17
MAX_CAMERAS       = 3
VIDEO_FPS         = 15
RESIZE_FACTOR     = 0.5
SAM2_MODEL        = "sam2.1_hiera_small"
IMAGE_EXTENSIONS  = {'.jpg','.jpeg','.png','.bmp','.tiff','.tif','.webp'}

s3  = boto3.client("s3", region_name=AWS_REGION)
pag = s3.get_paginator("list_objects_v2")
t_start = time.time()
print("=" * 70)
print(" CELL 10: FINAL OUTPUT GENERATOR")
print("=" * 70)

def s3_read_json(key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8"))
def list_s3_image_keys(prefix):
    keys = []
    try:
        for page in pag.paginate(Bucket=BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                if os.path.splitext(obj["Key"])[1].lower() in IMAGE_EXTENSIONS: keys.append(obj["Key"])
    except: pass
    return sorted(keys)
def find_manifest(prefix_to_scan):
    try:
        for page in pag.paginate(Bucket=BUCKET, Prefix=prefix_to_scan):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("output.manifest"): return obj["Key"]
    except: pass
    return None
def deep_parse(raw):
    for _ in range(5):
        if not isinstance(raw, str): return raw
        try: raw = json.loads(raw)
        except: return raw
    return raw
def defMeta(label):
    return {d["key"]: "False" for d in META_DEFS.get(label, [])}

LABELS = {
    "associate":{"name":"Associate","color":"#FF6D00","meta":[{"key":"is_interacting_with_pod","type":"bool"},{"key":"is_associate_wearing_glove","type":"bool"},{"key":"is_interacting_with_monitor","type":"bool"}]},
    "stepladder":{"name":"Step Ladder","color":"#00E5FF","meta":[{"key":"is_person_on_stepladder","type":"bool"},{"key":"is_3_point_touch_initiated_in_sequence","type":"bool"},{"key":"is_ascending","type":"bool"},{"key":"is_descending","type":"bool"},{"key":"is_hand_on_left_handrail","type":"bool"},{"key":"is_hand_on_right_handrail","type":"bool"},{"key":"is_hand_on_top_bar","type":"bool"}]},
    "tote":{"name":"Tote","color":"#FF1744","meta":[{"key":"is_tote_on_ground","type":"bool"},{"key":"is_tote_overfilled","type":"bool"},{"key":"is_tote_on_shelf","type":"bool"},{"key":"stacked_totes","type":"bool"}]},
    "trashbin":{"name":"Trash Bin","color":"#FFAB00","meta":[{"key":"is_trash_overfilled","type":"bool"}]},
    "backpack_purse":{"name":"Backpack / Purse","color":"#FFCCBC","meta":[{"key":"is_purse_backpack_on_ground","type":"bool"},{"key":"is_purse_backpack_in_storage_bin","type":"bool"},{"key":"is_purse_backpack_in_staging_area","type":"bool"},{"key":"is_backpack_on_shelf","type":"bool"},{"key":"is_backpack_on_stepladder","type":"bool"},{"key":"is_backpack_inside_tote","type":"bool"}]},
    "package_asin":{"name":"Package / ASIN","color":"#00E676","meta":[{"key":"is_package_on_ground","type":"bool"},{"key":"is_package_in_staging_area","type":"bool"},{"key":"is_package_in_tote","type":"bool"},{"key":"is_associate_carrying_package","type":"bool"},{"key":"is_package_on_stepladder","type":"bool"}]},
    "scanner":{"name":"Scanner","color":"#D500F9","meta":[{"key":"is_scanner_on_ground","type":"bool"},{"key":"is_scanner_on_shelf","type":"bool"},{"key":"is_scanner_in_associate_hand","type":"bool"}]},
    "personal_item_other":{"name":"Personal Item","color":"#2979FF","meta":[{"key":"is_jacket_on_ground","type":"bool"},{"key":"is_jacket_on_shelf","type":"bool"},{"key":"is_jacket_on_stepladder","type":"bool"},{"key":"is_bottle_on_floor","type":"bool"},{"key":"is_bottle_on_shelf","type":"bool"},{"key":"is_bottle_on_stepladder","type":"bool"},{"key":"is_earphone_on_floor","type":"bool"},{"key":"is_earphone_on_shelf","type":"bool"},{"key":"is_mobile_on_floor","type":"bool"},{"key":"is_mobile_on_shelf","type":"bool"},{"key":"is_spectacles_on_ground","type":"bool"},{"key":"is_spectacles_on_shelf","type":"bool"},{"key":"is_cloth_on_shelf","type":"bool"},{"key":"is_cloth_in_hand","type":"bool"}]},
    "ppe":{"name":"PPE","color":"#F50057","meta":[{"key":"is_glove_on_floor","type":"bool"},{"key":"is_glove_on_shelf","type":"bool"}]},
    "tissue_roll":{"name":"Tissue Roll","color":"#1DE9B6","meta":[{"key":"is_tissue_roll_in_hand","type":"bool"},{"key":"is_tissue_roll_on_shelf","type":"bool"},{"key":"is_tissue_roll_on_ground","type":"bool"},{"key":"is_tissue_roll_on_stepladder","type":"bool"}]},
    "tape":{"name":"Tape","color":"#40C4FF","meta":[{"key":"is_tape_cutter_on_ground","type":"bool"},{"key":"is_tape_cutter_on_shelf","type":"bool"},{"key":"is_tape_cutter_in_hand","type":"bool"},{"key":"is_tape_on_ground","type":"bool"},{"key":"is_tape_on_shelf","type":"bool"},{"key":"is_tape_in_associate_hand","type":"bool"},{"key":"is_tape_on_stepladder","type":"bool"}]},
    "miscellaneous_items":{"name":"Miscellaneous Items","color":"#880E4F","meta":[{"key":"is_sanitizer_on_ground","type":"bool"},{"key":"is_sanitizer_on_shelf","type":"bool"},{"key":"is_pouch_clutch_on_floor","type":"bool"},{"key":"is_pouch_clutch_on_shelf","type":"bool"},{"key":"is_pouch_clutch_on_stepladder","type":"bool"},{"key":"is_giftcard_on_ground","type":"bool"},{"key":"is_giftcard_on_shelf","type":"bool"},{"key":"is_unknown_object_on_shelf","type":"bool"},{"key":"is_unknown_object_on_stepladder","type":"bool"},{"key":"is_unknown_object_on_ground","type":"bool"}]},
    "debris":{"name":"Debris","color":"#FFD600","meta":[{"key":"is_debris_on_ground","type":"bool"},{"key":"is_debris_on_shelf","type":"bool"},{"key":"is_debris_on_stepladder","type":"bool"}]},
}
META_DEFS = {k: v["meta"] for k, v in LABELS.items()}


# ═══ LOAD DATA ═══════════════════════════════════════════════
print("\n[1/6] Loading SAM2 results...")
raw_sam2 = s3_read_json(f"{STAGE2_PREFIX}/full_results.json")
sam2_results = raw_sam2.get("instances", raw_sam2) if isinstance(raw_sam2, dict) and "instances" in raw_sam2 else raw_sam2
print(f"      {len(sam2_results)} instances in full_results.json")

# Also try loading per-instance COCO files — prefer these over full_results.json
frame_mapping_pre = s3_read_json(f"{OUTPUT_PREFIX}/frame_mapping.json")
for iid in frame_mapping_pre:
    coco_key = f"{STAGE2_PREFIX}/coco/{iid}/annotations.json"
    try:
        coco = s3_read_json(coco_key)
        if isinstance(coco, dict) and "cameras" in coco:
            sam2_results[iid] = coco
            if iid not in raw_sam2 and not (isinstance(raw_sam2, dict) and "instances" in raw_sam2 and iid in raw_sam2["instances"]):
                print(f"      + loaded {iid} from per-instance COCO")
    except Exception:
        pass
print(f"      {len(sam2_results)} total SAM2 instances")

print("[2/6] Loading frame mapping...")
frame_mapping = s3_read_json(f"{OUTPUT_PREFIX}/frame_mapping.json")
print(f"      {len(frame_mapping)} instances")

print("[3/6] Loading validation annotations...")
validation_anns = {}
stage3_manifest_key = find_manifest(STAGE3_PREFIX)
if stage3_manifest_key:
    lines = s3.get_object(Bucket=BUCKET, Key=stage3_manifest_key)["Body"].read().decode("utf-8").strip().split("\n")
    for raw_line in lines:
        task = json.loads(raw_line)
        iid = task.get("instance_id", "")
        if not iid: continue
        try:
            ad = s3_read_json(f"{STAGE3_PREFIX}/annotations/{iid}.json")
            validation_anns[iid] = deep_parse(ad) if isinstance(ad, str) else ad
        except: pass
    print(f"      {len(validation_anns)} instances loaded")
else:
    print("      No stage3 manifest")

print("[4/6] Loading verification verdicts...")
verification_verdicts = {}
verify_manifest_key = find_manifest(VERIFY_PREFIX)
if verify_manifest_key:
    vlines = s3.get_object(Bucket=BUCKET, Key=verify_manifest_key)["Body"].read().decode("utf-8").strip().split("\n")
    for i, raw_line in enumerate(vlines):
        task = json.loads(raw_line)
        iid = task.get("instance_id", "")
        meta = task.get(f"{VERIFY_JOB_NAME}-metadata", {})
        if not isinstance(meta, dict): meta = {}
        wr_ref = meta.get("worker-response-ref", "")
        if wr_ref and wr_ref.startswith("s3://"):
            parts = wr_ref.replace("s3://", "").split("/", 1)
            try:
                wr_data = json.loads(s3.get_object(Bucket=parts[0], Key=parts[1])["Body"].read().decode("utf-8"))
                answers = wr_data.get("answers", [])
                if isinstance(answers, list) and answers:
                    ac = deep_parse(answers[0].get("answerContent", {}))
                    if isinstance(ac, dict):
                        ann = deep_parse(ac.get("annotationData", "{}"))
                        if isinstance(ann, dict):
                            verification_verdicts[iid] = ann
                            print(f"      [{i:>2}] {iid[-40:]}: {ann.get('verdict','?')}")
                            continue
            except Exception as ex:
                print(f"      [{i:>2}] {iid[-40:]}: {ex}")
                continue
        print(f"      [{i:>2}] {iid[-40:]}: no worker-response-ref")
    print(f"      {len(verification_verdicts)} verdicts loaded")
else:
    print("      No verification manifest")


# ═══ BUILDER FUNCTIONS (defined before main loop) ════════════

def _build_from_corrected(corrected_frames, cam_idx, camera_id, nf, inst_id, deleted_objects, corrected_snapshot):
    tid_data = {}
    for fk, fd in corrected_frames.items():
        if not fk.startswith("frame_"): continue
        fi = fd.get("frame_index", int(fk.replace("frame_", "")))
        cameras = fd.get("cameras", [])
        cam_entry = None
        for ce in cameras:
            if ce.get("camera_id") == camera_id: cam_entry = ce; break
        if cam_entry is None and cam_idx < len(cameras): cam_entry = cameras[cam_idx]
        if cam_entry is None: continue
        for ann in cam_entry.get("annotations", []):
            tid, label = ann.get("tracking_id", ""), ann.get("label", "")
            if not tid or not label or tid in deleted_objects: continue
            if tid not in tid_data:
                tid_data[tid] = {"label": label, "label_name": ann.get("label_name", label), "frame_annotations": {}, "tracked_frames": 0}
            data = ann.get("data", {})
            bbox, area = None, 0
            if isinstance(data, dict) and data.get("w", 0) > 0:
                bbox = [int(data.get("x",0)), int(data.get("y",0)), int(data.get("w",0)), int(data.get("h",0))]
                area = bbox[2] * bbox[3]
            elif isinstance(data, list) and len(data) >= 3:
                xs = [p["x"] if isinstance(p, dict) else p[0] for p in data]
                ys = [p["y"] if isinstance(p, dict) else p[1] for p in data]
                bbox = [int(min(xs)), int(min(ys)), int(max(xs)-min(xs)), int(max(ys)-min(ys))]
                area = bbox[2] * bbox[3]
            meta = ann.get("metadata", defMeta(label))
            if tid in corrected_snapshot:
                sfk = f"frame_{fi:02d}"
                if sfk in corrected_snapshot[tid]:
                    sm = corrected_snapshot[tid][sfk]
                    if sm and isinstance(sm, dict):
                        for mk, mv in sm.items(): meta[mk] = mv
            tid_data[tid]["frame_annotations"][str(fi)] = {"bbox": bbox, "area": area, "has_mask": area > 0, "metadata": meta}
            tid_data[tid]["tracked_frames"] += 1
    return [{"label": d["label"], "tracking_id": tid, "source": "verified", "status": "pending",
             "tracked_frames": d["tracked_frames"], "total_frames": nf,
             "masks_s3_prefix": f"s3://{BUCKET}/{STAGE2_PREFIX}/masks/{inst_id}/{camera_id}/{d['label']}_{tid}/",
             "frame_annotations": d["frame_annotations"]} for tid, d in sorted(tid_data.items())]


def _build_from_sam2(cam_sam2, inst_val, corrected_snapshot, obj_statuses, deleted_objects, nf, inst_id, camera_id):
    objects_out = []
    for obj in cam_sam2.get("objects", []):
        label, tid = obj.get("label", ""), obj.get("tracking_id", "")
        if not tid or tid in deleted_objects: continue
        status = obj_statuses.get(tid, "pending")
        if status == "deleted": continue
        source = obj.get("source", "original")
        if source in ("validation_edit", "validation_added"): source = "rerun"
        obj_meta = obj.get("metadata", {})
        fa_out = {}
        for fs, fd in obj.get("frame_annotations", {}).items():
            fi = int(fs)
            meta = defMeta(label)
            if obj_meta and isinstance(obj_meta, dict):
                for mk, mv in obj_meta.items(): meta[mk] = mv
            fm = fd.get("metadata", {})
            if fm and isinstance(fm, dict):
                for mk, mv in fm.items(): meta[mk] = mv
            if isinstance(inst_val, dict):
                tl = inst_val.get("_metadata_propagation", {}).get("timelines", {}).get(tid, {}).get(f"frame_{fi:02d}", {}).get("effective", {})
                if tl and isinstance(tl, dict):
                    for mk, mv in tl.items(): meta[mk] = mv
            if tid in corrected_snapshot:
                vm = corrected_snapshot.get(tid, {}).get(f"frame_{fi:02d}", {})
                if vm and isinstance(vm, dict):
                    for mk, mv in vm.items(): meta[mk] = mv
            fa_out[fs] = {"bbox": fd.get("bbox"), "area": fd.get("area", 0), "has_mask": fd.get("has_mask", fd.get("area", 0) > 0), "metadata": meta}
        objects_out.append({"label": label, "tracking_id": tid, "source": source, "status": status,
                           "tracked_frames": obj.get("tracked_frames", 0), "total_frames": obj.get("total_frames", nf),
                           "masks_s3_prefix": f"s3://{BUCKET}/{STAGE2_PREFIX}/masks/{inst_id}/{camera_id}/{label}_{tid}/",
                           "frame_annotations": fa_out})
    return objects_out


def _build_from_validation(inst_val, cam_idx, camera_id, nf, inst_id, deleted_objects, corrected_snapshot):
    """Build objects from validation data when SAM2 results are missing."""
    if not isinstance(inst_val, dict):
        return []
    tid_data = {}
    for fk in sorted(inst_val.keys()):
        if not fk.startswith("frame_"): continue
        fd = inst_val[fk]
        if not isinstance(fd, dict): continue
        fi = int(fk.replace("frame_", ""))
        cameras = fd.get("cameras", [])
        if "validated_annotations" in fd:
            cameras = fd["validated_annotations"].get("cameras", cameras)
        cam_entry = None
        for ce in cameras:
            if ce.get("camera_id") == camera_id: cam_entry = ce; break
        if cam_entry is None and cam_idx < len(cameras): cam_entry = cameras[cam_idx]
        if cam_entry is None: continue
        for ann in cam_entry.get("annotations", []):
            tid, label = ann.get("tracking_id", ""), ann.get("label", "")
            if not tid or not label or tid in deleted_objects: continue
            if tid not in tid_data:
                tid_data[tid] = {"label": label, "label_name": ann.get("label_name", label), "frame_annotations": {}, "tracked_frames": 0}
            data = ann.get("data", {})
            bbox, area = None, 0
            if isinstance(data, dict) and data.get("w", 0) > 0:
                bbox = [int(data.get("x",0)), int(data.get("y",0)), int(data.get("w",0)), int(data.get("h",0))]
                area = bbox[2] * bbox[3]
            elif isinstance(data, list) and len(data) >= 3:
                xs = [p["x"] if isinstance(p, dict) else p[0] for p in data]
                ys = [p["y"] if isinstance(p, dict) else p[1] for p in data]
                bbox = [int(min(xs)), int(min(ys)), int(max(xs)-min(xs)), int(max(ys)-min(ys))]
                area = bbox[2] * bbox[3]
            meta = ann.get("metadata", defMeta(label))
            if tid in corrected_snapshot:
                sfk = f"frame_{fi:02d}"
                if sfk in corrected_snapshot[tid]:
                    sm = corrected_snapshot[tid][sfk]
                    if sm and isinstance(sm, dict):
                        for mk, mv in sm.items(): meta[mk] = mv
            tid_data[tid]["frame_annotations"][str(fi)] = {"bbox": bbox, "area": area, "has_mask": False, "metadata": meta}
            tid_data[tid]["tracked_frames"] += 1
    return [{"label": d["label"], "tracking_id": tid, "source": "original", "status": "pending",
             "tracked_frames": d["tracked_frames"], "total_frames": nf,
             "masks_s3_prefix": f"s3://{BUCKET}/{STAGE2_PREFIX}/masks/{inst_id}/{camera_id}/{d['label']}_{tid}/",
             "frame_annotations": d["frame_annotations"]} for tid, d in sorted(tid_data.items())]


# ═══ 5. MAIN LOOP ═══════════════════════════════════════════

print("\n[5/6] Building final output...")
all_labels_used = set()
final_instances = {}
total_objects = 0
total_rejected = 0

# Loop over frame_mapping (has ALL instances) instead of sam2_results (may be partial)
for inst_id in frame_mapping:
    inst_sam2 = sam2_results.get(inst_id, {})
    inst_mapping = frame_mapping.get(inst_id, {})
    inst_val = validation_anns.get(inst_id, {})
    inst_verify = verification_verdicts.get(inst_id, {})
    inst_cameras = inst_sam2.get("cameras", inst_sam2) if isinstance(inst_sam2, dict) and "cameras" in inst_sam2 else inst_sam2 if inst_sam2 else {}
    camera_ids = list(inst_mapping.keys())
    if not camera_ids: continue

    verdict = inst_verify.get("verdict", "")
    if verdict == "rejected": total_rejected += 1
    corrected_frames = inst_verify.get("corrected_frames", {})
    deleted_objects = set(inst_verify.get("deleted_objects", []))
    corrected_snapshot = inst_verify.get("corrected_metadata_snapshot", {})
    obj_statuses = inst_val.get("_object_statuses", {}) if isinstance(inst_val, dict) else {}
    has_corrected = bool(corrected_frames)

    cameras_out = {}
    for cam_idx, camera_id in enumerate(camera_ids):
        cam_map = inst_mapping[camera_id]
        cam_sam2 = inst_cameras.get(camera_id, {}) if isinstance(inst_cameras, dict) else {}
        ORIG_W, ORIG_H = cam_map["width"], cam_map["height"]
        total_frames = cam_map.get("total_frames", 0)
        sampled_indices = cam_map.get("sampled_indices", [])

        source_prefix = f"{SOURCE_PREFIX}/{inst_id}/{camera_id}/"
        all_source_keys = list_s3_image_keys(source_prefix)
        nf = len(all_source_keys) if all_source_keys else total_frames

        sampled_frame_uris, frame_name_mapping = [], {}
        for fi, src_idx in enumerate(sampled_indices):
            if all_source_keys and src_idx < len(all_source_keys):
                ok = all_source_keys[src_idx]
                ofn = os.path.basename(ok)
                sampled_frame_uris.append(f"s3://{BUCKET}/{ok}")
                frame_name_mapping[ofn] = {"sampled_index": fi, "source_frame_index": src_idx,
                    "renamed_to": f"frame_{src_idx:06d}.jpg",
                    "overlay_uri": f"s3://{BUCKET}/{STAGE2_PREFIX}/overlay_frames/{inst_id}/{camera_id}/frame_{src_idx:04d}.jpg"}
            else:
                sampled_frame_uris.append(f"s3://{BUCKET}/{STAGE0_PREFIX}/{inst_id}/{camera_id}/frame_{src_idx:06d}.jpg")

        if has_corrected:
            objects_out = _build_from_corrected(corrected_frames, cam_idx, camera_id, nf, inst_id, deleted_objects, corrected_snapshot)
        elif cam_sam2 and cam_sam2.get("objects"):
            objects_out = _build_from_sam2(cam_sam2, inst_val, corrected_snapshot, obj_statuses, deleted_objects, nf, inst_id, camera_id)
            # Merge: add any objects from validation that SAM2 doesn't have
            sam2_tids = set(o["tracking_id"] for o in objects_out)
            val_extras = _build_from_validation(inst_val, cam_idx, camera_id, nf, inst_id, deleted_objects, corrected_snapshot)
            for vo in val_extras:
                if vo["tracking_id"] not in sam2_tids:
                    objects_out.append(vo)
        else:
            objects_out = _build_from_validation(inst_val, cam_idx, camera_id, nf, inst_id, deleted_objects, corrected_snapshot)

        # Deduplicate by tracking_id (keep LAST occurrence — latest stage wins)
        seen_tids = {}
        for i, obj in enumerate(objects_out):
            seen_tids[obj["tracking_id"]] = i
        objects_out = [objects_out[i] for i in sorted(seen_tids.values())]

        for obj in objects_out:
            if obj.get("label"): all_labels_used.add(obj["label"])
            total_objects += 1

        cameras_out[camera_id] = {
            "camera_id": camera_id, "width": ORIG_W, "height": ORIG_H,
            "total_frames": nf if nf > 0 else total_frames,
            "sampled_indices": sampled_indices, "sampled_frame_uris": sampled_frame_uris,
            "frame_name_mapping": frame_name_mapping, "objects": objects_out,
            "overlay_video": f"s3://{BUCKET}/{STAGE2_PREFIX}/overlay_videos/{inst_id}/{camera_id}/overlay_video.mp4"}

    final_instances[inst_id] = {"instance_id": inst_id, "cameras": cameras_out}
    tag = "corrected" if has_corrected else ("sam2+merge" if inst_sam2 else "validation")
    csum = ", ".join(f"{c}({len(d['objects'])}obj)" for c, d in cameras_out.items())
    print(f"   {inst_id[-40:]}: {csum} [{tag}]")


# ═══ 6. ASSEMBLE + UPLOAD ═══════════════════════════════════

final_output = {
    "pipeline_version": PIPELINE_VERSION,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "config": {
        "labels": sorted(list(all_labels_used)),
        "num_sampled_frames": NUM_FRAMES,
        "sam2_model": SAM2_MODEL,
        "resize_factor": RESIZE_FACTOR,
        "video_fps": VIDEO_FPS,
        "source_prefix": f"s3://{BUCKET}/{SOURCE_PREFIX}",
        "output_prefix": f"s3://{BUCKET}/{OUTPUT_PREFIX}",
    },
    "instances": final_instances,
}

print("\n[6/6] Uploading...")
final_key = f"{OUTPUT_PREFIX}/final_output.json"
final_body = json.dumps(final_output, indent=2).encode("utf-8")
s3.put_object(Bucket=BUCKET, Key=final_key, Body=final_body, ContentType="application/json")

local_path = os.path.expanduser("~/SageMaker/final_output.json")
with open(local_path, "w") as f:
    json.dump(final_output, f, indent=2)

elapsed = time.time() - t_start
print(f"      S3: s3://{BUCKET}/{final_key}")
print(f"      Local: {local_path}")
print(f"      Size: {len(final_body):,} bytes ({len(final_body)/1024/1024:.1f} MB)")

print(f"\n{'=' * 70}")
print(f"  DONE ({elapsed:.1f}s)")
print(f"{'=' * 70}")
print(f"   Instances: {len(final_instances)}, Objects: {total_objects}")
print(f"   Labels: {sorted(list(all_labels_used))}")
print(f"   Rejected: {total_rejected}")

for iid, idata in final_instances.items():
    print(f"\n  {iid}")
    for cid, cd in idata["cameras"].items():
        print(f"     {cid}: {cd['total_frames']}f, {len(cd['sampled_frame_uris'])} sampled, {len(cd['objects'])} objects")
        for obj in cd["objects"]:
            print(f"        {obj['label']}[{obj['tracking_id']}]: {obj['tracked_frames']}/{obj['total_frames']}f "
                  f"status={obj['status']} ({len(obj['frame_annotations'])} frame_anns)")

print(f"\n  DELIVERABLE: s3://{BUCKET}/{final_key}")
