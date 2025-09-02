import streamlit as st
import zipfile
import os
import tempfile
from lxml import etree as ET

# --- Fungsi untuk bersihkan prefix ---
def clean_prefixes(root):
    """Hapus prefix ns1:, gx:, dll agar KML valid standar."""
    for elem in root.getiterator():
        # Bersihkan tag
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]  # ambil localname

        # Bersihkan atribut
        for attr in list(elem.attrib):
            if "}" in attr:
                local = attr.split("}", 1)[1]
                val = elem.attrib[attr]
                del elem.attrib[attr]
                elem.attrib[local] = val

# --- Fungsi ekstrak KMZ ---
def extract_kmz(uploaded_file):
    tmpdir = tempfile.mkdtemp()
    kmz_path = os.path.join(tmpdir, "uploaded.kmz")
    with open(kmz_path, "wb") as f:
        f.write(uploaded_file.read())
    with zipfile.ZipFile(kmz_path, "r") as z:
        z.extractall(tmpdir)
    return tmpdir, os.path.join(tmpdir, "doc.kml")

# --- Fungsi simpan KML ke KMZ ---
def save_to_kmz(root, original_kmz, output_name="result.kmz"):
    tmpdir = tempfile.mkdtemp()
    new_kml = os.path.join(tmpdir, "doc.kml")
    ET.ElementTree(root).write(new_kml, encoding="utf-8", xml_declaration=True)

    result = os.path.join(tmpdir, output_name)
    with zipfile.ZipFile(original_kmz, "r") as zin:
        with zipfile.ZipFile(result, "w") as zout:
            for item in zin.infolist():
                if item.filename != "doc.kml":
                    zout.writestr(item, zin.read(item.filename))
            zout.write(new_kml, "doc.kml")
    return result

# --- Menu 1: Gabungan HP + POLE ---
def rapikan_hp_dan_pole(uploaded_file):
    tmpdir, kml_file = extract_kmz(uploaded_file)

    parser = ET.XMLParser(recover=True, encoding="utf-8")
    tree = ET.parse(kml_file, parser=parser)
    root = tree.getroot()
    clean_prefixes(root)

    # 🔹 Cari folder HP
    hp_nodes = root.findall(".//Folder[name='HP']/Placemark")
    pole_nodes = root.findall(".//Folder[name='POLE']/Placemark")

    # Buat struktur baru
    new_doc = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = ET.SubElement(new_doc, "Document")

    # Folder HP COVER A-D
    for boundary in ["A", "B", "C", "D"]:
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = f"HP COVER {boundary}"
        for i, hp in enumerate(hp_nodes, start=1):
            new_hp = ET.SubElement(folder, "Placemark")
            ET.SubElement(new_hp, "name").text = f"HP {boundary}-{i}"
            for child in hp:
                if child.tag != "name":
                    new_hp.append(child)

    # Folder LINE A-D
    for line in ["A", "B", "C", "D"]:
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = f"LINE {line}"
        for i, pole in enumerate(pole_nodes, start=1):
            new_pole = ET.SubElement(folder, "Placemark")
            ET.SubElement(new_pole, "name").text = f"POLE {line}-{i}"
            for child in pole:
                if child.tag != "name":
                    new_pole.append(child)

    result = save_to_kmz(new_doc, os.path.join(tmpdir, "uploaded.kmz"))
    return result

# --- Menu 2: Rename NN ---
def rename_nn(uploaded_file):
    tmpdir, kml_file = extract_kmz(uploaded_file)

    parser = ET.XMLParser(recover=True, encoding="utf-8")
    tree = ET.parse(kml_file, parser=parser)
    root = tree.getroot()
    clean_prefixes(root)

    # Rename semua "NN" di HP
    for pm in root.findall(".//Folder[name='HP']/Placemark"):
        name_tag = pm.find("name")
        if name_tag is not None and "NN" in name_tag.text:
            name_tag.text = name_tag.text.replace("NN", "HP")

    result = save_to_kmz(root, os.path.join(tmpdir, "uploaded.kmz"))
    return result

# --- UI Streamlit ---
st.title("📌 KMZ Processor (2 Menu)")

menu = st.sidebar.radio("Pilih Menu:", ["Rapikan HP + POLE", "Rename NN di HP"])

uploaded_file = st.file_uploader("Upload KMZ", type=["kmz"])

if uploaded_file:
    if menu == "Rapikan HP + POLE":
        if st.button("Proses KMZ"):
            result = rapikan_hp_dan_pole(uploaded_file)
            with open(result, "rb") as f:
                st.download_button("Download KMZ Hasil", f, file_name="rapikan_hp_pole.kmz")
    elif menu == "Rename NN di HP":
        if st.button("Proses KMZ"):
            result = rename_nn(uploaded_file)
            with open(result, "rb") as f:
                st.download_button("Download KMZ Hasil", f, file_name="rename_nn.kmz")
