import os
import re
import math
import zipfile
import tempfile
from copy import deepcopy

import streamlit as st
from shapely.geometry import Point, LineString, Polygon
from lxml import etree as ET

st.title("📌 KMZ Tools")

MENU_OPTIONS = [
    "Gabung: Rapikan HP + Urutkan POLE Global",  # NEW (gabungan tanpa merusak fitur lama)
    "Rapikan HP ke Boundary",
    "Rename NN di HP",
    "Urutkan POLE Global",
]
menu = st.sidebar.radio("Pilih Menu", MENU_OPTIONS)

# =========================
# Helpers (umum)
# =========================
KML_NS = "http://www.opengis.net/kml/2.2"
ns = {"kml": KML_NS}

def extract_kml_from_kmz(uploaded_file):
    """Simpan upload ke file sementara, ekstrak KMZ, dan kembalikan (extract_dir, kmz_path, kml_arcname, kml_file_path)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
        tmp.write(uploaded_file.read())
        kmz_file = tmp.name

    extract_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_file, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        kml_name = next((f for f in files if f.lower().endswith(".kml")), None)

    if not kml_name:
        return None, None, None, None

    kml_file = os.path.join(extract_dir, kml_name)
    return extract_dir, kmz_file, kml_name, kml_file

def load_kml_tree(kml_file):
    parser = ET.XMLParser(recover=True, encoding="utf-8")
    tree = ET.parse(kml_file, parser=parser)
    root = tree.getroot()
    return tree, root

def get_coordinates(coord_text):
    coords = []
    for c in (coord_text or "").strip().split():
        parts = c.split(",")
        if len(parts) >= 2:
            lon = float(parts[0]); lat = float(parts[1])
            coords.append((lon, lat))
    return coords

def deg_threshold_from_meters(meters):
    # ~111_320 m per degree (kasar untuk lintang ekuator)
    return float(meters) / 111320.0

def clean_non_kml_namespaces(root):
    """
    Hapus SEMUA elemen yang namespace-nya bukan kml standar,
    dan buang atribut ber-namespace non-kml. Ini akan membersihkan gx:, ns1:, atom:, dsb.
    """
    # Hapus elemen non-KML
    to_remove = root.xpath('//*[namespace-uri()!="{}"]'.format(KML_NS))
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    # Bersihkan atribut ber-namespace non-KML
    for el in root.iter():
        # el.attrib pada lxml menyimpan QNames {ns}local
        new_attrib = {}
        for k, v in el.attrib.items():
            if k.startswith("{"):
                nsuri = k.split("}")[0][1:]
                local = k.split("}")[1]
                if nsuri == KML_NS:
                    new_attrib[local] = v  # keep as no-prefix
                else:
                    # drop non-kml attribute
                    pass
            else:
                # no namespace
                new_attrib[k] = v
        # replace attrib
        el.attrib.clear()
        el.attrib.update(new_attrib)

def copy_styles(old_doc, new_doc):
    """
    Copy Style/StyleMap/Schema dari Document lama → baru agar tampilan tetap menurut template.
    """
    if old_doc is None:
        return
    keep_locals = {"Style", "StyleMap", "Schema"}
    for child in list(old_doc):
        tag_local = ET.QName(child).localname
        if tag_local in keep_locals:
            new_doc.append(deepcopy(child))

def find_folders_with_prefix_line(root):
    """
    Ambil folder 'LINE *' → untuk boundary Polygon & cables LineString.
    return dict: { "LINE A": folder_element, ... }
    """
    res = {}
    for folder in root.findall(".//kml:Folder", ns):
        fname = folder.find("kml:name", ns)
        if fname is not None and (fname.text or "").strip().upper().startswith("LINE "):
            res[(fname.text or "").strip()] = folder
    return res

def collect_boundaries(root):
    """
    Baca Polygon di bawah Folder 'LINE *'
    return: { line_name: { boundary_name: Polygon(...) } }
    """
    boundaries = {}
    line_folders = find_folders_with_prefix_line(root)
    for line_name, folder in line_folders.items():
        boundaries[line_name] = {}
        for placemark in folder.findall(".//kml:Placemark", ns):
            pname = placemark.find("kml:name", ns)
            polygon = placemark.find(".//kml:Polygon", ns)
            if pname is not None and polygon is not None:
                coords_text = polygon.find(".//kml:coordinates", ns)
                if coords_text is None or coords_text.text is None:
                    continue
                coords = get_coordinates(coords_text.text)
                if len(coords) >= 3:
                    boundaries[line_name][(pname.text or "").strip()] = Polygon(coords)
    return boundaries

def collect_cables(root):
    """
    Baca LineString (Distribution Cable) di bawah Folder 'LINE *'
    return: { line_name: LineString(...) }
    """
    cables = {}
    line_folders = find_folders_with_prefix_line(root)
    for line_name, folder in line_folders.items():
        # ambil first LineString (bila ada banyak, Anda bisa adaptasi sesuai template)
        for placemark in folder.findall(".//kml:Placemark", ns):
            line = placemark.find(".//kml:LineString", ns)
            if line is not None:
                coords_text = line.find("kml:coordinates", ns)
                if coords_text is None or coords_text.text is None:
                    continue
                coords = get_coordinates(coords_text.text)
                if len(coords) >= 2:
                    cables[line_name] = LineString(coords)
                    break  # satu cable per LINE (sesuai template umum)
    return cables

def collect_hp_points(root):
    """
    Baca Placemark di Folder 'HP'
    return: list of (name_text, placemark_element, Point)
    """
    hp_points = []
    for folder in root.findall(".//kml:Folder", ns):
        fname = folder.find("kml:name", ns)
        if fname is not None and (fname.text or "").strip().upper() == "HP":
            for pm in folder.findall("kml:Placemark", ns):
                nm = pm.find("kml:name", ns)
                point = pm.find(".//kml:Point", ns)
                if nm is not None and point is not None:
                    coords_text = point.find("kml:coordinates", ns)
                    if coords_text is None or coords_text.text is None:
                        continue
                    parts = coords_text.text.strip().split(",")
                    if len(parts) >= 2:
                        lon = float(parts[0]); lat = float(parts[1])
                        hp_points.append(((nm.text or "").strip(), pm, Point(lon, lat)))
    return hp_points

def assign_hp_to_boundaries(hp_points, boundaries):
    """
    Map HP ke boundary.
    return: { line_name: { boundary_name: [placemark, ...] } }
    """
    assignments = {}
    # init keys supaya folder tetap muncul walau kosong
    for line, bdict in boundaries.items():
        assignments.setdefault(line, {})
        for bname in bdict.keys():
            assignments[line].setdefault(bname, [])

    for name, pm, pt in hp_points:
        for line, bdict in boundaries.items():
            hit = False
            for bname, poly in bdict.items():
                if poly.contains(pt):
                    assignments[line][bname].append(pm)
                    hit = True
                    break
            if hit:
                break
    return assignments

def collect_poles(root):
    """
    Baca Placemark POLE di Folder 'POLE'
    return: list of (name_elem, placemark_element, Point)
    """
    poles = []
    for folder in root.findall(".//kml:Folder", ns):
        fname = folder.find("kml:name", ns)
        if fname is not None and (fname.text or "").strip().upper() == "POLE":
            for pm in folder.findall("kml:Placemark", ns):
                nm = pm.find("kml:name", ns)
                pt = pm.find(".//kml:Point", ns)
                if nm is not None and pt is not None:
                    coords_text = pt.find("kml:coordinates", ns)
                    if coords_text is None or coords_text.text is None:
                        continue
                    parts = coords_text.text.strip().split(",")
                    if len(parts) >= 2:
                        lon = float(parts[0]); lat = float(parts[1])
                        poles.append((nm, pm, Point(lon, lat)))
    return poles

def assign_poles_to_lines(poles, cables, boundaries, threshold_deg):
    """
    Tentukan LINE untuk tiap POLE:
    - Prioritas: jarak ke cable LINE tertentu < threshold
    - Fallback: cek polygon boundary (contains)
    return: { line_name: [placemark, ...] }
    """
    assignments = {ln: [] for ln in boundaries.keys()}
    for nm, pm, pt in poles:
        assigned_line = None
        # Prioritas: kedekatan ke cable
        best_line = None
        best_dist = float("inf")
        for line_name, cable in cables.items():
            try:
                d = cable.distance(pt)  # jarak dalam derajat
            except Exception:
                d = float("inf")
            if d < best_dist:
                best_dist = d
                best_line = line_name
        if best_line is not None and best_dist <= threshold_deg:
            assigned_line = best_line

        # Fallback: boundary contains
        if not assigned_line:
            for line_name, bdict in boundaries.items():
                inside = False
                for poly in bdict.values():
                    if poly.contains(pt):
                        assigned_line = line_name
                        inside = True
                        break
                if inside:
                    break

        if assigned_line:
            assignments[assigned_line].append(pm)
    return assignments

def build_new_document_with_hp_and_poles(old_doc, hp_assignments, pole_assignments, prefix, pad_width):
    """
    Bangun <Document> baru berisi:
    - Style/StyleMap/Schema disalin dari Document lama
    - Folder per LINE:
        - subfolder <boundary> per boundary berisi HP yang ditempatkan
        - lalu daftar POLE (di level LINE, bukan di bawah boundary)
    POLE dinamai ulang secara global berdasarkan urutan LINE A→D.
    """
    new_doc = ET.Element(ET.QName(KML_NS, "Document"))

    # Copy styles dari doc lama agar template tampilan tetap
    copy_styles(old_doc, new_doc)

    # urutan LINE yang rapih (LINE A → LINE D)
    def line_sort_key(ln):
        # ln contoh "LINE A"
        m = re.search(r"LINE\s+([A-Z])", ln, re.IGNORECASE)
        return (ord(m.group(1).upper()) if m else 999, ln)

    # Global counter untuk POLE rename
    counter = 1

    for line in sorted(hp_assignments.keys(), key=line_sort_key):
        folder_line = ET.SubElement(new_doc, ET.QName(KML_NS, "Folder"))
        ET.SubElement(folder_line, ET.QName(KML_NS, "name")).text = line

        # boundary folders (HP)
        bdict = hp_assignments.get(line, {})
        for bname in sorted(bdict.keys()):
            boundary_folder = ET.SubElement(folder_line, ET.QName(KML_NS, "Folder"))
            ET.SubElement(boundary_folder, ET.QName(KML_NS, "name")).text = bname
            for pm in bdict[bname]:
                boundary_folder.append(pm)

        # append POLE di level LINE dan rename global
        for pm in pole_assignments.get(line, []):
            nm = pm.find("kml:name", ns)
            if nm is not None:
                nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
            folder_line.append(pm)
            counter += 1

    return new_doc

def replace_document_and_write(tree, root, new_doc):
    old_doc = root.find("kml:Document", ns)
    if old_doc is not None:
        root.remove(old_doc)
    root.append(new_doc)
    return tree

def write_back_to_kmz(kmz_file, kml_local_path, kml_arcname):
    """
    Timpa file KML di dalam KMZ lama (tanpa ganti nama KMZ).
    """
    with zipfile.ZipFile(kmz_file, "a", zipfile.ZIP_DEFLATED) as z:
        # Pastikan arcname sama seperti saat ekstrak (bisa 'doc.kml' atau path lain).
        z.write(kml_local_path, arcname=kml_arcname)

# =========================
# MENU: Gabungan (HP + POLE)
# =========================
if menu == "Gabung: Rapikan HP + Urutkan POLE Global":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    col1, col2, col3 = st.columns(3)
    with col1:
        prefix = st.text_input("Prefix nama POLE", value="MR.PTSTP.P")
    with col2:
        pad_width = st.number_input("Jumlah digit (contoh 3 → 001)", min_value=2, max_value=6, value=3, step=1)
    with col3:
        thr_m = st.number_input("Ambang jarak ke Cable (meter)", min_value=1, value=30, step=1)

    clean_ns = st.checkbox("Bersihkan namespace non-standar (gx/ns1/atom)", value=True)

    if uploaded_file is not None:
        extract_dir, kmz_file, kml_arcname, kml_file = extract_kml_from_kmz(uploaded_file)
        if not kml_file:
            st.error("❌ Tidak ada file .kml di dalam KMZ.")
            st.stop()

        # Parse
        tree, root = load_kml_tree(kml_file)

        # Opsional: bersihkan namespace non-standar
        if clean_ns:
            clean_non_kml_namespaces(root)

        # Kumpulkan data
        boundaries = collect_boundaries(root)
        cables = collect_cables(root)
        hp_points = collect_hp_points(root)
        hp_assign = assign_hp_to_boundaries(hp_points, boundaries)

        poles = collect_poles(root)
        thr_deg = deg_threshold_from_meters(thr_m)
        pole_assign = assign_poles_to_lines(poles, cables, boundaries, thr_deg)

        # Bangun Document baru (gabungan)
        old_doc = root.find("kml:Document", ns)
        new_doc = build_new_document_with_hp_and_poles(old_doc, hp_assign, pole_assign, prefix, pad_width)

        # Replace Document & simpan ke kml lokal
        tree = replace_document_and_write(tree, root, new_doc)
        tree.write(kml_file, encoding="utf-8", xml_declaration=True)

        # Timpa kembali ke KMZ lama (arcname sama)
        write_back_to_kmz(kmz_file, kml_file, kml_arcname)

        # Download hasil: nama KMZ tetap seperti upload (template yang sama)
        with open(kmz_file, "rb") as fh:
            st.success("✅ Berhasil gabungkan & update doc.kml di KMZ.")
            st.download_button("📥 Download KMZ (ditimpa, sesuai template)", fh, file_name=uploaded_file.name,
                               mime="application/vnd.google-earth.kmz")

# =========================
# MENU 1: Rapikan HP ke Boundary (LEGACY - tidak diubah)
# =========================
elif menu == "Rapikan HP ke Boundary":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

    if uploaded_file is not None:
        extract_dir, kmz_file, kml_arcname, kml_file = extract_kml_from_kmz(uploaded_file)
        if not kml_file:
            st.error("❌ Tidak ada file .kml di dalam KMZ")
            st.stop()

        tree, root = load_kml_tree(kml_file)

        boundaries = collect_boundaries(root)
        hp_points = collect_hp_points(root)
        assignments = assign_hp_to_boundaries(hp_points, boundaries)

        # Susun ulang KML (HP by boundary per LINE)
        old_doc = root.find("kml:Document", ns)
        new_doc = ET.Element(ET.QName(KML_NS, "Document"))
        copy_styles(old_doc, new_doc)

        def line_sort_key(ln):
            m = re.search(r"LINE\s+([A-Z])", ln, re.IGNORECASE)
            return (ord(m.group(1).upper()) if m else 999, ln)

        for line, bdict in sorted(assignments.items(), key=lambda kv: line_sort_key(kv[0])):
            line_folder = ET.SubElement(new_doc, ET.QName(KML_NS, "Folder"))
            ET.SubElement(line_folder, ET.QName(KML_NS, "name")).text = line
            for bname in sorted(bdict.keys()):
                boundary_folder = ET.SubElement(line_folder, ET.QName(KML_NS, "Folder"))
                ET.SubElement(boundary_folder, ET.QName(KML_NS, "name")).text = bname
                for pm in bdict[bname]:
                    boundary_folder.append(pm)

        tree = replace_document_and_write(tree, root, new_doc)
        tree.write(kml_file, encoding="utf-8", xml_declaration=True)
        write_back_to_kmz(kmz_file, kml_file, kml_arcname)

        with open(kmz_file, "rb") as fh:
            st.success("✅ Berhasil rapikan HP ke boundary & update doc.kml.")
            st.download_button("📥 Download KMZ (ditimpa)", fh, file_name=uploaded_file.name,
                               mime="application/vnd.google-earth.kmz")

# =========================
# MENU 2: Rename NN di HP (LEGACY - tidak diubah)
# =========================
elif menu == "Rename NN di HP":
    st.subheader("🔤 Ubah nama NN → NN-01, NN-02, ... di folder HP")

    uploaded_file = st.file_uploader("Upload file KML/KMZ", type=["kml", "kmz"])
    start_num = st.number_input("Nomor awal", min_value=1, value=1, step=1)
    pad_width = st.number_input("Jumlah digit (padding)", min_value=1, value=2, step=1)
    prefix = st.text_input("Prefix yang dicari", value="NN")

    if uploaded_file is not None:
        # Simpan & ekstrak bila KMZ
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[-1]) as tmp:
            tmp.write(uploaded_file.read())
            file_path = tmp.name

        extract_dir = tempfile.mkdtemp()
        if file_path.lower().endswith(".kmz"):
            with zipfile.ZipFile(file_path, "r") as z:
                z.extractall(extract_dir)
                files = z.namelist()
                kml_arcname = next((f for f in files if f.lower().endswith(".kml")), None)
                if not kml_arcname:
                    st.error("❌ Tidak ada file .kml di dalam KMZ.")
                    st.stop()
                kml_file = os.path.join(extract_dir, kml_arcname)
            kmz_file = file_path
        else:
            kml_arcname = None
            kml_file = file_path
            kmz_file = None

        tree, root = load_kml_tree(kml_file)

        # Cari folder HP
        def find_folder_by_name(el, name):
            for f in el.findall(".//kml:Folder", ns):
                n = f.find("kml:name", ns)
                if n is not None and (n.text or "").strip() == name:
                    return f
            return None

        hp_folder = find_folder_by_name(root, "HP")
        if hp_folder is None:
            st.error("❌ Folder 'HP' tidak ditemukan di KML/KMZ.")
            st.stop()

        # Kumpulkan placemark NN
        nn_placemarks = []
        for pm in hp_folder.findall("kml:Placemark", ns):
            nm = pm.find("kml:name", ns)
            if nm is None:
                continue
            text = (nm.text or "").strip()
            if text.upper().startswith(prefix.upper()):
                nn_placemarks.append(nm)

        if not nn_placemarks:
            st.warning("Tidak ada Placemark berawalan 'NN' di folder HP.")
            st.stop()

        # Rename berurutan
        counter = int(start_num)
        for nm in nn_placemarks:
            nm.text = f"{prefix}-{str(counter).zfill(int(pad_width))}"
            counter += 1

        # Simpan
        tree.write(kml_file, encoding="utf-8", xml_declaration=True)

        if kmz_file:
            write_back_to_kmz(kmz_file, kml_file, kml_arcname)
            with open(kmz_file, "rb") as fh:
                st.success("✅ Berhasil rename NN & update KMZ.")
                st.download_button("📥 Download KMZ (ditimpa)", fh, file_name=os.path.basename(kmz_file),
                                   mime="application/vnd.google-earth.kmz")
        else:
            with open(kml_file, "rb") as fh:
                st.success("✅ Berhasil rename NN & update KML.")
                st.download_button("📥 Download KML", fh, file_name=os.path.basename(kml_file),
                                   mime="application/vnd.google-earth.kml+xml")

# =========================
# MENU 3: Urutkan POLE Global (LEGACY - tidak diubah)
# =========================
elif menu == "Urutkan POLE Global":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    if uploaded_file is not None:
        prefix = st.text_input("Prefix nama POLE", value="MR.PTSTP.P")
        pad_width = st.number_input("Jumlah digit (contoh 3 → 001)", min_value=2, max_value=6, value=3, step=1)
        thr_m = st.number_input("Ambang jarak ke Cable (meter)", min_value=1, value=30, step=1)

        extract_dir, kmz_file, kml_arcname, kml_file = extract_kml_from_kmz(uploaded_file)
        if not kml_file:
            st.error("❌ Tidak ada file .kml di dalam KMZ")
            st.stop()

        tree, root = load_kml_tree(kml_file)

        boundaries = collect_boundaries(root)
        cables = collect_cables(root)
        poles = collect_poles(root)

        thr_deg = deg_threshold_from_meters(thr_m)
        assignments = assign_poles_to_lines(poles, cables, boundaries, thr_deg)

        # Susun ulang KML + penomoran global
        old_doc = root.find("kml:Document", ns)
        new_doc = ET.Element(ET.QName(KML_NS, "Document"))
        copy_styles(old_doc, new_doc)

        def line_sort_key(ln):
            m = re.search(r"LINE\s+([A-Z])", ln, re.IGNORECASE)
            return (ord(m.group(1).upper()) if m else 999, ln)

        counter = 1
        for line in sorted(assignments.keys(), key=line_sort_key):
            line_folder = ET.SubElement(new_doc, ET.QName(KML_NS, "Folder"))
            ET.SubElement(line_folder, ET.QName(KML_NS, "name")).text = line
            for pm in assignments[line]:
                nm = pm.find("kml:name", ns)
                if nm is not None:
                    nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
                line_folder.append(pm)
                counter += 1

        tree = replace_document_and_write(tree, root, new_doc)
        tree.write(kml_file, encoding="utf-8", xml_declaration=True)
        write_back_to_kmz(kmz_file, kml_file, kml_arcname)

        with open(kmz_file, "rb") as fh:
            st.success("✅ Berhasil urutkan POLE & update doc.kml.")
            st.download_button("📥 Download KMZ (ditimpa)", fh, file_name=uploaded_file.name,
                               mime="application/vnd.google-earth.kmz")
