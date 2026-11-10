"""Blind review page for the history-key repair test: the owner looks at the nutrition photo and says which candidate table matches the pack (private, local, nothing is published).

  python p8_steward/fix_review_page.py items  --set round1   -> output/review_set/fix_review_<set>_items.json (what the page shows) and fix_review_<set>_key.json (which candidate is which; NOT in the page)
  python p8_steward/fix_review_page.py photos --set round1   -> output/review_set/fix_review_<set>_photos.json (the photo address of each product, from OFF's public API, 4 s apart)
  python p8_steward/fix_review_page.py html   --set round1   -> output/review_set/fix_review_<set>.html (open it in a browser; Save writes fix_review_<set>_answers.json)
  python p8_steward/fix_review_page.py join   --set round1   -> reads the answers and the key and prints who was right

Selection (fixed 2026-11-08, before any answer): every product where HYBRID C's repair does not agree with the contributor's fix (valid alternatives), plus the first 40 agreeing products in order of
sha256('review-1:' + code); all shuffled by sha256('order-1:' + code). Candidate A and B are the hybrid's repaired record and the contributor's post-fix record, swapped by the parity of
sha256('swap-1:' + code). Answers: A, B, both match the pack, neither, can't tell.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
import fix_test_lib as t  # noqa: E402
import history_key_scan_check as hk  # noqa: E402
sys.path.insert(0, str(ROOT / "p7_triage_ml" / "labelling"))
import cards_lib as cl  # noqa: E402     (the word lists and the reading of OFF's text scan that the Label Studio cards used)

R = hk.REVIEW
MODEL = "gemini-3.5-flash-lite"
AGREEING_SAMPLE = 40
FIELDS = ("energy_kcal", "energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt", "sodium")
LABEL = {"energy_kcal": "Energy (kcal)", "energy_kj": "Energy (kJ)", "fat": "Fat (g)", "saturated_fat": "Saturated fat (g)", "carbohydrates": "Carbohydrates (g)",
         "sugars": "Sugars (g)", "fiber": "Fibre (g)", "proteins": "Protein (g)", "salt": "Salt (g)", "sodium": "Sodium (g)"}


def h(prefix: str, code: str) -> str:
    return hashlib.sha256((prefix + code).encode()).hexdigest()


def swapped(code: str) -> bool:
    return int(h("swap-1:", code), 16) % 2 == 1


def select(classified: list[tuple[dict, str]]) -> list[dict]:
    """classified = (row, class of HYBRID C). Returns the rows to review in page order."""
    diff = [r for r, c in classified if c == "valid_alternative"]
    agree = sorted((r for r, c in classified if c == "agrees"), key=lambda r: h("review-1:", r["code"]))[:AGREEING_SAMPLE]
    return sorted(diff + agree, key=lambda r: h("order-1:", r["code"]))


def candidate_values(values: dict) -> dict:
    return {f: round(values[f], 3) for f in FIELDS if values.get(f) is not None}


LOOSE_SERVING = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|ml)\b", re.IGNORECASE)


def serving_for_page(row: dict, reading: dict | None) -> tuple[float | None, str]:
    """The serving size (g or ml) used to turn per-100 values into per-serving ones: the one the model read from the pack text, else the one on the product record. Returns (size, where it came from)."""
    m = LOOSE_SERVING.search((reading or {}).get("serving_size") or "")
    if m:
        return float(m.group(1).replace(",", ".")), "read from the pack text"
    s = t.serving_of(row)
    return (s, "from the product record") if s else (None, "")


def glossary_from_scan(scan: dict | None) -> dict:
    """The words under the photo, as in the Label Studio cards: the languages OFF's own text scan found on the photo, and for each nutrient the word in those languages = the English word.
    Words only, no numbers. English-only packs and photos without a listed language get just the note."""
    langs = cl.printed_languages(cl.ocr_languages(scan or {}))
    g = cl.glossary_lines({"photo_languages": langs})
    others = [c for c in langs if c != "en"]
    return {"title": g["g_title"], "note": g["g_note"], "lines": [g[k] for k in cl.GLOSSARY_KEYS] if others else []}


def build_item(row: dict, hybrid_record: dict, reading: dict | None = None, scan: dict | None = None) -> tuple[dict, dict]:
    hyb, con = candidate_values(hybrid_record), candidate_values(t.key(row))
    a, b = (con, hyb) if swapped(row["code"]) else (hyb, con)
    serving = re.sub(r"\d+\.\d{3,}", lambda m: f"{float(m.group(0)):.2f}".rstrip("0").rstrip("."), row.get("serving_size") or "")      # 56.00000000000001 g -> 56 g
    size, src = serving_for_page(row, reading)
    item = {"code": row["code"], "A": a, "B": b, "stored_before": candidate_values(t.before(row)), "serving": serving, "serving_g": size, "serving_src": src,
            "basis_hint": (reading or {}).get("basis") or "", "glossary": glossary_from_scan(scan)}
    key = {"A": "contributor" if swapped(row["code"]) else "hybrid", "B": "hybrid" if swapped(row["code"]) else "contributor"}
    return item, key


def hybrid_records(which: str):
    import dev_ocr_reader as dr
    import fix_test_agent as fa
    import reader_decision as rd
    rows = json.loads(fa.files(which, MODEL)[0].read_text(encoding="utf8"))
    readings = json.loads(fa.files(which, MODEL)[1].read_text(encoding="utf-8"))
    out = []
    for row in rows:
        text = dr.scan_text(row["code"], fa.VERSION)[:6000]
        dec = rd.decide(t.before(row), readings.get(row["code"], {}).get("reading"), text, t.group_of_row(row), fa.VERSION)
        prop = t.agent_proposal(dec)
        filled = t.complete_partners(t.before(row), dec.get("reading100") or {}, prop) if prop else None
        proposal = t.hybrid_agent_then_reading(row, filled, dec.get("reading100"))
        out.append((row, t.classify(row, proposal), {**t.before(row), **{f: v for f, v in (proposal or {}).items() if v is not None}}, readings.get(row["code"], {}).get("reading") or {}))
    return out


def cmd_items(which: str) -> None:
    triples = hybrid_records(which)
    chosen = select([(r, c) for r, c, _, _ in triples])
    rec = {r["code"]: x for r, _, x, _ in triples}
    cls = {r["code"]: c for r, c, _, _ in triples}
    rdg = {r["code"]: g for r, _, _, g in triples}
    items, key = [], {}
    for row in chosen:
        scan_file = R / "ocr_json" / f"{row['code']}.json"
        item, k = build_item(row, rec[row["code"]], rdg[row["code"]], json.loads(scan_file.read_text(encoding="utf8")) if scan_file.exists() and scan_file.stat().st_size > 2 else None)
        items.append(item)
        key[row["code"]] = {**k, "kind": "differs" if cls[row["code"]] == "valid_alternative" else "agrees", "group": t.group_of_row(row)}
    (R / f"fix_review_{which}_items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf8")
    (R / f"fix_review_{which}_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=0), encoding="utf8")
    print(len(items), "items:", sum(v["kind"] == "differs" for v in key.values()), "differ,", sum(v["kind"] == "agrees" for v in key.values()), "agree")


def cmd_photos(which: str) -> None:
    import fetch_ocr_text as fo
    out_file = R / f"fix_review_{which}_photos.json"
    done = json.loads(out_file.read_text(encoding="utf8")) if out_file.exists() else {}
    for item in json.loads((R / f"fix_review_{which}_items.json").read_text(encoding="utf8")):
        code = item["code"]
        if code in done:
            continue
        product = fo.get_json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images").get("product") or {}
        display = ((product.get("selected_images") or {}).get("nutrition") or {}).get("display") or {}
        url = sorted(display.items())[0][1] if display else ""
        done[code] = re.sub(r"\.\d+\.jpg$", ".full.jpg", url) if url else ""
        out_file.write_text(json.dumps(done), encoding="utf8")
        print(code, "photo" if url else "NO PHOTO", flush=True)


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Which table matches the pack?</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f4f4f2;color:#1b1b1b}
header{position:sticky;top:0;background:#1b1b1b;color:#fff;padding:8px 16px;display:flex;gap:16px;align-items:center;z-index:5}
header span{font-size:14px} header button{margin-left:auto}
main{display:grid;grid-template-columns:minmax(380px,1.3fr) minmax(360px,1fr);gap:16px;padding:16px}
#wrap{display:flex;gap:8px;align-items:flex-start}
.gloss{background:#fff;border:1px solid #ccc;border-radius:8px;padding:6px 10px;margin-top:8px;font-size:12px;line-height:1.35}.gloss .note{color:#666;margin-bottom:3px}
.gloss .g{columns:2;column-gap:18px}.gloss .g div{break-inside:avoid;padding:1px 0}
#photo{flex:1;min-width:0;background:#222;border:1px solid #ccc;border-radius:8px;height:calc(100vh - 120px);overflow:hidden;position:relative;cursor:grab;user-select:none;touch-action:none}
#photo.drag{cursor:grabbing}
#pmsg{position:absolute;left:0;right:0;top:42%;text-align:center;color:#eee;font-size:15px;z-index:1;display:none}#pmsg a{color:#9cc2ff;margin-left:8px}
#photo img{position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;pointer-events:none}
#tools{flex:none;width:48px;display:flex;flex-direction:column;gap:6px;max-height:calc(100vh - 120px);overflow:auto}
#left{position:relative;max-height:calc(100vh - 100px);overflow:auto;padding-right:6px}
#tools button{width:44px;height:36px;padding:0;background:rgba(255,255,255,.92);font-size:15px}
#zl{background:rgba(0,0,0,.65);color:#fff;border-radius:6px;font-size:12px;text-align:center;padding:4px 0}
#right{max-height:calc(100vh - 120px);overflow:auto;padding-right:6px}
.tables{display:grid;grid-template-columns:1fr 1fr;gap:12px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #ccc;border-radius:8px;overflow:hidden;font-size:14px}
th{background:#e8e8e4;padding:6px;text-align:left} td{padding:5px 6px;border-top:1px solid #eee} td.n{text-align:right;font-variant-numeric:tabular-nums}
tr.same td{background:#e9f5ec}
tr.differ td{background:#fff0c7}
.key{font-size:12px;margin:4px 0 8px}.key i{display:inline-block;width:12px;height:12px;border-radius:3px;margin:0 4px -2px 8px;border:1px solid #bbb}
.choices{margin-top:14px;display:grid;gap:8px}
.choices label{background:#fff;border:2px solid #ccc;border-radius:8px;padding:10px 12px;cursor:pointer;display:block}
.choices label.sel{border-color:#1a56db;background:#e8f0ff}
.meta{font-size:13px;color:#555;margin:6px 0}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid #999;background:#fff;cursor:pointer}
details{margin-top:10px;font-size:13px}
</style></head><body>
<header><span id="pos"></span><span id="saved"></span><button id="prev">Previous (&larr;)</button><button id="next">Next (&rarr;)</button><button id="save">Save answers</button></header>
<main><div id="left"><div id="wrap"><div id="photo"><img id="img" alt="nutrition photo"><div id="pmsg"></div></div>
<div id="tools">
<button data-a="in" title="Zoom in (+ or mouse wheel)">+</button><button data-a="out" title="Zoom out (- or mouse wheel)">&minus;</button>
<button data-a="fit" title="Fit to window (F or double-click)">Fit</button>
<button data-a="rl" title="Rotate left ([)">&#8634;</button><button data-a="rr" title="Rotate right (] or R)">&#8635;</button>
<button data-a="bp" title="Brighter">&#9728;+</button><button data-a="bm" title="Darker">&#9728;&minus;</button>
<button data-a="cp" title="More contrast">&#9680;+</button><button data-a="cm" title="Less contrast">&#9680;&minus;</button>
<button data-a="reset" title="Reset the view">Reset</button><div id="zl"></div></div></div>
<div class="meta"><a id="open" target="_blank" rel="noopener">open the photo in a new tab</a> | <a href="#" id="jump">translations below</a> | drag to move, mouse wheel to zoom (scroll this column from its edge or the scrollbar) | <span id="serv"></span></div><div class="gloss" id="gloss"></div></div>
<div id="right"><div class="meta">Look at the photo, then say which table matches what the pack prints (per 100 g or 100 ml).</div>
<div class="key">Row colour: <i style="background:#e9f5ec"></i>same in A and B <i style="background:#fff0c7"></i>different in A and B (check these rows)</div>
<div class="tables"><div><b>Table A</b><table id="ta"></table></div><div><b>Table B</b><table id="tb"></table></div></div>
<div class="choices" id="choices"></div>
<details><summary>Show the values stored before the fix</summary><table id="tc"></table></details></div></main>
<script>
const ITEMS=__ITEMS__, PHOTOS=__PHOTOS__, LABEL=__LABEL__, SET="__SET__";
const CH=[["A","1","A matches the pack"],["B","2","B matches the pack"],["both","3","Both match the pack"],["neither","4","Neither matches the pack"],["unsure","5","I can't tell (blurry, per serving only, ...)"]];
let i=0, ans=JSON.parse(localStorage.getItem("fixreview_"+SET)||"{}"), v={s:1,r:0,x:0,y:0,b:1,c:1}, fitS=1;
const $=id=>document.getElementById(id);
function ps(x,S){return Math.round(x*S)/100}
function tab(el,vals,o,S){el.innerHTML="<tr><th>Nutrient</th><th>per 100</th>"+(S?"<th>per serving ("+S+" g/ml)</th>":"")+"</tr>"+Object.keys(LABEL).map(f=>{const x=vals[f],y=o?o[f]:undefined;
 const d=o&&x!==undefined&&y!==undefined&&(f==="energy_kj"||f==="energy_kcal"?Math.abs(x-y)>Math.max(0.10*Math.abs(y),f==="energy_kj"?8:2):(Math.abs(x-y)>0.001&&Math.abs(x-y)>0.10*Math.max(Math.abs(x),Math.abs(y))));const miss=o&&((x===undefined)!==(y===undefined));const cl=o?((d||miss)?" class='differ'":" class='same'"):"";
 return "<tr"+cl+"><td>"+LABEL[f]+"</td><td class='n'>"+(x===undefined?"&mdash;":x)+"</td>"+(S?"<td class='n'>"+(x===undefined?"&mdash;":ps(x,S))+"</td>":"")+"</tr>"}).join("")}
function vp(){const p=$("photo");return {w:p.clientWidth,h:p.clientHeight}}
function apply(){const img=$("img");if(!img.naturalWidth)return;img.style.width=img.naturalWidth+"px";img.style.height=img.naturalHeight+"px";
 img.style.transform="translate("+v.x+"px,"+v.y+"px) rotate("+v.r+"deg) scale("+v.s+") translate("+(-img.naturalWidth/2)+"px,"+(-img.naturalHeight/2)+"px)";
 img.style.filter="brightness("+v.b+") contrast("+v.c+")";$("zl").textContent=Math.round(v.s*100)+"%"}
function fit(){const img=$("img");if(!img.naturalWidth)return;const {w,h}=vp(),q=v.r%180===0;
 fitS=Math.min(w/(q?img.naturalWidth:img.naturalHeight),h/(q?img.naturalHeight:img.naturalWidth));v.s=fitS;v.x=w/2;v.y=h/2;apply()}
function zoomAt(f,mx,my){const {w,h}=vp();if(mx===undefined){mx=w/2;my=h/2}const s2=Math.max(0.03,Math.min(10,v.s*f)),k=s2/v.s;v.x=mx-(mx-v.x)*k;v.y=my-(my-v.y)*k;v.s=s2;apply()}
function rot(d){v.r=(v.r+d+360)%360;fit()}
function act(a){({in:()=>zoomAt(1.25),out:()=>zoomAt(1/1.25),fit:fit,rl:()=>rot(-90),rr:()=>rot(90),
 bp:()=>{v.b=Math.min(3,v.b+0.15);apply()},bm:()=>{v.b=Math.max(0.3,v.b-0.15);apply()},cp:()=>{v.c=Math.min(4,v.c+0.2);apply()},cm:()=>{v.c=Math.max(0.3,v.c-0.2);apply()},
 reset:()=>{v={s:1,r:0,x:0,y:0,b:1,c:1};fit()}})[a]()}
document.querySelectorAll("#tools button").forEach(b=>b.onclick=e=>{e.stopPropagation();act(b.dataset.a)});
let drag=null;const P=$("photo");
P.onmousedown=e=>{if(e.target.closest("#tools")||e.target.closest("#pmsg"))return;drag={x:e.clientX-v.x,y:e.clientY-v.y};P.classList.add("drag")};
window.onmousemove=e=>{if(drag){v.x=e.clientX-drag.x;v.y=e.clientY-drag.y;apply()}};
window.onmouseup=()=>{drag=null;P.classList.remove("drag")};
P.addEventListener("wheel",e=>{e.preventDefault();const r=P.getBoundingClientRect();zoomAt(e.deltaY<0?1.15:1/1.15,e.clientX-r.left,e.clientY-r.top)},{passive:false});
P.ondblclick=e=>{if(e.target.closest("#tools"))return;const r=P.getBoundingClientRect();if(v.s>fitS*1.05)fit();else zoomAt(2.5/(v.s/fitS),e.clientX-r.left,e.clientY-r.top)};
$("img").onload=fit;window.onresize=fit;
$("jump").onclick=e=>{e.preventDefault();$("left").scrollTop=$("gloss").offsetTop-8};
function prefetch(k){const it=ITEMS[k];if(!it)return;const u=PHOTOS[it.code];if(u)new Image().src=u}
let loadTok=0;
function loadPhoto(code,url){const img=$("img"),msg=$("pmsg"),tok=++loadTok;img.style.visibility="hidden";img.removeAttribute("src");msg.style.display="block";
 if(!url){msg.textContent="No photo for this case.";return}
 msg.textContent="Loading photo...";
 const tries=[url,url.replace(".full.jpg",".400.jpg"),url+"?retry="+Date.now()];let k=0;
 const next=()=>{if(tok!==loadTok)return;
  if(k>=tries.length){msg.innerHTML="The photo did not load. <button id='pretry'>Try again</button> <a href='"+url+"' target='_blank' rel='noopener'>open it in a new tab</a>";$("pretry").onclick=()=>loadPhoto(code,url);return}
  const probe=new Image();let done=false;const timer=setTimeout(()=>{if(!done){done=true;next()}},20000);
  probe.onload=()=>{if(done)return;done=true;clearTimeout(timer);if(tok!==loadTok)return;img.src=probe.src;img.style.visibility="visible";msg.style.display="none";fit();setTimeout(fit,60);prefetch(i+1);prefetch(i+2)};
  probe.onerror=()=>{if(done)return;done=true;clearTimeout(timer);next()};
  probe.src=tries[k++]};
 next()}
function show(){const it=ITEMS[i];$("pos").textContent="Case "+(i+1)+" of "+ITEMS.length+" | answered "+Object.keys(ans).length;
 tab($("ta"),it.A,it.B,it.serving_g);tab($("tb"),it.B,it.A,it.serving_g);tab($("tc"),it.stored_before,null,it.serving_g);
 const u=PHOTOS[it.code];v={s:1,r:0,x:0,y:0,b:1,c:1};$("open").href=u||"#";loadPhoto(it.code,u);
 const g=it.glossary,esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;");
 $("gloss").innerHTML=g?"<b>"+esc(g.title)+"</b><div class='note'>"+esc(g.note)+"</div>"+(g.lines.length?"<div class='g'>"+g.lines.map(l=>"<div>"+esc(l)+"</div>").join("")+"</div>":""):"";
 $("jump").style.display=(g&&g.lines.length)?"":"none";$("left").scrollTop=0;
 const parts=[];if(it.basis_hint)parts.push("reader's guess at the pack's columns: "+it.basis_hint+" (may be wrong)");
 parts.push(it.serving_g?("serving "+it.serving_g+" g/ml, "+it.serving_src):"no serving size known: the per-serving column is not available");$("serv").textContent=parts.join(" | ");
 $("choices").innerHTML=CH.map(c=>"<label class='"+(ans[it.code]===c[0]?"sel":"")+"'><input type='radio' name='c' value='"+c[0]+"' "+(ans[it.code]===c[0]?"checked":"")+"> <b>"+c[1]+"</b> &nbsp;"+c[2]+"</label>").join("");
 document.querySelectorAll("input[name=c]").forEach(r=>r.onchange=()=>set(r.value));$("right").scrollTop=0}
function set(val){ans[ITEMS[i].code]=val;localStorage.setItem("fixreview_"+SET,JSON.stringify(ans));$("saved").textContent="saved in this browser";
 if(Object.keys(ans).length%10===0)$("saved").textContent="10 more answered: press Save answers to keep a file copy";
 const it=ITEMS[i];document.querySelectorAll("#choices label").forEach(l=>l.classList.toggle("sel",l.querySelector("input").value===ans[it.code]));$("pos").textContent="Case "+(i+1)+" of "+ITEMS.length+" | answered "+Object.keys(ans).length}
function go(d){i=Math.max(0,Math.min(ITEMS.length-1,i+d));show()}
$("prev").onclick=()=>go(-1);$("next").onclick=()=>go(1);
$("save").onclick=()=>{const b=new Blob([JSON.stringify(ans,null,1)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="fix_review_"+SET+"_answers.json";a.click()};
document.onkeydown=e=>{const k=e.key;if(k==="ArrowRight")go(1);else if(k==="ArrowLeft")go(-1);else if(k==="+"||k==="=")act("in");else if(k==="-")act("out");else if(k==="f"||k==="F")act("fit");
 else if(k==="r"||k==="R"||k==="]")act("rr");else if(k==="[")act("rl");
 else{const c=CH.find(c=>c[1]===k);if(c){set(c[0]);setTimeout(()=>go(1),150)}}};
show();
</script></body></html>
"""


def render(items: list[dict], photos: dict, which: str) -> str:
    return (PAGE.replace("__ITEMS__", json.dumps(items, ensure_ascii=False)).replace("__PHOTOS__", json.dumps(photos)).replace("__LABEL__", json.dumps(LABEL)).replace("__SET__", html.escape(which)))


def cmd_html(which: str) -> None:
    items = json.loads((R / f"fix_review_{which}_items.json").read_text(encoding="utf8"))
    photos = json.loads((R / f"fix_review_{which}_photos.json").read_text(encoding="utf8"))
    out = R / f"fix_review_{which}.html"
    shown = [i for i in items if photos.get(i["code"])]                      # a product OFF has no nutrition photo for cannot be judged: left out, counted
    key = json.loads((R / f"fix_review_{which}_key.json").read_text(encoding="utf8"))
    out.write_text(render(shown, photos, which), encoding="utf8")
    kinds = [key[i["code"]]["kind"] for i in shown]
    print("written", out, "| shown", len(shown), f"({kinds.count('differs')} differ, {kinds.count('agrees')} agree) | left out, no photo:", len(items) - len(shown))


def join(answers: dict, key: dict) -> dict:
    """Who was right, from the owner's answers and the key: counts by kind (differs/agrees) of contributor / hybrid / both / neither / unsure."""
    out: dict = {}
    for code, a in answers.items():
        k = key[code]
        who = {"A": k["A"], "B": k["B"]}.get(a, a)
        out.setdefault(k["kind"], {}).setdefault(who, 0)
        out[k["kind"]][who] += 1
    return out


def cmd_join(which: str) -> None:
    key = json.loads((R / f"fix_review_{which}_key.json").read_text(encoding="utf8"))
    answers = json.loads((R / f"fix_review_{which}_answers.json").read_text(encoding="utf8"))
    print(json.dumps(join(answers, key), indent=1), "| answered", len(answers), "of", len(key))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["items", "photos", "html", "join"])
    ap.add_argument("--set", default="round1", dest="which")
    a = ap.parse_args()
    {"items": cmd_items, "photos": cmd_photos, "html": cmd_html, "join": cmd_join}[a.cmd](a.which)


if __name__ == "__main__":
    main()
