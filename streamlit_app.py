import os
import re
import zipfile
import tempfile
from copy import deepcopy

import streamlit as st
from shapely.geometry import Point, LineString, Polygon
from lxml import etree as ET

st.title("📌 KMZ Tools")

MENU_OPTIONS = [
    "Gabung: Rapikan HP + Urutkan POLE Global (HP COVER + POLE)",  # updated
    "Rapikan HP ke Boundary",
    "Rename NN di HP",
    "Urutkan POLE Global",
]
menu = st.sidebar.radio("Pilih Menu", MENU_OPTIONS)

# =========================
# Helpers
# =========================
KML_NS = "http://www.opengis.net/kml/2.2"
ns = {"kml": KML_NS}

def extract_kml_from_kmz(uploaded_file):
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
    return float(meters) / 111320.0  # kasar

def clean_non_kml_namespaces(root):
    to_remove = root.xpath('//*[namespace-uri()!="{}"]'.format(KML_NS))
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    for el in root.iter():
        new_attrib = {}
        for k, v in el.attrib.items():
            if k.startswith("{"):
                nsuri = k.split("}")[0][1:]
                local = k.split("}")[1]
                if nsuri == KML_NS:
                    new_attrib[local] = v
            else:
                new_attrib[k] = v
        el.attrib.clear()
        el.attrib.update(new_attrib)

def copy_styles(old_doc, new_doc):
    if old_doc is None:
        return
    keep_locals = {"Style", "StyleMap", "Schema"}
    for child in list(old_doc):
        tag_local = ET.QName(child).localname
        if tag_local in keep_locals:
            new_doc.append(deepcopy(child))

def find_folders_with_prefix_line(root):
    res = {}
    for folder in root.findall(".//kml:Folder", ns):
        fname = folder.find("kml:name", ns)
        if fname is not None and (fname.text or "").strip().upper().startswith("LINE "):
            res[(fname.text or "").strip()] = folder
    return res

def collect_boundaries(root):
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
    cables = {}
    line_folders = find_folders_with_prefix_line(root)
    for line_name, folder in line_folders.items():
        for placemark in folder.findall(".//kml:Placemark", ns):
            line = placemark.find(".//kml:LineString", ns)
            if line is not None:
                coords_text = line.find("kml:coordinates", ns)
                if coords_text is None or coords_text.text is None:
                    continue
                coords = get_coordinates(coords_text.text)
                if len(coords) >= 2:
                    cables[line_name] = LineString(coords)
                    break
    return cables

def collect_hp_points(root):
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
    assignments = {}
    for line, bdict in boundaries.items():
        assignments.setdefault(line, {})
        for bname in bdict.keys():
            assignments[line].setdefault(bname, [])
    for name, pm, pt in hp_points:
        for line, bdict in boundaries.items():
            for bname, poly in bdict.items():
                if poly.contains(pt):
                    assignments[line][bname].append(pm)
                    break
    return assignments

def collect_poles(root):
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
    assignments = {ln: [] for ln in boundaries.keys()}
    for nm, pm, pt in poles:
        assigned_line = None
        best_line, best_dist = None, float("inf")
        for line_name, cable in cables.items():
            try:
                d = cable.distance(pt)
            except Exception:
                d = float("inf")
            if d < best_dist:
                best_dist, best_line = d, line_name
        if best_line is not None and best_dist <= threshold_deg:
            assigned_line = best_line
        if not assigned_line:
            for line_name, bdict in boundaries.items():
                if any(poly.contains(pt) for poly in bdict.values()):
                    assigned_line = line_name
                    break
        if assigned_line:
            assignments[assigned_line].append(pm)
    return assignments

def build_new_document_separated(old_doc, hp_assignments, pole_assignments, prefix, pad_width):
    new_doc = ET.Element(ET.QName(KML_NS, "Document"))
    copy_styles(old_doc, new_doc)

    # HP COVER
    hp_root = ET.SubElement(new_doc, ET.QName(KML_NS, "Folder"))
    ET.SubElement(hp_root, ET.QName(KML_NS, "name")).text = "HP COVER"
    for line in sorted(hp_assignments.keys()):
        subf = ET.SubElement(hp_root, ET.QName(KML_NS, "Folder"))
        ET.SubElement(subf, ET.QName(KML_NS, "name")).text = f"HP COVER {line[-1]}"
        for bname, pms in hp_assignments[line].items():
            bf = ET.SubElement(subf, ET.QName(KML_NS, "Folder"))
            ET.SubElement(bf, ET.QName(KML_NS, "name")).text = bname
            for pm in pms:
                bf.append(pm)

    # POLE
    pole_root = ET.SubElement(new_doc, ET.QName(KML_NS, "Folder"))
    ET.SubElement(pole_root, ET.QName(KML_NS, "name")).text = "POLE"
    counter = 1
    for line in sorted(pole_assignments.keys()):
        subf = ET.SubElement(pole_root, ET.QName(KML_NS, "Folder"))
        ET.SubElement(subf, ET.QName(KML_NS, "name")).text = line
        for pm in pole_assignments[line]:
            nm = pm.find("kml:name", ns)
            if nm is not None:
                nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
            subf.append(pm)
            counter += 1

    return new_doc

def replace_document_and_write(tree, root, new_doc):
    old_doc = root.find("kml:Document", ns)
    if old_doc is not None:
        root.remove(old_doc)
    root.append(new_doc)
    return tree

def write_back_to_kmz(kmz_file, kml_local_path, kml_arcname):
    with zipfile.ZipFile(kmz_file, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(kml_local_path, arcname=kml_arcname)

# =========================
# MENU utama
# =========================
if menu == "Gabung: Rapikan HP + Urutkan POLE Global (HP COVER + POLE)":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    col1, col2, col3 = st.columns(3)
    with col1:
        prefix = st.text_input("Prefix nama POLE", value="MR.PTSTP.P")
    with col2:
        pad_width = st.number_input("Jumlah digit (contoh 3 → 001)", min_value=2, max_value=6, value=3, step=1)
    with col3:
        thr_m = st.number_input("Ambang jarak ke Cable (meter)", min_value=1, value=30, step=1)

    clean_ns = st.checkbox("Bersihkan namespace non-standar", value=True)

    if uploaded_file is not None:
        extract_dir, kmz_file, kml_arcname, kml_file = extract_kml_from_kmz(uploaded_file)
        if not kml_file:
            st.error("❌ Tidak ada .kml dalam KMZ.")
            st.stop()

        tree, root = load_kml_tree(kml_file)
        if clean_ns:
            clean_non_kml_namespaces(root)

        boundaries = collect_boundaries(root)
        cables = collect_cables(root)
        hp_points = collect_hp_points(root)
        hp_assign = assign_hp_to_boundaries(hp_points, boundaries)

        poles = collect_poles(root)
        thr_deg = deg_threshold_from_meters(thr_m)
        pole_assign = assign_poles_to_lines(poles, cables, boundaries, thr_deg)

        old_doc = root.find("kml:Document", ns)
        new_doc = build_new_document_separated(old_doc, hp_assign, pole_assign, prefix, pad_width)

        tree = replace_document_and_write(tree, root, new_doc)
        tree.write(kml_file, encoding="utf-8", xml_declaration=True)
        write_back_to_kmz(kmz_file, kml_file, kml_arcname)

        with open(kmz_file, "rb") as fh:
            st.success("✅ Berhasil update KMZ dengan struktur HP COVER + POLE.")
            st.download_button("📥 Download KMZ", fh, file_name=uploaded_file.name,
                               mime="application/vnd.google-earth.kmz")
