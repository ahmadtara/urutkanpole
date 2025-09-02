import os
import zipfile
import tempfile
import streamlit as st
from shapely.geometry import Point, Polygon, LineString
from lxml import etree as ET
import re

#  Bersih dari tag gx:, ns1:, dll. pada file KML
def clean_invalid_tags(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"<(/?)(gx|ns1):[^>]+>", "", content)
    content = re.sub(r"\s+(gx|ns1):[^=]+=\"[^\"]*\"", "", content)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

ns = {"kml": "http://www.opengis.net/kml/2.2"}

st.title("📌 KMZ Tools")

menu = st.sidebar.radio("Pilih Menu", [
    "Rapikan HP ke Boundary",
    "Rename NN di HP",
    "Urutkan POLE Global"
])

# ------------------------
# MENU 1: Rapikan HP ke Boundary
# ------------------------
if menu == "Rapikan HP ke Boundary":
    uploaded = st.file_uploader("Upload KMZ file", type="kmz")
    if uploaded:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
            tmp.write(uploaded.read())
            kmz_path = tmp.name

        st.success(f"Upload sukses: {uploaded.name}")

        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(kmz_path, 'r') as z:
            z.extractall(extract_dir)
            kml_name = next((f for f in z.namelist() if f.lower().endswith(".kml")), None)

        if not kml_name:
            st.error("Tidak ditemukan file .kml di dalam KMZ.")
        else:
            kml_path = os.path.join(extract_dir, kml_name)
            clean_invalid_tags(kml_path)

            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_path, parser)
            root = tree.getroot()

            def get_coords(text):
                return [(float(x.split(",")[0]), float(x.split(",")[1]))
                        for x in text.strip().split()]

            # Ambil boundary polygons & HP placemarks (dengan objek asli)
            boundaries = {}
            hp_placemarks = []
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is None:
                    continue

                if fname.text == "HP":
                    for pm in folder.findall("kml:Placemark", ns):
                        pt = pm.find(".//kml:Point", ns)
                        if pt is not None:
                            coords = pt.find("kml:coordinates", ns).text.strip()
                            lon, lat, *_ = map(float, coords.split(","))
                            hp_placemarks.append((Point(lon, lat), pm))

                elif fname.text.startswith("LINE "):
                    line_name = fname.text
                    boundaries[line_name] = {}
                    for pm in folder.findall("kml:Placemark", ns):
                        poly = pm.find(".//kml:Polygon", ns)
                        name_el = pm.find("kml:name", ns)
                        if poly is not None and name_el is not None:
                            coords = get_coords(poly.find("kml:coordinates", ns).text)
                            boundaries[line_name][name_el.text] = Polygon(coords)

            # Assign HP to polygons
            assignments = {ln: {bn: [] for bn in bd} for ln, bd in boundaries.items()}
            for pt, pm in hp_placemarks:
                for ln, bd in boundaries.items():
                    for bn, poly in bd.items():
                        if poly.contains(pt):
                            assignments[ln][bn].append(pm)
                            break

            # Buat KML baru dengan placemark asli
            doc = ET.Element("kml", xmlns=ns["kml"])
            dcel = ET.SubElement(doc, "Document")
            for ln, bd in assignments.items():
                lf = ET.SubElement(dcel, "Folder")
                ET.SubElement(lf, "name").text = ln
                for bn, pms in bd.items():
                    bf = ET.SubElement(lf, "Folder")
                    ET.SubElement(bf, "name").text = bn
                    for pm in pms:
                        bf.append(pm)

            out_kml = os.path.join(extract_dir, "output.kml")
            ET.ElementTree(doc).write(out_kml, encoding="utf-8", xml_declaration=True)

            out_kmz = os.path.join(extract_dir, "output.kmz")
            with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(out_kml, "doc.kml")

            with open(out_kmz, "rb") as f:
                st.download_button("Download KMZ Rapikan HP", f, "rapikan_hp.kmz",
                                   mime="application/vnd.google-earth.kmz")

# ------------------------
# MENU 2: Rename NN di HP
# ------------------------
elif menu == "Rename NN di HP":
    st.subheader("Rename NN di folder 'HP'")
    uploaded = st.file_uploader("Upload KML/KMZ", type=["kml", "kmz"])
    prefix = st.text_input("Prefix yang dicari", value="NN")
    start_num = st.number_input("Nomor awal", min_value=1, value=1)
    pad_width = st.number_input("Jumlah digit", min_value=1, value=2)

    if uploaded:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded.name)[-1]) as tmp:
            tmp.write(uploaded.read())
            file_path = tmp.name

        extract_dir = tempfile.mkdtemp()
        if file_path.lower().endswith(".kmz"):
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(extract_dir)
                kml_name = next((f for f in z.namelist() if f.lower().endswith(".kml")), None)
            if not kml_name:
                st.error("Tidak ada .kml di KMZ.")
                st.stop()
            kml_path = os.path.join(extract_dir, kml_name)
        else:
            kml_path = file_path

        clean_invalid_tags(kml_path)
        parser = ET.XMLParser(recover=True, encoding="utf-8")
        tree = ET.parse(kml_path, parser)
        root = tree.getroot()

        hp_folder = next((f for f in root.findall(".//kml:Folder", ns)
                          if f.find("kml:name", ns) is not None
                          and f.find("kml:name", ns).text == "HP"), None)
        if hp_folder is None:
            st.error("Folder 'HP' tidak ditemukan.")
            st.stop()

        placemarks = []
        for pm in hp_folder.findall("kml:Placemark", ns):
            nm = pm.find("kml:name", ns)
            if nm is not None and nm.text and nm.text.upper().startswith(prefix.upper()):
                placemarks.append(nm)

        if not placemarks:
            st.warning("Tidak ditemukan Placemark yang cocok.")
            st.stop()

        num = start_num
        for nm in placemarks:
            nm.text = f"{prefix}-{str(num).zfill(pad_width)}"
            num += 1

        out_kml = os.path.join(extract_dir, "renamed.kml")
        tree.write(out_kml, encoding="utf-8", xml_declaration=True)
        out_kmz = os.path.join(extract_dir, "renamed.kmz")
        with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(out_kml, "doc.kml")

        with open(out_kmz, "rb") as f:
            st.download_button("Download KMZ Renamed NN", f, "rename_nn.kmz",
                               mime="application/vnd.google-earth.kmz")

# ------------------------
# MENU 3: Urutkan POLE Global
# ------------------------
elif menu == "Urutkan POLE Global":
    uploaded = st.file_uploader("Upload KMZ file", type="kmz")
    prefix = st.text_input("Prefix nama POLE (boleh kosong)", value="MR.PTSTP.P")
    pad_width = st.number_input("Digit penomoran", min_value=2, max_value=6, value=3)
    st.caption("Jika kosong, output hanya berupa angka seperti 001, 002, dst.")

    if uploaded:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
            tmp.write(uploaded.read())
            kmz_path = tmp.name

        st.success(f"Upload sukses: {uploaded.name}")

        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(kmz_path, 'r') as z:
            z.extractall(extract_dir)
            kml_name = next((f for f in z.namelist() if f.lower().endswith(".kml")), None)

        if not kml_name:
            st.error("Tidak ditemukan file .kml di dalam KMZ.")
        else:
            kml_path = os.path.join(extract_dir, kml_name)
            clean_invalid_tags(kml_path)

            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_path, parser)
            root = tree.getroot()

            cables = {}
            boundaries = {}
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is None or not fname.text.startswith("LINE "):
                    continue
                line_name = fname.text
                cables[line_name] = None
                boundaries[line_name] = {}

                for pm in folder.findall("kml:Placemark", ns):
                    ls = pm.find(".//kml:LineString", ns)
                    poly = pm.find(".//kml:Polygon", ns)
                    name_el = pm.find("kml:name", ns)

                    if ls is not None:
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in ls.find("kml:coordinates", ns).text.strip().split()]
                        cables[line_name] = LineString(coords)
                    elif poly is not None and name_el is not None:
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in poly.find("kml:coordinates", ns).text.strip().split()]
                        boundaries[line_name][name_el.text] = Polygon(coords)

            pole_points = []
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is None or fname.text != "POLE":
                    continue
                for pm in folder.findall("kml:Placemark", ns):
                    point = pm.find(".//kml:Point", ns)
                    if point is not None:
                        coords = point.find("kml:coordinates", ns).text.strip()
                        lon, lat, *_ = map(float, coords.split(","))
                        pole_points.append((pm, Point(lon, lat)))

            assignments = {ln: [] for ln in boundaries.keys()}
            for pm, pt in pole_points:
                assigned = None
                for ln, ls in cables.items():
                    if ls and ls.distance(pt) < 1e-4:  # kira-kira <30m
                        assigned = ln
                        break
                if not assigned:
                    for ln, bds in boundaries.items():
                        if any(poly.contains(pt) for poly in bds.values()):
                            assigned = ln
                            break
                if assigned:
                    assignments[assigned].append(pm)

            doc = ET.Element("kml", xmlns=ns["kml"])
            dcel = ET.SubElement(doc, "Document")

            counter = 1
            for ln in sorted(assignments.keys()):
                lf = ET.SubElement(dcel, "Folder")
                ET.SubElement(lf, "name").text = ln
                for pm in assignments[ln]:
                    nm_el = pm.find("kml:name", ns)
                    if nm_el is not None:
                        nm_el.text = (f"{prefix}{str(counter).zfill(pad_width)}"
                                      if prefix.strip()
                                      else str(counter).zfill(pad_width))
                        counter += 1
                    lf.append(pm)

            out_kml = os.path.join(extract_dir, "poles_global.kml")
            ET.ElementTree(doc).write(out_kml, encoding="utf-8", xml_declaration=True)

            out_kmz = os.path.join(extract_dir, "poles_global.kmz")
            with zipfile.ZipFile(out_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(out_kml, "doc.kml")

            with open(out_kmz, "rb") as f:
                st.download_button("Download KMZ POLE Global", f, "pole_global.kmz",
                                   mime="application/vnd.google-earth.kmz")
