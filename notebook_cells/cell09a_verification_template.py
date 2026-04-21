# ============================================================
# CELL 9A — VERIFICATION + FULL CORRECTION TEMPLATE
# ============================================================
# Features:
#   - View video / frames (original + SAM2 overlay)
#   - See all objects + metadata per frame (current frame only)
#   - EDIT metadata (True/False) per object per frame
#   - DELETE objects (remove tracking ID)
#   - RELABEL objects (change label + tracking ID)
#   - ADD new objects (draw bbox on frame, assign label + track)
#   - Accept or Reject with reasons
#   - Output includes all corrections at frame level
#
# CHANGES FROM ORIGINAL:
#   - Sidebar shows only CURRENT FRAME objects (not all frames)
#   - Added Delete, Relabel, Add New buttons per object
#   - Added drawing tools for adding new annotations
#   - Submit payload includes correction log
#   - Updated to 14 labels
#   - No blob preloading
# ============================================================

import boto3, json, os, re

AWS_REGION    = "ap-south-1"
BUCKET        = "drishti-lab"
OUTPUT_PREFIX = "area-organization-science/output/object_fall"
STAGE2_PREFIX = f"{OUTPUT_PREFIX}/stage2_sam2"
STAGE3_PREFIX = f"{OUTPUT_PREFIX}/stage3_validation"
VERIFY_PREFIX = f"{OUTPUT_PREFIX}/stage4_verification"
NUM_FRAMES    = 17
MAX_CAMERAS   = 3

LABELS = {
    "associate":{"name":"Associate","color":"#FF6D00","meta":[
        {"key":"is_interacting_with_pod","label":"Interacting with Pod","type":"bool"},
        {"key":"is_associate_wearing_glove","label":"Wearing Gloves","type":"bool"},
        {"key":"is_interacting_with_monitor","label":"Interacting with Monitor","type":"bool"}]},
    "stepladder":{"name":"Step Ladder","color":"#00E5FF","meta":[
        {"key":"is_person_on_stepladder","label":"Person on Step Ladder","type":"bool"},
        {"key":"is_3_point_touch_initiated_in_sequence","label":"3-Point Touch Initiated","type":"bool"},
        {"key":"is_ascending","label":"Ascending","type":"bool"},
        {"key":"is_descending","label":"Descending","type":"bool"},
        {"key":"is_hand_on_left_handrail","label":"Hand on Left Handrail","type":"bool"},
        {"key":"is_hand_on_right_handrail","label":"Hand on Right Handrail","type":"bool"},
        {"key":"is_hand_on_top_bar","label":"Hand on Top Bar","type":"bool"}]},
    "tote":{"name":"Tote","color":"#FF1744","meta":[
        {"key":"is_tote_on_ground","label":"Tote on Ground","type":"bool"},
        {"key":"is_tote_overfilled","label":"Tote Overfilled","type":"bool"},
        {"key":"is_tote_on_shelf","label":"Tote on Shelf","type":"bool"},
        {"key":"stacked_totes","label":"Stacked Totes","type":"bool"}]},
    "trashbin":{"name":"Trash Bin","color":"#FFAB00","meta":[
        {"key":"is_trash_overfilled","label":"Trash Overfilled","type":"bool"}]},
    "backpack_purse":{"name":"Backpack / Purse","color":"#FFCCBC","meta":[
        {"key":"is_purse_backpack_on_ground","label":"On Ground","type":"bool"},
        {"key":"is_purse_backpack_in_storage_bin","label":"In Storage Bin","type":"bool"},
        {"key":"is_purse_backpack_in_staging_area","label":"In Staging Area","type":"bool"},
        {"key":"is_backpack_on_shelf","label":"Backpack on Shelf","type":"bool"},
        {"key":"is_backpack_on_stepladder","label":"Backpack on Step Ladder","type":"bool"},
        {"key":"is_backpack_inside_tote","label":"Backpack Inside Tote","type":"bool"}]},
    "package_asin":{"name":"Package / ASIN","color":"#00E676","meta":[
        {"key":"is_package_on_ground","label":"Package on Ground","type":"bool"},
        {"key":"is_package_in_staging_area","label":"Package in Staging Area","type":"bool"},
        {"key":"is_package_in_tote","label":"Package Inside Tote","type":"bool"},
        {"key":"is_associate_carrying_package","label":"Associate Carrying Package","type":"bool"},
        {"key":"is_package_on_stepladder","label":"Package on Step Ladder","type":"bool"}]},
    "scanner":{"name":"Scanner","color":"#D500F9","meta":[
        {"key":"is_scanner_on_ground","label":"Scanner on Ground","type":"bool"},
        {"key":"is_scanner_on_shelf","label":"Scanner on Shelf","type":"bool"},
        {"key":"is_scanner_in_associate_hand","label":"Scanner in Associate Hand","type":"bool"}]},
    "personal_item_other":{"name":"Personal Item","color":"#2979FF","meta":[
        {"key":"is_jacket_on_ground","label":"Jacket on Ground","type":"bool"},
        {"key":"is_jacket_on_shelf","label":"Jacket on Shelf","type":"bool"},
        {"key":"is_jacket_on_stepladder","label":"Jacket on Step Ladder","type":"bool"},
        {"key":"is_bottle_on_floor","label":"Bottle on Floor","type":"bool"},
        {"key":"is_bottle_on_shelf","label":"Bottle on Shelf","type":"bool"},
        {"key":"is_bottle_on_stepladder","label":"Bottle on Step Ladder","type":"bool"},
        {"key":"is_earphone_on_floor","label":"Earphone on Floor","type":"bool"},
        {"key":"is_earphone_on_shelf","label":"Earphone on Shelf","type":"bool"},
        {"key":"is_mobile_on_floor","label":"Mobile on Floor","type":"bool"},
        {"key":"is_mobile_on_shelf","label":"Mobile on Shelf","type":"bool"},
        {"key":"is_spectacles_on_ground","label":"Spectacles on Ground","type":"bool"},
        {"key":"is_spectacles_on_shelf","label":"Spectacles on Shelf","type":"bool"},
        {"key":"is_cloth_on_shelf","label":"Cloth on Shelf","type":"bool"},
        {"key":"is_cloth_in_hand","label":"Cloth in Hand","type":"bool"}]},
    "ppe":{"name":"PPE","color":"#F50057","meta":[
        {"key":"is_glove_on_floor","label":"Glove on Floor","type":"bool"},
        {"key":"is_glove_on_shelf","label":"Glove on Shelf","type":"bool"}]},
    "tissue_roll":{"name":"Tissue Roll","color":"#1DE9B6","meta":[
        {"key":"is_tissue_roll_in_hand","label":"Tissue Roll in Hand","type":"bool"},
        {"key":"is_tissue_roll_on_shelf","label":"Tissue Roll on Shelf","type":"bool"},
        {"key":"is_tissue_roll_on_ground","label":"Tissue Roll on Ground","type":"bool"},
        {"key":"is_tissue_roll_on_stepladder","label":"Tissue Roll on Step Ladder","type":"bool"}]},
    "tape":{"name":"Tape","color":"#40C4FF","meta":[
        {"key":"is_tape_cutter_on_ground","label":"Tape Cutter on Ground","type":"bool"},
        {"key":"is_tape_cutter_on_shelf","label":"Tape Cutter on Shelf","type":"bool"},
        {"key":"is_tape_cutter_in_hand","label":"Tape Cutter in Hand","type":"bool"},
        {"key":"is_tape_on_ground","label":"Tape on Ground","type":"bool"},
        {"key":"is_tape_on_shelf","label":"Tape on Shelf","type":"bool"},
        {"key":"is_tape_in_associate_hand","label":"Tape in Associate Hand","type":"bool"},
        {"key":"is_tape_on_stepladder","label":"Tape on Step Ladder","type":"bool"}]},
    "miscellaneous_items":{"name":"Miscellaneous Items","color":"#880E4F","meta":[
        {"key":"is_sanitizer_on_ground","label":"Sanitizer on Ground","type":"bool"},
        {"key":"is_sanitizer_on_shelf","label":"Sanitizer on Shelf","type":"bool"},
        {"key":"is_pouch_clutch_on_floor","label":"Pouch / Clutch on Floor","type":"bool"},
        {"key":"is_pouch_clutch_on_shelf","label":"Pouch / Clutch on Shelf","type":"bool"},
        {"key":"is_pouch_clutch_on_stepladder","label":"Pouch / Clutch on Step Ladder","type":"bool"},
        {"key":"is_giftcard_on_ground","label":"Gift Card on Ground","type":"bool"},
        {"key":"is_giftcard_on_shelf","label":"Gift Card on Shelf","type":"bool"},
        {"key":"is_unknown_object_on_shelf","label":"Unknown Object on Shelf","type":"bool"},
        {"key":"is_unknown_object_on_stepladder","label":"Unknown Object on Step Ladder","type":"bool"},
        {"key":"is_unknown_object_on_ground","label":"Unknown Object on Ground","type":"bool"}]},
    "debris":{"name":"Debris","color":"#FFD600","meta":[
        {"key":"is_debris_on_ground","label":"Debris on Ground","type":"bool"},
        {"key":"is_debris_on_shelf","label":"Debris on Shelf","type":"bool"},
        {"key":"is_debris_on_stepladder","label":"Debris on Step Ladder","type":"bool"}]},
}

s3 = boto3.client("s3", region_name=AWS_REGION)
NF = NUM_FRAMES
NC = MAX_CAMERAS
LABELS_JS = json.dumps({k:{"name":v["name"],"color":v["color"]} for k,v in LABELS.items()})
META_DEFS_JS = json.dumps({k:v["meta"] for k,v in LABELS.items()})

print("=" * 70)
print(" GENERATING VERIFICATION + FULL CORRECTION TEMPLATE")
print("=" * 70)

# ── Build URL spans ──
spans = ""
for c in range(NC):
    for f in range(NF):
        spans += f'<span class="furl" data-c="{c}" data-f="{f}" style="display:none">'
        spans += '{%- if task.input.c' + str(c) + '_f' + f'{f:02d}' + ' -%}{{ task.input.c' + str(c) + '_f' + f'{f:02d}' + ' | grant_read_access }}{%- endif -%}</span>\n'
for c in range(NC):
    for f in range(NF):
        spans += f'<span class="ovurl" data-c="{c}" data-f="{f}" style="display:none">'
        spans += '{%- if task.input.cam' + str(c) + '_ov' + f'{f:02d}' + '_url -%}{{ task.input.cam' + str(c) + '_ov' + f'{f:02d}' + '_url | grant_read_access }}{%- endif -%}</span>\n'
for c in range(NC):
    spans += f'<span class="vidurl" data-c="{c}" style="display:none">'
    spans += '{%- if task.input.cam' + str(c) + '_video_url -%}{{ task.input.cam' + str(c) + '_video_url | grant_read_access }}{%- endif -%}</span>\n'
spans += '<span id="m-camids" style="display:none">{{ task.input.camera_ids | default: "EMPTY_ARR" }}</span>\n'
spans += '<span id="m-instid" style="display:none">{{ task.input.instance_id | default: "unknown" }}</span>\n'
spans += '<span id="m-worker" style="display:none">{{ task.input.worker_info | default: "unknown" }}</span>\n'
spans += '<span id="m-fps" style="display:none">{{ task.input.fps | default: "15" }}</span>\n'
spans += '<span id="m-ann-ref" style="display:none">{%- if task.input.validated_annotations_ref -%}{{ task.input.validated_annotations_ref | grant_read_access }}{%- endif -%}</span>\n'

# ── Label buttons for Add New ──
label_opts = ""
for k, v in LABELS.items():
    label_opts += f'<option value="{k}" data-color="{v["color"]}">{v["name"]}</option>\n'

print(f"  Spans: {len(spans):,} chars")

# ── CSS ──
CSS = """<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',Arial,sans-serif;background:#f5f5f5;color:#1a1a1a;font-size:13px}
.hdr{background:#fff;padding:10px 20px;display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #1565C0;flex-wrap:wrap;gap:6px}
.hdr h2{color:#1565C0;font-size:16px}
.hdr em{color:#e65100;font-style:normal}
.badge{background:#e3f2fd;color:#1565C0;padding:3px 12px;border-radius:16px;font-size:11px;font-weight:600}
.main{display:flex;height:calc(100vh - 52px);overflow:hidden}
.left{flex:1;display:flex;flex-direction:column;min-width:0}
.right{width:440px;overflow-y:auto;background:#fff;border-left:2px solid #e0e0e0}
.bar{display:flex;align-items:center;gap:6px;padding:6px 12px;background:#fff;border-bottom:1px solid #e0e0e0;flex-wrap:wrap;flex-shrink:0}
.btn{padding:4px 12px;border:1.5px solid #bdbdbd;background:#fff;color:#555;border-radius:5px;cursor:pointer;font-size:11px;font-weight:600}
.btn:hover{border-color:#1565C0;color:#1565C0}
.btn.act{background:#1565C0;border-color:#1565C0;color:#fff}
.cam-btn{padding:3px 10px;border:2px solid #0288d1;background:#fff;color:#0288d1;border-radius:5px;cursor:pointer;font-size:11px;font-weight:800;font-family:monospace}
.cam-btn.act{background:#0288d1;color:#fff}
.fn-btn{width:32px;height:28px;border:2px solid #D0D7E2;border-radius:4px;background:#FAFAFA;color:#555;font-weight:700;cursor:pointer;font-size:11px}
.fn-btn:hover{background:#E3F2FD;border-color:#42A5F5}
.fn-btn.act{background:#FF7043;color:#FFF;border-color:#FF7043}
.fn-btn.has{border-color:#66BB6A;background:#E8F5E9;color:#2E7D32}
.viewer{flex:1;overflow:auto;background:#111;position:relative;min-height:0;cursor:crosshair}
.viewer img{display:block}
.viewer canvas{position:absolute;top:0;left:0;pointer-events:none}
.tbar{display:flex;gap:6px;align-items:center;padding:5px 12px;background:#f0f4f8;border-bottom:1px solid #ccc;flex-wrap:wrap}
.tbtn{padding:4px 12px;border-radius:5px;font-size:11px;font-weight:700;cursor:pointer;border:2px solid #D0D7E2;background:#FAFAFA;color:#555}
.tbtn.act{color:#FFF}
#t-orig.act{background:#4A90D9;border-color:#4A90D9}
#t-sam.act{background:#FF7043;border-color:#FF7043}
.sec-hdr{padding:8px 12px;font-size:12px;font-weight:700;color:#1565C0;background:#e3f2fd;border-bottom:1px solid #bbdefb;position:sticky;top:0;z-index:2;display:flex;justify-content:space-between;align-items:center}
.sec-hdr .cnt{background:#1565C0;color:#fff;padding:1px 8px;border-radius:10px;font-size:11px}
.obj-card{padding:8px 12px;border-bottom:1px solid #f0f0f0}
.obj-card:hover{background:#fafafa}
.obj-card.deleted{opacity:.4;background:#ffebee}
.obj-hdr{display:flex;align-items:center;gap:6px;margin-bottom:4px;flex-wrap:wrap}
.obj-dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}
.obj-name{font-size:12px;font-weight:600;color:#333}
.obj-cam{font-size:9px;color:#fff;background:#0288d1;padding:1px 6px;border-radius:4px;font-family:monospace}
.obj-btns{display:flex;gap:4px;margin-top:4px;flex-wrap:wrap}
.ob{padding:3px 8px;border:1.5px solid #ddd;background:#fff;border-radius:4px;cursor:pointer;font-size:10px;font-weight:600;color:#666}
.ob:hover{border-color:#1565C0;color:#1565C0}
.ob.del{border-color:#E53935;color:#E53935}
.ob.del:hover{background:#FFEBEE}
.ob.restore{border-color:#43A047;color:#43A047}
.ob.restore:hover{background:#E8F5E9}
.mrow{display:flex;align-items:center;gap:6px;padding:3px 0;font-size:11px;border-bottom:1px solid #f5f5f5}
.mrow label{color:#555;font-weight:600;min-width:140px;flex-shrink:0}
.mrow select{padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;min-width:60px;cursor:pointer}
.mrow select.mt{background:#E8F5E9;color:#2E7D32;border:1.5px solid #A5D6A7}
.mrow select.mf{background:#FFEBEE;color:#C62828;border:1.5px solid #EF9A9A}
.meta-changed{background:#FFF8E1;border:1px solid #FFE0B2;border-radius:4px;padding:1px 5px;font-size:9px;color:#E65100;font-weight:700;margin-left:4px}
.relabel-row{display:none;padding:6px;background:#FFF3E0;border:1px solid #FFE0B2;border-radius:6px;margin-top:4px}
.relabel-row.vis{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.relabel-row select{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600}
.relabel-row .rb{padding:3px 10px;border:none;border-radius:4px;font-size:11px;font-weight:700;cursor:pointer;background:#FF9800;color:#fff}
.relabel-row .rb:hover{background:#F57C00}
.add-sec{padding:8px 12px;border-bottom:1px solid #e0e0e0}
.add-bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.add-bar select{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600;border:2px solid #43A047}
.add-bar input{padding:3px 8px;border-radius:4px;font-size:11px;border:2px solid #43A047;width:50px;font-weight:700}
.add-bar .ab{padding:4px 12px;border:none;border-radius:4px;font-size:11px;font-weight:700;cursor:pointer;background:#43A047;color:#fff}
.add-bar .ab:hover{background:#2E7D32}
.add-hint{font-size:10px;color:#777;margin-top:4px}
.draw-active{border:3px solid #43A047!important}
.prop-box{margin:6px 12px;padding:8px;border-radius:6px;font-size:11px}
.prop-box.ok{background:#E8F5E9;border:1px solid #A5D6A7;color:#2E7D32}
.prop-box.warn{background:#FFF3E0;border:1px solid #FFE0B2;color:#E65100}
.verdict{padding:14px 12px;background:#fff;border-top:2px solid #e0e0e0;display:flex;flex-direction:column;gap:8px;align-items:center}
.vbtn{padding:10px 28px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;border:none;min-width:180px;text-align:center}
#v-acc{background:#43A047;color:#fff}
#v-acc:hover{background:#2E7D32}
#v-rej{background:#E53935;color:#fff}
#v-rej:hover{background:#C62828}
.rej-reason{display:none;width:90%;padding:6px;border:2px solid #E53935;border-radius:6px;font-size:11px;resize:vertical;min-height:50px}
.rej-reason.vis{display:block}
.rej-cats{display:none;flex-wrap:wrap;gap:4px;margin-bottom:6px}
.rej-cats.vis{display:flex}
.rej-cat{padding:3px 10px;border:1.5px solid #ccc;border-radius:4px;font-size:10px;cursor:pointer;font-weight:600}
.rej-cat:hover{border-color:#E53935;color:#E53935}
.rej-cat.sel{background:#FFEBEE;border-color:#E53935;color:#C62828}
.vid-wrap{flex:1;min-height:0;background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}
.vid-wrap video{max-width:100%;max-height:100%;object-fit:contain}
.chg-log{padding:6px 12px;background:#F3E5F5;border-bottom:1px solid #CE93D8;font-size:10px;max-height:100px;overflow-y:auto;display:none}
.chg-log.vis{display:block}
.chg-log h5{margin:0 0 3px;color:#7B1FA2;font-size:11px}
.cl-entry{padding:1px 0;border-bottom:1px solid #E1BEE7;color:#555}
</style>"""

# ── HTML ──
HTML = (
"""<script src="https://assets.crowd.aws/crowd-html-elements.js"></script>
<crowd-form><div>""" + spans +
"""<div class="hdr"><h2>&#128270; <em>Verification</em> + Correction</h2>
<span class="badge" id="instId">loading...</span></div>
<div class="main"><div class="left">
<div class="bar">
<button type="button" class="btn act" id="mVideo">&#9654; Video</button>
<button type="button" class="btn" id="mFrames">&#128444; Frames</button>
<span style="width:1px;height:20px;background:#ccc"></span>
<span id="camTabs"></span></div>
<div id="vid-sec" style="display:flex;flex:1;flex-direction:column;min-height:0">
<div class="vid-wrap"><video id="vVid" controls muted loop playsinline></video></div></div>
<div id="frm-sec" style="display:none;flex:1;flex-direction:column;min-height:0">
<div class="bar" id="fnav"></div>
<div class="tbar">
<button type="button" class="tbtn act" id="t-orig">Original</button>
<button type="button" class="tbtn" id="t-sam">SAM2 Overlay</button>
<span id="draw-status" style="font-size:10px;color:#43A047;font-weight:700;margin-left:12px"></span></div>
<div class="viewer" id="fview">
<img id="fimg" src=""/>
<canvas id="fcv"></canvas></div></div>
</div>
<div class="right">
<div class="sec-hdr">All Objects &#8212; Frame <span id="metaFrame">0</span>
<span class="cnt" id="objCount">0</span>
<span style="font-size:9px;color:#777;font-weight:400">HERE=on this frame+cam</span></div>
<div id="objList"></div>
<div class="sec-hdr" style="background:#e8f5e9;color:#2e7d32;border-color:#a5d6a7">Add New Object</div>
<div class="add-sec"><div class="add-bar">
<select id="addLabel">""" + label_opts +
"""</select>
<span style="font-size:10px;color:#555">Track#</span>
<input type="number" id="addNum" value="1" min="1" max="99"/>
<button type="button" class="ab" id="addBtn">+ Draw on Frame</button></div>
<div class="add-hint" id="addHint">Select label, set track number, click Draw, then click+drag on image.</div></div>
<div class="sec-hdr" style="background:#F3E5F5;color:#7B1FA2;border-color:#CE93D8">Change Log
<span class="cnt" id="logCount">0</span></div>
<div class="chg-log" id="chgLog"><h5>Changes</h5><div id="clBody"></div></div>
<div class="verdict">
<button type="button" class="vbtn" id="v-acc">&#10004; Accept</button>
<button type="button" class="vbtn" id="v-rej">&#10008; Reject</button>
<div class="rej-cats" id="rejCats">
<span class="rej-cat" data-r="metadata_wrong">Metadata Wrong</span>
<span class="rej-cat" data-r="propagation_gap">Propagation Gap</span>
<span class="rej-cat" data-r="mask_quality">Mask Quality</span>
<span class="rej-cat" data-r="missing_object">Missing Object</span>
<span class="rej-cat" data-r="wrong_label">Wrong Label</span>
<span class="rej-cat" data-r="other">Other</span></div>
<textarea class="rej-reason" id="rejReason" placeholder="Describe the issue..."></textarea>
</div></div></div>
<input type="hidden" name="annotationData" id="annotationData" value="{}"/>
</div></crowd-form>""")

print(f"  CSS: {len(CSS):,} chars, HTML: {len(HTML):,} chars")

# ── JAVASCRIPT ──
JS = '<script>\ntry{\nvar NF=' + str(NF) + ',NC=' + str(NC) + ';\nvar LABELS=' + LABELS_JS + ';\nvar META_DEFS=' + META_DEFS_JS + ';\n'
JS += r"""function rsp(id){var e=document.getElementById(id);return e?e.textContent.trim():"";}
function isSent(v){return !v||v==="EMPTY_OBJ"||v==="EMPTY_ARR"||v==="EMPTY";}
function cln(d){return JSON.parse(JSON.stringify(d));}
function defMeta(lb){var ds=META_DEFS[lb]||[],m={};for(var i=0;i<ds.length;i++){if(ds[i].type==="bool")m[ds[i].key]="False";}return m;}

var iv=rsp("m-instid");document.getElementById("instId").textContent=iv||"unknown";
var CAM_NAMES=[];try{var cv=rsp("m-camids");if(!isSent(cv))CAM_NAMES=JSON.parse(cv);}catch(e){}
while(CAM_NAMES.length<NC)CAM_NAMES.push("CAM_"+CAM_NAMES.length);
var ACTUAL_NC=Math.min(CAM_NAMES.length,NC);

var origUrls=[],ovUrls=[],vidUrls=[];
for(var c=0;c<NC;c++){origUrls.push([]);ovUrls.push([]);vidUrls.push("");for(var f=0;f<NF;f++){origUrls[c].push("");ovUrls[c].push("");}}
document.querySelectorAll(".furl").forEach(function(sp){var c=parseInt(sp.dataset.c),f=parseInt(sp.dataset.f),u=sp.textContent.trim();if(u&&u.length>5&&c<NC&&f<NF)origUrls[c][f]=u;});
document.querySelectorAll(".ovurl").forEach(function(sp){var c=parseInt(sp.dataset.c),f=parseInt(sp.dataset.f),u=sp.textContent.trim();if(u&&u.length>5&&c<NC&&f<NF)ovUrls[c][f]=u;});
document.querySelectorAll(".vidurl").forEach(function(sp){var c=parseInt(sp.dataset.c),u=sp.textContent.trim();if(u&&u.length>5&&c<NC)vidUrls[c]=u;});

var curCam=0,curFP=0,viewMode="video",imgMode="orig";
var annData={},allFA={};
var verdict="",rejectReasons=[],rejectText="";
var metaOverrides={},changeLog=[];
var deletedTids={};
var drawMode=null,drawLabel="",drawTid="",drawColor="",DS={active:false,sx:0,sy:0};

// ═══ METADATA ENGINE ═══
function getEffectiveMeta(tid,frame){
var lbl=tid.split("#")[0],base=defMeta(lbl);
for(var fp2=0;fp2<=frame;fp2++){var fa=allFA[fp2]||[];
for(var i=0;i<fa.length;i++){if(fa[i].trackingId===tid&&fa[i].origMeta){var om=fa[i].origMeta;for(var k in om)base[k]=om[k];break;}}}
if(metaOverrides[tid]){for(var fp2=0;fp2<=frame;fp2++){var ov=metaOverrides[tid][fp2];if(ov){for(var k in ov)base[k]=ov[k];}}}
return base;}

function setMetaVal(tid,frame,key,value){
if(!metaOverrides[tid])metaOverrides[tid]={};
if(!metaOverrides[tid][frame])metaOverrides[tid][frame]={};
var old=getEffectiveMeta(tid,frame)[key]||"False";
metaOverrides[tid][frame][key]=value;
addLog("metadata","f"+frame+" "+tid+" "+key+": "+old+" -> "+value);
buildObjPanel();saveOutput();}

// ═══ CHANGE LOG ═══
function addLog(type,msg){changeLog.push({type:type,msg:msg,ts:new Date().toISOString()});updLog();}
function updLog(){var el=document.getElementById("chgLog"),body=document.getElementById("clBody"),cnt=document.getElementById("logCount");
cnt.textContent=changeLog.length;
if(!changeLog.length){el.classList.remove("vis");return;}
el.classList.add("vis");
var h="";for(var i=changeLog.length-1;i>=Math.max(0,changeLog.length-20);i--){
h+='<div class="cl-entry"><b>'+changeLog[i].type+'</b>: '+changeLog[i].msg+'</div>';}
body.innerHTML=h;}

// ═══ PARSE ANNOTATIONS ═══
var annRef=rsp("m-ann-ref");
function parseAnns(raw){try{raw=raw.replace(/&quot;/g,'"').replace(/&amp;/g,'&');
var p=raw;for(var i=0;i<5;i++){if(typeof p==="string"){try{p=JSON.parse(p);}catch(e){break;}}else break;}
if(typeof p==="object"&&p!==null){annData=p;buildAllFA();}}catch(e){}
buildObjPanel();saveOutput();}

function buildAllFA(){allFA={};
for(var fk in annData){if(!fk.startsWith("frame_"))continue;
var fd=annData[fk];if(!fd)continue;
var fp=parseInt(fk.replace("frame_",""));if(isNaN(fp))continue;
var cams=fd.validated_annotations?fd.validated_annotations.cameras:(fd.cameras||[]);
var frameAnns=[];
for(var ci=0;ci<cams.length;ci++){var ca=cams[ci].annotations||[];
for(var ai=0;ai<ca.length;ai++){var a=ca[ai];if(!a.label)continue;
var origM=a.metadata||defMeta(a.label);
frameAnns.push({ci:ci,label:a.label,color:a.color||(LABELS[a.label]?LABELS[a.label].color:"#999"),
labelName:a.label_name||(LABELS[a.label]?LABELS[a.label].name:a.label),
trackingId:a.tracking_id||"",tool:a.tool||"bbox",data:a.data||null,origMeta:cln(origM)});}}
if(frameAnns.length)allFA[fp]=frameAnns;}}

if(annRef&&annRef.indexOf("http")===0){var xhr=new XMLHttpRequest();xhr.open("GET",annRef,true);
xhr.onload=function(){if(xhr.status===200)parseAnns(xhr.responseText);};xhr.send();}
else{var inline=rsp("m-ann-ref");if(!isSent(inline))parseAnns(inline);else{buildObjPanel();saveOutput();}}

// ═══ DELETE OBJECT ═══
function deleteObj(tid){deletedTids[tid]=true;
addLog("delete","Deleted "+tid+" from all frames");
buildObjPanel();renderCanvas();saveOutput();}

function restoreObj(tid){delete deletedTids[tid];
addLog("restore","Restored "+tid);
buildObjPanel();renderCanvas();saveOutput();}

// ═══ RELABEL OBJECT ═══
function relabelObj(oldTid,newLabel,newNum){
var newTid=newLabel+"#"+newNum;
if(newTid===oldTid){addLog("relabel","No change: "+oldTid);return;}
// Check for conflict
for(var fp=0;fp<NF;fp++){var fa=allFA[fp]||[];
for(var i=0;i<fa.length;i++){if(fa[i].trackingId===newTid&&fa[i].trackingId!==oldTid){
alert("Conflict: "+newTid+" already exists. Pick a different number.");return;}}}
var newColor=LABELS[newLabel]?LABELS[newLabel].color:"#999";
var newName=LABELS[newLabel]?LABELS[newLabel].name:newLabel;
for(var fp=0;fp<NF;fp++){var fa=allFA[fp]||[];
for(var i=0;i<fa.length;i++){if(fa[i].trackingId===oldTid){
fa[i].trackingId=newTid;fa[i].label=newLabel;fa[i].color=newColor;fa[i].labelName=newName;
fa[i].origMeta=defMeta(newLabel);}}}
if(metaOverrides[oldTid]){metaOverrides[newTid]=metaOverrides[oldTid];delete metaOverrides[oldTid];}
if(deletedTids[oldTid]){deletedTids[newTid]=true;delete deletedTids[oldTid];}
addLog("relabel",oldTid+" -> "+newTid+" ("+newName+")");
buildObjPanel();renderCanvas();saveOutput();}

// ═══ ADD NEW OBJECT (drawing) ═══
function startDraw(){
var sel=document.getElementById("addLabel");
var num=document.getElementById("addNum").value||"1";
drawLabel=sel.value;drawColor=LABELS[drawLabel]?LABELS[drawLabel].color:"#999";
drawTid=drawLabel+"#"+num;drawMode="bbox";DS.active=false;
document.getElementById("draw-status").textContent="DRAWING: "+drawTid+" — click+drag on image";
document.getElementById("fview").classList.add("draw-active");
document.getElementById("addHint").textContent="Click and drag on the image to draw a bounding box for "+drawTid;}

function finishDraw(ci,x,y,w,h){
if(w<5||h<5){cancelDraw();return;}
var fp=curFP;if(!allFA[fp])allFA[fp]=[];
var lObj=LABELS[drawLabel]||{};
allFA[fp].push({ci:ci,label:drawLabel,color:drawColor,
labelName:lObj.name||drawLabel,trackingId:drawTid,
tool:"bbox",data:{x:Math.round(x),y:Math.round(y),w:Math.round(w),h:Math.round(h)},
origMeta:defMeta(drawLabel)});
addLog("add","Added "+drawTid+" on f"+fp+" cam"+ci+" bbox=["+Math.round(x)+","+Math.round(y)+","+Math.round(w)+","+Math.round(h)+"]");
cancelDraw();buildObjPanel();renderCanvas();saveOutput();}

function cancelDraw(){drawMode=null;DS.active=false;
document.getElementById("draw-status").textContent="";
document.getElementById("fview").classList.remove("draw-active");
document.getElementById("addHint").textContent="Select label, set track number, click Draw, then click+drag on image.";
renderCanvas();}

document.getElementById("addBtn").addEventListener("click",function(){
if(viewMode!=="frames"){document.getElementById("mFrames").click();}
startDraw();});

// ═══ CANVAS DRAWING (for bbox preview + existing annotations) ═══
var fimg=document.getElementById("fimg"),fcv=document.getElementById("fcv");
function renderCanvas(){
var ctx=fcv.getContext("2d");
if(!fimg.naturalWidth){ctx.clearRect(0,0,fcv.width,fcv.height);return;}
fcv.width=fimg.naturalWidth;fcv.height=fimg.naturalHeight;
fcv.style.width=fimg.style.width||fimg.naturalWidth+"px";
fcv.style.height=fimg.style.height||fimg.naturalHeight+"px";
ctx.clearRect(0,0,fcv.width,fcv.height);
// Draw existing annotations for current frame + camera
var fa=allFA[curFP]||[];
for(var i=0;i<fa.length;i++){var a=fa[i];
if(a.ci!==curCam||deletedTids[a.trackingId])continue;
if(a.data&&a.tool==="bbox"){var d=a.data;
ctx.strokeStyle=a.color;ctx.lineWidth=2;ctx.strokeRect(d.x,d.y,d.w,d.h);
ctx.fillStyle=a.color;ctx.globalAlpha=0.15;ctx.fillRect(d.x,d.y,d.w,d.h);ctx.globalAlpha=1;
ctx.font="bold 11px Arial";var tw=ctx.measureText(a.labelName+" #"+(a.trackingId.split("#")[1]||"")).width;
ctx.fillStyle=a.color;ctx.fillRect(d.x,d.y-16,tw+8,16);
ctx.fillStyle="#FFF";ctx.fillText(a.labelName+" #"+(a.trackingId.split("#")[1]||""),d.x+4,d.y-4);}
if(a.data&&a.tool==="polygon"&&Array.isArray(a.data)&&a.data.length>=3){
ctx.strokeStyle=a.color;ctx.lineWidth=2;ctx.beginPath();
ctx.moveTo(a.data[0].x,a.data[0].y);
for(var j=1;j<a.data.length;j++)ctx.lineTo(a.data[j].x,a.data[j].y);
ctx.closePath();ctx.stroke();ctx.fillStyle=a.color;ctx.globalAlpha=0.15;ctx.fill();ctx.globalAlpha=1;
ctx.font="bold 11px Arial";ctx.fillStyle=a.color;
ctx.fillText(a.labelName+" #"+(a.trackingId.split("#")[1]||""),a.data[0].x,a.data[0].y-4);}}
// Draw preview if drawing
if(drawMode&&DS.active){ctx.strokeStyle=drawColor;ctx.lineWidth=2;ctx.setLineDash([6,3]);
var x1=Math.min(DS.sx,DS.cx),y1=Math.min(DS.sy,DS.cy),w1=Math.abs(DS.cx-DS.sx),h1=Math.abs(DS.cy-DS.sy);
ctx.strokeRect(x1,y1,w1,h1);ctx.setLineDash([]);}}

// Mouse events for drawing
var viewer=document.getElementById("fview");
fcv.style.pointerEvents="auto";
fcv.addEventListener("mousedown",function(e){
if(!drawMode)return;e.preventDefault();
var r=fimg.getBoundingClientRect();
var scaleX=fimg.naturalWidth/r.width,scaleY=fimg.naturalHeight/r.height;
DS.sx=(e.clientX-r.left)*scaleX;DS.sy=(e.clientY-r.top)*scaleY;DS.cx=DS.sx;DS.cy=DS.sy;DS.active=true;});
fcv.addEventListener("mousemove",function(e){
if(!drawMode||!DS.active)return;
var r=fimg.getBoundingClientRect();
var scaleX=fimg.naturalWidth/r.width,scaleY=fimg.naturalHeight/r.height;
DS.cx=(e.clientX-r.left)*scaleX;DS.cy=(e.clientY-r.top)*scaleY;renderCanvas();});
document.addEventListener("mouseup",function(e){
if(!drawMode||!DS.active)return;DS.active=false;
var x=Math.min(DS.sx,DS.cx),y=Math.min(DS.sy,DS.cy),w=Math.abs(DS.cx-DS.sx),h=Math.abs(DS.cy-DS.sy);
finishDraw(curCam,x,y,w,h);});

// ═══ BUILD OBJECT PANEL (ALL objects, current-frame indicator) ═══
function buildObjPanel(){
var el=document.getElementById("objList");
document.getElementById("metaFrame").textContent=curFP;
// Collect ALL tracking IDs across ALL frames
var tidMap={};
for(var fp=0;fp<NF;fp++){var fa=allFA[fp]||[];
for(var i=0;i<fa.length;i++){var a=fa[i];if(!a.trackingId)continue;
if(!tidMap[a.trackingId])tidMap[a.trackingId]={label:a.label,color:a.color,labelName:a.labelName,cameras:{},frames:{},onCurrentFrame:false,onCurrentCam:false};
tidMap[a.trackingId].cameras[a.ci]=true;tidMap[a.trackingId].frames[fp]=true;}}
// Check which are on current frame + current camera
var curFA=allFA[curFP]||[];
for(var i=0;i<curFA.length;i++){var a=curFA[i];if(!a.trackingId||!tidMap[a.trackingId])continue;
tidMap[a.trackingId].onCurrentFrame=true;
if(a.ci===curCam)tidMap[a.trackingId].onCurrentCam=true;}
var keys=Object.keys(tidMap).sort();
document.getElementById("objCount").textContent=keys.length;
if(!keys.length){el.innerHTML='<div style="padding:12px;color:#999;text-align:center">No objects found</div>';return;}
var h="";
for(var ki=0;ki<keys.length;ki++){var tid=keys[ki],info=tidMap[tid];
var isDel=!!deletedTids[tid];
var onFrame=info.onCurrentFrame;
var onCam=info.onCurrentCam;
var defs=META_DEFS[info.label]||[];
var meta=getEffectiveMeta(tid,curFP);
var num=tid.split("#")[1]||"?";
var nFrames=Object.keys(info.frames).length;
var nCams=Object.keys(info.cameras).length;
// Card style: bright if on current frame, faded if not
var cardCls="obj-card"+(isDel?" deleted":"")+(onFrame?"":" not-here");
h+='<div class="'+cardCls+'" style="'+(onFrame?"":"opacity:.55;background:#f9f9f9")+'">';
h+='<div class="obj-hdr"><div class="obj-dot" style="background:'+info.color+'"></div>';
h+='<span class="obj-name">'+info.labelName+' #'+num+'</span>';
// Presence badge
if(onCam)h+='<span style="font-size:9px;padding:1px 6px;border-radius:8px;background:#E8F5E9;color:#2E7D32;font-weight:700">HERE</span>';
else if(onFrame)h+='<span style="font-size:9px;padding:1px 6px;border-radius:8px;background:#FFF3E0;color:#E65100;font-weight:700">other cam</span>';
else h+='<span style="font-size:9px;padding:1px 6px;border-radius:8px;background:#f5f5f5;color:#999;font-weight:600">f:'+Object.keys(info.frames).join(",")+'</span>';
// Camera badges
var camKeys=Object.keys(info.cameras);
for(var ci2=0;ci2<camKeys.length;ci2++){var cIdx=parseInt(camKeys[ci2]);h+='<span class="obj-cam">'+CAM_NAMES[cIdx]+'</span>';}
h+='<span style="font-size:9px;color:#999;margin-left:4px">'+nFrames+'f/'+nCams+'c</span>';
h+='</div>';
// Action buttons
h+='<div class="obj-btns">';
if(isDel){h+='<button type="button" class="ob restore" onclick="restoreObj(\''+tid+'\')">Restore</button>';}
else{
h+='<button type="button" class="ob del" onclick="deleteObj(\''+tid+'\')">Delete</button>';
h+='<button type="button" class="ob" onclick="toggleRelabel(\''+tid+'\')">Relabel</button>';}
h+='</div>';
// Relabel row: existing TIDs + new label option
h+='<div class="relabel-row" id="rl-'+tid.replace("#","_")+'">';
h+='<select id="rls-'+tid.replace("#","_")+'" style="flex:1;font-size:11px">';
h+='<optgroup label="Existing Objects">';
for(var ek=0;ek<keys.length;ek++){var etid=keys[ek];if(etid===tid)continue;
var einfo=tidMap[etid];h+='<option value="'+etid+'">'+einfo.labelName+' #'+etid.split("#")[1]+' ('+Object.keys(einfo.frames).length+'f)</option>';}
h+='</optgroup><optgroup label="New Label + Number">';
for(var lk in LABELS){for(var nn=1;nn<=9;nn++){var candidate=lk+"#"+nn;
var exists=!!tidMap[candidate];if(exists)continue;
h+='<option value="'+candidate+'">+ '+LABELS[lk].name+' #'+nn+' (new)</option>';}}
h+='</optgroup></select>';
h+='<button type="button" class="rb" onclick="doRelabel(\''+tid+'\')">Apply</button></div>';
// Metadata (only if not deleted)
if(!isDel&&defs.length){for(var di=0;di<defs.length;di++){var d=defs[di],v=meta[d.key]||"False";
var changed=metaOverrides[tid]&&metaOverrides[tid][curFP]&&metaOverrides[tid][curFP][d.key]!==undefined;
var cls=(v==="True")?"mt":"mf";
h+='<div class="mrow"><label>'+d.label+'</label>';
h+='<select class="'+cls+'" data-tid="'+tid+'" data-mk="'+d.key+'">';
h+='<option value="False"'+(v==="False"?' selected':'')+'>False</option>';
h+='<option value="True"'+(v==="True"?' selected':'')+'>True</option></select>';
if(changed)h+='<span class="meta-changed">edited</span>';
h+='</div>';}}
h+='</div>';}
el.innerHTML=h;
el.querySelectorAll("select[data-tid]").forEach(function(sel){
sel.addEventListener("change",function(e){e.stopPropagation();
setMetaVal(this.dataset.tid,curFP,this.dataset.mk,this.value);});});}

function toggleRelabel(tid){var el=document.getElementById("rl-"+tid.replace("#","_"));
if(el)el.classList.toggle("vis");}
function doRelabel(tid){var sel=document.getElementById("rls-"+tid.replace("#","_"));
if(!sel||!sel.value)return;
var newTid=sel.value;var parts=newTid.split("#");
if(parts.length!==2){alert("Invalid selection");return;}
relabelObj(tid,parts[0],parts[1]);}

// ═══ CAMERA + FRAME NAV ═══
function buildCamTabs(){var el=document.getElementById("camTabs");el.innerHTML="";
for(var ci=0;ci<ACTUAL_NC;ci++){(function(idx){var b=document.createElement("button");
b.type="button";b.className="cam-btn"+(idx===0?" act":"");
b.textContent=CAM_NAMES[idx].length>6?CAM_NAMES[idx].slice(-4):CAM_NAMES[idx];
b.onclick=function(){curCam=idx;document.querySelectorAll(".cam-btn").forEach(function(t,i){t.classList.toggle("act",i===idx);});
if(viewMode==="video")loadVid();else{loadImg();buildObjPanel();renderCanvas();}};
el.appendChild(b);})(ci);}}

function buildFNav(){var el=document.getElementById("fnav");el.innerHTML="";
var pb=document.createElement("button");pb.type="button";pb.className="btn";pb.textContent="< Prev";
pb.onclick=function(){if(curFP>0){curFP--;updFrame();}};el.appendChild(pb);
for(var i=0;i<NF;i++){(function(fp){var b=document.createElement("button");
b.type="button";b.className="fn-btn"+(fp===0?" act":"")+(allFA[fp]?" has":"");
b.textContent=fp;b.dataset.fp=fp;b.onclick=function(){curFP=fp;updFrame();};
el.appendChild(b);})(i);}
var nb=document.createElement("button");nb.type="button";nb.className="btn";nb.textContent="Next >";
nb.onclick=function(){if(curFP<NF-1){curFP++;updFrame();}};el.appendChild(nb);}

function updFrame(){cancelDraw();
document.querySelectorAll(".fn-btn").forEach(function(b){b.classList.toggle("act",parseInt(b.dataset.fp)===curFP);});
loadImg();buildObjPanel();}

function loadImg(){var img=fimg;
var url=(imgMode==="sam")?ovUrls[curCam][curFP]:origUrls[curCam][curFP];
if(!url||url.length<5)url=origUrls[curCam][curFP];
if(url&&url.length>5){img.onload=function(){renderCanvas();};img.src=url;}
else renderCanvas();}

function loadVid(){var vid=document.getElementById("vVid");var url=vidUrls[curCam];
if(url&&url.length>5){vid.src=url;vid.load();var p=vid.play();if(p&&p.catch)p.catch(function(){});}}

// Mode switching
document.getElementById("mVideo").addEventListener("click",function(){viewMode="video";this.classList.add("act");
document.getElementById("mFrames").classList.remove("act");
document.getElementById("vid-sec").style.display="flex";document.getElementById("frm-sec").style.display="none";
cancelDraw();loadVid();});
document.getElementById("mFrames").addEventListener("click",function(){viewMode="frames";this.classList.add("act");
document.getElementById("mVideo").classList.remove("act");
document.getElementById("vid-sec").style.display="none";document.getElementById("frm-sec").style.display="flex";
loadImg();buildObjPanel();});
document.getElementById("t-orig").addEventListener("click",function(){imgMode="orig";this.classList.add("act");
document.getElementById("t-sam").classList.remove("act");loadImg();});
document.getElementById("t-sam").addEventListener("click",function(){imgMode="sam";this.classList.add("act");
document.getElementById("t-orig").classList.remove("act");loadImg();});

// Verdict
document.getElementById("v-acc").addEventListener("click",function(){verdict="accepted";rejectReasons=[];rejectText="";
document.getElementById("rejCats").classList.remove("vis");document.getElementById("rejReason").classList.remove("vis");
this.style.boxShadow="0 0 0 3px #A5D6A7";document.getElementById("v-rej").style.boxShadow="";saveOutput();});
document.getElementById("v-rej").addEventListener("click",function(){verdict="rejected";
document.getElementById("rejCats").classList.add("vis");document.getElementById("rejReason").classList.add("vis");
this.style.boxShadow="0 0 0 3px #EF9A9A";document.getElementById("v-acc").style.boxShadow="";saveOutput();});
document.querySelectorAll(".rej-cat").forEach(function(c){c.addEventListener("click",function(){
this.classList.toggle("sel");rejectReasons=[];
document.querySelectorAll(".rej-cat.sel").forEach(function(s){rejectReasons.push(s.dataset.r);});saveOutput();});});
document.getElementById("rejReason").addEventListener("input",function(){rejectText=this.value;saveOutput();});

// Keyboard
document.addEventListener("keydown",function(e){
if(e.target.tagName==="TEXTAREA"||e.target.tagName==="INPUT"||e.target.tagName==="SELECT")return;
if(e.key==="Escape")cancelDraw();
if(e.key==="ArrowRight"&&viewMode==="frames"){curFP=Math.min(NF-1,curFP+1);updFrame();}
if(e.key==="ArrowLeft"&&viewMode==="frames"){curFP=Math.max(0,curFP-1);updFrame();}});

// ═══ SAVE OUTPUT ═══
function saveOutput(){
var allTids={};
for(var fp=0;fp<NF;fp++){var fa=allFA[fp]||[];
for(var i=0;i<fa.length;i++)if(fa[i].trackingId)allTids[fa[i].trackingId]=fa[i].label;}
var metaSnapshot={};
for(var tid in allTids){if(deletedTids[tid])continue;
metaSnapshot[tid]={};for(var fp=0;fp<NF;fp++){
metaSnapshot[tid]["frame_"+String(fp).padStart(2,"0")]=getEffectiveMeta(tid,fp);}}
var payload={instance_id:iv||"unknown",verdict:verdict,
reject_reasons:rejectReasons,reject_text:rejectText,
num_cameras:ACTUAL_NC,camera_ids:CAM_NAMES.slice(0,ACTUAL_NC),total_frames:NF,
deleted_objects:Object.keys(deletedTids),
metadata_corrections:metaOverrides,
corrected_metadata_snapshot:metaSnapshot,
change_log:changeLog,
// Include corrected frame data
corrected_frames:{}};
for(var fp=0;fp<NF;fp++){var fa=allFA[fp]||[];if(!fa.length)continue;
var fk="frame_"+String(fp).padStart(2,"0");
var camOut=[];
for(var ci=0;ci<ACTUAL_NC;ci++){var camAnns=[];
for(var i=0;i<fa.length;i++){if(fa[i].ci===ci&&!deletedTids[fa[i].trackingId]){
camAnns.push({label:fa[i].label,label_name:fa[i].labelName,color:fa[i].color,
tool:fa[i].tool,data:fa[i].data,tracking_id:fa[i].trackingId,
metadata:getEffectiveMeta(fa[i].trackingId,fp)});}}
camOut.push({camera_id:CAM_NAMES[ci],annotations:camAnns});}
payload.corrected_frames[fk]={frame_index:fp,cameras:camOut};}
payload.submitted_at=new Date().toISOString();
document.getElementById("annotationData").value=JSON.stringify(payload);}

buildCamTabs();buildFNav();loadVid();buildObjPanel();saveOutput();
}catch(err){console.error("ERR:",err);}
"""
JS += '\n</script>'

print(f"  JS: {len(JS):,} chars")

# ── COMBINE + UPLOAD ──
full_template = CSS + HTML + JS
full_template = full_template.encode("utf-8", errors="replace").decode("utf-8")

# Minify
full_template = re.sub(r'/\*.*?\*/', '', full_template, flags=re.DOTALL)
full_template = re.sub(r'[ \t]{2,}', ' ', full_template)
tlines = [l.strip() for l in full_template.splitlines()]
full_template = '\n'.join(l for l in tlines if l)

sz = len(full_template)
print(f"\n  Final size: {sz:,} bytes ({sz/1024:.1f} KB)")
if sz > 100000:
    raise RuntimeError(f"Too large: {sz:,} (limit 100K)")
print(f"  Under 100K limit")

template_key = f"{VERIFY_PREFIX}/template.html"
s3.put_object(Bucket=BUCKET, Key=template_key,
              Body=full_template.encode("utf-8"), ContentType="text/html")
print(f"\n  Uploaded: s3://{BUCKET}/{template_key}")

os.makedirs("template", exist_ok=True)
with open("template/verification_template.html", "w", encoding="utf-8") as f:
    f.write(full_template)
print(f"  Local: template/verification_template.html")

# Verify
checks = {
    "deleteObj":       "deleteObj" in full_template,
    "relabelObj":      "relabelObj" in full_template,
    "startDraw":       "startDraw" in full_template,
    "finishDraw":      "finishDraw" in full_template,
    "setMetaVal":      "setMetaVal" in full_template,
    "corrected_frames":"corrected_frames" in full_template,
    "change_log":      "change_log" in full_template,
    "deleted_objects":  "deleted_objects" in full_template,
    "crowd-form":      "<crowd-form>" in full_template,
    "no blobCache":    "blobCache" not in full_template,
    "no fetch(":       "fetch(" not in full_template,
}
all_ok = all(checks.values())
print(f"\n  Checks:")
for name, passed in checks.items():
    print(f"    {'OK' if passed else 'FAIL'} {name}")
print(f"\n  Overall: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
print(f"\n{'='*70}")
print(f" DONE — Run Cell 9B next for manifest generation")
print(f"{'='*70}")
