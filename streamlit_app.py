import os
import zipfile
import tempfile
import re
import streamlit as st
from shapely.geometry import Point, LineString, Polygon
from lxml import etree as ET

# =========================
# ✅ Fungsi untuk membersihkan namespace asing
# =========================
def strip_namespace(file_path):
    parser = ET.XMLParser(recover=True, encoding="utf-8")
    tree = ET.parse(file_path, parser)
    root = tree.getroot()

    for elem in root.getiterator():
        if not hasattr(elem.tag, 'find'):
            continue
        i = elem.tag.find('}')
        if i >= 0:
            elem.tag = elem.tag[i+1:]

    # Hapus atribut namespace (xmlns:xxx)
    for at in list(root.attrib.keys()):
        if at.startswith("xmlns:") or at == "xmlns":
            del root.attrib[at]

    tree.write(file_path, encoding="utf-8", xml_declaration=True)

# =========================
st.title("🗺️ KMZ Tools")

menu = st.sidebar.selectbox("Pilih menu", [
    "Rapikan HP ke Boundary",
    "Rename NN di HP",
    "Urutkan POLE Global"
])

# =========================
# MENU: Urutkan POLE Global
# =========================
if menu == "Urutkan POLE Global":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
            tmp.write(uploaded_file.read())
            kmz_file = tmp.name
        st.success(f"✅ File berhasil diupload: {uploaded_file.name}")

        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(kmz_file, 'r') as z:
            z.extractall(extract_dir)
            files = z.namelist()
            kml_name = next((f for f in files if f.lower().endswith(".kml")), None)

        if not kml_name:
            st.error("❌ Tidak ada file .kml di dalam KMZ")
            st.stop()
        kml_file = os.path.join(extract_dir, kml_name)

        # ✅ Bersihkan namespace sebelum parsing
        strip_namespace(kml_file)

        parser = ET.XMLParser(recover=True, encoding="utf-8")
        tree = ET.parse(kml_file, parser=parser)
        root = tree.getroot()
        ns = {"kml": "http://www.opengis.net/kml/2.2"}

        # Input prefix manual
        prefix = st.text_input("Prefix nama POLE (boleh dikosongkan)", value="MR.PTSTP.P")
        st.caption("💡 Jika dikosongkan, nama POLE akan berupa angka berurutan (contoh: 001, 002, dst)")
        pad_width = st.number_input("Jumlah digit penomoran", min_value=2, max_value=6, value=3, step=1)

        # Ambil Distribution Cable (LineString)
        cables = {}
        for folder in root.findall(".//Folder"):
            fname = folder.find("name")
            if fname is not None and fname.text.startswith("LINE "):
                line_name = fname.text
                for placemark in folder.findall(".//Placemark"):
                    line = placemark.find(".//LineString")
                    if line is not None:
                        coords_text = line.find("coordinates").text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        cables[line_name] = LineString(coords)

        # Ambil Boundary (Polygon)
        boundaries = {}
        for folder in root.findall(".//Folder"):
            fname = folder.find("name")
            if fname is not None and fname.text.startswith("LINE "):
                line_name = fname.text
                boundaries[line_name] = {}
                for placemark in folder.findall(".//Placemark"):
                    pname = placemark.find("name")
                    polygon = placemark.find(".//Polygon")
                    if pname is not None and polygon is not None:
                        coords_text = polygon.find(".//coordinates").text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        boundaries[line_name][pname.text] = Polygon(coords)

        # Ambil POLE (Point)
        poles = []
        for folder in root.findall(".//Folder"):
            fname = folder.find("name")
            if fname is not None and fname.text == "POLE":
                for placemark in folder.findall("Placemark"):
                    pname = placemark.find("name")
                    point = placemark.find(".//Point")
                    if pname is not None and point is not None:
                        coords_text = point.find("coordinates").text.strip()
                        lon, lat, *_ = map(float, coords_text.split(","))
                        poles.append((pname, placemark, Point(lon, lat)))

        # Assign POLE ke line (cek cable dulu, fallback boundary)
        assignments = {ln: [] for ln in boundaries.keys()}
        for pname, pm, pt in poles:
            assigned_line = None
            # cek distribution cable terdekat
            for line_name, cable in cables.items():
                if cable.distance(pt) < 0.0001:  # threshold ~30m
                    assigned_line = line_name
                    break
            # fallback ke boundary
            if not assigned_line:
                for line_name, bdict in boundaries.items():
                    for poly in bdict.values():
                        if poly.contains(pt):
                            assigned_line = line_name
                            break
                    if assigned_line:
                        break
            if assigned_line:
                assignments[assigned_line].append(pm)

        # Susun ulang KML dengan penomoran global
        document = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        doc_el = ET.SubElement(document, "Document")
        counter = 1
        for line in sorted(assignments.keys()):
            line_folder = ET.SubElement(doc_el, "Folder")
            ET.SubElement(line_folder, "name").text = line
            for pm in assignments[line]:
                nm = pm.find("name")
                if nm is not None:
                    if prefix.strip():
                        nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
                    else:
                        nm.text = str(counter).zfill(int(pad_width))
                line_folder.append(pm)
                counter += 1

        # Simpan hasil
        new_kml = os.path.join(extract_dir, "poles_global.kml")
        ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)
        output_kmz = os.path.join(extract_dir, "poles_global.kmz")
        with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(new_kml, "doc.kml")

        with open(output_kmz, "rb") as f:
            st.download_button("📥 Download POLE Global", f, file_name="poles_global.kmz")
