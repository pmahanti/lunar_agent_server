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

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lunar Geology Agent</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem; background: #f9f9f7; color: #1a1a1a; }
  .wrap { max-width: 960px; margin: 0 auto; }
  h2 { font-size: 18px; font-weight: 500; margin: 0 0 4px; }
  .subtitle { font-size: 13px; color: #888; margin: 0 0 1.25rem; }
  .presets { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
  .preset { font-size: 12px; padding: 4px 10px; border-radius: 6px; background: #f5f5f3; border: 0.5px solid #ddd; color: #555; cursor: pointer; }
  .preset:hover { background: #eee; }
  .coord-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-bottom: 4px; align-items: end; }
  .coord-row label { display: block; font-size: 12px; color: #888; margin-bottom: 4px; }
  .coord-row input { width: 100%; font-family: monospace; font-size: 13px; border: 0.5px solid #ddd; border-radius: 6px; padding: 7px 10px; background: #fff; }
  .coord-row input:focus { outline: none; border-color: #aaa; }
  #runBtn { height: 36px; padding: 0 20px; font-size: 14px; font-weight: 500; background: #fff; border: 0.5px solid #aaa; border-radius: 8px; cursor: pointer; white-space: nowrap; }
  #runBtn:hover { background: #f5f5f3; }
  #runBtn:disabled { opacity: 0.4; cursor: not-allowed; }
  .err { font-size: 12px; color: #A32D2D; margin-bottom: 8px; min-height: 18px; }
  .agent-err { font-size: 13px; color: #A32D2D; background: #FCEBEB; border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; display: none; }
  .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
  @media (max-width: 640px) { .panels { grid-template-columns: 1fr; } }
  .panel { background: #fff; border: 0.5px solid #e8e8e5; border-radius: 12px; padding: 1rem; min-height: 320px; }
  .panel-label { font-size: 11px; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; color: #aaa; margin-bottom: 12px; }

  /* Word cloud */
  #cloudPanel { position: relative; overflow: hidden; min-height: 320px; }
  #cloudCanvas { position: absolute; inset: 0; width: 100%; height: 100%; }
  .cloud-empty { font-size: 13px; color: #bbb; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); white-space: nowrap; }
  .cloud-word {
    position: absolute;
    font-family: system-ui, sans-serif;
    font-weight: 500;
    opacity: 0;
    transform: scale(0.5);
    transition: opacity 0.5s ease, transform 0.5s ease;
    pointer-events: none;
    white-space: nowrap;
    line-height: 1;
  }
  .cloud-word.visible { opacity: 1; transform: scale(1); }

  /* Briefing panel */
  .empty { font-size: 13px; color: #bbb; }
  .briefing-title { font-size: 15px; font-weight: 500; margin-bottom: 12px; }
  .named-feature-box { margin-bottom: 12px; background: #F0FDF4; border: 0.5px solid #86EFAC; border-radius: 8px; padding: 8px 10px; }
  .named-feature-box .nf-label { font-size: 11px; font-weight: 500; color: #166534; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 3px; }
  .named-feature-box .nf-body { font-size: 13px; color: #14532D; line-height: 1.6; }
  .section { margin-bottom: 10px; }
  .sec-label { font-size: 11px; font-weight: 500; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
  .sec-body { font-size: 13px; color: #222; line-height: 1.6; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
  .tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #EBF3FD; color: #185FA5; border: 0.5px solid #B5D4F4; }
  .tag.researcher { background: #f5f5f3; color: #555; border-color: #ddd; }
  .confidence { font-size: 12px; color: #666; background: #f9f9f7; border-radius: 6px; padding: 7px 10px; border-left: 2px solid #ddd; margin-top: 6px; font-style: italic; }
  .briefing-panel { overflow-y: auto; max-height: 640px; }
</style>
</head>
<body>
<div class="wrap">
  <h2>Lunar geology agent</h2>
  <p class="subtitle">Enter coordinates &rarr; agent synthesizes geologic briefing</p>
  <div class="presets" id="presets"></div>
  <div class="coord-row">
    <div>
      <label for="coordInput">Coordinates &mdash; lat, lon (&minus;180 to 180)</label>
      <input id="coordInput" type="text" value="7.37, -59.02" placeholder="e.g. 7.37, -59.02">
    </div>
    <button id="runBtn" onclick="runAgent()">Run agent &nearr;</button>
  </div>
  <div class="err" id="coordErr"></div>
  <div class="agent-err" id="agentErr"></div>
  <div class="panels">
    <div class="panel" id="cloudPanel">
      <div class="panel-label">Keyword cloud</div>
      <div id="cloudEmpty" class="cloud-empty">Words will appear as the agent runs&hellip;</div>
    </div>
    <div class="panel briefing-panel">
      <div class="panel-label">Geologic briefing</div>
      <div id="briefingOut"><p class="empty">Briefing will appear once the agent completes&hellip;</p></div>
    </div>
  </div>
</div>
<script>
const PRESETS = [
  { label: "Reiner Gamma", lat: 7.37, lon: -59.02 },
  { label: "Cobra Head", lat: 24.65, lon: -49.24 },
  { label: "Apollo 11", lat: 0.67, lon: 23.47 },
  { label: "Tycho crater", lat: -43.31, lon: -11.36 },
  { label: "Mare Imbrium", lat: 32.8, lon: -15.6 },
  { label: "Aristarchus plateau", lat: 26.0, lon: -47.5 },
];

const TOOLS = ["LROC_proximity_search","crater_catalog_query","named_feature_lookup","spectral_unit_lookup","topography_query","thermal_inertia_lookup"];

// Words to strip from cloud
const STOP = new Set("a an the and or but in on at to of for with from by is was are were be been has have had it its this that these those as at if no not also be such cm km m nT".split(" "));

// Color palette for cloud words
const COLORS = ["#185FA5","#0F6E56","#534AB7","#993C1D","#3B6D11","#854F0B","#A32D2D","#0F6E56","#185FA5","#534AB7"];

// Tool label → short tag shown during loading
const TOOL_TAGS = {
  "LROC_proximity_search":  ["LROC","NAC","WAC","imagery","context","morphology","mosaic"],
  "crater_catalog_query":   ["craters","ejecta","D/d","morphometry","SFD","density","age"],
  "named_feature_lookup":   ["swirl","dome","rille","scarp","vent","anomaly","feature"],
  "spectral_unit_lookup":   ["FeO","TiO2","pyroxene","olivine","plagioclase","M3","spectral"],
  "topography_query":       ["LOLA","elevation","slope","roughness","DEM","relief","topography"],
  "thermal_inertia_lookup": ["Diviner","TI","regolith","bolometric","thermal","rock abundance"],
};

function parseCoords(str) {
  const parts = str.split(",").map(s => s.trim());
  if (parts.length !== 2) return null;
  const la = parseFloat(parts[0]), lo = parseFloat(parts[1]);
  if (isNaN(la)||isNaN(lo)||la<-90||la>90||lo<-180||lo>180) return null;
  return { la, lo };
}

const presetsEl = document.getElementById("presets");
PRESETS.forEach(p => {
  const btn = document.createElement("button");
  btn.className="preset"; btn.textContent=p.label;
  btn.onclick=()=>{ document.getElementById("coordInput").value=p.lat+", "+p.lon; document.getElementById("coordErr").textContent=""; };
  presetsEl.appendChild(btn);
});
document.getElementById("coordInput").addEventListener("keydown", e=>{ if(e.key==="Enter") runAgent(); });

// ── Word cloud engine ─────────────────────────────────────────────────────────

let placedWords = []; // {x, y, w, h} bounding boxes already placed

function cloudReset() {
  placedWords = [];
  const panel = document.getElementById("cloudPanel");
  panel.querySelectorAll(".cloud-word").forEach(el => el.remove());
  document.getElementById("cloudEmpty").style.display = "";
}

function extractWords(text, minLen=4) {
  return text
    .replace(/[()[\]{},."';:!?\/\\]/g, " ")
    .split(/\s+/)
    .map(w => w.replace(/[^a-zA-Z0-9\-\/]/g,""))
    .filter(w => w.length >= minLen && !STOP.has(w.toLowerCase()) && !/^\d+$/.test(w));
}

function scoreWords(words) {
  const freq = {};
  words.forEach(w => { const k=w.toLowerCase(); freq[k]=(freq[k]||0)+1; });
  // dedupe, keep original casing of first occurrence
  const seen = new Set();
  const result = [];
  words.forEach(w => { const k=w.toLowerCase(); if(!seen.has(k)){seen.add(k);result.push({word:w,count:freq[k]});} });
  return result.sort((a,b)=>b.count-a.count);
}

function overlaps(a, b, pad=4) {
  return !(a.x+a.w+pad < b.x || b.x+b.w+pad < a.x || a.y+a.h+pad < b.y || b.y+b.h+pad < a.y);
}

function tryPlace(panel, wordEl, fontSize) {
  const pw = panel.clientWidth - 24;
  const ph = panel.clientHeight - 48; // leave room for label
  wordEl.style.fontSize = fontSize + "px";
  wordEl.style.opacity = "0";
  wordEl.style.transform = "scale(1)";
  panel.appendChild(wordEl);
  const ww = wordEl.offsetWidth;
  const wh = wordEl.offsetHeight;

  // Spiral outward from centre
  const cx = pw / 2 - ww / 2;
  const cy = ph / 2 - wh / 2 + 28;
  const maxR = Math.min(pw, ph) * 0.48;

  for (let r = 0; r < maxR; r += 4) {
    const steps = Math.max(8, Math.floor(2 * Math.PI * r / 6));
    const angleOffset = Math.random() * Math.PI * 2;
    for (let i = 0; i < steps; i++) {
      const angle = angleOffset + (2 * Math.PI * i) / steps;
      const x = Math.round(cx + r * Math.cos(angle));
      const y = Math.round(cy + r * Math.sin(angle));
      if (x < 0 || y < 28 || x + ww > pw || y + wh > ph) continue;
      const box = { x, y, w: ww, h: wh };
      if (!placedWords.some(p => overlaps(p, box))) {
        placedWords.push(box);
        wordEl.style.left = x + "px";
        wordEl.style.top  = y + "px";
        return true;
      }
    }
  }
  // fallback: remove if no space
  wordEl.remove();
  return false;
}

async function addWordsToCloud(words, colorIdx) {
  const panel = document.getElementById("cloudPanel");
  document.getElementById("cloudEmpty").style.display = "none";
  const color = COLORS[colorIdx % COLORS.length];

  for (let i = 0; i < words.length; i++) {
    const {word, count} = words[i];
    const fontSize = Math.min(22, Math.max(10, 10 + count * 3 + (i < 3 ? 6 - i*2 : 0)));
    const el = document.createElement("span");
    el.className = "cloud-word";
    el.textContent = word;
    el.style.color = color;
    el.style.fontSize = fontSize + "px";

    const placed = tryPlace(panel, el, fontSize);
    if (placed) {
      await new Promise(r => setTimeout(r, 60 + Math.random() * 80));
      el.classList.add("visible");
    }
  }
}

// ── Agent ─────────────────────────────────────────────────────────────────────

function tags(arr, cls) { return arr.map(f=>'<span class="tag '+(cls||"")+'">'+f+'</span>').join(""); }

async function runAgent() {
  document.getElementById("coordErr").textContent = "";
  const agentErrEl = document.getElementById("agentErr");
  agentErrEl.style.display = "none";

  const parsed = parseCoords(document.getElementById("coordInput").value);
  if (!parsed) { document.getElementById("coordErr").textContent = "Enter as: lat, lon (lat -90 to 90, lon -180 to 180)"; return; }
  const {la, lo} = parsed;

  const btn = document.getElementById("runBtn");
  btn.disabled = true;

  cloudReset();
  document.getElementById("briefingOut").innerHTML = '<p class="empty">Waiting for agent...</p>';

  // Stream tool-specific keywords while waiting for the server response
  let toolIdx = 0;
  const streamInterval = setInterval(async () => {
    if (toolIdx < TOOLS.length) {
      const t = TOOLS[toolIdx];
      const words = TOOL_TAGS[t].map(w => ({word: w, count: 1}));
      await addWordsToCloud(words, toolIdx);
      toolIdx++;
    }
  }, 600);

  try {
    const resp = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: la, lon: lo })
    });
    const result = await resp.json();
    if (result.error) throw new Error(result.error);

    clearInterval(streamInterval);

    // Extract words from all tool results + briefing and add to cloud
    const allText = [
      ...(result.tools || []).map(t => t.result || ""),
      result.briefing?.geomorphology || "",
      result.briefing?.stratigraphy || "",
      result.briefing?.spectral_mineralogy || "",
      result.briefing?.topography || "",
      result.briefing?.named_feature || "",
      (result.briefing?.notable_features || []).join(" "),
    ].join(" ");

    const extracted = scoreWords(extractWords(allText));
    // Add in batches with slight delay between each word
    await addWordsToCloud(extracted.slice(0, 60), 7);

    // Render briefing
    const b = result.briefing || {};
    let html = "";
    if (result.location_name) html += '<div class="briefing-title">'+result.location_name+' ('+la.toFixed(2)+'&deg;, '+lo.toFixed(2)+'&deg;)</div>';
    if (b.named_feature) html += '<div class="named-feature-box"><div class="nf-label">Named feature</div><div class="nf-body">'+b.named_feature+'</div></div>';
    [["Geomorphology",b.geomorphology],["Stratigraphy",b.stratigraphy],
     ["Spectral mineralogy",b.spectral_mineralogy],["Topography",b.topography]
    ].forEach(([label,text])=>{
      if(text) html+='<div class="section"><div class="sec-label">'+label+'</div><div class="sec-body">'+text+'</div></div>';
    });
    if(b.notable_features?.length) html+='<div class="section"><div class="sec-label">Notable features</div><div class="tags">'+tags(b.notable_features)+'</div></div>';
    if(b.relevant_researchers?.length) html+='<div class="section"><div class="sec-label">Key researchers</div><div class="tags">'+tags(b.relevant_researchers,"researcher")+'</div></div>';
    if(b.confidence_notes) html+='<div class="confidence">'+b.confidence_notes+'</div>';
    document.getElementById("briefingOut").innerHTML = html;

  } catch(err) {
    clearInterval(streamInterval);
    agentErrEl.textContent = "Agent error: " + err.message;
    agentErrEl.style.display = "block";
    document.getElementById("briefingOut").innerHTML = '<p class="empty">Briefing unavailable.</p>';
  }

  btn.disabled = false;
}
</script>
</body>
</html>"""


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
