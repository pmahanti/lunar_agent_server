import os, json, math, sqlite3
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import anthropic, urllib.request

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

DB_PATH = os.environ.get("DB_PATH", "/tmp/lunar_queries.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL, lon REAL, location_name TEXT,
            result_json TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.commit(); conn.close()

init_db()

def haversine(lat1, lon1, lat2, lon2):
    R = 1737.4
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def key_word(name):
    skip = {"mare","region","basin","area","western","eastern","northern","southern","central"}
    words = [w.lower() for w in (name or "").split() if w.lower() not in skip]
    return words[0] if words else ""

def find_cached(la, lo, radius_km=15):
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT lat,lon,location_name,result_json FROM queries ORDER BY ts DESC LIMIT 500").fetchall()
        conn.close()
        for rlat,rlon,rname,rjson in rows:
            dist = haversine(la, lo, rlat, rlon)
            if dist <= radius_km:
                return rname, json.loads(rjson), round(dist, 2)
    except Exception:
        pass
    return None, None, None

def save_query(la, lo, location_name, result):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO queries (lat,lon,location_name,result_json) VALUES (?,?,?,?)",
                     (la, lo, location_name, json.dumps(result)))
        conn.commit(); conn.close()
    except Exception:
        pass

@app.route("/map-tile")
def map_tile():
    try:
        la = float(request.args.get("lat", 0))
        lo = float(request.args.get("lon", 0))
        d  = float(request.args.get("d", 2.5))
        bbox = f"{lo-d},{la-d},{lo+d},{la+d}"
        url = (f"https://wms.im-ldi.com/wms?SERVICE=WMS&VERSION=1.1.1"
               f"&REQUEST=GetMap&LAYERS=luna_wac_global&BBOX={bbox}"
               f"&WIDTH=480&HEIGHT=300&SRS=EPSG:4326&FORMAT=image/png&STYLES=")
        req = urllib.request.Request(url, headers={"User-Agent": "LunarGeoAgent/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read()
        return Response(data, mimetype="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

SYSTEM = """You are a lunar geology agent with the Lunar Geology Skill Library. Simulate 6 Python tools then synthesize a briefing.

named_feature_lookup checks: Swirls (Reiner Gamma ~7.5N 59W, Mare Ingenii, Airy, Marginis, Gerasimovich, Hopmann, Rima Sirsalis, Firsov); Domes (Rumker Hills, Gruithuisen gamma/delta ~36N 40W, Marius Hills, Hortensius, Cauchy); Scarps (Discovery Rupes, Lee-Lincoln, Rupes Recta ~22S 8W, Altai); Rilles/vents: Vallis Schroteri ~25N 50W, Cobra Head vent ~24.5N 49.5W (elliptical ~10km collapse pit, lava tube vent), Hadley Rille ~25N 3.6E, Rima Hyginus ~7.5N 7.8E, Rima Ariadaeus ~6.5N 14E; Wrinkle ridges; Pyroclastics (Alphonsus, Aristarchus plateau glass beads); Magnetic anomalies; Named mare/highland units. Report none if >50km.

PRIORITY: Named feature beats regional. Feature within ~15km = primary ID.

Respond ONLY valid JSON no markdown:
{"location_name":"named feature if within ~10km else regional","tools":[{"tool":"LROC_proximity_search","result":"..."},{"tool":"crater_catalog_query","result":"..."},{"tool":"named_feature_lookup","result":"..."},{"tool":"spectral_unit_lookup","result":"..."},{"tool":"topography_query","result":"..."},{"tool":"thermal_inertia_lookup","result":"..."}],"briefing":{"geomorphology":"2-3 sentences","stratigraphy":"2-3 sentences","spectral_mineralogy":"2-3 sentences","topography":"1-2 sentences","named_feature":"name,type,properties,significance if present else omit","notable_features":["f1","f2","f3"],"relevant_researchers":["Last, F. (specialty)","Last, F. (specialty)","Last, F. (specialty)"],"confidence_notes":"1 sentence"}}"""

@app.route("/query", methods=["POST"])
def query():
    data = request.get_json()
    if not data: return jsonify({"error": "no JSON body"}), 400
    la = data.get("lat"); lo = data.get("lon")
    if la is None or lo is None: return jsonify({"error": "lat and lon required"}), 400
    if not (-90<=la<=90) or not (-180<=lo<=180): return jsonify({"error": "coordinates out of range"}), 400
    cached_name, cached_result, dist_km = find_cached(la, lo)
    if cached_result and key_word(cached_name) == key_word(cached_result.get("location_name","")):
        cached_result["_cached"] = True
        cached_result["_cache_dist_km"] = dist_km
        cached_result["_cache_location"] = cached_name
        cached_result["_lroc_images"] = find_lroc_nearby(la, lo)
        return jsonify(cached_result)
    # Find nearby LROC featured images
    lroc_images = find_lroc_nearby(la, lo)
    lroc_ctx = ""
    if lroc_images:
        lroc_ctx = "\n\nNearby LROC Featured Images (reference these if relevant):\n"
        for img in lroc_images:
            lroc_ctx += f"- [{img['title']}]({img['url']}) — {img['dist_km']} km away\n"

    try:
        msg = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=4096, system=SYSTEM,
            messages=[{"role":"user","content":f"Coordinates: lat={la}, lon={lo}{lroc_ctx}"}])
        raw = msg.content[0].text.strip()
        result = json.loads(raw.replace("```json","").replace("```","").strip())
        save_query(la, lo, result.get("location_name",""), result)
        result["_cached"] = False
        result["_lroc_images"] = find_lroc_nearby(la, lo)
        return jsonify(result)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSON parse error: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stats")
def stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        total  = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
        recent = conn.execute("SELECT lat,lon,location_name,ts FROM queries ORDER BY ts DESC LIMIT 10").fetchall()
        conn.close()
        return jsonify({"total_queries":total,"recent":[{"lat":r[0],"lon":r[1],"name":r[2],"ts":r[3]} for r in recent]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── LROC featured images ──────────────────────────────────────────────────────
import threading, time, urllib.parse
from bs4 import BeautifulSoup

LROC_BASE = "https://lroc.im-ldi.com"

def init_lroc_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lroc_images (
            id INTEGER PRIMARY KEY,
            title TEXT, url TEXT, thumbnail TEXT,
            snippet TEXT, lat REAL, lon REAL,
            scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.commit(); conn.close()

init_lroc_table()

def extract_coords(text):
    import re
    pats = [
        r'([-]?\d+\.?\d*)\s*°?\s*([NnSs])[,;\s]+\s*([-]?\d+\.?\d*)\s*°?\s*([EeWw])',
        r'(?:centered at|center:|located at|center)\s*([-]?\d+\.?\d*)[°\s,]+\s*([-]?\d+\.?\d*)',
    ]
    for pat in pats:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            g = m.groups()
            if len(g) == 4:
                lat = float(g[0]) * (-1 if g[1].upper() == 'S' else 1)
                lon = float(g[2]) * (-1 if g[3].upper() == 'W' else 1)
            else:
                lat, lon = float(g[0]), float(g[1])
            if lon > 180: lon -= 360
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return round(lat, 4), round(lon, 4)
    return None, None

def lroc_already_scraped(image_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT id FROM lroc_images WHERE id=?", (image_id,)).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False

def save_lroc_image(image_id, title, url, thumbnail, snippet, lat, lon):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO lroc_images (id,title,url,thumbnail,snippet,lat,lon) VALUES (?,?,?,?,?,?,?)",
            (image_id, title, url, thumbnail, snippet, lat, lon))
        conn.commit(); conn.close()
    except Exception:
        pass

def scrape_lroc_pages():
    """Background thread: scrape LROC listing pages, extract coords, store in DB."""
    time.sleep(5)  # wait for app to start
    page = 1
    while True:
        try:
            url = f"{LROC_BASE}/images?page={page}"
            req = urllib.request.Request(url, headers={"User-Agent": "LunarGeoAgent/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("a.block-link")
            if not cards:
                break  # no more pages
            new_count = 0
            for card in cards:
                href = card.get("href", "")
                import re
                m = re.search(r'/images/(\d+)', href)
                if not m: continue
                image_id = int(m.group(1))
                if lroc_already_scraped(image_id): continue
                title_el = card.select_one("h3.card-title")
                title = title_el.get_text(strip=True) if title_el else ""
                snippet_el = card.select_one("p.card-text.flex-grow-1")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                img_el = card.select_one("img.card-img-top")
                thumbnail = img_el.get("src", "") if img_el else ""
                if thumbnail and not thumbnail.startswith("http"):
                    thumbnail = LROC_BASE + thumbnail
                lat, lon = extract_coords(snippet)
                if lat is None:  # try title too
                    lat, lon = extract_coords(title)
                save_lroc_image(image_id, title, LROC_BASE + href, thumbnail, snippet, lat, lon)
                new_count += 1
                time.sleep(0.5)
            page += 1
            time.sleep(2)
            if new_count == 0 and page > 2:
                break  # all already scraped
        except Exception as e:
            time.sleep(30)
            break

# Start background scraper
threading.Thread(target=scrape_lroc_pages, daemon=True).start()

def find_lroc_nearby(la, lo, radius_km=120, limit=3):
    """Find nearby LROC featured images within radius_km."""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute("SELECT id, title, url, thumbnail, snippet, lat, lon FROM lroc_images WHERE lat IS NOT NULL ORDER BY id DESC").fetchall()
        except Exception:
            rows = []
        conn.close()
        results = []
        for row in rows:
            rid, title, url, thumb, snippet, rlat, rlon = row
            dist = haversine(la, lo, rlat, rlon)
            if dist <= radius_km:
                results.append({"id":rid,"title":title,"url":url,"thumbnail":thumb,
                                 "snippet":snippet[:200],"dist_km":round(dist,1)})
        results.sort(key=lambda x: x["dist_km"])
        return results[:limit]
    except Exception:
        return []

@app.route("/lroc-index-status")
def lroc_index_status():
    try:
        conn = sqlite3.connect(DB_PATH)
        total = conn.execute("SELECT COUNT(*) FROM lroc_images").fetchone()[0]
        with_coords = conn.execute("SELECT COUNT(*) FROM lroc_images WHERE lat IS NOT NULL").fetchone()[0]
        conn.close()
        return jsonify({"indexed": total, "with_coords": with_coords})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── PDF generation ────────────────────────────────────────────────────────────
def build_pdf(la, lo, result):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Image, HRFlowable, KeepTogether)
    from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
    from reportlab.platypus.flowables import Flowable
    import datetime, tempfile, os

    W_page, H_page = letter
    M = 0.65 * inch
    W = W_page - 2 * M

    C = {
        "header":  HexColor("#0a1a3a"),
        "accent":  HexColor("#1a6ebd"),
        "teal":    HexColor("#0f6e56"),
        "body":    HexColor("#374151"),
        "muted":   HexColor("#6b7280"),
        "border":  HexColor("#d1d5db"),
        "feat_bg": HexColor("#f0fdf4"),
        "feat_br": HexColor("#86efac"),
        "feat_tx": HexColor("#14532d"),
    }

    class HeaderBar(Flowable):
        def __init__(self, coords, date_str, width):
            Flowable.__init__(self)
            self.coords = coords; self.date_str = date_str
            self.width = width; self.height = 52
        def draw(self):
            cv = self.canv
            cv.setFillColor(C["header"])
            cv.rect(0, 0, self.width, self.height, fill=1, stroke=0)
            cv.setFillColor(HexColor("#38bdf8"))
            cv.circle(16, self.height/2, 4, fill=1, stroke=0)
            cv.setFillColor(white); cv.setFont("Helvetica-Bold", 13)
            cv.drawString(28, self.height/2 + 3, "Lunar Geology Brief")
            cv.setFont("Helvetica", 8.5); cv.setFillColor(HexColor("#94a3b8"))
            cv.drawRightString(self.width-10, self.height/2 + 3, self.coords)
            cv.drawRightString(self.width-10, self.height/2 - 10, self.date_str)

    class FeatureBox(Flowable):
        def __init__(self, text, width):
            Flowable.__init__(self)
            self._t = text; self.width = width; self._p = 9
            cpp = int((width - 2*self._p) / 5.8)
            lines = max(2, len(text)//cpp + 1)
            self.height = 16 + lines * 13 + 2*self._p
        def draw(self):
            cv = self.canv
            cv.setFillColor(C["feat_bg"]); cv.setStrokeColor(C["feat_br"])
            cv.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)
            cv.setFont("Helvetica-Bold", 7.5); cv.setFillColor(C["teal"])
            cv.drawString(self._p, self.height-self._p-7, "NAMED FEATURE")
            cv.setFont("Helvetica", 9); cv.setFillColor(C["feat_tx"])
            words = self._t.split()
            line, y = [], self.height - self._p - 20
            mw = self.width - 2*self._p
            for w in words:
                test = " ".join(line+[w])
                if cv.stringWidth(test,"Helvetica",9) > mw:
                    cv.drawString(self._p, y, " ".join(line)); y -= 12; line = [w]
                else:
                    line.append(w)
            if line: cv.drawString(self._p, y, " ".join(line))

    def S(name, **kw):
        defaults = dict(fontName="Helvetica", fontSize=9.5, textColor=C["body"],
                        leading=14, spaceAfter=5)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    ST = {
        "loc":     S("loc", fontName="Helvetica-Bold", fontSize=17, textColor=C["header"], spaceAfter=3, leading=20),
        "sub":     S("sub", fontSize=9.5, textColor=C["muted"], spaceAfter=12),
        "caption": S("cap", fontName="Helvetica-Oblique", fontSize=8.5, textColor=C["muted"], spaceAfter=8, leading=12),
        "label":   S("lbl", fontName="Helvetica-Bold", fontSize=7.5, textColor=C["accent"], spaceBefore=10, spaceAfter=2, leading=10),
        "body":    S("bod", alignment=TA_JUSTIFY, spaceAfter=6),
        "tag":     S("tag", fontSize=8.5, textColor=C["accent"], spaceAfter=2),
        "footer":  S("ftr", fontSize=7, textColor=C["muted"], alignment=TA_CENTER),
        "pub":     S("pub", fontName="Helvetica-Oblique", fontSize=8.5, textColor=C["muted"], spaceBefore=6),
        "lroc_h":  S("lroc_h", fontName="Helvetica-Bold", fontSize=8.5, textColor=C["accent"], spaceAfter=4, spaceBefore=10),
        "lroc_t":  S("lroc_t", fontSize=8.5, textColor=HexColor("#1a6ebd"), spaceAfter=2, leading=12),
        "lroc_d":  S("lroc_d", fontSize=7.5, textColor=C["muted"], spaceAfter=6),
    }

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=M, rightMargin=M,
                            topMargin=0.3*inch, bottomMargin=0.45*inch)
    story = []
    date_str = datetime.date.today().strftime("%d %B %Y")
    loc_name = result.get("location_name", f"{la:.4f}°, {lo:.4f}°")
    b = result.get("briefing", {})

    # Header bar
    coords_str = f"{la:.4f}°{'N' if la>=0 else 'S'}, {abs(lo):.4f}°{'E' if lo>=0 else 'W'}"
    story.append(HeaderBar(coords_str, date_str, W))
    story.append(Spacer(1, 12))

    # Location title
    story.append(Paragraph(loc_name, ST["loc"]))
    story.append(Paragraph(f"{coords_str}  ·  Generated {date_str}", ST["sub"]))

    # Map image from LunaServ
    try:
        d = 2.5
        bbox = f"{lo-d},{la-d},{lo+d},{la+d}"
        url = (f"https://wms.im-ldi.com/wms?SERVICE=WMS&VERSION=1.1.1"
               f"&REQUEST=GetMap&LAYERS=luna_wac_global&BBOX={bbox}"
               f"&WIDTH=900&HEIGHT=560&SRS=EPSG:4326&FORMAT=image/png&STYLES=")
        req = urllib.request.Request(url, headers={"User-Agent": "LunarGeoAgent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            img_data = r.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(img_data); tmp.close()
        story.append(Image(tmp.name, width=W, height=W*0.56))
        story.append(Paragraph(
            f"LROC WAC Global Mosaic — {loc_name}. "
            f"Field of view ~{d*2*30:.0f} km. "
            "[NASA/GSFC/Arizona State University | LunaServ WMS]",
            ST["caption"]))
        os.unlink(tmp.name)
    except Exception:
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 6))

    # Named feature
    nf = b.get("named_feature", "")
    if nf:
        story.append(FeatureBox(nf, W))
        story.append(Spacer(1, 8))

    # Science sections
    for label, key in [("GEOMORPHOLOGY","geomorphology"),("STRATIGRAPHY","stratigraphy"),
                        ("SPECTRAL MINERALOGY","spectral_mineralogy"),("TOPOGRAPHY","topography")]:
        text = b.get(key, "")
        if text:
            story.append(KeepTogether([
                Paragraph(label, ST["label"]),
                Paragraph(text, ST["body"]),
            ]))

    # Tags
    nots = b.get("notable_features", [])
    if nots:
        story.append(Paragraph("NOTABLE FEATURES", ST["label"]))
        story.append(Paragraph("  ·  ".join(nots), ST["tag"]))
    researchers = b.get("relevant_researchers", [])
    if researchers:
        story.append(Paragraph("KEY RESEARCHERS", ST["label"]))
        story.append(Paragraph("  ·  ".join(researchers), ST["tag"]))
    conf = b.get("confidence_notes","")
    if conf:
        story.append(Paragraph(conf, ST["pub"]))

    # Nearby LROC images
    lroc_imgs = result.get("_lroc_images") or find_lroc_nearby(la, lo)
    if lroc_imgs:
        story.append(Spacer(1, 8))
        story.append(Paragraph("NEARBY LROC FEATURED IMAGES", ST["lroc_h"]))
        for img in lroc_imgs:
            story.append(Paragraph(
                f'<link href="{img["url"]}" color="#1a6ebd">{img["title"]}</link>',
                ST["lroc_t"]))
            story.append(Paragraph(
                f'{img["dist_km"]} km from query point  ·  {img["url"]}',
                ST["lroc_d"]))

    # Footer
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", color=C["border"], thickness=0.4))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        f"Generated by Lunar Geology Brief  ·  {date_str}  ·  "
        "Briefing synthesized by Claude (Anthropic)  ·  "
        "Imagery: LROC WAC Global Mosaic [NASA/GSFC/Arizona State University]",
        ST["footer"]))
    story.append(Paragraph(
        "Lunar Reconnaissance Orbiter Camera  ·  Science Operations Center  ·  Arizona State University",
        ST["footer"]))

    doc.build(story)
    return buf.getvalue()


HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n<title>Lunar Geology Brief</title>\n<style>\n*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\nbody { font-family: system-ui, sans-serif; background: #070d1a; color: #e2e8f0; }\n.header { padding: 1.5rem 2rem 1.25rem; border-bottom: 1px solid rgba(255,255,255,0.06); }\n.header-inner { max-width: 1040px; margin: 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }\n.brand { display: flex; align-items: center; gap: 10px; }\n.brand-dot { width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; box-shadow: 0 0 8px #38bdf8; flex-shrink: 0; }\n.brand h1 { font-size: 15px; font-weight: 500; letter-spacing: 0.04em; color: #f1f5f9; }\n.brand p  { font-size: 11px; color: #475569; margin-top: 2px; }\n.presets { display: flex; gap: 5px; flex-wrap: wrap; }\n.preset { font-size: 11px; padding: 3px 10px; border-radius: 20px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); color: #94a3b8; cursor: pointer; transition: all 0.15s; }\n.preset:hover { background: rgba(56,189,248,0.1); border-color: rgba(56,189,248,0.3); color: #38bdf8; }\n.input-section { max-width: 1040px; margin: 1.2rem auto 0; padding: 0 2rem; }\n.input-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: end; }\n.input-row label { display: block; font-size: 10px; color: #334155; margin-bottom: 5px; letter-spacing: 0.08em; text-transform: uppercase; }\n.input-row input { width: 100%; font-family: monospace; font-size: 13px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 9px 12px; color: #e2e8f0; transition: border-color 0.15s; }\n.input-row input:focus { outline: none; border-color: rgba(56,189,248,0.4); }\n.input-row input::placeholder { color: #1e3a5f; }\n#runBtn { height: 38px; padding: 0 22px; font-size: 13px; font-weight: 500; background: #0ea5e9; border: none; border-radius: 8px; color: #fff; cursor: pointer; transition: background 0.15s; white-space: nowrap; }\n#runBtn:hover { background: #38bdf8; }\n#runBtn:disabled { opacity: 0.35; cursor: not-allowed; }\n.err { font-size: 11px; color: #f87171; margin-top: 5px; min-height: 16px; }\n.agent-err { font-size: 12px; color: #fca5a5; background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.15); border-radius: 8px; padding: 8px 12px; margin-top: 8px; display: none; }\n.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; max-width: 1040px; margin: 1.25rem auto 0; padding: 0 2rem 2rem; }\n@media (max-width: 660px) { .panels { grid-template-columns: 1fr; } .input-row { grid-template-columns: 1fr; } }\n.panel { background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.07); border-radius: 12px; padding: 1.1rem; }\n.panel-label { font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: #1e3a5f; margin-bottom: 12px; }\n.map-wrap { position: relative; width: 100%; height: 170px; border-radius: 8px; overflow: hidden; background: #0a1628; margin-bottom: 12px; }\n.map-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0; transition: opacity 0.5s; }\n.map-wrap img.loaded { opacity: 1; }\n.map-cross { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); width: 14px; height: 14px; pointer-events: none; }\n.map-cross::before { content:""; position: absolute; width: 1px; height: 14px; background: #38bdf8; box-shadow: 0 0 4px #38bdf8; left: 50%; transform: translateX(-50%); }\n.map-cross::after  { content:""; position: absolute; height: 1px; width: 14px; background: #38bdf8; box-shadow: 0 0 4px #38bdf8; top: 50%; transform: translateY(-50%); }\n.map-loading { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #1e3a5f; }\n.zoom-btns { position: absolute; bottom: 6px; right: 6px; display: flex; gap: 3px; }\n.zoom-btn { width: 22px; height: 22px; background: rgba(0,0,0,0.55); border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; color: #94a3b8; font-size: 15px; cursor: pointer; display: flex; align-items: center; justify-content: center; }\n.zoom-btn:hover { background: rgba(56,189,248,0.2); color: #38bdf8; }\n#cloudPanel { position: relative; overflow: hidden; min-height: 340px; }\n#cloudWords { position: absolute; inset: 0; top: 32px; }\n.cloud-hint { font-size: 12px; color: #1e3a5f; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); white-space: nowrap; }\n.cw { position: absolute; font-weight: 500; line-height: 1; opacity: 0; transition: opacity 0.45s ease; white-space: nowrap; user-select: none; }\n.cw.show { opacity: 1; }\n#briefingPanel { min-height: 340px; }\n.briefing-scroll { overflow-y: auto; max-height: 490px; }\n.briefing-scroll::-webkit-scrollbar { width: 3px; }\n.briefing-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }\n.empty { font-size: 12px; color: #1e3a5f; }\n.cache-badge { display: inline-block; font-size: 10px; padding: 2px 7px; border-radius: 999px; background: rgba(251,191,36,0.1); color: #fbbf24; border: 1px solid rgba(251,191,36,0.2); margin-bottom: 10px; }\n.briefing-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #f1f5f9; }\n.briefing-coords { font-size: 11px; font-weight: 400; color: #334155; }\n.named-feature-box { margin-bottom: 12px; background: rgba(16,185,129,0.07); border: 1px solid rgba(16,185,129,0.18); border-radius: 8px; padding: 9px 11px; }\n.nf-label { font-size: 10px; font-weight: 600; color: #34d399; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 3px; }\n.nf-body { font-size: 12px; color: #a7f3d0; line-height: 1.65; }\n.section { margin-bottom: 10px; }\n.sec-label { font-size: 10px; font-weight: 600; color: #1e3a5f; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 2px; }\n.sec-body { font-size: 12px; color: #94a3b8; line-height: 1.65; }\n.tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }\n.tag { font-size: 10px; padding: 2px 7px; border-radius: 999px; background: rgba(56,189,248,0.08); color: #7dd3fc; border: 1px solid rgba(56,189,248,0.12); }\n.tag.researcher { background: rgba(255,255,255,0.03); color: #475569; border-color: rgba(255,255,255,0.06); }\n.lroc-section { margin-top: 12px; }\n.lroc-card { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.05); text-decoration: none; }\n.lroc-card:last-child { border-bottom: none; }\n.lroc-card:hover .lroc-title { color: #38bdf8; }\n.lroc-thumb { width: 52px; height: 38px; object-fit: cover; border-radius: 4px; flex-shrink: 0; background: #0a1628; }\n.lroc-info { flex: 1; min-width: 0; }\n.lroc-title { font-size: 11px; color: #94a3b8; line-height: 1.4; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-overflow: clip; }\n.lroc-dist { font-size: 10px; color: #334155; margin-top: 2px; }\n.confidence { font-size: 11px; color: #334155; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 6px 10px; border-left: 2px solid rgba(255,255,255,0.06); margin-top: 8px; font-style: italic; }\n</style>\n</head>\n<body>\n<div class="header">\n  <div class="header-inner">\n    <div class="brand">\n      <div class="brand-dot"></div>\n      <div><h1>Lunar Geology Brief</h1><p>Enter lunar surface coordinates &rarr; Get location geology</p></div>\n    </div>\n    <div class="presets" id="presets"></div>\n  </div>\n</div>\n<div class="input-section">\n  <div class="input-row">\n    <div>\n      <label for="coordInput">Coordinates &mdash; lat, lon</label>\n      <input id="coordInput" type="text" value="7.37, -59.02" placeholder="e.g. 7.37, -59.02" autocomplete="off">\n    </div>\n    <button id="runBtn" onclick="runAgent()">Generate</button>\n    <button id="pdfBtn" onclick="downloadPdf()" style="display:none;height:38px;padding:0 16px;font-size:12px;font-weight:500;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);border-radius:8px;color:#94a3b8;cursor:pointer;white-space:nowrap">&#8595; PDF</button>\n  </div>\n  <div class="err" id="coordErr"></div>\n  <div class="agent-err" id="agentErr"></div>\n</div>\n<div class="panels">\n  <div class="panel" id="cloudPanel">\n    <div class="panel-label">Keyword cloud</div>\n    <div id="cloudWords"><div class="cloud-hint" id="cloudHint">Run a query to build the cloud</div></div>\n  </div>\n  <div class="panel" id="briefingPanel">\n    <div class="panel-label">Geologic briefing</div>\n    <div class="map-wrap" id="mapWrap" style="display:none">\n      <div class="map-loading" id="mapLoading">Loading imagery&hellip;</div>\n      <img id="mapImg" alt="LunaServ WAC">\n      <div class="map-cross"></div>\n      <div class="zoom-btns">\n        <button class="zoom-btn" onclick="adjustZoom(-0.8)">+</button>\n        <button class="zoom-btn" onclick="adjustZoom(0.8)">&minus;</button>\n      </div>\n    </div>\n    <div class="briefing-scroll">\n      <div id="briefingOut"><p class="empty">Briefing appears here&hellip;</p></div>\n    </div>\n  </div>\n</div>\n<script>\nconst PRESETS=[{label:"Reiner Gamma",lat:7.37,lon:-59.02},{label:"Cobra Head",lat:24.65,lon:-49.24},{label:"Apollo 11",lat:0.67,lon:23.47},{label:"Tycho",lat:-43.31,lon:-11.36},{label:"Mare Imbrium",lat:32.8,lon:-15.6},{label:"Aristarchus",lat:26.0,lon:-47.5}];\nconst TOOLS=["LROC_proximity_search","crater_catalog_query","named_feature_lookup","spectral_unit_lookup","topography_query","thermal_inertia_lookup"];\nconst TOOL_SEEDS={\n  "LROC_proximity_search":[{w:"LROC",s:20},{w:"NAC",s:15},{w:"WAC",s:13},{w:"imagery",s:13},{w:"morphology",s:14},{w:"mosaic",s:12}],\n  "crater_catalog_query":[{w:"craters",s:18},{w:"ejecta",s:15},{w:"morphometry",s:14},{w:"density",s:13},{w:"SFD",s:13},{w:"D/d",s:12}],\n  "named_feature_lookup":[{w:"named feature",s:18},{w:"swirl",s:16},{w:"dome",s:15},{w:"rille",s:15},{w:"scarp",s:14},{w:"anomaly",s:13}],\n  "spectral_unit_lookup":[{w:"FeO",s:20},{w:"TiO2",s:17},{w:"pyroxene",s:15},{w:"olivine",s:14},{w:"plagioclase",s:13}],\n  "topography_query":[{w:"LOLA",s:19},{w:"elevation",s:16},{w:"slope",s:15},{w:"roughness",s:14},{w:"DEM",s:14}],\n  "thermal_inertia_lookup":[{w:"Diviner",s:18},{w:"thermal inertia",s:16},{w:"regolith",s:15},{w:"rock abundance",s:13}]\n};\nconst SEED_COLORS=["#1d6fa4","#0e7490","#1d4ed8","#1a6b5e","#2563a8","#155e75"];\nconst RESULT_COLORS=["#38bdf8","#34d399","#818cf8","#fb923c","#a78bfa","#22d3ee","#4ade80","#60a5fa"];\nconst STOP=new Set("a an the and or but in on at to of for with from by is was are were be been has have had it its this that these those as if no not also such cm km nt per via very over near within about along show shows".split(" "));\n\nlet currentLat=0,currentLon=0,currentZoom=2.5,lastResult=null;\n\nfunction parseCoords(str){\n  const p=str.split(",").map(s=>s.trim());\n  if(p.length!==2)return null;\n  const la=parseFloat(p[0]),lo=parseFloat(p[1]);\n  if(isNaN(la)||isNaN(lo)||la<-90||la>90||lo<-180||lo>180)return null;\n  return{la,lo};\n}\n\nfunction adjustZoom(delta){\n  currentZoom=Math.max(0.4,Math.min(10,currentZoom+delta));\n  loadMap(currentLat,currentLon,currentZoom);\n}\n\nfunction loadMap(la,lo,d){\n  const wrap=document.getElementById("mapWrap"),img=document.getElementById("mapImg"),loading=document.getElementById("mapLoading");\n  wrap.style.display="block";\n  img.classList.remove("loaded");\n  loading.style.display="flex";\n  img.onload=function(){img.classList.add("loaded");loading.style.display="none";};\n  img.onerror=function(){loading.textContent="Imagery unavailable";};\n  img.src="/map-tile?lat="+la+"&lon="+lo+"&d="+d;\n}\n\nconst measurer=document.createElement("div");\nmeasurer.style.cssText="position:fixed;top:-9999px;left:-9999px;visibility:hidden;pointer-events:none;font-family:system-ui,sans-serif;font-weight:500;";\ndocument.body.appendChild(measurer);\n\nlet placedBoxes=[],seenWords=new Set();\n\nfunction cloudReset(){\n  placedBoxes=[];seenWords.clear();\n  document.getElementById("cloudWords").innerHTML=\'<div class="cloud-hint" id="cloudHint">Building\\u2026</div>\';\n}\n\nfunction measureEl(el){measurer.appendChild(el);const w=el.offsetWidth,h=el.offsetHeight;measurer.removeChild(el);return{w,h};}\n\nfunction overlaps(a,b){const p=4;return!(a.x+a.w+p<b.x||b.x+b.w+p<a.x||a.y+a.h+p<b.y||b.y+b.h+p<a.y);}\n\nfunction tryPlace(container,el,vertical){\n  const cw=container.clientWidth||380,ch=container.clientHeight||310;\n  const m=measureEl(el);\n  const bw=vertical?m.h:m.w,bh=vertical?m.w:m.h;\n  const cx=cw/2-bw/2,cy=ch/2-bh/2,maxR=Math.min(cw,ch)*0.46;\n  for(let r=0;r<maxR;r+=3){\n    const steps=Math.max(6,Math.floor(2*Math.PI*r/5));\n    const off=Math.random()*Math.PI*2;\n    for(let i=0;i<steps;i++){\n      const angle=off+2*Math.PI*i/steps;\n      const x=Math.round(cx+r*Math.cos(angle)),y=Math.round(cy+r*Math.sin(angle));\n      if(x<2||y<2||x+bw>cw-2||y+bh>ch-2)continue;\n      const box={x,y,w:bw,h:bh};\n      if(!placedBoxes.some(function(p){return overlaps(p,box);})){placedBoxes.push(box);el.style.left=x+"px";el.style.top=y+"px";return true;}\n    }\n  }\n  return false;\n}\n\nasync function addWord(text,size,color,vertical){\n  const key=text.toLowerCase();if(seenWords.has(key))return;seenWords.add(key);\n  const hint=document.getElementById("cloudHint");if(hint)hint.remove();\n  const container=document.getElementById("cloudWords");\n  const el=document.createElement("span");el.className="cw";el.textContent=text;\n  el.style.fontSize=size+"px";el.style.color=color;\n  if(vertical){el.style.writingMode="vertical-rl";el.style.transform="rotate(180deg)";}\n  if(!tryPlace(container,el,vertical))return;\n  container.appendChild(el);\n  await new Promise(function(r){requestAnimationFrame(r);});\n  await new Promise(function(r){requestAnimationFrame(r);});\n  el.classList.add("show");\n}\n\nasync function addWordList(words,colorFn,delay){\n  for(let i=0;i<words.length;i++){\n    await addWord(words[i].w,words[i].s,colorFn(i),Math.random()<0.28);\n    await new Promise(function(r){setTimeout(r,(delay||80)+Math.random()*50);});\n  }\n}\n\nfunction extractWords(text){\n  const freq={};\n  text.replace(/[()[\\]{},."\';:!?]/g," ").split(/\\s+/).map(function(w){return w.replace(/[^a-zA-Z0-9\\/-]/g,"");})\n    .filter(function(w){return w.length>=4&&!STOP.has(w.toLowerCase())&&!/^\\d+$/.test(w);})\n    .forEach(function(w){const k=w.toLowerCase();if(!freq[k])freq[k]=[w,0];freq[k][1]++;});\n  return Object.values(freq).sort(function(a,b){return b[1]-a[1];}).slice(0,55)\n    .map(function(entry,i){return{w:entry[0],s:Math.min(21,Math.max(10,10+Math.floor(entry[1]*2.5)+(i<4?5-i:0)))};});\n}\n\nfunction tags(arr,cls){return arr.map(function(f){return \'<span class="tag \'+(cls||"")+\'">\'+f+\'</span>\';}).join("");}\n\nconst presetsEl=document.getElementById("presets");\nPRESETS.forEach(function(p){\n  const btn=document.createElement("button");btn.className="preset";btn.textContent=p.label;\n  btn.onclick=function(){document.getElementById("coordInput").value=p.lat+", "+p.lon;document.getElementById("coordErr").textContent="";};\n  presetsEl.appendChild(btn);\n});\ndocument.getElementById("coordInput").addEventListener("keydown",function(e){if(e.key==="Enter")runAgent();});\n\nasync function downloadPdf(){\n  const btn=document.getElementById(\'pdfBtn\');\n  if(!lastResult) return;\n  const orig=btn.textContent; btn.textContent=\'Generating…\'; btn.disabled=true;\n  try{\n    const resp=await fetch(\'/pdf\',{\n      method:\'POST\',headers:{\'Content-Type\':\'application/json\'},\n      body:JSON.stringify({lat:currentLat,lon:currentLon,result:lastResult})\n    });\n    if(!resp.ok){const e=await resp.json().catch(()=>({error:resp.status}));throw new Error(e.error||resp.status);}\n    const blob=await resp.blob();\n    const url=URL.createObjectURL(blob);\n    const a=document.createElement(\'a\');\n    const safe=(lastResult.location_name||\'brief\').replace(/[^a-z0-9]/gi,\'_\').slice(0,40);\n    a.download=\'lunar_brief_\'+safe+\'.pdf\'; a.href=url;\n    document.body.appendChild(a); a.click(); document.body.removeChild(a);\n    URL.revokeObjectURL(url);\n  } catch(err){ alert(\'PDF error: \'+err.message); }\n  btn.textContent=orig; btn.disabled=false;\n}\n\nasync function runAgent(){\n  document.getElementById("coordErr").textContent="";\n  const errEl=document.getElementById("agentErr");errEl.style.display="none";\n  const parsed=parseCoords(document.getElementById("coordInput").value);\n  if(!parsed){document.getElementById("coordErr").textContent="Enter as: lat, lon (lat -90..90, lon -180..180)";return;}\n  const la=parsed.la,lo=parsed.lo;\n  currentLat=la;currentLon=lo;currentZoom=2.5;\n  document.getElementById("runBtn").disabled=true;\n  lastResult=null; cloudReset(); document.getElementById(\'pdfBtn\').style.display=\'none\';\n  document.getElementById("briefingOut").innerHTML=\'<p class="empty">Waiting for agent\\u2026</p>\';\n  loadMap(la,lo,currentZoom);\n\n  let toolIdx=0,streaming=true;\n  (async function(){\n    while(streaming&&toolIdx<TOOLS.length){\n      const seeds=TOOL_SEEDS[TOOLS[toolIdx]],ci=toolIdx;\n      await addWordList(seeds,function(i){return SEED_COLORS[ci%SEED_COLORS.length];},100);\n      toolIdx++;\n      await new Promise(function(r){setTimeout(r,150);});\n    }\n  })();\n\n  try{\n    const resp=await fetch("/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lat:la,lon:lo})});\n    const result=await resp.json();\n    if(result.error)throw new Error(result.error);\n    streaming=false;\n\n    const allText=[(result.tools||[]).map(function(t){return t.result||"";}).join(" "),\n      (result.briefing||{}).geomorphology||"",(result.briefing||{}).stratigraphy||"",\n      (result.briefing||{}).spectral_mineralogy||"",(result.briefing||{}).topography||"",\n      (result.briefing||{}).named_feature||"",((result.briefing||{}).notable_features||[]).join(" ")].join(" ");\n    await addWordList(extractWords(allText),function(i){return RESULT_COLORS[i%RESULT_COLORS.length];},50);\n\n    const b=result.briefing||{};let html="";\n    // PDF download button\n    lastResult = result;\n    document.getElementById(\'pdfBtn\').style.display=\'inline-block\';\n    if(result._cached)html+=\'<div class="cache-badge">&#9889; Cached &mdash; \'+result._cache_dist_km+\' km from \'+result._cache_location+\'</div>\';\n    if(result.location_name)html+=\'<div class="briefing-title">\'+result.location_name+\' <span class="briefing-coords">(\'+la.toFixed(2)+\'&deg;, \'+lo.toFixed(2)+\'&deg;)</span></div>\';\n    if(b.named_feature)html+=\'<div class="named-feature-box"><div class="nf-label">Named feature</div><div class="nf-body">\'+b.named_feature+\'</div></div>\';\n    [["Geomorphology",b.geomorphology],["Stratigraphy",b.stratigraphy],["Spectral mineralogy",b.spectral_mineralogy],["Topography",b.topography]].forEach(function(pair){\n      if(pair[1])html+=\'<div class="section"><div class="sec-label">\'+pair[0]+\'</div><div class="sec-body">\'+pair[1]+\'</div></div>\';\n    });\n    if(b.notable_features&&b.notable_features.length)html+=\'<div class="section"><div class="sec-label">Notable features</div><div class="tags">\'+tags(b.notable_features)+\'</div></div>\';\n    if(b.relevant_researchers&&b.relevant_researchers.length)html+=\'<div class="section"><div class="sec-label">Key researchers</div><div class="tags">\'+tags(b.relevant_researchers,"researcher")+\'</div></div>\';\n    if(b.confidence_notes)html+=\'<div class="confidence">\'+b.confidence_notes+\'</div>\';\n    // LROC nearby images\n    if(result._lroc_images && result._lroc_images.length){\n      html+=\'<div class="lroc-section"><div class="sec-label">Nearby LROC featured images</div>\';\n      result._lroc_images.forEach(function(img){\n        html+=\'<a class="lroc-card" href="\'+img.url+\'" target="_blank" rel="noopener">\';\n        if(img.thumbnail) html+=\'<img class="lroc-thumb" src="\'+img.thumbnail+\'" alt="" loading="lazy">\';\n        html+=\'<div class="lroc-info"><div class="lroc-title">\'+img.title+\'</div>\';\n        html+=\'<div class="lroc-dist">\'+img.dist_km+\' km away</div></div></a>\';\n      });\n      html+=\'</div>\';\n    }\n    document.getElementById("briefingOut").innerHTML=html;\n  }catch(err){\n    streaming=false;\n    errEl.textContent="Error: "+err.message;errEl.style.display="block";\n    document.getElementById("briefingOut").innerHTML=\'<p class="empty">Briefing unavailable.</p>\';\n  }\n  document.getElementById("runBtn").disabled=false;\n}\n</script>\n</body>\n</html>\n'


@app.route("/pdf", methods=["POST"])
def generate_pdf():
    data = request.get_json()
    if not data:
        return jsonify({"error": "no JSON body"}), 400
    try:
        la     = float(data["lat"])
        lo     = float(data["lon"])
        result = data["result"]
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        pdf_bytes = build_pdf(la, lo, result)
        safe  = result.get("location_name","brief").replace(" ","_").replace("/","_")[:40]
        fname = "lunar_brief_" + safe + ".pdf"
        return Response(pdf_bytes, mimetype="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="' + fname + '"'})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/")
def index():
    return HTML, 200, {"Content-Type": "text/html"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
