import streamlit as st
import zipfile
import os
import io
import xml.etree.ElementTree as ET

# ======================
# Fungsi bersihkan prefix (gx:, ns1:, dll)
# ======================
def clean_prefixes(root):
    for elem in root.iter():
        # Bersihkan tag dari namespace
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        # Bersihkan atribut dari namespace
        for attr in list(elem.attrib):
            if "}" in attr:
                local = attr.split("}", 1)[1]
                val = elem.attrib[attr]
                del elem.attrib[attr]
                elem.attrib[local] = val

# ======================
# Fungsi untuk simpan ulang KML ke KMZ
# ======================
def save_to_kmz(tree, uploaded_file, output_name="doc.kml"):
    mem = io.BytesIO()
    with zipfile.ZipFile(uploaded_file, "r") as zin:
        with zipfile.ZipFile(mem, "w") as zout:
            for item in zin.infolist():
                if item.filename != "doc.kml":
                    zout.writestr(item, zin.read(item.filename))
            # simpan doc.kml baru
            kml_bytes = ET.tostring(tree.getroot(), encoding="utf-8", method="xml")
            zout.writestr(output_name, kml_bytes)
    mem.seek(0)
    return mem

# ======================
# STREAMLIT APP
# ======================
st.title("📂 KMZ Processor")

menu = st.sidebar.radio("Pilih Menu:", ["Gabungan: Rapikan HP & POLE", "Rename NN di HP"])

# ======================
# MENU 1: Gabungan Rapikan HP ke Boundary & Urutkan POLE Global
# ======================
if menu == "Gabungan: Rapikan HP & POLE":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

    if uploaded_file:
        with zipfile.ZipFile(uploaded_file, "r") as kmz:
            if "doc.kml" not in kmz.namelist():
                st.error("doc.kml tidak ditemukan di dalam KMZ!")
            else:
                kml_data = kmz.read("doc.kml")
                parser = ET.XMLParser()
                tree = ET.ElementTree(ET.fromstring(kml_data, parser=parser))
                root = tree.getroot()
                clean_prefixes(root)  # 🔥 bersihkan prefix

                # Buat struktur gabungan: Folder HP COVER A-D & LINE A-D
                document = root.find("Document")
                if document is None:
                    st.error("Document tidak ditemukan di KML!")
                else:
                    # Buat folder HP COVER A-D
                    for label in ["A", "B", "C", "D"]:
                        folder = ET.Element("Folder")
                        name = ET.SubElement(folder, "name")
                        name.text = f"HP COVER {label}"
                        document.append(folder)

                    # Buat folder LINE A-D
                    for label in ["A", "B", "C", "D"]:
                        folder = ET.Element("Folder")
                        name = ET.SubElement(folder, "name")
                        name.text = f"LINE {label}"
                        document.append(folder)

                    # Simpan kembali ke KMZ
                    result = save_to_kmz(tree, uploaded_file)
                    st.success("KMZ berhasil diproses & dibersihkan dari prefix.")
                    st.download_button("Download KMZ Hasil", data=result, file_name="cleaned.kmz")

# ======================
# MENU 2: Rename NN di HP
# ======================
elif menu == "Rename NN di HP":
    uploaded_file = st.file_uploader("Upload file KMZ untuk Rename HP", type=["kmz"])

    if uploaded_file:
        with zipfile.ZipFile(uploaded_file, "r") as kmz:
            if "doc.kml" not in kmz.namelist():
                st.error("doc.kml tidak ditemukan di dalam KMZ!")
            else:
                kml_data = kmz.read("doc.kml")
                parser = ET.XMLParser()
                tree = ET.ElementTree(ET.fromstring(kml_data, parser=parser))
                root = tree.getroot()
                clean_prefixes(root)  # 🔥 bersihkan prefix

                document = root.find("Document")
                if document is None:
                    st.error("Document tidak ditemukan di KML!")
                else:
                    # Rename semua <Placemark> yang punya NN
                    for placemark in document.findall(".//Placemark"):
                        name = placemark.find("name")
                        if name is not None and name.text and name.text.startswith("NN"):
                            name.text = name.text.replace("NN", "HP", 1)

                    # Simpan kembali ke KMZ
                    result = save_to_kmz(tree, uploaded_file)
                    st.success("Rename NN → HP selesai & prefix dibersihkan.")
                    st.download_button("Download KMZ Hasil", data=result, file_name="rename_hp.kmz")
