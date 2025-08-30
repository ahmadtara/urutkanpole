import streamlit as st
import tempfile
from lxml import etree as ET
import simplekml
from shapely.geometry import Point, LineString, Polygon

DIST_THRESHOLD = 30  # meter

def parse_kml(kml_file):
    """Parse langsung file KML"""
    parser = ET.XMLParser(recover=True)
    tree = ET.parse(kml_file, parser=parser)
    return tree

def extract_geometry(placemark):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    geom = placemark.find(".//kml:Point/kml:coordinates", ns)
    if geom is not None:
        lon, lat, *_ = map(float, geom.text.strip().split(","))
        return Point(lon, lat)

    geom = placemark.find(".//kml:LineString/kml:coordinates", ns)
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
        return LineString(coords)

    geom = placemark.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
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

def export_kml(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    kml = simplekml.Kml()
    for line_name, content in classified.items():
        f_line = kml.newfolder(name=line_name)
        poles = content.get("POLE", [])
        f_pole = f_line.newfolder(name="POLE")
        for i, (old_name, p) in enumerate(poles, 1):
            new_name = f"{prefix}{str(i).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
    kml.save(output_path)

# ============================
# STREAMLIT APP
# ============================
st.title("📍 Urutkan POLE ke LINE dari KML")

uploaded_file = st.file_uploader("Upload file KML", type=["kml"])

if uploaded_file is not None:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp_kml:
            tmp_kml.write(uploaded_file.read())
            tmp_kml_path = tmp_kml.name

        with st.spinner("🔍 Memproses file KML..."):
            tree = parse_kml(tmp_kml_path)
            classified = classify_poles(tree)

            out_path = tempfile.mktemp(suffix=".kml")
            export_kml(classified, out_path)

        with open(out_path, "rb") as f:
            st.success("✅ Proses selesai! Silakan download hasilnya.")
            st.download_button("⬇️ Download KML hasil", f, file_name="POLE_per_LINE.kml")

    except Exception as e:
        st.error(f"❌ Error: {e}")
