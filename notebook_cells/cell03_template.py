# ============================================================
# CELL 3A — TEMPLATE CSS (NO METADATA, NO BLOBS)
# ============================================================
# Stage 1: Annotation only — labels + tracking IDs + shapes
# No metadata dropdowns, no blob preloading
# Updated: 14 labels (added tape, miscellaneous_items, debris)
# ============================================================
import json as _json, os

NF = NUM_FRAMES
NC = MAX_CAMERAS

LABELS_JS = _json.dumps({k: {"name": v["name"], "color": v["color"]} for k, v in LABELS.items()})

TEMPLATE_CSS = """<style>
*{box-sizing:border-box}
body{font-family:'Segoe UI',Arial,sans-serif;background:#F0F2F5;color:#333;margin:0}
#mc{display:flex;flex-direction:column;align-items:center;padding:16px;max-width:1800px;margin:0 auto}
#toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;width:100%;padding:10px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.tb-grp{display:flex;align-items:center;gap:6px;padding:4px 10px;border-radius:6px;background:#F7F8FA;border:1px solid #E8ECF0}
.tb-lbl{font-size:11px;font-weight:700;color:#777;text-transform:uppercase;letter-spacing:.5px}
.tb-sld{width:100px;cursor:pointer}
.tb-v{font-size:12px;font-weight:600;color:#333;min-width:36px;text-align:center}
#frame-nav{display:flex;flex-wrap:wrap;gap:5px;align-items:center;justify-content:center;width:100%;padding:10px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.fn-btn{width:40px;height:34px;border:2px solid #D0D7E2;border-radius:6px;background:#FAFAFA;color:#555;font-weight:700;cursor:pointer;font-size:13px;transition:all .15s}
.fn-btn:hover{background:#E3F2FD;border-color:#42A5F5}
.fn-btn.act{background:#FF7043;color:#FFF;border-color:#FF7043}
.fn-btn.done{border-color:#66BB6A;background:#E8F5E9;color:#2E7D32}
.fn-btn.done.act{background:#FF7043;color:#FFF;border-color:#FF7043}
.fn-btn.f0-req{border-color:#EF5350;animation:pulse0 1.5s infinite}
@keyframes pulse0{0%,100%{box-shadow:0 0 0 0 rgba(239,83,80,.4)}50%{box-shadow:0 0 0 6px rgba(239,83,80,0)}}
#btnPrev,#btnNext{padding:6px 16px;height:34px;border:2px solid #42A5F5;border-radius:6px;background:#42A5F5;color:#FFF;font-weight:700;cursor:pointer;font-size:13px}
#btnPrev:hover,#btnNext:hover{background:#1E88E5}
#btnPrev:disabled,#btnNext:disabled{opacity:.4;cursor:not-allowed}
.fn-info{font-size:12px;color:#777;font-weight:600;margin:0 6px}
#cam-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center;width:100%;padding:8px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.cam-tab{padding:6px 16px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;border:2px solid #D0D7E2;background:#FAFAFA;color:#666;transition:all .2s;user-select:none}
.cam-tab:hover{border-color:#999}
.cam-tab.act{background:#4A90D9;color:#FFF;border-color:#4A90D9}
#cam-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;width:100%}
.cam-panel{background:#222;border:2px solid #555;border-radius:8px;overflow:hidden;flex:1 1 420px;max-width:600px;min-width:340px;position:relative;transition:border .2s}
.cam-panel.act-cam{border-color:#4A90D9;border-width:3px}
.cam-panel.solo{max-width:1200px;flex:1 1 100%}
.cam-panel.solo .zc{max-height:750px}
.cam-panel.blurry-cam{border-color:#FF9800!important;border-style:dashed!important}
.cam-panel.rotated-cam{border-color:#AB47BC!important}
.cam-hdr{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;background:#333;color:#FFF;font-size:12px;font-weight:600;cursor:pointer;user-select:none;flex-wrap:wrap;gap:4px}
.cam-hdr:hover{background:#444}
.cam-hdr .cid{font-size:13px}
.cam-hdr-left{display:flex;align-items:center;gap:6px}
.cam-hdr-right{display:flex;align-items:center;gap:8px}
.blur-cb-wrap{display:flex;align-items:center;gap:4px;font-size:11px;color:#FF9800;cursor:pointer}
.blur-cb-wrap input{cursor:pointer;accent-color:#FF9800}
.rot-btn-wrap{display:flex;align-items:center;gap:4px;font-size:11px;color:#CE93D8;cursor:pointer;user-select:none}
.rot-btn{background:#4A235A;border:1px solid #AB47BC;color:#CE93D8;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;cursor:pointer;transition:all .15s}
.rot-btn:hover{background:#6A1B9A;color:#FFF;border-color:#CE93D8}
.rot-badge{display:inline-block;background:#6A1B9A;color:#E1BEE7;font-size:9px;padding:1px 5px;border-radius:8px;margin-left:3px;font-weight:700}
.zc{max-height:550px;overflow:auto;position:relative;cursor:grab;background:#111}
.zc.panning{cursor:grabbing}
.zc.drawing{cursor:crosshair}
.zc.vtxedit{cursor:pointer}
.zc::-webkit-scrollbar{width:8px;height:8px}
.zc::-webkit-scrollbar-track{background:#333}
.zc::-webkit-scrollbar-thumb{background:#666;border-radius:4px}
.iw{position:relative;display:inline-block;transform-origin:0 0}
.iw img{display:block}
.iw canvas{position:absolute;top:0;left:0}
.zoom-badge{display:inline-block;background:#555;color:#FFF;font-size:10px;padding:1px 6px;border-radius:8px;margin-left:6px}
#label-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center;width:100%;padding:10px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.label-tab{display:flex;align-items:center;gap:5px;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;border:3px solid #D0D7E2;background:#FAFAFA;color:#555;transition:all .2s;user-select:none}
.label-tab:hover{border-color:#999;background:#F0F0F0}
.label-tab.act{color:#FFF;transform:scale(1.03);box-shadow:0 2px 10px rgba(0,0,0,.15)}
.label-dot{width:12px;height:12px;border-radius:50%;border:2px solid rgba(0,0,0,.2);flex-shrink:0}
.label-hint{font-size:11px;color:#999;font-style:italic}
#tracking-bar{display:none;flex-wrap:wrap;gap:6px;align-items:center;justify-content:center;width:100%;padding:10px 16px;background:#FFF8E1;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06);border:2px solid #FFE0B2}
#tracking-bar.show{display:flex}
.trk-btn{display:flex;align-items:center;gap:5px;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;border:2px solid #D0D7E2;background:#FAFAFA;color:#555;transition:all .2s;user-select:none}
.trk-btn:hover{border-color:#FF9800;background:#FFF3E0}
.trk-btn.act{background:#FF9800;color:#FFF;border-color:#FF9800;box-shadow:0 2px 8px rgba(255,152,0,.3)}
.trk-btn .trk-num{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;font-size:11px;font-weight:800;margin-right:2px}
.trk-new-btn{padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;border:2px dashed #66BB6A;background:#E8F5E9;color:#2E7D32;transition:all .2s}
.trk-new-btn:hover{background:#C8E6C9;border-color:#43A047}
.trk-hint{font-size:11px;color:#E65100;font-weight:600}
.trk-usage{font-size:9px;color:#999;margin-left:2px}
.ann-tid{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:800;background:#FF9800;color:#FFF;margin-left:4px}
.ann-tid-cell{font-weight:700;color:#E65100;white-space:nowrap}
#tool-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;width:100%;padding:10px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06)}
.tool-btn{display:flex;align-items:center;gap:5px;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;border:2px solid #D0D7E2;background:#FAFAFA;color:#555;transition:all .2s;user-select:none}
.tool-btn:hover{border-color:#999;background:#F0F0F0}
.tool-btn.act{background:#4A90D9;color:#FFF;border-color:#4A90D9;box-shadow:0 2px 8px rgba(74,144,217,.3)}
.tool-btn:disabled{opacity:.4;cursor:not-allowed}
.tool-btn.undo-btn{background:#FFF;color:#1565C0;border-color:#90CAF9}
.tool-btn.undo-btn:hover:not(:disabled){background:#E3F2FD}
.tool-btn.undo-btn:disabled{opacity:.35}
.tool-btn.redo-btn{background:#FFF;color:#2E7D32;border-color:#A5D6A7}
.tool-btn.redo-btn:hover:not(:disabled){background:#E8F5E9}
.tool-btn.redo-btn:disabled{opacity:.35}
.tool-btn.vtx-act{background:#FF8F00!important;color:#FFF!important;border-color:#FF8F00!important}
#draw-hint{width:100%;padding:6px 16px;text-align:center;font-size:12px;color:#777;background:#FFFDE7;border:1px solid #FFF9C4;border-radius:6px;margin-bottom:8px;display:none}
#draw-hint.show{display:block}
#ann-status{width:100%;padding:8px 16px;border-radius:6px;font-weight:600;text-align:center;font-size:13px;margin-top:10px}
.ann-empty{background:#E8F5E9;color:#2E7D32;border:1px solid #A5D6A7}
.ann-has{background:#E3F2FD;color:#1565C0;border:1px solid #90CAF9}
#ann-list{width:100%;margin-top:8px;max-height:420px;overflow-y:auto;font-size:12px}
#ann-list table{width:100%;border-collapse:collapse}
#ann-list th{background:#EEF2F7;padding:5px 8px;text-align:left;color:#555;font-weight:600;border-bottom:2px solid #D0D7E2;font-size:11px;position:sticky;top:0;z-index:1}
#ann-list td{padding:4px 8px;border-bottom:1px solid #E8ECF0;color:#444;vertical-align:top}
#ann-list tr:hover{background:#F5F8FC}
#ann-list tr.sel-ann{background:#FFF3E0!important}
.ann-del{cursor:pointer;color:#C62828;font-weight:700;font-size:14px;padding:0 4px;border:none;background:none}
.ann-del:hover{color:#F44336}
.ann-color-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px;vertical-align:middle}
#track-legend{width:100%;margin-top:8px;padding:8px 16px;background:#FFF8E1;border:1px solid #FFE082;border-radius:8px;font-size:12px;display:none}
#track-legend.show{display:block}
#track-legend h4{margin:0 0 6px;color:#E65100;font-size:13px}
.tl-row{display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid #FFF3E0}
.tl-tid{font-weight:800;min-width:140px}
.tl-cam-badge{display:inline-block;padding:1px 6px;border-radius:8px;font-size:9px;font-weight:700;margin:0 2px;color:#FFF}
.subw{display:flex;justify-content:center;width:100%;margin-top:14px}
</style>"""

print("Cell 3A - CSS ready (no metadata styles)")


# ============================================================
# CELL 3B — TEMPLATE HTML (NO METADATA)
# ============================================================

url_spans = ""
for c in range(NC):
    for f in range(NF):
        key = f"c{c}_f{f:02d}"
        url_spans += f'<span class="furl" data-c="{c}" data-f="{f}" style="display:none">{{{{ task.input.{key} | grant_read_access }}}}</span>\n'

label_buttons = ""
for k, v in LABELS.items():
    label_buttons += f'<div class="label-tab" data-label="{k}" data-color="{v["color"]}"><span class="label-dot" style="background:{v["color"]}"></span>{v["name"]}</div>\n'

TEMPLATE_HTML = (
"""<script src="https://assets.crowd.aws/crowd-html-elements.js"></script>
<crowd-form><div id="mc">"""
+ url_spans +
"""<span id="m-camids" style="display:none">{{ task.input.camera_ids }}</span>
<div id="evt-info" style="width:100%;padding:8px 16px;background:#FFF;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 6px rgba(0,0,0,.06);font-size:13px;color:#555;text-align:center">
<span style="font-weight:700;color:#4A90D9">Source:</span>
<span id="evt-name">{{ task.input.instance_id }}</span>
<span style="margin-left:20px;font-weight:700;color:#4A90D9">Frame:</span>
<span id="evt-frame">0</span>
<span style="margin-left:20px;font-weight:700;color:#E65100" id="f0-warn">&#9888; Frame 0 REQUIRED</span>
</div>
<div id="frame-nav">
<button type="button" id="btnPrev">&#9664; Prev</button>
<span id="frameBtns"></span>
<button type="button" id="btnNext">Next &#9654;</button>
<span class="fn-info" id="fn-info">0/""" + str(NF) + """ annotated</span>
</div>
<div id="label-bar">
<span class="tb-lbl" style="margin-right:4px">1. Label:</span>"""
+ label_buttons +
"""<span class="label-hint" id="label-hint">&#8592; Pick a label</span>
</div>
<div id="tracking-bar">
<span class="tb-lbl" style="margin-right:6px">2. Track ID:</span>
<span id="track-btns"></span>
<button type="button" class="trk-new-btn" id="trk-new-btn">+ New Object</button>
<span class="trk-hint" id="track-hint">&#8592; Select which object instance</span>
</div>
<div id="tool-bar">
<span class="tb-lbl" style="margin-right:6px">3. Tool:</span>
<button type="button" class="tool-btn" data-tool="bbox" disabled>&#11036; Bounding Box</button>
<button type="button" class="tool-btn" data-tool="polygon" disabled>&#9670; Polygon</button>
<button type="button" class="tool-btn" data-tool="vtxedit">&#9995; Edit Vertices</button>
<span style="margin-left:12px;border-left:2px solid #E0E0E0;height:28px"></span>
<button type="button" class="tool-btn undo-btn" id="undo-btn" disabled>&#8617; Undo</button>
<button type="button" class="tool-btn redo-btn" id="redo-btn" disabled>&#8618; Redo</button>
</div>
<div id="draw-hint"></div>
<div id="toolbar">
<div class="tb-grp"><span class="tb-lbl">Zoom</span>
<input type="range" id="zsl" name="zsl_ignore" class="tb-sld" min="0.5" max="10" step="0.25" value="1"/>
<span class="tb-v" id="zvl">1.0x</span></div>
<div class="tb-grp"><span class="tb-lbl">Brightness</span>
<input type="range" id="bsl" name="bsl_ignore" class="tb-sld" min="50" max="300" step="5" value="100"/>
<span class="tb-v" id="bvl">100%</span></div>
</div>
<div id="cam-bar"></div>
<div id="cam-grid"></div>
<div id="track-legend"><h4>&#128279; Tracking Summary (this frame)</h4><div id="tl-body"></div></div>
<div id="ann-status" class="ann-empty">No annotations yet</div>
<div id="ann-list"></div>
<input type="hidden" name="annotationData" id="annotationData" value="{}"/>
<div class="subw"><crowd-button form-action="submit" id="submit-btn">Submit</crowd-button></div>
</div></crowd-form>""")

print("Cell 3B - HTML ready (no metadata panel, no metadata changelog)")


# ============================================================
# CELL 3C — JAVASCRIPT PART 1 (NO METADATA, NO BLOBS)
# ============================================================

TEMPLATE_JS_1 = (
"""<script>
try{
var NF=""" + str(NF) + """,NC=""" + str(NC) + """;
var CAM_NAMES=[];
try{CAM_NAMES=JSON.parse(document.getElementById("m-camids").textContent.trim())}catch(e){for(var i=0;i<NC;i++)CAM_NAMES.push("Camera_"+i)}
if(CAM_NAMES.length<NC){for(var i=CAM_NAMES.length;i<NC;i++)CAM_NAMES.push("Camera_"+i)}
var LABELS=""" + LABELS_JS + """;
var CC=["#4A90D9","#E67E22","#27AE60","#8E44AD","#C0392B"];
var BRIGHT_COLORS=["#00E5FF","#76FF03","#FFEA00","#00E676","#1DE9B6","#40C4FF","#FFD600"];
function isBright(c){return BRIGHT_COLORS.indexOf(c)>=0}

var frameUrls=[];
for(var c=0;c<NC;c++){frameUrls.push([]);for(var ff=0;ff<NF;ff++)frameUrls[c].push("")}
document.querySelectorAll(".furl").forEach(function(sp){
var c=parseInt(sp.dataset.c),ff=parseInt(sp.dataset.f),u=sp.textContent.trim();
if(c<NC&&ff<NF)frameUrls[c][ff]=u;
});

function r10(v){return Math.round(v*10)/10}
function cln(d){return JSON.parse(JSON.stringify(d))}
function dst(a,b,c,d){return Math.sqrt((a-c)*(a-c)+(b-d)*(b-d))}

var camRotation=[];
for(var i=0;i<NC;i++)camRotation.push(0);

function rotateCam(ci){camRotation[ci]=(camRotation[ci]+90)%360;applyRotation(ci);updRotBadge(ci);updRotPanel(ci);}

function applyRotation(ci){
var s=CS[ci];if(!s||!s.img||!s.loaded)return;
var deg=camRotation[ci],z=s.zoom,oW=s.iW,oH=s.iH;
var swapped=(deg===90||deg===270);
var dW=swapped?oH*z:oW*z,dH=swapped?oW*z:oH*z;
s.img.style.transformOrigin="top left";
if(deg===0){s.img.style.transform="";s.img.style.marginLeft="0px";s.img.style.marginTop="0px"}
else if(deg===90){s.img.style.transform="rotate(90deg) translateY(-100%)";s.img.style.marginLeft=oH*z+"px";s.img.style.marginTop="0px"}
else if(deg===180){s.img.style.transform="rotate(180deg)";s.img.style.marginLeft=oW*z+"px";s.img.style.marginTop=oH*z+"px"}
else if(deg===270){s.img.style.transform="rotate(270deg) translateX(-100%)";s.img.style.marginLeft="0px";s.img.style.marginTop=oW*z+"px"}
s.cv.width=dW;s.cv.height=dH;s.cv.style.width=dW+"px";s.cv.style.height=dH+"px";
s.iwrap.style.width=dW+"px";s.iwrap.style.height=dH+"px";render(ci);
}

function updRotBadge(ci){document.querySelectorAll(".rot-badge[data-ci='"+ci+"']").forEach(function(b){b.textContent=camRotation[ci]+"\\u00B0";b.style.display=camRotation[ci]===0?"none":"inline-block";});}
function updRotPanel(ci){var s=CS[ci];if(!s||!s.panel)return;if(camRotation[ci]!==0)s.panel.classList.add("rotated-cam");else s.panel.classList.remove("rotated-cam");}

function canvasToImage(ci,cx2,cy2){
var s=CS[ci],z=s.zoom,deg=camRotation[ci],iW=s.iW,iH=s.iH;
var ix=cx2/z,iy=cy2/z;
if(deg===0)return{x:ix,y:iy};if(deg===90)return{x:iy,y:iW-ix};
if(deg===180)return{x:iW-ix,y:iH-iy};if(deg===270)return{x:iH-iy,y:ix};
return{x:ix,y:iy};
}

var curTrackId="";
function scanTrackIds(label){
var idSet={};
for(var fp=0;fp<NF;fp++){var fa=(fp===curFP)?anns:(allFA[fp]||[]);
for(var i=0;i<fa.length;i++){if(fa[i].label===label&&fa[i].trackingId){
var tid=fa[i].trackingId;if(!idSet[tid])idSet[tid]={frames:{},cams:{}};
idSet[tid].frames[fp]=true;idSet[tid].cams[fa[i].ci]=true;}}}return idSet;
}

function nextTrkNum(label){var ids=scanTrackIds(label),maxN=0;for(var tid in ids){var parts=tid.split("#");if(parts.length===2){var n=parseInt(parts[1]);if(n>maxN)maxN=n}}return maxN+1;}
function trkDisplay(tid){if(!tid)return"\\u2014";var parts=tid.split("#");if(parts.length===2){var lObj=LABELS[parts[0]];return(lObj?lObj.name:parts[0])+" #"+parts[1]}return tid;}
function trkShort(tid){if(!tid)return"";var parts=tid.split("#");return parts.length===2?" #"+parts[1]:""}

function buildTrackBar(){
var tb=document.getElementById("tracking-bar"),bc=document.getElementById("track-btns"),hint=document.getElementById("track-hint");
if(!curLabel){tb.classList.remove("show");return}
tb.classList.add("show");bc.innerHTML="";
var ids=scanTrackIds(curLabel);
var sorted=Object.keys(ids).sort(function(a,b){return(parseInt(a.split("#")[1])||0)-(parseInt(b.split("#")[1])||0)});
hint.textContent=sorted.length===0?"No existing "+LABELS[curLabel].name+" \\u2014 click '+ New Object'":sorted.length+" existing "+LABELS[curLabel].name+" object(s)";
for(var si=0;si<sorted.length;si++){(function(tid,info){
var btn=document.createElement("div");btn.className="trk-btn"+(curTrackId===tid?" act":"");
var num=tid.split("#")[1]||"?";var fC=Object.keys(info.frames).length,cC=Object.keys(info.cams).length;
btn.innerHTML='<span class="trk-num" style="background:'+curColor+';color:'+(isBright(curColor)?"#000":"#FFF")+'">'+num+'</span>'+LABELS[curLabel].name+' #'+num+'<span class="trk-usage">('+fC+'f/'+cC+'c)</span>';
btn.addEventListener("click",function(){curTrackId=tid;buildTrackBar();
document.querySelectorAll(".tool-btn[data-tool='bbox'],.tool-btn[data-tool='polygon']").forEach(function(b){b.disabled=false});updHint();updCurs();});
bc.appendChild(btn);})(sorted[si],ids[sorted[si]])}
document.getElementById("trk-new-btn").onclick=function(){var nn=nextTrkNum(curLabel);curTrackId=curLabel+"#"+nn;buildTrackBar();
document.querySelectorAll(".tool-btn[data-tool='bbox'],.tool-btn[data-tool='polygon']").forEach(function(b){b.disabled=false});updHint();updCurs();};
}

function buildTrackLegend(){
var el=document.getElementById("track-legend"),body=document.getElementById("tl-body");
if(!anns.length){el.classList.remove("show");return}
var groups={};for(var i=0;i<anns.length;i++){var tid=anns[i].trackingId||"untracked";if(!groups[tid])groups[tid]={color:anns[i].color,cams:{}};groups[tid].cams[anns[i].ci]=true;}
var keys=Object.keys(groups);if(!keys.length){el.classList.remove("show");return}
el.classList.add("show");var h="";
for(var k=0;k<keys.length;k++){var tid=keys[k],g=groups[tid];
h+='<div class="tl-row"><span class="tl-tid" style="color:'+g.color+'">'+trkDisplay(tid)+'</span><span>';
for(var ci2=0;ci2<NC;ci2++){var present=g.cams[ci2]===true;h+='<span class="tl-cam-badge" style="background:'+(present?CC[ci2%CC.length]:"#CCC")+'">C'+ci2+(present?" \\u2713":" \\u2717")+'</span>';}
h+='</span></div>';}body.innerHTML=h;
}
""")

print("Cell 3C - JS Part 1 ready (no metadata engine, no blobs)")


# ============================================================
# CELL 3D — JAVASCRIPT PART 2 (Drawing + Camera + Submit — NO METADATA)
# ============================================================

TEMPLATE_JS_2 = """
var CS=[];for(var ci=0;ci<NC;ci++)CS.push({id:CAM_NAMES[ci],iW:0,iH:0,blurry:false,loaded:false,panel:null,img:null,cv:null,cx:null,zc:null,iwrap:null,zoom:1});
var allFA={},allUndo={},allRedo={};
var anns=[],undoSt=[],redoSt=[];
var curFP=0,curLabel="",curColor="",curTool="",aCam=0,viewM="all",bright=100,submitting=false,selAnn=-1;
var DS={active:false,ci:-1,sx:0,sy:0,cx:0,cy:0,polyPts:[],preview:false};
var VD={active:false,ai:-1,pi:-1,orig:null,ci:-1,saved:false};
var vertexUndoStack=[],vertexRedoStack=[];

function saveVertexState(ai,desc){if(ai>=0&&ai<anns.length&&anns[ai].tool==="polygon"){vertexUndoStack.push({annotationIndex:ai,oldVertexData:cln(anns[ai].data),description:desc});vertexRedoStack=[];if(vertexUndoStack.length>50)vertexUndoStack.shift();}}
function undoVertexMovement(){if(!vertexUndoStack.length)return false;var last=vertexUndoStack.pop();if(last.annotationIndex>=0&&last.annotationIndex<anns.length){vertexRedoStack.push({annotationIndex:last.annotationIndex,oldVertexData:cln(anns[last.annotationIndex].data)});anns[last.annotationIndex].data=cln(last.oldVertexData);render(anns[last.annotationIndex].ci);updAL();return true;}return false;}

function buildFN(){var c=document.getElementById("frameBtns");c.innerHTML="";for(var i=0;i<NF;i++){var b=document.createElement("button");b.type="button";b.className="fn-btn";b.textContent=i;b.dataset.fp=i;b.onclick=(function(fp){return function(){navTo(fp)}})(i);c.appendChild(b);}}
function saveFrame(){allFA[curFP]=cln(anns);allUndo[curFP]=cln(undoSt);allRedo[curFP]=cln(redoSt)}
function loadFrame(fp){anns=allFA[fp]?cln(allFA[fp]):[];undoSt=allUndo[fp]?cln(allUndo[fp]):[];redoSt=allRedo[fp]?cln(allRedo[fp]):[]}

function navTo(fp){if(fp<0||fp>=NF)return;cancelDraw();saveFrame();curFP=fp;loadFrame(fp);selAnn=-1;vertexUndoStack=[];vertexRedoStack=[];
document.getElementById("evt-frame").textContent=fp;
document.getElementById("btnPrev").disabled=(fp===0);document.getElementById("btnNext").disabled=(fp===NF-1);
for(var c=0;c<NC;c++){var s=CS[c];if(!s.img)continue;s.loaded=false;
s.img.onload=(function(ci2){return function(){CS[ci2].loaded=true;CS[ci2].iW=this.naturalWidth;CS[ci2].iH=this.naturalHeight;applyCZ(ci2);applyRotation(ci2);}})(c);
s.img.onerror=(function(ci2){return function(){}})(c);
s.img.src=frameUrls[c][fp]||"";}
document.querySelectorAll(".fn-btn").forEach(function(b){b.classList.toggle("act",parseInt(b.dataset.fp)===fp)});
updAS();updAL();updUR();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();}

function updFNBtns(){document.querySelectorAll(".fn-btn").forEach(function(b){var fp=parseInt(b.dataset.fp),hasAnns=allFA[fp]&&allFA[fp].length>0;b.classList.toggle("done",hasAnns);if(fp===0&&!hasAnns)b.classList.add("f0-req");else b.classList.remove("f0-req");});}
function updFNInfo(){var cnt=0;for(var fp=0;fp<NF;fp++)if(allFA[fp]&&allFA[fp].length>0)cnt++;document.getElementById("fn-info").textContent=cnt+"/"+NF+" annotated";}
function updF0Warn(){var ok=allFA[0]&&allFA[0].length>0;var el=document.getElementById("f0-warn");if(ok){el.textContent="\\u2714 Frame 0 done";el.style.color="#2E7D32"}else{el.textContent="\\u26A0 Frame 0 REQUIRED";el.style.color="#E65100"}}

function getZm(c){return CS[c]?CS[c].zoom:1}
function syncZS(){var z=getZm(aCam);zsl.value=z;zvl.textContent=z.toFixed(2)+"x"}
function applyCZ(c){var s=CS[c];if(!s.loaded)return;var z=s.zoom,deg=camRotation[c],swapped=(deg===90||deg===270);var dW=swapped?s.iH*z:s.iW*z,dH=swapped?s.iW*z:s.iH*z;s.img.style.width=s.iW*z+"px";s.img.style.height=s.iH*z+"px";s.cv.width=dW;s.cv.height=dH;s.cv.style.width=dW+"px";s.cv.style.height=dH+"px";s.iwrap.style.width=dW+"px";s.iwrap.style.height=dH+"px";s.img.style.filter="brightness("+bright+"%)";render(c);}
function updZB(){document.querySelectorAll(".zoom-badge").forEach(function(b){var c2=parseInt(b.dataset.ci);if(CS[c2])b.textContent=CS[c2].zoom.toFixed(1)+"x";});}

var zsl=document.getElementById("zsl"),zvl=document.getElementById("zvl"),bsl=document.getElementById("bsl"),bvl=document.getElementById("bvl"),camBar=document.getElementById("cam-bar"),camGrid=document.getElementById("cam-grid"),undoBtn=document.getElementById("undo-btn"),redoBtn=document.getElementById("redo-btn");
zsl.addEventListener("input",function(){var s=CS[aCam];if(!s)return;var oZ=s.zoom;s.zoom=parseFloat(this.value);zvl.textContent=s.zoom.toFixed(2)+"x";if(s.loaded&&s.zc){var a2=(s.zc.scrollLeft+s.zc.clientWidth/2)/oZ,b2=(s.zc.scrollTop+s.zc.clientHeight/2)/oZ;applyCZ(aCam);applyRotation(aCam);s.zc.scrollLeft=a2*s.zoom-s.zc.clientWidth/2;s.zc.scrollTop=b2*s.zoom-s.zc.clientHeight/2;}updZB();});
bsl.addEventListener("input",function(){bright=parseInt(this.value);bvl.textContent=bright+"%";for(var c=0;c<CS.length;c++)if(CS[c].img)CS[c].img.style.filter="brightness("+bright+"%)";});

document.querySelectorAll(".label-tab").forEach(function(tab){tab.addEventListener("click",function(){document.querySelectorAll(".label-tab").forEach(function(t){t.classList.remove("act");t.style.background="";t.style.color="";});this.classList.add("act");curLabel=this.dataset.label;curColor=this.dataset.color;this.style.background=curColor;this.style.color=isBright(curColor)?"#000":"#FFF";document.getElementById("label-hint").textContent="\\u2713 "+LABELS[curLabel].name;curTrackId="";buildTrackBar();document.querySelectorAll(".tool-btn[data-tool='bbox'],.tool-btn[data-tool='polygon']").forEach(function(b){b.disabled=true});updHint();updCurs();});});

var allTB=document.querySelectorAll(".tool-btn[data-tool]");
allTB.forEach(function(btn){btn.addEventListener("click",function(){if(this.disabled)return;var t=this.dataset.tool;if(curTool===t){curTool="";this.classList.remove("act","vtx-act")}else{allTB.forEach(function(b){b.classList.remove("act","vtx-act")});curTool=t;if(t==="vtxedit")this.classList.add("vtx-act");else this.classList.add("act");}cancelDraw();updCurs();updHint();});});

function drawReady(){return curLabel!==""&&curTrackId!==""&&(curTool==="bbox"||curTool==="polygon")}
function updCurs(){for(var c=0;c<CS.length;c++){if(!CS[c].zc)continue;var cl=CS[c].zc.classList;cl.remove("drawing","vtxedit");if(curTool==="vtxedit")cl.add("vtxedit");else if(drawReady())cl.add("drawing");}}
function updHint(){var h=document.getElementById("draw-hint");if(curTool==="vtxedit"){h.innerHTML="\\u270B <b>Edit Vertices:</b> Drag white circles. Ctrl+Z undoes.";h.classList.add("show");return}if(curTool==="polygon"){h.innerHTML="&#9670; <b>Polygon:</b> Click points, double-click to finish.";h.classList.add("show");return}if(!curLabel){h.textContent="Step 1: Select a label.";h.classList.add("show");return}if(!curTrackId){h.innerHTML="\\u2705 Label: <b>"+LABELS[curLabel].name+"</b> \\u2014 Step 2: Pick or create a Track ID.";h.classList.add("show");return}if(!curTool){h.innerHTML="\\u2705 <b>"+LABELS[curLabel].name+"</b> | <b style='color:#E65100'>"+trkDisplay(curTrackId)+"</b> \\u2014 Step 3: Pick a tool.";h.classList.add("show");return}var tn={bbox:"Bounding Box",polygon:"Polygon"}[curTool]||"";var ins={bbox:"Click+drag on ANY camera.",polygon:"Click points, double-click to close (min 3)."}[curTool]||"";h.innerHTML="<span style='color:"+curColor+";font-weight:700'>\\u25CF "+LABELS[curLabel].name+"</span> <span class='ann-tid'>"+trkShort(curTrackId)+"</span> \\u2014 <b>"+tn+"</b>: "+ins;h.classList.add("show");}
function cancelDraw(){if(DS.active||DS.polyPts.length>0){DS.active=false;DS.ci=-1;DS.polyPts=[];DS.preview=false;for(var c=0;c<CS.length;c++)render(c);}}

document.getElementById("btnPrev").addEventListener("click",function(){navTo(curFP-1)});
document.getElementById("btnNext").addEventListener("click",function(){navTo(curFP+1)});

function hitVtx(ci,ix,iy){var rad=16/CS[ci].zoom,best=null,bestD=rad;for(var i=anns.length-1;i>=0;i--){var a=anns[i];if(a.ci!==ci)continue;if(a.tool==="polygon"){for(var j=0;j<a.data.length;j++){var dd=dst(ix,iy,a.data[j].x,a.data[j].y);if(dd<bestD){bestD=dd;best={ai:i,pi:j}}}}if(a.tool==="bbox"){var d=a.data;var cs2=[{x:d.x,y:d.y},{x:d.x+d.w,y:d.y},{x:d.x+d.w,y:d.y+d.h},{x:d.x,y:d.y+d.h}];for(var j=0;j<4;j++){var dd=dst(ix,iy,cs2[j].x,cs2[j].y);if(dd<bestD){bestD=dd;best={ai:i,pi:j}}}}}return best;}
function moveBBC(orig,pi,nx,ny){var x=orig.x,y=orig.y,x2=orig.x+orig.w,y2=orig.y+orig.h;if(pi===0){x=nx;y=ny}else if(pi===1){x2=nx;y=ny}else if(pi===2){x2=nx;y2=ny}else if(pi===3){x=nx;y2=ny}var fw=Math.abs(x2-x),fh=Math.abs(y2-y);if(fw<3)fw=3;if(fh<3)fh=3;return{x:Math.min(x,x2),y:Math.min(y,y2),w:fw,h:fh};}

function render(ci){var s=CS[ci];if(!s.cx||!s.loaded)return;var z=s.zoom,deg=camRotation[ci];s.cx.clearRect(0,0,s.cv.width,s.cv.height);s.cx.save();var cW=s.cv.width,cH=s.cv.height;if(deg===90){s.cx.translate(cW,0);s.cx.rotate(Math.PI/2)}else if(deg===180){s.cx.translate(cW,cH);s.cx.rotate(Math.PI)}else if(deg===270){s.cx.translate(0,cH);s.cx.rotate(-Math.PI/2)}for(var i=0;i<anns.length;i++)if(anns[i].ci===ci)drawA(s.cx,anns[i],z,1,i===selAnn);if(curTool==="vtxedit"){for(var i=0;i<anns.length;i++){var a=anns[i];if(a.ci!==ci)continue;var isAc=(VD.active&&VD.ai===i);if(a.tool==="polygon"){for(var j=0;j<a.data.length;j++)drawH(s.cx,a.data[j].x*z,a.data[j].y*z,a.color,(isAc&&VD.pi===j));}if(a.tool==="bbox"){var dd=a.data;var cs2=[{x:dd.x,y:dd.y},{x:dd.x+dd.w,y:dd.y},{x:dd.x+dd.w,y:dd.y+dd.h},{x:dd.x,y:dd.y+dd.h}];for(var j=0;j<4;j++)drawH(s.cx,cs2[j].x*z,cs2[j].y*z,a.color,(isAc&&VD.pi===j));}}}if(DS.preview&&DS.ci===ci){if(curTool==="bbox"&&DS.active){s.cx.strokeStyle=curColor;s.cx.lineWidth=2;s.cx.setLineDash([6,3]);s.cx.globalAlpha=.8;var x1=DS.sx*z,y1=DS.sy*z,x2=DS.cx*z,y2=DS.cy*z;s.cx.strokeRect(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1));s.cx.setLineDash([]);s.cx.globalAlpha=1;dLbl(s.cx,LABELS[curLabel].name+trkShort(curTrackId),Math.min(x1,x2),Math.min(y1,y2)-4,curColor);}if(curTool==="polygon"&&DS.polyPts.length>0){s.cx.strokeStyle=curColor;s.cx.lineWidth=2;s.cx.globalAlpha=.8;s.cx.beginPath();s.cx.moveTo(DS.polyPts[0].x*z,DS.polyPts[0].y*z);for(var j=1;j<DS.polyPts.length;j++)s.cx.lineTo(DS.polyPts[j].x*z,DS.polyPts[j].y*z);if(DS.active)s.cx.lineTo(DS.cx*z,DS.cy*z);s.cx.stroke();for(var j=0;j<DS.polyPts.length;j++){s.cx.fillStyle=curColor;s.cx.beginPath();s.cx.arc(DS.polyPts[j].x*z,DS.polyPts[j].y*z,5,0,Math.PI*2);s.cx.fill();}s.cx.globalAlpha=1;dLbl(s.cx,LABELS[curLabel].name+trkShort(curTrackId),DS.polyPts[0].x*z,DS.polyPts[0].y*z-4,curColor);}}s.cx.restore();}

function drawH(cx,x,y,col,active){var r2=active?9:7;cx.fillStyle=active?"#FFD600":"#FFF";cx.strokeStyle=col;cx.lineWidth=active?3:2;cx.beginPath();cx.arc(x,y,r2,0,Math.PI*2);cx.fill();cx.stroke();}
function drawA(cx,a,z,al,hl){cx.globalAlpha=al;var lblTxt=a.labelName+trkShort(a.trackingId);if(a.tool==="bbox"){var d=a.data;cx.strokeStyle=a.color;cx.lineWidth=hl?4:2;cx.setLineDash([]);cx.strokeRect(d.x*z,d.y*z,d.w*z,d.h*z);cx.fillStyle=a.color;cx.globalAlpha=hl?.2:.1;cx.fillRect(d.x*z,d.y*z,d.w*z,d.h*z);cx.globalAlpha=al;dLbl(cx,lblTxt,d.x*z,d.y*z-4,a.color);}if(a.tool==="polygon"){var pts=a.data;if(pts.length<3)return;cx.strokeStyle=a.color;cx.lineWidth=hl?4:2;cx.beginPath();cx.moveTo(pts[0].x*z,pts[0].y*z);for(var j=1;j<pts.length;j++)cx.lineTo(pts[j].x*z,pts[j].y*z);cx.closePath();cx.stroke();cx.fillStyle=a.color;cx.globalAlpha=hl?.25:.15;cx.fill();cx.globalAlpha=al;dLbl(cx,lblTxt,pts[0].x*z,pts[0].y*z-4,a.color);}cx.globalAlpha=1;}
function dLbl(cx,t,x,y,c){cx.font="bold 11px 'Segoe UI',Arial,sans-serif";var tw=cx.measureText(t).width;cx.fillStyle=c;cx.globalAlpha=.85;cx.fillRect(x-2,y-22,tw+8,14);cx.globalAlpha=1;cx.fillStyle=isBright(c)?"#000":"#FFF";cx.fillText(t,x+2,y-11);}

function pushU(a){undoSt.push(a);redoSt=[];updUR()}
function updUR(){var hasPolyPts=(curTool==="polygon"&&DS.polyPts.length>0);var hasVtxUndo=(curTool==="vtxedit"&&vertexUndoStack.length>0);undoBtn.disabled=!undoSt.length&&!hasPolyPts&&!hasVtxUndo;redoBtn.disabled=!redoSt.length;}

function saveA(ci,tool,data){var ann={ci:ci,label:curLabel,color:curColor,labelName:LABELS[curLabel].name,tool:tool,data:data,trackingId:curTrackId};anns.push(ann);pushU({type:"add",ann:cln(ann),idx:anns.length-1});render(ci);updAS();updAL();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();}
function delA(idx){var rm=anns.splice(idx,1)[0];pushU({type:"del",ann:cln(rm),idx:idx});if(selAnn===idx)selAnn=-1;else if(selAnn>idx)selAnn--;render(rm.ci);updAS();updAL();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();}

undoBtn.addEventListener("click",function(){if(curTool==="polygon"&&DS.polyPts.length>0){DS.polyPts.pop();for(var c=0;c<CS.length;c++)if(DS.ci===c)render(c);updUR();return;}if(curTool==="vtxedit"&&vertexUndoStack.length>0){undoVertexMovement();updUR();return}if(!undoSt.length)return;var a=undoSt.pop();if(a.type==="add"){var rm=anns.splice(a.idx,1)[0];redoSt.push({type:"add",ann:cln(rm),idx:a.idx});render(rm.ci)}else if(a.type==="del"){anns.splice(a.idx,0,cln(a.ann));redoSt.push({type:"del",ann:cln(a.ann),idx:a.idx});render(a.ann.ci)}else if(a.type==="vtx"){anns[a.idx].data=cln(a.oldD);redoSt.push({type:"vtx",idx:a.idx,oldD:cln(a.newD),newD:cln(a.oldD)});render(anns[a.idx].ci)}selAnn=-1;updAS();updAL();updUR();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();});
redoBtn.addEventListener("click",function(){if(!redoSt.length)return;var a=redoSt.pop();if(a.type==="add"){anns.splice(a.idx,0,cln(a.ann));undoSt.push({type:"add",ann:cln(a.ann),idx:a.idx});render(a.ann.ci)}else if(a.type==="del"){var rm=anns.splice(a.idx,1)[0];undoSt.push({type:"del",ann:cln(rm),idx:a.idx});render(rm.ci)}else if(a.type==="vtx"){anns[a.idx].data=cln(a.newD);undoSt.push({type:"vtx",idx:a.idx,oldD:cln(a.oldD),newD:cln(a.newD)});render(anns[a.idx].ci)}selAnn=-1;updAS();updAL();updUR();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();});

function updAS(){var el=document.getElementById("ann-status");if(!anns.length){el.className="ann-empty";el.textContent="No annotations on Frame "+curFP}else{el.className="ann-has";el.textContent=anns.length+" annotation(s) on Frame "+curFP}saveFrame();updFNBtns();}

function updAL(){var el=document.getElementById("ann-list");if(!anns.length){el.innerHTML="";return}
var h='<table><tr><th>#</th><th>Cam</th><th>Label</th><th>Track ID</th><th>Tool</th><th>Rotation</th><th>Del</th></tr>';
for(var i=0;i<anns.length;i++){var a=anns[i],rotDeg=camRotation[a.ci]||0;
h+='<tr class="'+(i===selAnn?"sel-ann":"")+'" data-idx="'+i+'">';
h+='<td>'+(i+1)+'</td><td>'+CS[a.ci].id+'</td>';
h+='<td><span class="ann-color-dot" style="background:'+a.color+'"></span>'+a.labelName+'</td>';
h+='<td class="ann-tid-cell"><span class="ann-tid">'+trkShort(a.trackingId)+'</span> '+trkDisplay(a.trackingId)+'</td>';
h+='<td>'+a.tool+'</td>';
h+='<td>'+(rotDeg===0?'<span style="color:#999">0\\u00B0</span>':'<span style="color:#AB47BC;font-weight:700">'+rotDeg+'\\u00B0</span>')+'</td>';
h+='<td><button type="button" class="ann-del" data-idx="'+i+'">\\u2715</button></td></tr>';}
h+='</table>';el.innerHTML=h;
el.querySelectorAll(".ann-del").forEach(function(b){b.addEventListener("click",function(e){e.stopPropagation();delA(parseInt(this.dataset.idx))});});
el.querySelectorAll("tr[data-idx]").forEach(function(r2){r2.addEventListener("click",function(e){if(e.target.tagName==="BUTTON")return;var idx=parseInt(this.dataset.idx);selAnn=(selAnn===idx)?-1:idx;updAL();for(var c=0;c<CS.length;c++)render(c);});});}
"""

print("Cell 3D - JS Part 2 (drawing + annotation list — NO metadata column)")


# ============================================================
# CELL 3D continued — Camera panels + Submit (NO METADATA in payload)
# ============================================================

TEMPLATE_JS_3 = """
function buildCB(){camBar.innerHTML="";if(CS.length<=1){viewM="all";return}
var at=document.createElement("div");at.className="cam-tab"+(viewM==="all"?" act":"");at.textContent="All ("+CS.length+")";at.addEventListener("click",function(){viewM="all";buildCB();layP()});camBar.appendChild(at);
for(var ci=0;ci<CS.length;ci++){(function(idx){var t=document.createElement("div");t.className="cam-tab"+(viewM===idx?" act":"");t.textContent="Cam: "+CS[idx].id;t.style.borderColor=CC[idx%CC.length];if(viewM===idx){t.style.background=CC[idx%CC.length];t.style.color="#FFF"}t.addEventListener("click",function(){viewM=idx;aCam=idx;buildCB();layP();syncZS()});camBar.appendChild(t);})(ci)}}

function buildP(ci){var s=CS[ci];var pnl=document.createElement("div");pnl.className="cam-panel";pnl.dataset.ci=ci;if(s.blurry)pnl.classList.add("blurry-cam");if(camRotation[ci]!==0)pnl.classList.add("rotated-cam");
var hdr=document.createElement("div");hdr.className="cam-hdr";
var leftDiv=document.createElement("div");leftDiv.className="cam-hdr-left";
var ls=document.createElement("span");ls.innerHTML='<span class="cid" style="color:'+CC[ci%CC.length]+'">'+s.id+'</span> <span class="zoom-badge" data-ci="'+ci+'">'+s.zoom.toFixed(1)+'x</span>';
var rs=document.createElement("span");rs.id="res"+ci;rs.style.fontSize="10px";rs.style.color="#AAA";rs.textContent="--";
leftDiv.appendChild(ls);leftDiv.appendChild(rs);
var rightDiv=document.createElement("div");rightDiv.className="cam-hdr-right";
var bw=document.createElement("label");bw.className="blur-cb-wrap";bw.addEventListener("click",function(e){e.stopPropagation()});
var bc=document.createElement("input");bc.type="checkbox";bc.className="blur-cb";bc.checked=s.blurry;bc.name="blur_cam_"+ci+"_ignore";bc.addEventListener("change",(function(c2){return function(){CS[c2].blurry=this.checked;updBl(c2)}})(ci));
var blTxt=document.createElement("span");blTxt.textContent="Blurry";bw.appendChild(bc);bw.appendChild(blTxt);
var rotWrap=document.createElement("div");rotWrap.className="rot-btn-wrap";rotWrap.addEventListener("click",function(e){e.stopPropagation()});
var rotBtn=document.createElement("button");rotBtn.type="button";rotBtn.className="rot-btn";rotBtn.innerHTML="\\u21BB Rotate";
var rotBadge=document.createElement("span");rotBadge.className="rot-badge";rotBadge.dataset.ci=ci;rotBadge.textContent=camRotation[ci]+"\\u00B0";rotBadge.style.display=camRotation[ci]===0?"none":"inline-block";
rotBtn.addEventListener("click",(function(c2){return function(e){e.stopPropagation();rotateCam(c2)}})(ci));
rotWrap.appendChild(rotBtn);rotWrap.appendChild(rotBadge);rightDiv.appendChild(bw);rightDiv.appendChild(rotWrap);
hdr.appendChild(leftDiv);hdr.appendChild(rightDiv);
hdr.addEventListener("click",function(e){if(e.target.tagName==="INPUT"||e.target.tagName==="LABEL"||e.target.tagName==="BUTTON")return;aCam=ci;updHL();syncZS();});
pnl.appendChild(hdr);
var zc=document.createElement("div");zc.className="zc";s.zc=zc;if(curTool==="vtxedit")zc.classList.add("vtxedit");else if(drawReady())zc.classList.add("drawing");
var iw=document.createElement("div");iw.className="iw";s.iwrap=iw;
var img=document.createElement("img");s.img=img;
var cv=document.createElement("canvas");s.cv=cv;s.cx=cv.getContext("2d");
iw.appendChild(img);iw.appendChild(cv);zc.appendChild(iw);pnl.appendChild(zc);s.panel=pnl;

(function(zcE,cvE,cI){var isP=false,px2,py2,sx2,sy2;
function getP(e){var r=cvE.getBoundingClientRect();return canvasToImage(cI,e.clientX-r.left,e.clientY-r.top)}
cvE.style.pointerEvents="auto";
cvE.addEventListener("mousedown",function(e){if(e.button!==0)return;e.preventDefault();e.stopPropagation();
if(curTool==="vtxedit"){var p=getP(e),hit=hitVtx(cI,p.x,p.y);if(hit){aCam=cI;updHL();saveVertexState(hit.ai,"vtx");VD.active=true;VD.ai=hit.ai;VD.pi=hit.pi;VD.ci=cI;VD.orig=cln(anns[hit.ai].data);VD.saved=false;selAnn=hit.ai;updAL();render(cI);}else{selAnn=-1;updAL();for(var c2=0;c2<CS.length;c2++)render(c2)}return;}
if(drawReady()){aCam=cI;updHL();syncZS();var p=getP(e);if(curTool==="bbox"){DS.active=true;DS.ci=cI;DS.sx=p.x;DS.sy=p.y;DS.cx=p.x;DS.cy=p.y;DS.preview=true}else if(curTool==="polygon"){if(DS.ci!==cI||!DS.preview){DS.polyPts=[];DS.ci=cI;DS.preview=true;DS.active=true}DS.polyPts.push({x:p.x,y:p.y});DS.cx=p.x;DS.cy=p.y;render(cI);updUR();}return;}
isP=true;px2=e.clientX;py2=e.clientY;sx2=zcE.scrollLeft;sy2=zcE.scrollTop;zcE.classList.add("panning");});
cvE.addEventListener("mousemove",function(e){if(VD.active&&VD.ci===cI){var p=getP(e),a=anns[VD.ai];if(a.tool==="polygon")a.data[VD.pi]={x:r10(p.x),y:r10(p.y)};else if(a.tool==="bbox"){var nd=moveBBC(VD.orig,VD.pi,p.x,p.y);a.data={x:r10(nd.x),y:r10(nd.y),w:r10(nd.w),h:r10(nd.h)}}render(cI);return;}if(DS.active&&DS.ci===cI){var p=getP(e);DS.cx=p.x;DS.cy=p.y;render(cI);return}if(DS.preview&&DS.ci===cI&&curTool==="polygon"){var p=getP(e);DS.cx=p.x;DS.cy=p.y;render(cI);return}});
document.addEventListener("mousemove",function(e){if(isP){zcE.scrollLeft=sx2-(e.clientX-px2);zcE.scrollTop=sy2-(e.clientY-py2)}});
cvE.addEventListener("mouseup",function(e){if(VD.active&&VD.ci===cI&&!VD.saved){VD.saved=true;VD.active=false;render(cI);updAL();updUR();return}if(DS.active&&DS.ci===cI&&curTool==="bbox"){var p=getP(e);var x1=Math.min(DS.sx,p.x),y1=Math.min(DS.sy,p.y),w=Math.abs(p.x-DS.sx),h=Math.abs(p.y-DS.sy);if(w>3&&h>3)saveA(cI,"bbox",{x:r10(x1),y:r10(y1),w:r10(w),h:r10(h)});DS.active=false;DS.preview=false;render(cI);return;}});
document.addEventListener("mouseup",function(){if(isP){isP=false;zcE.classList.remove("panning")}if(VD.active&&!VD.saved){VD.saved=true;VD.active=false;if(CS[VD.ci])render(VD.ci);updAL();updUR()}});
cvE.addEventListener("dblclick",function(e){if(curTool==="polygon"&&DS.ci===cI&&DS.polyPts.length>=3){e.preventDefault();saveA(cI,"polygon",DS.polyPts.map(function(pt){return{x:r10(pt.x),y:r10(pt.y)}}));DS.active=false;DS.preview=false;DS.polyPts=[];render(cI);updUR();}});
cvE.addEventListener("contextmenu",function(e){e.preventDefault()});zcE.addEventListener("contextmenu",function(e){e.preventDefault()});
zcE.addEventListener("wheel",function(e){if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();var s2=CS[cI],oZ=s2.zoom;s2.zoom=Math.max(0.5,Math.min(10,s2.zoom+(e.deltaY<0?0.25:-0.25)));if(s2.zoom===oZ)return;aCam=cI;var rc=zcE.getBoundingClientRect(),mx=e.clientX-rc.left,my=e.clientY-rc.top;var ix=(zcE.scrollLeft+mx)/oZ,iy=(zcE.scrollTop+my)/oZ;applyCZ(cI);applyRotation(cI);zcE.scrollLeft=ix*s2.zoom-mx;zcE.scrollTop=iy*s2.zoom-my;syncZS();updHL();updZB();},{passive:false});
})(zc,cv,ci);return pnl;}

function updBl(ci){var s=CS[ci];if(!s.panel)return;if(s.blurry)s.panel.classList.add("blurry-cam");else s.panel.classList.remove("blurry-cam");}
function layP(){camGrid.innerHTML="";for(var ci=0;ci<CS.length;ci++){CS[ci].panel=null;CS[ci].img=null;CS[ci].cv=null;CS[ci].cx=null;CS[ci].zc=null;CS[ci].iwrap=null;CS[ci].loaded=false;}for(var ci=0;ci<CS.length;ci++){if(viewM!=="all"&&viewM!==ci)continue;var p=buildP(ci);if(viewM!=="all")p.classList.add("solo");camGrid.appendChild(p);loadI(ci);}updHL();syncZS();}
function updHL(){var ps=camGrid.querySelectorAll(".cam-panel");for(var i=0;i<ps.length;i++){var c2=parseInt(ps[i].dataset.ci);ps[i].classList.toggle("act-cam",c2===aCam);}}
function loadI(ci){var s=CS[ci];if(!s.img)return;var url=frameUrls[ci][curFP]||"";s.img.onload=function(){s.loaded=true;s.iW=s.img.naturalWidth;s.iH=s.img.naturalHeight;var resEl=document.getElementById("res"+ci);if(resEl)resEl.textContent=s.iW+"x"+s.iH;if(!window._zi){window._zi=true;var nV=0;for(var j=0;j<CS.length;j++)if(viewM==="all"||viewM===j)nV++;var aW=camGrid.clientWidth||1200,pC=nV>1?(aW-10*(nV-1))/nV:aW;for(var j=0;j<CS.length;j++)if(CS[j].iW>0&&pC>50&&CS[j].iW>pC)CS[j].zoom=Math.max(0.25,Math.min(1.5,Math.round(pC/CS[j].iW*100)/100));}applyCZ(ci);applyRotation(ci);syncZS();updZB();};s.img.onerror=function(){};s.img.src=url;}

document.addEventListener("keydown",function(e){if(e.target.tagName==="SELECT"||e.target.tagName==="INPUT")return;
if(e.key==="Escape"){cancelDraw();updHint()}
if(e.key==="ArrowRight")navTo(curFP+1);if(e.key==="ArrowLeft")navTo(curFP-1);
if(e.key>="1"&&e.key<="9"){var idx=parseInt(e.key)-1;var tabs=document.querySelectorAll(".label-tab");if(idx<tabs.length)tabs[idx].click()}
if(e.key==="b"||e.key==="B"){var bb=document.querySelector(".tool-btn[data-tool='bbox']");if(bb&&!bb.disabled)bb.click()}
if(e.key==="p"||e.key==="P"){var pb=document.querySelector(".tool-btn[data-tool='polygon']");if(pb&&!pb.disabled)pb.click()}
if(e.key==="v"||e.key==="V"){var vb=document.querySelector(".tool-btn[data-tool='vtxedit']");if(vb)vb.click()}
if(e.key==="r"||e.key==="R"){rotateCam(aCam)}
if(e.ctrlKey&&!e.shiftKey&&(e.key==="z"||e.key==="Z")){e.preventDefault();if(curTool==="polygon"&&DS.polyPts.length>0){DS.polyPts.pop();for(var c=0;c<CS.length;c++)if(DS.ci===c)render(c);updUR();return}if(curTool==="vtxedit"&&vertexUndoStack.length>0){undoVertexMovement();updUR();return}if(undoSt.length>0){undoBtn.click();return}}
if((e.ctrlKey&&e.key==="y")||(e.ctrlKey&&e.shiftKey&&(e.key==="z"||e.key==="Z"))){e.preventDefault();if(redoSt.length)redoBtn.click()}
if((e.key==="Delete"||e.key==="Backspace")&&selAnn>=0&&selAnn<anns.length){e.preventDefault();delA(selAnn)}});

// ═══ SUBMIT — LEAN PAYLOAD (NO METADATA) ═══
document.querySelector("crowd-form").addEventListener("submit",function(e){
if(submitting){e.preventDefault();return}
saveFrame();
var f0=allFA[0]||[];
if(f0.length===0){e.preventDefault();alert("Frame 0 is MANDATORY.");navTo(0);submitting=false;return;}
submitting=true;
var sb=document.getElementById("submit-btn");if(sb)sb.disabled=true;

var payload={},totalAnns=0,annotatedFrames=0,globalTracks={};
for(var fp=0;fp<NF;fp++){
var frameAnns=allFA[fp]||[],frameKey="frame_"+String(fp).padStart(2,"0"),camOut=[];
for(var ci=0;ci<NC;ci++){var camAnns=[];
for(var i=0;i<frameAnns.length;i++){if(frameAnns[i].ci===ci){
camAnns.push({label:frameAnns[i].label,label_name:frameAnns[i].labelName,color:frameAnns[i].color,tool:frameAnns[i].tool,data:frameAnns[i].data,tracking_id:frameAnns[i].trackingId||""});
var tid=frameAnns[i].trackingId||"untracked";
if(!globalTracks[tid])globalTracks[tid]={label:frameAnns[i].label,label_name:frameAnns[i].labelName,frames:{},cameras:{}};
globalTracks[tid].frames[fp]=true;globalTracks[tid].cameras[ci]=true;}}
camOut.push({camera_id:CS[ci].id,blurry:CS[ci].blurry,rotation_degrees:camRotation[ci],annotations:camAnns});totalAnns+=camAnns.length;}
payload[frameKey]={frame_index:fp,num_annotations:frameAnns.length,cameras:camOut};
if(frameAnns.length>0)annotatedFrames++;}

var trackSummary={};
for(var tid in globalTracks){var gt=globalTracks[tid];
trackSummary[tid]={label:gt.label,label_name:gt.label_name,total_frames:Object.keys(gt.frames).length,
frame_list:Object.keys(gt.frames).map(function(f){return parseInt(f)}).sort(function(a,b){return a-b}),
camera_ids:Object.keys(gt.cameras).map(function(c){return CAM_NAMES[parseInt(c)]})};}

var camSettings={};
for(var ci=0;ci<NC;ci++)camSettings[CAM_NAMES[ci]]={rotation_degrees:camRotation[ci],blurry:CS[ci].blurry};

payload["_meta"]={total_frames:NF,annotated_frames:annotatedFrames,total_annotations:totalAnns,num_cameras:NC,camera_ids:CAM_NAMES,num_labels:Object.keys(LABELS).length,label_names:Object.keys(LABELS),total_tracked_objects:Object.keys(globalTracks).length,submitted_at:new Date().toISOString()};
payload["_tracking"]={total_unique_objects:Object.keys(trackSummary).length,objects:trackSummary};
payload["_camera_settings"]=camSettings;

document.getElementById("annotationData").value=JSON.stringify(payload);
});

buildFN();buildCB();layP();updAS();updHint();updFNInfo();updF0Warn();buildTrackBar();buildTrackLegend();navTo(0);
}catch(err){console.error(err.message)}
</script>"""

print("Cell 3D continued - Camera panels + Submit ready (NO metadata in payload)")


# ============================================================
# CELL 3E — COMBINE + UPLOAD
# ============================================================

TEMPLATE_JS = TEMPLATE_JS_1 + TEMPLATE_JS_2 + TEMPLATE_JS_3
full_template = TEMPLATE_CSS + TEMPLATE_HTML + TEMPLATE_JS

def clean_surrogates(s):
    return s.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")

full_template = clean_surrogates(full_template)

surrogates = sum(1 for ch in full_template if 0xD800 <= ord(ch) <= 0xDFFF)

template_key = f"{STAGE1_PREFIX}/template.html"
s3.put_object(
    Bucket=BUCKET,
    Key=template_key,
    Body=full_template.encode("utf-8"),
    ContentType="text/html"
)

TEMPLATE_S3_URI = f"s3://{BUCKET}/{template_key}"
template_size   = len(full_template)

os.makedirs("template", exist_ok=True)
with open("template/template.html", "w", encoding="utf-8") as f:
    f.write(full_template)

print("=" * 60)
print("  TEMPLATE UPLOAD COMPLETE")
print("=" * 60)
print(f"  S3 URI    : {TEMPLATE_S3_URI}")
print(f"  Size      : {template_size:,} bytes ({template_size/1024:.1f} KB)")
print(f"  Surrogates: {surrogates} {'Clean' if surrogates==0 else 'Found!'}")
print(f"  Local     : template/template.html")

# Verify key removals
checks = {
    "NO metadata panel":    "meta-panel" not in full_template,
    "NO META_DEFS":         "META_DEFS" not in full_template,
    "NO metaOverrides":     "metaOverrides" not in full_template,
    "NO getEffectiveMeta":  "getEffectiveMeta" not in full_template,
    "NO buildMetaPanel":    "buildMetaPanel" not in full_template,
    "NO syncAnnMeta":       "syncAnnMeta" not in full_template,
    "NO blobCache":         "blobCache" not in full_template,
    "NO fetch(":            "fetch(" not in full_template,
    "NO createObjectURL":   "createObjectURL" not in full_template,
    "HAS crowd-form":       "<crowd-form>" in full_template,
    "HAS annotationData":   "annotationData" in full_template,
    "HAS navTo":            "navTo" in full_template,
    "HAS buildTrackBar":    "buildTrackBar" in full_template,
}

all_ok = all(checks.values())
print(f"\n  Checks:")
for name, passed in checks.items():
    print(f"    {'OK' if passed else 'FAIL'} {name}")
print(f"\n  Overall: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
print("=" * 60)
