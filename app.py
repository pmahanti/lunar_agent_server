import os, json
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM = """You are a lunar geology agent operating with the Lunar Geology Skill Library — a scientifically rigorous reference system for the Moon. When given coordinates you simulate running 6 Python tools from the library, then synthesize a geologic briefing.

Simulate realistic, scientifically accurate outputs for each tool at the given location, drawing on actual published lunar science.

The named_feature_lookup tool queries a catalog of all non-crater named and catalogued lunar surface features. It checks whether the coordinates fall on or near any of the following feature classes — report any matches with the feature name, type, and key physical properties:

- Swirls: Reiner Gamma, Mare Ingenii, Airy, Marginis, Gerasimovich, Hopmann, Rima Sirsalis, Firsov, and others — report swirl name, crustal magnetic field strength (nT), albedo contrast, formation hypothesis
- Volcanic domes: Rumker Hills, Gruithuisen domes (gamma, delta), Marius Hills, Hortensius domes, Cauchy domes — report dome diameter, height, flank slope, inferred composition
- Scarps and lobate scarps: Discovery Rupes, Lee-Lincoln scarp, Rupes Recta (Straight Wall), Altai Scarp — report scarp length, height, vergence, tectonic interpretation
- Sinuous rilles and associated vents: Vallis Schroteri (~25N, 50W) and its source vent Cobra Head (~24.5N, 49.5W) — Cobra Head is the large elliptical collapse pit (~10 km wide) at the head of Vallis Schroteri, interpreted as the proximal lava tube vent; report vent dimensions, depth, and relationship to the rille system. Hadley Rille (~25N, 3.6E), Rima Hyginus (~7.5N, 7.8E), Rima Ariadaeus (~6.5N, 14E) — report rille length, width, depth, inferred origin (lava tube collapse, erosion, tectonic)
- Wrinkle ridges: report ridge system name, mare unit, compressional context
- Pyroclastic deposits: Alphonsus dark spots, Aristarchus plateau glass beads, Mare Vaporum deposit — report deposit type, extent, glass composition
- Magnetic anomalies not coincident with swirls: report anomaly name or coordinates, field strength
- Named mare units and highland terrains: report unit name, stratigraphy, age
- If no named feature is present within ~50 km, report "No named non-crater feature within search radius."

PRIORITY RULE: A specific named feature (vent, dome, rille, swirl, scarp) always takes precedence over a broad regional descriptor (ejecta blanket, mare unit, highland terrain). If the point is within ~15 km of a named feature, that feature is the primary identification even if it sits within a larger named region.

For each tool provide a concise 1-2 sentence result grounded in real data.

Respond ONLY in valid JSON, no markdown, no preamble:
{
  "location_name": "If a named non-crater feature (swirl, dome, rille, scarp, vent etc.) is present at or within ~10 km of the coordinates, use that feature name as the primary identifier (e.g. 'Cobra Head vent', 'Reiner Gamma swirl', 'Gruithuisen Gamma dome'). Only fall back to mare/terrain/regional description if no named feature is present.",
  "tools": [
    {"tool": "LROC_proximity_search", "result": "..."},
    {"tool": "crater_catalog_query", "result": "..."},
    {"tool": "named_feature_lookup", "result": "..."},
    {"tool": "spectral_unit_lookup", "result": "..."},
    {"tool": "topography_query", "result": "..."},
    {"tool": "thermal_inertia_lookup", "result": "..."}
  ],
  "briefing": {
    "geomorphology": "2-3 sentences on surface morphology, crater density, terrain type",
    "stratigraphy": "2-3 sentences on stratigraphic context, age, unit boundaries",
    "spectral_mineralogy": "2-3 sentences on mineralogy from spectral data (FeO, TiO2, olivine, pyroxene etc.)",
    "topography": "1-2 sentences on elevation, slope, roughness from LOLA",
    "named_feature": "If a named non-crater feature is present: feature name, type, key physical properties, and scientific significance. Omit this field entirely if no feature is present.",
    "notable_features": ["feature1", "feature2", "feature3"],
    "relevant_researchers": ["Lastname, F. (specialty)", "Lastname, F. (specialty)", "Lastname, F. (specialty)"],
    "confidence_notes": "1 sentence on data quality or coverage caveats at this location"
  }
}"""

HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lunar Geology Brief</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #070d1a; color: #e2e8f0; padding: 0; }
  .header { padding: 1.75rem 2rem 1.25rem; border-bottom: 1px solid rgba(255,255,255,0.06); }
  .header-inner { max-width: 1000px; margin: 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-dot { width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; box-shadow: 0 0 8px #38bdf8; flex-shrink: 0; }
  .brand h1 { font-size: 16px; font-weight: 500; letter-spacing: 0.04em; color: #f1f5f9; }
  .brand p  { font-size: 12px; color: #475569; margin-top: 2px; }
  .presets { display: flex; gap: 5px; flex-wrap: wrap; }
  .preset { font-size: 11px; padding: 4px 10px; border-radius: 20px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); color: #94a3b8; cursor: pointer; transition: all 0.15s; }
  .preset:hover { background: rgba(56,189,248,0.1); border-color: rgba(56,189,248,0.3); color: #38bdf8; }
  .input-section { max-width: 1000px; margin: 1.25rem auto 0; padding: 0 2rem; }
  .input-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }
  .input-row label { display: block; font-size: 10px; color: #334155; margin-bottom: 5px; letter-spacing: 0.08em; text-transform: uppercase; }
  .input-row input { width: 100%; font-family: monospace; font-size: 13px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 9px 12px; color: #e2e8f0; transition: border-color 0.15s; }
  .input-row input:focus { outline: none; border-color: rgba(56,189,248,0.4); }
  .input-row input::placeholder { color: #1e3a5f; }
  #runBtn { height: 38px; padding: 0 22px; font-size: 13px; font-weight: 500; letter-spacing: 0.04em; background: #0ea5e9; border: none; border-radius: 8px; color: #fff; cursor: pointer; transition: background 0.15s; white-space: nowrap; }
  #runBtn:hover { background: #38bdf8; }
  #runBtn:disabled { opacity: 0.35; cursor: not-allowed; }
  .err { font-size: 11px; color: #f87171; margin-top: 5px; min-height: 16px; }
  .agent-err { font-size: 12px; color: #fca5a5; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.15); border-radius: 8px; padding: 8px 12px; margin-top: 8px; display: none; }
  .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; max-width: 1000px; margin: 1.5rem auto 0; padding: 0 2rem 2rem; }
  @media (max-width: 640px) { .panels { grid-template-columns: 1fr; } .input-row { grid-template-columns: 1fr; } }
  .panel { background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 1.25rem; min-height: 340px; }
  .panel-label { font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #1e3a5f; margin-bottom: 14px; }
  #cloudPanel { position: relative; overflow: hidden; }
  #cloudWords { position: absolute; inset: 0; top: 32px; }
  .cloud-hint { font-size: 12px; color: #1e3a5f; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); white-space: nowrap; }
  .cw { position: absolute; font-weight: 500; line-height: 1; opacity: 0; transition: opacity 0.45s ease; white-space: nowrap; user-select: none; }
  .cw.show { opacity: 1; }
  .briefing-panel { overflow-y: auto; max-height: 580px; }
  .briefing-panel::-webkit-scrollbar { width: 3px; }
  .briefing-panel::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
  .empty { font-size: 12px; color: #1e3a5f; }
  .briefing-title { font-size: 14px; font-weight: 600; margin-bottom: 14px; color: #f1f5f9; }
  .briefing-coords { font-size: 11px; font-weight: 400; color: #334155; }
  .named-feature-box { margin-bottom: 14px; background: rgba(16,185,129,0.07); border: 1px solid rgba(16,185,129,0.18); border-radius: 8px; padding: 10px 12px; }
  .nf-label { font-size: 10px; font-weight: 600; color: #34d399; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; }
  .nf-body { font-size: 12px; color: #a7f3d0; line-height: 1.65; }
  .section { margin-bottom: 12px; }
  .sec-label { font-size: 10px; font-weight: 600; color: #1e3a5f; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 3px; }
  .sec-body { font-size: 12px; color: #94a3b8; line-height: 1.65; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
  .tag { font-size: 10px; padding: 2px 8px; border-radius: 999px; background: rgba(56,189,248,0.08); color: #7dd3fc; border: 1px solid rgba(56,189,248,0.12); }
  .tag.researcher { background: rgba(255,255,255,0.03); color: #475569; border-color: rgba(255,255,255,0.06); }
  .confidence { font-size: 11px; color: #334155; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 7px 10px; border-left: 2px solid rgba(255,255,255,0.06); margin-top: 8px; font-style: italic; }
</style>
</head>
<body>
<div class="header">
  <div class="header-inner">
    <div class="brand">
      <div class="brand-dot"></div>
      <div><h1>Lunar Geology Brief</h1><p>Enter lunar surface coordinates &rarr; Get location geology</p></div>
    </div>
    <div class="presets" id="presets"></div>
  </div>
</div>
<div class="input-section">
  <div class="input-row">
    <div>
      <label for="coordInput">Coordinates &mdash; lat, lon</label>
      <input id="coordInput" type="text" value="7.37, -59.02" placeholder="e.g. 7.37, -59.02" autocomplete="off">
    </div>
    <button id="runBtn" onclick="runAgent()">Generate</button>
  </div>
  <div class="err" id="coordErr"></div>
  <div class="agent-err" id="agentErr"></div>
</div>
<div class="panels">
  <div class="panel" id="cloudPanel">
    <div class="panel-label">Keyword cloud</div>
    <div id="cloudWords"><div class="cloud-hint" id="cloudHint">Run a query to build the cloud</div></div>
  </div>
  <div class="panel briefing-panel">
    <div class="panel-label">Geologic briefing</div>
    <div id="briefingOut"><p class="empty">Briefing appears here&hellip;</p></div>
  </div>
</div>
<script>
const PRESETS=[{label:"Reiner Gamma",lat:7.37,lon:-59.02},{label:"Cobra Head",lat:24.65,lon:-49.24},{label:"Apollo 11",lat:0.67,lon:23.47},{label:"Tycho",lat:-43.31,lon:-11.36},{label:"Mare Imbrium",lat:32.8,lon:-15.6},{label:"Aristarchus",lat:26.0,lon:-47.5}];
const TOOLS=["LROC_proximity_search","crater_catalog_query","named_feature_lookup","spectral_unit_lookup","topography_query","thermal_inertia_lookup"];
const TOOL_SEEDS={
  "LROC_proximity_search":[{w:"LROC",s:20},{w:"NAC",s:15},{w:"WAC",s:13},{w:"imagery",s:13},{w:"morphology",s:14},{w:"mosaic",s:12}],
  "crater_catalog_query":[{w:"craters",s:18},{w:"ejecta",s:15},{w:"morphometry",s:14},{w:"density",s:13},{w:"SFD",s:13},{w:"D/d",s:12}],
  "named_feature_lookup":[{w:"named feature",s:18},{w:"swirl",s:16},{w:"dome",s:15},{w:"rille",s:15},{w:"scarp",s:14},{w:"anomaly",s:13}],
  "spectral_unit_lookup":[{w:"FeO",s:20},{w:"TiO2",s:17},{w:"pyroxene",s:15},{w:"olivine",s:14},{w:"plagioclase",s:13},{w:"M³",s:13}],
  "topography_query":[{w:"LOLA",s:19},{w:"elevation",s:16},{w:"slope",s:15},{w:"roughness",s:14},{w:"DEM",s:14},{w:"relief",s:12}],
  "thermal_inertia_lookup":[{w:"Diviner",s:18},{w:"thermal inertia",s:16},{w:"regolith",s:15},{w:"rock abundance",s:13},{w:"bolometric",s:12}]
};
const SEED_COLORS=["#1d6fa4","#0e7490","#1d4ed8","#1a6b5e","#2563a8","#155e75"];
const RESULT_COLORS=["#38bdf8","#34d399","#818cf8","#fb923c","#a78bfa","#22d3ee","#4ade80","#60a5fa"];
const STOP=new Set("a an the and or but in on at to of for with from by is was are were be been has have had it its this that these those as if no not also such cm km nT per via very over near within about along show shows near were".split(" "));

function parseCoords(str){const p=str.split(",").map(s=>s.trim());if(p.length!==2)return null;const la=parseFloat(p[0]),lo=parseFloat(p[1]);if(isNaN(la)||isNaN(lo)||la<-90||la>90||lo<-180||lo>180)return null;return{la,lo};}
const presetsEl=document.getElementById("presets");
PRESETS.forEach(p=>{const btn=document.createElement("button");btn.className="preset";btn.textContent=p.label;btn.onclick=()=>{document.getElementById("coordInput").value=p.lat+", "+p.lon;document.getElementById("coordErr").textContent="";};presetsEl.appendChild(btn);});
document.getElementById("coordInput").addEventListener("keydown",e=>{if(e.key==="Enter")runAgent();});

const measurer=document.createElement("div");
measurer.style.cssText="position:fixed;top:-9999px;left:-9999px;visibility:hidden;pointer-events:none;";
document.body.appendChild(measurer);

let placedBoxes=[],seenWords=new Set();

function cloudReset(){placedBoxes=[];seenWords.clear();document.getElementById("cloudWords").innerHTML='<div class="cloud-hint" id="cloudHint">Building&hellip;</div>';}

function measureEl(el){measurer.appendChild(el);const w=el.offsetWidth,h=el.offsetHeight;measurer.removeChild(el);return{w,h};}

function overlaps(a,b){const pad=4;return!(a.x+a.w+pad<b.x||b.x+b.w+pad<a.x||a.y+a.h+pad<b.y||b.y+b.h+pad<a.y);}

function tryPlace(container,el,vertical){
  const cw=container.clientWidth||380,ch=container.clientHeight||310;
  const{w,h}=measureEl(el);
  const bw=vertical?h:w,bh=vertical?w:h;
  const cx=cw/2-bw/2,cy=ch/2-bh/2;
  const maxR=Math.min(cw,ch)*0.46;
  for(let r=0;r<maxR;r+=3){
    const steps=Math.max(6,Math.floor(2*Math.PI*r/5));
    const off=Math.random()*Math.PI*2;
    for(let i=0;i<steps;i++){
      const angle=off+(2*Math.PI*i/steps);
      const x=Math.round(cx+r*Math.cos(angle));
      const y=Math.round(cy+r*Math.sin(angle));
      if(x<2||y<2||x+bw>cw-2||y+bh>ch-2)continue;
      const box={x,y,w:bw,h:bh};
      if(!placedBoxes.some(p=>overlaps(p,box))){placedBoxes.push(box);el.style.left=x+"px";el.style.top=y+"px";return true;}
    }
  }
  return false;
}

async function addWord(text,size,color,vertical){
  const key=text.toLowerCase();if(seenWords.has(key))return;seenWords.add(key);
  const hint=document.getElementById("cloudHint");if(hint)hint.remove();
  const container=document.getElementById("cloudWords");
  const el=document.createElement("span");el.className="cw";el.textContent=text;
  el.style.fontSize=size+"px";el.style.color=color;
  if(vertical){el.style.writingMode="vertical-rl";el.style.transform="rotate(180deg)";}
  if(!tryPlace(container,el,vertical))return;
  container.appendChild(el);
  await new Promise(r=>requestAnimationFrame(r));
  await new Promise(r=>requestAnimationFrame(r));
  el.classList.add("show");
}

async function addWordList(words,colorFn,delay){
  for(let i=0;i<words.length;i++){
    const{w,s}=words[i];
    await addWord(w,s,colorFn(i),Math.random()<0.28);
    await new Promise(r=>setTimeout(r,(delay||80)+Math.random()*50));
  }
}

function extractWords(text){
  const freq={};
  text.replace(/[()\[\]{},."'\;:!?]/g," ").split(/\s+/).map(w=>w.replace(/[^a-zA-Z0-9\/\-]/g,""))
    .filter(w=>w.length>=4&&!STOP.has(w.toLowerCase())&&!/^\d+$/.test(w))
    .forEach(w=>{const k=w.toLowerCase();if(!freq[k])freq[k]=[w,0];freq[k][1]++;});
  return Object.values(freq).sort((a,b)=>b[1]-a[1]).slice(0,55)
    .map(([w,c],i)=>({w,s:Math.min(21,Math.max(10,10+Math.floor(c*2.5)+(i<4?5-i:0)))}));
}

function tags(arr,cls){return arr.map(f=>'<span class="tag '+(cls||"")+'">'+(f)+'</span>').join("");}

async function runAgent(){
  document.getElementById("coordErr").textContent="";
  const errEl=document.getElementById("agentErr");errEl.style.display="none";
  const parsed=parseCoords(document.getElementById("coordInput").value);
  if(!parsed){document.getElementById("coordErr").textContent="Enter as: lat, lon  (lat -90..90, lon -180..180)";return;}
  const{la,lo}=parsed;
  document.getElementById("runBtn").disabled=true;
  cloudReset();
  document.getElementById("briefingOut").innerHTML='<p class="empty">Waiting for agent&hellip;</p>';
  let toolIdx=0,streaming=true;
  (async()=>{
    while(streaming&&toolIdx<TOOLS.length){
      const seeds=TOOL_SEEDS[TOOLS[toolIdx]];const ci=toolIdx;
      await addWordList(seeds,i=>SEED_COLORS[ci%SEED_COLORS.length],100);
      toolIdx++;await new Promise(r=>setTimeout(r,150));
    }
  })();
  try{
    const resp=await fetch("/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lat:la,lon:lo})});
    const result=await resp.json();if(result.error)throw new Error(result.error);
    streaming=false;
    const allText=[(result.tools||[]).map(t=>t.result||"").join(" "),result.briefing?.geomorphology||"",result.briefing?.stratigraphy||"",result.briefing?.spectral_mineralogy||"",result.briefing?.topography||"",result.briefing?.named_feature||"",(result.briefing?.notable_features||[]).join(" ")].join(" ");
    await addWordList(extractWords(allText),i=>RESULT_COLORS[i%RESULT_COLORS.length],50);
    const b=result.briefing||{};let html="";
    if(result.location_name)html+='<div class="briefing-title">'+result.location_name+' <span class="briefing-coords">('+la.toFixed(2)+'&deg;, '+lo.toFixed(2)+'&deg;)</span></div>';
    if(b.named_feature)html+='<div class="named-feature-box"><div class="nf-label">Named feature</div><div class="nf-body">'+b.named_feature+'</div></div>';
    [["Geomorphology",b.geomorphology],["Stratigraphy",b.stratigraphy],["Spectral mineralogy",b.spectral_mineralogy],["Topography",b.topography]].forEach(([label,text])=>{if(text)html+='<div class="section"><div class="sec-label">'+label+'</div><div class="sec-body">'+text+'</div></div>';});
    if(b.notable_features?.length)html+='<div class="section"><div class="sec-label">Notable features</div><div class="tags">'+tags(b.notable_features)+'</div></div>';
    if(b.relevant_researchers?.length)html+='<div class="section"><div class="sec-label">Key researchers</div><div class="tags">'+tags(b.relevant_researchers,"researcher")+'</div></div>';
    if(b.confidence_notes)html+='<div class="confidence">'+b.confidence_notes+'</div>';
    document.getElementById("briefingOut").innerHTML=html;
  }catch(err){
    streaming=false;errEl.textContent="Error: "+err.message;errEl.style.display="block";
    document.getElementById("briefingOut").innerHTML='<p class="empty">Briefing unavailable.</p>';
  }
  document.getElementById("runBtn").disabled=false;
}
</script>
</body>
</html>'''



@app.route("/")
def index():
    return HTML, 200, {"Content-Type": "text/html"}


@app.route("/query", methods=["POST"])
def query():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no JSON body"}), 400
    la = data.get("lat")
    lo = data.get("lon")
    if la is None or lo is None:
        return jsonify({"error": "lat and lon required"}), 400
    if not (-90 <= la <= 90) or not (-180 <= lo <= 180):
        return jsonify({"error": "coordinates out of range"}), 400
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Coordinates: lat={la}, lon={lo}"}]
        )
        raw = msg.content[0].text.strip()
        result = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return jsonify(result)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSON parse error: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
