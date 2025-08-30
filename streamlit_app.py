import zipfile
import os
import tempfile
import simplekml
import pandas as pd
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon
import streamlit as st

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 30  


def parse_kmz(kmz_path):
    """Extract KMZ ke folder sementara dan parse KML utama"""
    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_path, 'r') as zf:
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

    tree = ET.parse(kml_file)
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

    # ambil semua POLE global (urutan sesuai KML asli)
    poles = []
    for pm in doc.findall(".//kml:Folder[kml:name='POLE']//kml:Placemark", ns):
        name = pm.find("kml:name", ns).text
        geom = extract_geometry(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    # Simpan semua kabel & boundary per LINE
    lines_data = {}
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

        lines_data[line_name.upper()] = {
            "cable": cable,
            "boundaries": boundaries,
            "poles": []
        }

    # Assign setiap POLE ke line terdekat
    for name, p in poles:
        assigned_line = None
        proj_val = None

        for line_name, content in lines_data.items():
            cable = content["cable"]
            boundaries = content["boundaries"]

            # cek ke kabel
            if cable and isinstance(cable, LineString):
                d = p.distance(cable)
                if d <= DIST_THRESHOLD / 111320:  # meter → degree approx
                    assigned_line = line_name
                    proj_val = cable.project(p)
                    break

            # kalau tidak kena kabel, cek boundary
            if not assigned_line and boundaries:
                for bname, boundary in boundaries:
                    if isinstance(boundary, Polygon) and p.within(boundary):
                        line_key = bname[0].upper()  # huruf depan boundary
                        if line_key in line_name.upper():
                            assigned_line = line_name
                            proj_val = p.x
                            break
            if assigned_line:
                break

        if assigned_line:
            lines_data[assigned_line]["poles"].append((name, p, proj_val))

    return lines_data


def export_kmz(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    """Export hasil ke KMZ baru, folder per LINE dengan urutan global"""
    kml = simplekml.Kml()

    # urutan line A→Z
    line_order = sorted(classified.keys())

    counter = 1
    for line_name in line_order:
        f_line = kml.newfolder(name=line_name)
        f_pole = f_line.newfolder(name="POLE")

        poles = classified[line_name]["poles"]
        for (old_name, p, _) in poles:
            new_name = f"{prefix}{str(counter).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
            counter += 1

    kml.savekmz(output_path)


# ==============================
# STREAMLIT APP
# ==============================
st.title("📍 Urutkan POLE ke Line dari KMZ")

uploaded_file = st.file_uploader("Upload file KMZ", type="kmz")

if uploaded_file is not None:
    with st.spinner("🔍 Memproses KMZ..."):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
            tmp.write(uploaded_file.read())
            kmz_path = tmp.name

        try:
            tree, _ = parse_kmz(kmz_path)
            classified = classify_poles(tree)

            # Buat DataFrame untuk preview
            data_rows = []
            counter = 1
            for line_name in sorted(classified.keys()):
                for (old_name, p, _) in classified[line_name]["poles"]:
                    new_name = f"MR.OATKRP.P{str(counter).zfill(3)}"
                    data_rows.append([line_name, old_name, new_name, p.x, p.y])
                    counter += 1

            df = pd.DataFrame(data_rows, columns=["LINE", "Old Name", "New Name", "Longitude", "Latitude"])

            st.subheader("📊 Hasil klasifikasi POLE per LINE")
            st.dataframe(df, use_container_width=True)

            output_path = "output_pole_per_line.kmz"
            export_kmz(classified, output_path)

            st.success("✅ Selesai! File siap diunduh")

            with open(output_path, "rb") as f:
                st.download_button("⬇️ Download hasil KMZ", f, file_name="output_pole_per_line.kmz")

        except Exception as e:
            st.error(f"❌ Error: {e}")
