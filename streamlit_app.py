import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon
import streamlit as st

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 30  

def load_file(uploaded_file):
    """Terima file .kml atau .kmz, return tree XML"""
    tmpdir = tempfile.mkdtemp()
    filepath = os.path.join(tmpdir, uploaded_file.name)
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if filepath.endswith(".kmz"):
        with zipfile.ZipFile(filepath, 'r') as zf:
            zf.extractall(tmpdir)
        # cari file KML di dalam KMZ
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith(".kml"):
                    filepath = os.path.join(root, f)
                    break

    # parse KML (abaikan namespace aneh)
    parser = ET.XMLParser(recover=True, ns_clean=True)
    tree = ET.parse(filepath, parser=parser)
    return tree


def extract_geometry(placemark):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    geom = placemark.find(".//kml:Point/kml:coordinates", ns)
    if geom is not None:
        lon, lat, *_ = map(float, geom.text.strip().split(","))
        return Point(lon, lat)

    geom = placemark.find(".//kml:LineString/kml:coordinates", ns)
    if geom is not None:
        coords = [(float(c.split(",")[0]), float(c.split(",")[1])) 
                  for c in geom.text.strip().split()]
        return LineString(coords)

    geom = placemark.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    if geom is not None:
        coords = [(float(c.split(",")[0]), float(c.split(",")[1])) 
                  for c in geom.text.strip().split()]
        return Polygon(coords)
    return None


def classify_poles(tree):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    doc = tree.getroot()

    # poles
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

        cable = None
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "DISTRIBUTION CABLE" in nm:
                cable = extract_geometry(pm)

        boundaries = []
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "BOUNDARY" in nm:
                boundaries.append((nm, extract_geometry(pm)))

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
                if d <= DIST_THRESHOLD / 111320:
                    result[line_name]["POLE"].append((name, p))
                    assigned = True
                    break

            for bname, boundary in info["boundaries"]:
                if isinstance(boundary, Polygon) and p.within(boundary):
                    line_key = bname[0].upper()
                    if line_key in line_name.upper():
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
        poles = content.get("POLE", [])
        f_pole = f_line.newfolder(name="POLE")
        for i, (old_name, p) in enumerate(poles, 1):
            new_name = f"{prefix}{str(i).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
    kml.savekmz(output_path)


# ----------------
# STREAMLIT APP
# ----------------
st.title("Urutkan POLE ke Line")

uploaded_file = st.file_uploader("Upload KML atau KMZ", type=["kml", "kmz"])

if uploaded_file:
    try:
        tree = load_file(uploaded_file)
        classified = classify_poles(tree)

        out_path = os.path.join(tempfile.gettempdir(), "output_pole_per_line.kmz")
        export_kmz(classified, out_path)

        with open(out_path, "rb") as f:
            st.download_button("Download hasil KMZ", f, file_name="output_pole_per_line.kmz")
    except Exception as e:
        st.error(f"❌ Error: {e}")
