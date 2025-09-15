import os
import re
import zipfile
import tempfile
import streamlit as st
from shapely.geometry import Point, Polygon, LineString
from lxml import etree as ET

# ==============================
# Fungsi Pembersih Raw XML
# ==============================
def clean_raw_xml(raw_xml: bytes) -> bytes:
    # Hapus namespace asing
    raw_xml = re.sub(rb'\s+xmlns:(?!gx)[a-zA-Z0-9_]+="[^"]*"', b"", raw_xml)
    # Hapus prefix asing di tag
    raw_xml = re.sub(rb"<(/?)[a-zA-Z0-9_]+:", rb"<\1", raw_xml)
    # Hapus prefix asing di atribut
    raw_xml = re.sub(rb"\s+[a-zA-Z0-9_]+:([a-zA-Z0-9_]+=)", rb" \1", raw_xml)
    # Tambah namespace standar di root <kml>
    raw_xml = re.sub(
        rb"<kml[^>]*>",
        b'<kml xmlns="http://www.opengis.net/kml/2.2" '
        b'xmlns:gx="http://www.google.com/kml/ext/2.2">',
        raw_xml,
        count=1
    )
    return raw_xml


def load_and_clean_kml(kmz_or_kml_path: str) -> str:
    extract_dir = tempfile.mkdtemp()
    if kmz_or_kml_path.lower().endswith(".kmz"):
        with zipfile.ZipFile(kmz_or_kml_path, 'r') as z:
            z.extractall(extract_dir)
            files = z.namelist()
            kml_name = next((f for f in files if f.lower().endswith(".kml")), None)
            if not kml_name:
                raise FileNotFoundError("❌ Tidak ada file .kml di dalam KMZ.")
            kml_file = os.path.join(extract_dir, kml_name)
    else:
        kml_file = kmz_or_kml_path

    with open(kml_file, "rb") as f:
        raw_xml = f.read()
    cleaned = clean_raw_xml(raw_xml)

    cleaned_kml = os.path.join(extract_dir, "cleaned.kml")
    with open(cleaned_kml, "wb") as f:
        f.write(cleaned)

    return cleaned_kml


def clean_kmz(kmz_bytes, output_kml, output_kmz):
    with tempfile.TemporaryDirectory() as extract_dir:
        tmp_kmz = os.path.join(extract_dir, "uploaded.kmz")
        with open(tmp_kmz, "wb") as f:
            f.write(kmz_bytes)

        # Ekstrak KMZ
        with zipfile.ZipFile(tmp_kmz, 'r') as kmz:
            kmz.extractall(extract_dir)

        # Cari file KML utama
        main_kml = None
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f.endswith(".kml"):
                    main_kml = os.path.join(root, f)
                    break
            if main_kml:
                break

        if not main_kml:
            raise FileNotFoundError("❌ Tidak ada file .kml di dalam KMZ")

        # Baca & bersihkan
        with open(main_kml, "rb") as f:
            raw_xml = f.read()
        cleaned = clean_raw_xml(raw_xml)

        # Simpan hasil KML
        with open(output_kml, "wb") as f:
            f.write(cleaned)

        # Bungkus ulang jadi KMZ
        with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as zf:
            for folder, _, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(folder, file)
                    arcname = os.path.relpath(file_path, extract_dir)
                    if file_path == main_kml:
                        zf.write(output_kml, arcname)
                    else:
                        zf.write(file_path, arcname)


# ==============================
# STREAMLIT APP
# ==============================
st.title("📌 KMZ Tools Aman")

menu = st.sidebar.radio("Pilih Menu", [
    "Rapikan HP ke Boundary",
    "Rename NN di HP",
    "Urutkan POLE Global",
    "Bersihkan"
])

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

        try:
            kml_file = load_and_clean_kml(kmz_file)
            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            root = tree.getroot()
            ns = {"kml": "http://www.opengis.net/kml/2.2"}

            def get_coordinates(coord_text):
                return [(float(c.split(",")[0]), float(c.split(",")[1]))
                        for c in coord_text.strip().split()]

            # Ambil boundary
            boundaries = {}
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is not None and fname.text.startswith("LINE "):
                    line_name = fname.text
                    boundaries[line_name] = {}
                    for placemark in folder.findall(".//kml:Placemark", ns):
                        pname = placemark.find("kml:name", ns)
                        polygon = placemark.find(".//kml:Polygon", ns)
                        if pname is not None and polygon is not None:
                            coords_text = polygon.find(".//kml:coordinates", ns).text
                            boundaries[line_name][pname.text] = Polygon(get_coordinates(coords_text))

            # Ambil titik HP
            hp_points = []
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is not None and fname.text == "HP":
                    for placemark in folder.findall("kml:Placemark", ns):
                        pname = placemark.find("kml:name", ns)
                        point = placemark.find(".//kml:Point", ns)
                        if pname is not None and point is not None:
                            coords_text = point.find("kml:coordinates", ns).text.strip()
                            lon, lat, *_ = map(float, coords_text.split(","))
                            hp_points.append((pname.text, Point(lon, lat), placemark))

            # Assign ke boundary
            assignments = {ln: {bn: [] for bn in bdict.keys()} for ln, bdict in boundaries.items()}
            assigned_count = 0
            for name, point, placemark in hp_points:
                for line, bdict in boundaries.items():
                    for bname, poly in bdict.items():
                        if poly.contains(point):
                            assignments[line][bname].append(placemark)
                            assigned_count += 1
                            break

            st.info(f"📍 HP ditemukan: {len(hp_points)}, masuk boundary: {assigned_count}")

            # Susun ulang
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

            new_kml = os.path.join(os.path.dirname(kml_file), "output.kml")
            ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)
            output_kmz = os.path.join(os.path.dirname(kml_file), "output.kmz")
            with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(new_kml, "doc.kml")

            with open(output_kmz, "rb") as f:
                st.download_button("📥 Download KMZ Hasil", f, "output.kmz",
                                   mime="application/vnd.google-earth.kmz")
        except Exception as e:
            st.error(f"❌ Gagal memproses: {e}")

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

        try:
            kml_file = load_and_clean_kml(file_path)
            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            root = tree.getroot()
            ns = {"kml": "http://www.opengis.net/kml/2.2"}

            hp_folder = None
            for f in root.findall(".//kml:Folder", ns):
                n = f.find("kml:name", ns)
                if n is not None and (n.text or "").strip() == "HP":
                    hp_folder = f
                    break

            if hp_folder is None:
                st.error("❌ Folder 'HP' tidak ditemukan.")
                st.stop()

            nn_placemarks = []
            for pm in hp_folder.findall("kml:Placemark", ns):
                nm = pm.find("kml:name", ns)
                if nm is not None and (nm.text or "").strip().upper().startswith(prefix.upper()):
                    nn_placemarks.append(nm)

            st.info(f"✏️ NN ditemukan: {len(nn_placemarks)}")

            counter = int(start_num)
            for nm in nn_placemarks:
                nm.text = f"{prefix}-{str(counter).zfill(int(pad_width))}"
                counter += 1

            out_dir = tempfile.mkdtemp()
            new_kml = os.path.join(out_dir, "renamed.kml")
            tree.write(new_kml, encoding="utf-8", xml_declaration=True)
            output_kmz = os.path.join(out_dir, "renamed.kmz")
            with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(new_kml, "doc.kml")

            with open(output_kmz, "rb") as f:
                st.download_button("⬇️ Download KMZ hasil rename", f, file_name="renamed.kmz")
        except Exception as e:
            st.error(f"❌ Gagal memproses: {e}")

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

        try:
            kml_file = load_and_clean_kml(kmz_file)
            parser = ET.XMLParser(recover=True, encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            root = tree.getroot()
            ns = {"kml": "http://www.opengis.net/kml/2.2"}

            prefix = st.text_input("Prefix nama POLE (boleh dikosongkan)", value="MR.PTSTP.P")
            pad_width = st.number_input("Jumlah digit penomoran", min_value=2, max_value=6, value=3, step=1)

            cables, boundaries, poles = {}, {}, []

            # Ambil cable LINE
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is not None and fname.text and fname.text.startswith("LINE "):
                    line_name = fname.text
                    for placemark in folder.findall(".//kml:Placemark", ns):
                        line = placemark.find(".//kml:LineString", ns)
                        if line is not None:
                            coords_el = line.find("kml:coordinates", ns)
                            if coords_el is None or coords_el.text is None:
                                continue
                            coords_text = coords_el.text.strip()
                            if not coords_text:
                                continue
                            try:
                                coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                          for x in coords_text.split()]
                                cables[line_name] = LineString(coords)
                            except Exception:
                                pass

            # Ambil boundary polygon
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is not None and fname.text and fname.text.startswith("LINE "):
                    line_name = fname.text
                    boundaries[line_name] = {}
                    for placemark in folder.findall(".//kml:Placemark", ns):
                        pname = placemark.find("kml:name", ns)
                        polygon = placemark.find(".//kml:Polygon", ns)
                        if pname is not None and pname.text and polygon is not None:
                            coords_el = polygon.find(".//kml:coordinates", ns)
                            if coords_el is None or coords_el.text is None:
                                continue
                            coords_text = coords_el.text.strip()
                            if not coords_text:
                                continue
                            try:
                                coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                          for x in coords_text.split()]
                                boundaries[line_name][pname.text] = Polygon(coords)
                            except Exception:
                                pass

            # Ambil titik POLE
            for folder in root.findall(".//kml:Folder", ns):
                fname = folder.find("kml:name", ns)
                if fname is not None and fname.text and fname.text == "POLE":
                    for placemark in folder.findall("kml:Placemark", ns):
                        pname = placemark.find("kml:name", ns)
                        point = placemark.find(".//kml:Point", ns)
                        if pname is not None and pname.text and point is not None:
                            coords_el = point.find("kml:coordinates", ns)
                            if coords_el is None or coords_el.text is None:
                                continue
                            coords_text = coords_el.text.strip()
                            if not coords_text:
                                continue
                            try:
                                lon, lat, *_ = map(float, coords_text.split(","))
                                poles.append((pname, placemark, Point(lon, lat)))
                            except Exception:
                                pass

            st.info(f"📍 POLE ditemukan: {len(poles)}")

            # Assign POLE ke LINE / boundary terdekat
            assignments = {ln: [] for ln in boundaries.keys()}
            assigned_count = 0
            for pname, pm, pt in poles:
                assigned_line = None
                for line_name, cable in cables.items():
                    try:
                        if cable.distance(pt) < 0.0003:  # sekitar 30m
                            assigned_line = line_name
                            break
                    except Exception:
                        pass
                if not assigned_line:
                    for line_name, bdict in boundaries.items():
                        for poly in bdict.values():
                            try:
                                if poly.contains(pt):
                                    assigned_line = line_name
                                    break
                            except Exception:
                                pass
                        if assigned_line:
                            break
                if assigned_line:
                    assignments[assigned_line].append(pm)
                    assigned_count += 1

            st.info(f"✅ POLE berhasil di-assign ke LINE/boundary: {assigned_count}")

            # Susun ulang & beri nama baru
            document = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            doc_el = ET.SubElement(document, "Document")
            counter = 1
            for line in sorted(assignments.keys()):
                line_folder = ET.SubElement(doc_el, "Folder")
                ET.SubElement(line_folder, "name").text = line
                for pm in assignments[line]:
                    nm = pm.find("kml:name", ns)
                    if nm is not None:
                        if prefix.strip():
                            nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
                        else:
                            nm.text = str(counter).zfill(int(pad_width))
                    line_folder.append(pm)
                    counter += 1

            new_kml = os.path.join(os.path.dirname(kml_file), "poles_global.kml")
            ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)
            output_kmz = os.path.join(os.path.dirname(kml_file), "poles_global.kmz")
            with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(new_kml, "doc.kml")

            with open(output_kmz, "rb") as f:
                st.download_button("📥 Download POLE Global", f,
                                   file_name="poles_global.kmz",
                                   mime="application/vnd.google-earth.kmz")
        except Exception as e:
            st.error(f"❌ Gagal memproses: {e}")

# =========================
# MENU 4: Bersihkan KMZ
# =========================
elif menu == "Bersihkan":
    st.subheader("🧹 Bersihkan Namespace & Prefix Asing di KMZ/KML")

    uploaded_file = st.file_uploader("Upload file KMZ kotor", type=["kmz"])
    if uploaded_file is not None:
        output_kml = "clean_output.kml"
        output_kmz = "clean_output.kmz"

        if st.button("🚀 Bersihkan"):
            try:
                clean_kmz(uploaded_file.read(), output_kml, output_kmz)
                st.success("✅ File berhasil dibersihkan tanpa merusak isi")

                with open(output_kml, "rb") as f:
                    st.download_button("⬇️ Download KML Bersih", f, file_name="clean.kml")

                with open(output_kmz, "rb") as f:
                    st.download_button("⬇️ Download KMZ Bersih", f, file_name="clean.kmz")

            except Exception as e:
                st.error(f"❌ Gagal memproses: {e}")
