import os, json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__, static_folder="static")
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


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/query", methods=["POST"])
def query():
    data = request.get_json()
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
