import streamlit as st
import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 30  

def parse_kmz(kmz_file):
    """Extract KMZ ke folder sementara dan parse KML utama"""
    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_file, 'r') as zf:
        zf.extractall(tmpdir)

    # Cari file .kml
    kml_file = None
    for root, dirs, files in os.walk(tmpdir):
        for f in files:
            if f.endswith('.kml'):
                kml_file = os.path.join(root, f)
                break
    if not kml_file:
        raise FileNotFoundError("KML file tidak ditemukan dalam KMZ")

    # Parse tanpa error namespace
    parser = ET.XMLParser(recover=True)
    tree = ET.parse(kml_file, parser=parser)
    return tree, tmpdir


def extract_geometry(placemark):
    """Ambil Point / LineString / Polygon dari Placemark"""
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
    """Klasifikasikan POLE ke dalam masing-masing LINE"""
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    doc = tree.getroot()

    # ambil semua POLE global (urut sesuai file asli)
    poles = []
    for pm in doc.findall(".//kml:Folder[kml:name='POLE']//kml:Placemark", ns):
        name = pm.find("kml:name", ns).text
        geom = extract_geometry(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    # siapkan dict hasil
    result = {f"LINE {ch}": {"POLE": []} for ch in ["A", "B", "C", "D"]}

    # kumpulkan kabel & boundary per line
    line_info = {}
    for line_folder in doc.findall(".//kml:Folder", ns):
        line_name = line_folder.find("kml:name", ns).text
        if not line_name or not line_name.upper().startswith("LINE"):
            continue

        # cari distribution cable
        cable = None
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "DISTRIBUTION CABLE" in nm:
                cable = extract_geometry(pm)

        # cari boundary
        boundaries = []
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "BOUNDARY" in nm:
                boundaries.append((nm, extract_geometry(pm)))

        line_info[line_name.upper()] = {"cable": cable, "boundaries": boundaries}

    # assign poles sesuai urutan global
    for name, p in poles:
        assigned = False
        # cek line A-D
        for line_name in result.keys():
            info = line_info.get(line_name.upper())
            if not info:
                continue

            # cek kabel
            cable = info["cable"]
            if cable and isinstance(cable, LineString):
                d = p.distance(cable)
                if d <= DIST_THRESHOLD / 111320:  # deg → meter
                    result[line_name]["POLE"].append((name, p))
                    assigned = True
                    break

            # kalau gagal, cek boundary
            for bname, boundary in info["boundaries"]:
                if isinstance(boundary, Polygon) and p.within(boundary):
                    # validasi huruf A/B/C/D boundary vs line
                    line_key = bname[0].upper()
                    if line_key in line_name.upper():
                        result[line_name]["POLE"].append((name, p))
                        assigned = True
                        break
            if assigned:
                break

    return result


def export_kmz(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    """Export hasil ke KMZ baru, folder per LINE"""
    kml = simplekml.Kml()
    for line_name, content in classified.items():
        f_line = kml.newfolder(name=line_name)
        poles = content.get("POLE", [])
        f_pole = f_line.newfolder(name="POLE")
        for i, (old_name, p) in enumerate(poles, 1):
            new_name = f"{prefix}{str(i).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
    kml.savekmz(output_path)


# ================================
# STREAMLIT APP
# ================================
st.title("📍 Urutkan POLE ke LINE dari KMZ")

uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

if uploaded_file is not None:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp_kmz:
            tmp_kmz.write(uploaded_file.read())
            tmp_kmz_path = tmp_kmz.name

        with st.spinner("🔍 Memproses file KMZ..."):
            tree, _ = parse_kmz(tmp_kmz_path)
            classified = classify_poles(tree)

            out_path = tempfile.mktemp(suffix=".kmz")
            export_kmz(classified, out_path)

        with open(out_path, "rb") as f:
            st.success("✅ Proses selesai! Silakan download hasilnya.")
            st.download_button("⬇️ Download KMZ hasil", f, file_name="POLE_per_LINE.kmz")

    except Exception as e:
        st.error(f"❌ Error: {e}")
