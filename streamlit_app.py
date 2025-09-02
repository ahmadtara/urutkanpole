import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import io
import os
from collections import defaultdict

# ===== Utility: clean namespace =====
def clean_xml_namespaces(kml_bytes):
    parser = ET.XMLParser(encoding="utf-8")
    tree = ET.ElementTree(ET.fromstring(kml_bytes, parser=parser))
    root = tree.getroot()

    # hapus prefix gx:, ns1:, dsb
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        new_attrib = {}
        for k, v in elem.attrib.items():
            if "}" in k:
                k = k.split("}", 1)[1]
            new_attrib[k] = v
        elem.attrib = new_attrib

    return tree

# ===== Utility: save back to KMZ =====
def save_to_kmz(tree, uploaded_file, new_name="doc.kml"):
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    buffer.seek(0)

    new_kmz = io.BytesIO()
    with zipfile.ZipFile(uploaded_file, "r") as zin:
        with zipfile.ZipFile(new_kmz, "w") as zout:
            for item in zin.infolist():
                if item.filename != "doc.kml":
                    zout.writestr(item, zin.read(item.filename))
            zout.writestr(new_name, buffer.read())
    new_kmz.seek(0)
    return new_kmz

# ===== Step 1: Gabungan HP & POLE =====
def process_hp_pole(tree):
    root = tree.getroot()

    # buat Document baru
    doc = ET.Element("Document")

    # Buat folder HP COVER A-D
    hp_folders = {l: ET.SubElement(doc, "Folder") for l in ["A", "B", "C", "D"]}
    for l, f in hp_folders.items():
        name = ET.SubElement(f, "name"); name.text = f"HP COVER {l}"

    # Buat folder LINE A-D
    line_folders = {l: ET.SubElement(doc, "Folder") for l in ["A", "B", "C", "D"]}
    for l, f in line_folders.items():
        name = ET.SubElement(f, "name"); name.text = f"LINE {l}"

    # Ambil semua Placemark
    for pm in root.findall(".//Placemark"):
        name = pm.findtext("name", "")
        if name.startswith("HP") and "A" in name:
            hp_folders["A"].append(pm)
        elif name.startswith("HP") and "B" in name:
            hp_folders["B"].append(pm)
        elif name.startswith("HP") and "C" in name:
            hp_folders["C"].append(pm)
        elif name.startswith("HP") and "D" in name:
            hp_folders["D"].append(pm)
        elif name.startswith("POLE") and "A" in name:
            line_folders["A"].append(pm)
        elif name.startswith("POLE") and "B" in name:
            line_folders["B"].append(pm)
        elif name.startswith("POLE") and "C" in name:
            line_folders["C"].append(pm)
        elif name.startswith("POLE") and "D" in name:
            line_folders["D"].append(pm)

    # ganti root -> Document baru
    new_tree = ET.ElementTree(doc)
    return new_tree

# ===== Step 2: Rename NN di HP =====
def rename_nn_hp(tree):
    root = tree.getroot()
    count = 0
    for pm in root.findall(".//Placemark"):
        name_elem = pm.find("name")
        if name_elem is not None and "NN" in name_elem.text:
            count += 1
            name_elem.text = name_elem.text.replace("NN", f"HP-{count}")
    return tree, count

# ===== Streamlit App =====
st.title("📌 KMZ Processor")

menu = st.sidebar.radio("Pilih Menu", ["Gabungan HP & POLE", "Rename NN di HP"])

uploaded_file = st.file_uploader("Upload KMZ", type=["kmz"])

if uploaded_file:
    if menu == "Gabungan HP & POLE":
        with zipfile.ZipFile(uploaded_file, "r") as z:
            kml_bytes = z.read("doc.kml")
        tree = clean_xml_namespaces(kml_bytes)
        new_tree = process_hp_pole(tree)
        new_kmz = save_to_kmz(new_tree, uploaded_file)

        st.success("Berhasil gabungkan HP & POLE ✅")
        st.download_button("Download KMZ Hasil", data=new_kmz, file_name="hasil_gabungan.kmz")

    elif menu == "Rename NN di HP":
        with zipfile.ZipFile(uploaded_file, "r") as z:
            kml_bytes = z.read("doc.kml")
        tree = clean_xml_namespaces(kml_bytes)
        new_tree, count = rename_nn_hp(tree)
        new_kmz = save_to_kmz(new_tree, uploaded_file)

        st.success(f"Berhasil rename {count} HP yang ada 'NN' ✅")
        st.download_button("Download KMZ Hasil", data=new_kmz, file_name="hasil_rename.kmz")
