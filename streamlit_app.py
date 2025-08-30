import streamlit as st
import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon

DIST_THRESHOLD = 30  # meter

def parse_kmz(kmz_path):
    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_path, 'r') as zf:
        zf.extractall(tmpdir)
    kml_file = None
    for root, _, files in os.walk(tmpdir):
        for f in files:
            if f.endswith('.kml'):
                kml_file = os.path.join(root, f)
                break
    if not kml_file:
        raise FileNotFoundError("KML file tidak ditemukan dalam KMZ")
    tree = ET.parse(kml_file)
    return tree, tmpdir

def extract_geometry(pm):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    geom = pm.find(".//kml:Point/kml:coordinates", ns)
    if geom is not None:
        lon, lat, *_ = map(float, geom.text.strip().split(","))
        return Point(lon, lat)
    geom = pm.find(".//kml:LineString/kml:coordinates", ns)
    if geom is not None:
        coords = [(float(c.split(",")[0]), float(c.split(",")[1])) for c in geom.text.strip().split()]
        return LineString(coords)
    geom = pm.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    if geom is not None:
        coords = [(float(c.split(",")[0]), float(c.split(",")[1])) for c in geom.text.strip().split()]
        return Polygon(coords)
    return None

def classify_poles(tree):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    doc = tree.getroot()

    poles = []
    for pm in doc.findall(".//kml:Folder[kml:name='POLE']//kml:Placemark", ns):
        name = pm.find("kml:name", ns).text
        geom = extract_geometry(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    result = {f"LINE {ch}": {"POLE": []} for ch in ["A", "B", "C", "D"]}

    line_info = {}
    for line_folder in doc.findall(".//kml:Folder", ns):
        line_name = line_folder.find("kml:name", ns).text
        if not line_name or not line_name.upper().startswith("LINE"):
            continue

        cable, boundaries = None, []
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            geom = extract_geometry(pm)
            if "DISTRIBUTION CABLE" in nm:
                cable = geom
            if "BOUNDARY" in nm:
                boundaries.append((nm, geom))

        line_info[line_name.upper()] = {"cable": cable, "boundaries": boundaries}

    for name, p in poles:
        assigned = False
        for line_name in result.keys():
            info = line_info.get(line_name.upper())
            if not info:
                continue
            cable = info["cable"]
            if cable and isinstance(cable, LineString):
                d = p.distance(cable)
                if d <= DIST_THRESHOLD / 111320:  # approx deg → meter
                    result[line_name]["POLE"].append((name, p))
                    assigned = True
                    break
            for bname, boundary in info["boundaries"]:
                if isinstance(boundary, Polygon) and p.within(boundary):
                    if bname[0].upper() in line_name.upper():
                        result[line_name]["POLE"].append((name, p))
                        assigned = True
                        break
            if assigned:
                break
    return result

def export_kmz(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    kml = simplekml.Kml()
    for line_name, content in classified.items():
        f_line = kml.newfolder(name=line_name)
        f_pole = f_line.newfolder(name="POLE")
        for i, (old_name, p) in enumerate(content.get("POLE", []), 1):
            new_name = f"{prefix}{str(i).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
    kml.savekmz(output_path)

# ---------------- Streamlit ----------------
st.title("📍 Urutkan POLE ke LINE (KMZ)")

uploaded = st.file_uploader("Upload file KMZ", type="kmz")
if uploaded:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    st.success("✅ KMZ berhasil dibaca, memproses...")

    tree, _ = parse_kmz(tmp_path)
    classified = classify_poles(tree)

    out_path = tmp_path.replace(".kmz", "_output.kmz")
    export_kmz(classified, out_path)

    with open(out_path, "rb") as f:
        st.download_button("⬇️ Download hasil KMZ", f, file_name="POLE_output.kmz")
