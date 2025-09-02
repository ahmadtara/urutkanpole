import os
import zipfile
import tempfile
import streamlit as st
from shapely.geometry import Point, LineString, Polygon
from lxml import etree as ET

st.title("📌 KMZ Tools")

menu = st.sidebar.radio("Pilih Menu", [
    "Rapikan HP ke Boundary",
    "Rename NN di HP",   
    "Urutkan POLE Global"
])

# ===== Helper: bersihkan prefix =====
def strip_namespace(tree):
    for elem in tree.iter():
        if not hasattr(elem.tag, "find"):
            continue
        i = elem.tag.find("}")
        if i != -1:
            elem.tag = elem.tag[i+1:]
    ET.cleanup_namespaces(tree)
    return tree

# ===== Helper: koordinat =====
def get_coordinates(coord_text):
    coords = []
    for c in coord_text.strip().split():
        lon, lat, *_ = map(float, c.split(","))
        coords.append((lon, lat))
    return coords

# =========================
# MENU 1: Rapikan HP ke Boundary
# =========================
if menu == "Rapikan HP ke Boundary":
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

        if kml_name is None:
            st.error("❌ Tidak ada file .kml di dalam KMZ")
        else:
            kml_file = os.path.join(extract_dir, kml_name)

            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            tree = strip_namespace(tree)
            root = tree.getroot()

            # Ambil boundary LINE A/B/C/D
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
                            coords = get_coordinates(coords_text)
                            boundaries[line_name][pname.text] = Polygon(coords)

            # Ambil titik HP
            hp_points = []
            for folder in root.findall(".//Folder"):
                fname = folder.find("name")
                if fname is not None and fname.text == "HP":
                    for placemark in folder.findall("Placemark"):
                        pname = placemark.find("name")
                        point = placemark.find(".//Point")
                        if pname is not None and point is not None:
                            coords_text = point.find("coordinates").text.strip()
                            lon, lat, *_ = map(float, coords_text.split(","))
                            hp_points.append((pname.text, Point(lon, lat), placemark))

            # Assign ke boundary
            assignments = {}
            for line, bdict in boundaries.items():
                for bname in bdict.keys():
                    assignments.setdefault(line, {}).setdefault(bname, [])

            for name, point, placemark in hp_points:
                for line, bdict in boundaries.items():
                    for bname, poly in bdict.items():
                        if poly.contains(point):
                            assignments[line][bname].append(placemark)
                            break

            # Susun ulang KML
            document = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            doc_el = ET.SubElement(document, "Document")

            for line, bdict in assignments.items():
                line_folder = ET.SubElement(doc_el, "Folder")
                ET.SubElement(line_folder, "name").text = line
                for bname, placemarks in bdict.items():
                    boundary_folder = ET.SubElement(line_folder, "Folder")
                    ET.SubElement(boundary_folder, "name").text = bname
                    for pm in placemarks:
                        boundary_folder.append(pm)

            new_kml = os.path.join(extract_dir, "output.kml")
            ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)

            output_kmz = os.path.join(extract_dir, "output.kmz")
            with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(new_kml, "doc.kml")

            with open(output_kmz, "rb") as f:
                st.download_button("📥 Download KMZ Hasil", f, "output.kmz",
                                   mime="application/vnd.google-earth.kmz")

# =========================
# MENU 2: Rename NN di HP
# =========================
elif menu == "Rename NN di HP":
    st.subheader("🔤 Ubah nama NN → NN-01, NN-02, ... di folder HP")

    uploaded_file = st.file_uploader("Upload file KML/KMZ", type=["kml", "kmz"])
    start_num = st.number_input("Nomor awal", min_value=1, value=1, step=1)
    pad_width = st.number_input("Jumlah digit (padding)", min_value=1, value=2, step=1)
    prefix = st.text_input("Prefix yang dicari", value="NN")

    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[-1]) as tmp:
            tmp.write(uploaded_file.read())
            file_path = tmp.name

        extract_dir = tempfile.mkdtemp()
        if file_path.lower().endswith(".kmz"):
            with zipfile.ZipFile(file_path, 'r') as z:
                z.extractall(extract_dir)
                files = z.namelist()
                kml_name = next((f for f in files if f.lower().endswith(".kml")), None)
                if not kml_name:
                    st.error("❌ Tidak ada file .kml di dalam KMZ.")
                    st.stop()
                kml_file = os.path.join(extract_dir, kml_name)
        else:
            kml_file = file_path

        parser = ET.XMLParser(recover=True, encoding="utf-8")
        tree = ET.parse(kml_file, parser=parser)
        tree = strip_namespace(tree)
        root = tree.getroot()

        hp_folder = None
        for f in root.findall(".//Folder"):
            n = f.find("name")
            if n is not None and n.text.strip() == "HP":
                hp_folder = f
                break

        if hp_folder is None:
            st.error("❌ Folder 'HP' tidak ditemukan.")
            st.stop()

        nn_placemarks = []
        for pm in hp_folder.findall("Placemark"):
            nm = pm.find("name")
            if nm is not None and (nm.text or "").strip().upper().startswith(prefix.upper()):
                nn_placemarks.append(nm)

        counter = int(start_num)
        for nm in nn_placemarks:
            nm.text = f"{prefix}-{str(counter).zfill(int(pad_width))}"
            counter += 1

        new_kml = os.path.join(extract_dir, "renamed.kml")
        tree.write(new_kml, encoding="utf-8", xml_declaration=True)

        output_kmz = os.path.join(extract_dir, "renamed.kmz")
        with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(new_kml, "doc.kml")

        with open(output_kmz, "rb") as f:
            st.download_button("📥 Download KMZ Renamed", f,
                               file_name="renamed.kmz",
                               mime="application/vnd.google-earth.kmz")

# =========================
# MENU 3: Urutkan POLE Global
# =========================
elif menu == "Urutkan POLE Global":
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

        parser = ET.XMLParser(recover=True, encoding="utf-8")
        tree = ET.parse(kml_file, parser=parser)
        tree = strip_namespace(tree)
        root = tree.getroot()

        prefix = st.text_input("Prefix nama POLE", value="MR.PTSTP.P")
        pad_width = st.number_input("Jumlah digit", min_value=2, max_value=6, value=3, step=1)

        # Kabel
        cables = {}
        for folder in root.findall(".//Folder"):
            fname = folder.find("name")
            if fname is not None and fname.text.startswith("LINE "):
                for placemark in folder.findall("Placemark"):
                    line = placemark.find(".//LineString")
                    if line is not None:
                        coords_text = line.find("coordinates").text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        cables[fname.text] = LineString(coords)

        # Boundary
        boundaries = {}
        for folder in root.findall(".//Folder"):
            fname = folder.find("name")
            if fname is not None and fname.text.startswith("LINE "):
                boundaries[fname.text] = {}
                for placemark in folder.findall("Placemark"):
                    pname = placemark.find("name")
                    polygon = placemark.find(".//Polygon")
                    if pname is not None and polygon is not None:
                        coords_text = polygon.find(".//coordinates").text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        boundaries[fname.text][pname.text] = Polygon(coords)

        # POLE
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

        assignments = {ln: [] for ln in boundaries.keys()}
        for pname, pm, pt in poles:
            assigned_line = None
            for line_name, cable in cables.items():
                if cable.distance(pt) < 0.0001:  # threshold ~30m
                    assigned_line = line_name
                    break
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

        document = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        doc_el = ET.SubElement(document, "Document")
        counter = 1
        for line in sorted(assignments.keys()):
            line_folder = ET.SubElement(doc_el, "Folder")
            ET.SubElement(line_folder, "name").text = line
            for pm in assignments[line]:
                nm = pm.find("name")
                if nm is not None:
                    nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
                line_folder.append(pm)
                counter += 1

        new_kml = os.path.join(extract_dir, "poles_global.kml")
        ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)
        output_kmz = os.path.join(extract_dir, "poles_global.kmz")
        with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(new_kml, "doc.kml")

        with open(output_kmz, "rb") as f:
            st.download_button("📥 Download POLE Global", f,
                               file_name="poles_global.kmz",
                               mime="application/vnd.google-earth.kmz")
