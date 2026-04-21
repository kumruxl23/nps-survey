# ============================================================
# CELL 1 — IMPORTS + CONFIGURATION
# ============================================================
# CHANGES FROM ORIGINAL:
#   - Updated LABELS: 14 labels (added tape, miscellaneous_items, debris)
#   - New keys in backpack_purse, package_asin, personal_item_other, tissue_roll
#   - No metadata removed here — LABELS still has meta defs
#     (needed by later stages for validation/verification)
# ============================================================

import os, sys, json, shutil, time, gc, re
import numpy as np
import cv2
import boto3
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime
from collections import defaultdict

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# ═══════════════════ EDIT THESE ═══════════════════
AWS_REGION   = "ap-south-1"
BUCKET       = "drishti-lab"

SOURCE_PREFIX  = "area-organization-science/prod/BFI1/March-26-usecase-simulation/events/object_fall"
SOURCE_TYPE    = "images"
VIDEO_FILENAME = "video_15fps.mp4"
OUTPUT_PREFIX  = "area-organization-science/output/object_fall"

NUM_FRAMES    = 17
MAX_INSTANCES = None
MAX_CAMERAS   = 3
VIDEO_FPS     = 15

SAM2_DIR        = os.path.expanduser("~/SageMaker/sam2")
SAM2_CHECKPOINT = os.path.join(SAM2_DIR, "checkpoints", "sam2.1_hiera_small.pt")
SAM2_CONFIG     = "configs/sam2.1/sam2.1_hiera_s.yaml"
RESIZE_FACTOR   = 0.5

# ═══════════════════ LABELS + METADATA ═══════════════════
# Full label definitions with metadata — used by ALL stages.
# Stage 1 template ignores metadata (annotation-only).
# Stages 2+ (validation, verification) use metadata.

LABELS = {
    "associate": {
        "name": "Associate",
        "color": "#FF6D00",
        "meta": [
            {"key": "is_interacting_with_pod",       "label": "Interacting with Pod",       "type": "bool"},
            {"key": "is_associate_wearing_glove",     "label": "Wearing Gloves",             "type": "bool"},
            {"key": "is_interacting_with_monitor",    "label": "Interacting with Monitor",   "type": "bool"},
        ]
    },
    "stepladder": {
        "name": "Step Ladder",
        "color": "#00E5FF",
        "meta": [
            {"key": "is_person_on_stepladder",                "label": "Person on Step Ladder",    "type": "bool"},
            {"key": "is_3_point_touch_initiated_in_sequence", "label": "3-Point Touch Initiated",  "type": "bool"},
            {"key": "is_ascending",                           "label": "Ascending",                "type": "bool"},
            {"key": "is_descending",                          "label": "Descending",               "type": "bool"},
            {"key": "is_hand_on_left_handrail",               "label": "Hand on Left Handrail",    "type": "bool"},
            {"key": "is_hand_on_right_handrail",              "label": "Hand on Right Handrail",   "type": "bool"},
            {"key": "is_hand_on_top_bar",                     "label": "Hand on Top Bar",          "type": "bool"},
        ]
    },
    "tote": {
        "name": "Tote",
        "color": "#FF1744",
        "meta": [
            {"key": "is_tote_on_ground",  "label": "Tote on Ground",  "type": "bool"},
            {"key": "is_tote_overfilled", "label": "Tote Overfilled", "type": "bool"},
            {"key": "is_tote_on_shelf",   "label": "Tote on Shelf",   "type": "bool"},
            {"key": "stacked_totes",      "label": "Stacked Totes",   "type": "bool"},
        ]
    },
    "trashbin": {
        "name": "Trash Bin",
        "color": "#FFAB00",
        "meta": [
            {"key": "is_trash_overfilled", "label": "Trash Overfilled", "type": "bool"},
        ]
    },
    "backpack_purse": {
        "name": "Backpack / Purse",
        "color": "#FFCCBC",
        "meta": [
            {"key": "is_purse_backpack_on_ground",       "label": "On Ground",                         "type": "bool"},
            {"key": "is_purse_backpack_in_storage_bin",  "label": "In Storage Bin",                    "type": "bool"},
            {"key": "is_purse_backpack_in_staging_area", "label": "In Staging Area (Not Storage Bin)", "type": "bool"},
            {"key": "is_backpack_on_shelf",              "label": "Backpack on Shelf",                 "type": "bool"},
            {"key": "is_backpack_on_stepladder",         "label": "Backpack on Step Ladder",           "type": "bool"},
            {"key": "is_backpack_inside_tote",           "label": "Backpack Inside Tote",              "type": "bool"},
        ]
    },
    "package_asin": {
        "name": "Package / ASIN",
        "color": "#00E676",
        "meta": [
            {"key": "is_package_on_ground",          "label": "Package on Ground",          "type": "bool"},
            {"key": "is_package_in_staging_area",    "label": "Package in Staging Area",    "type": "bool"},
            {"key": "is_package_in_tote",            "label": "Package Inside Tote",        "type": "bool"},
            {"key": "is_associate_carrying_package", "label": "Associate Carrying Package", "type": "bool"},
            {"key": "is_package_on_stepladder",      "label": "Package on Step Ladder",     "type": "bool"},
        ]
    },
    "scanner": {
        "name": "Scanner",
        "color": "#D500F9",
        "meta": [
            {"key": "is_scanner_on_ground",         "label": "Scanner on Ground",         "type": "bool"},
            {"key": "is_scanner_on_shelf",          "label": "Scanner on Shelf",          "type": "bool"},
            {"key": "is_scanner_in_associate_hand", "label": "Scanner in Associate Hand", "type": "bool"},
        ]
    },
    "personal_item_other": {
        "name": "Personal Item",
        "color": "#2979FF",
        "meta": [
            {"key": "is_jacket_on_ground",      "label": "Jacket on Ground",      "type": "bool"},
            {"key": "is_jacket_on_shelf",       "label": "Jacket on Shelf",       "type": "bool"},
            {"key": "is_jacket_on_stepladder",  "label": "Jacket on Step Ladder", "type": "bool"},
            {"key": "is_bottle_on_floor",       "label": "Bottle on Floor",       "type": "bool"},
            {"key": "is_bottle_on_shelf",       "label": "Bottle on Shelf",       "type": "bool"},
            {"key": "is_bottle_on_stepladder",  "label": "Bottle on Step Ladder", "type": "bool"},
            {"key": "is_earphone_on_floor",     "label": "Earphone on Floor",     "type": "bool"},
            {"key": "is_earphone_on_shelf",     "label": "Earphone on Shelf",     "type": "bool"},
            {"key": "is_mobile_on_floor",       "label": "Mobile on Floor",       "type": "bool"},
            {"key": "is_mobile_on_shelf",       "label": "Mobile on Shelf",       "type": "bool"},
            {"key": "is_spectacles_on_ground",  "label": "Spectacles on Ground",  "type": "bool"},
            {"key": "is_spectacles_on_shelf",   "label": "Spectacles on Shelf",   "type": "bool"},
            {"key": "is_cloth_on_shelf",        "label": "Cloth on Shelf",        "type": "bool"},
            {"key": "is_cloth_in_hand",         "label": "Cloth in Hand",         "type": "bool"},
        ]
    },
    "ppe": {
        "name": "PPE",
        "color": "#F50057",
        "meta": [
            {"key": "is_glove_on_floor", "label": "Glove on Floor", "type": "bool"},
            {"key": "is_glove_on_shelf", "label": "Glove on Shelf", "type": "bool"},
        ]
    },
    "tissue_roll": {
        "name": "Tissue Roll",
        "color": "#1DE9B6",
        "meta": [
            {"key": "is_tissue_roll_in_hand",        "label": "Tissue Roll in Hand",        "type": "bool"},
            {"key": "is_tissue_roll_on_shelf",       "label": "Tissue Roll on Shelf",       "type": "bool"},
            {"key": "is_tissue_roll_on_ground",      "label": "Tissue Roll on Ground",      "type": "bool"},
            {"key": "is_tissue_roll_on_stepladder",  "label": "Tissue Roll on Step Ladder", "type": "bool"},
        ]
    },
    "tape": {
        "name": "Tape",
        "color": "#40C4FF",
        "meta": [
            {"key": "is_tape_cutter_on_ground",  "label": "Tape Cutter on Ground",  "type": "bool"},
            {"key": "is_tape_cutter_on_shelf",   "label": "Tape Cutter on Shelf",   "type": "bool"},
            {"key": "is_tape_cutter_in_hand",    "label": "Tape Cutter in Hand",    "type": "bool"},
            {"key": "is_tape_on_ground",         "label": "Tape on Ground",         "type": "bool"},
            {"key": "is_tape_on_shelf",          "label": "Tape on Shelf",          "type": "bool"},
            {"key": "is_tape_in_associate_hand", "label": "Tape in Associate Hand", "type": "bool"},
            {"key": "is_tape_on_stepladder",     "label": "Tape on Step Ladder",    "type": "bool"},
        ]
    },
    "miscellaneous_items": {
        "name": "Miscellaneous Items",
        "color": "#880E4F",
        "meta": [
            {"key": "is_sanitizer_on_ground",          "label": "Sanitizer on Ground",           "type": "bool"},
            {"key": "is_sanitizer_on_shelf",           "label": "Sanitizer on Shelf",            "type": "bool"},
            {"key": "is_pouch_clutch_on_floor",        "label": "Pouch / Clutch on Floor",       "type": "bool"},
            {"key": "is_pouch_clutch_on_shelf",        "label": "Pouch / Clutch on Shelf",       "type": "bool"},
            {"key": "is_pouch_clutch_on_stepladder",   "label": "Pouch / Clutch on Step Ladder", "type": "bool"},
            {"key": "is_giftcard_on_ground",           "label": "Gift Card on Ground",           "type": "bool"},
            {"key": "is_giftcard_on_shelf",            "label": "Gift Card on Shelf",            "type": "bool"},
            {"key": "is_unknown_object_on_shelf",      "label": "Unknown Object on Shelf",       "type": "bool"},
            {"key": "is_unknown_object_on_stepladder", "label": "Unknown Object on Step Ladder", "type": "bool"},
            {"key": "is_unknown_object_on_ground",     "label": "Unknown Object on Ground",      "type": "bool"},
        ]
    },
    "debris": {
        "name": "Debris",
        "color": "#FFD600",
        "meta": [
            {"key": "is_debris_on_ground",     "label": "Debris on Ground",      "type": "bool"},
            {"key": "is_debris_on_shelf",      "label": "Debris on Shelf",       "type": "bool"},
            {"key": "is_debris_on_stepladder", "label": "Debris on Step Ladder", "type": "bool"},
        ]
    },
}

# ═══════════════════ DERIVED PATHS ═══════════════════
STAGE0_PREFIX = f"{OUTPUT_PREFIX}/stage0_frames"
STAGE1_PREFIX = f"{OUTPUT_PREFIX}/stage1_annotation"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"

s3 = boto3.client("s3", region_name=AWS_REGION)

# ═══════════════════ HELPERS ═══════════════════
def list_s3_prefixes(bucket, prefix):
    prefixes = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            prefixes.append(cp["Prefix"])
    return sorted(prefixes)

def list_s3_objects(bucket, prefix, exts=(".jpg", ".jpeg", ".png")):
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(exts):
                keys.append(obj["Key"])
    return sorted(keys)

def s3_exists(bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except:
        return False

def sample_indices(total, n=NUM_FRAMES):
    if total <= n:
        return list(range(total))
    return [round(i * (total - 1) / (n - 1)) for i in range(n)]

# ═══════════════════ VERIFY PATH ═══════════════════
print("Cell 1 loaded")
print(f"   Source  : s3://{BUCKET}/{SOURCE_PREFIX}")
print(f"   Output  : s3://{BUCKET}/{OUTPUT_PREFIX}")
print(f"   Labels  : {len(LABELS)} — {', '.join(LABELS.keys())}")
print(f"   Frames  : {NUM_FRAMES} per camera")
print(f"   SAM2    : {os.path.basename(SAM2_CHECKPOINT)} + resize {RESIZE_FACTOR}")

print(f"\n{'='*60}")
print("  LABEL COLOR SUMMARY")
print(f"{'='*60}")
for k, v in LABELS.items():
    print(f"   {v['color']}  {v['name']:<25} ({len(v['meta'])} metadata fields)")

_top = list_s3_prefixes(BUCKET, SOURCE_PREFIX)
if _top:
    print(f"\n   S3 path verified! Found {len(_top)} instance folders:")
    for p in _top[:5]:
        print(f"   {p.rstrip('/').split('/')[-1]}/")
    if len(_top) > 5:
        print(f"   ... and {len(_top)-5} more")
else:
    print(f"\n   WARNING: No folders found at SOURCE_PREFIX!")
    print(f"   Please verify: s3://{BUCKET}/{SOURCE_PREFIX}/")
