import streamlit as st
import zipfile
import os
from xml.etree import ElementTree as ET

st.set_page_config(page_title="KMZ Rapikan", layout="wide")

def extract_kml_from_kmz(uploaded_file):
    with zipfile.ZipFile(uploaded_file, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".kml"):
                return zf.read(name)
    return None

def save_kmz(kml_str, output_kmz="hasil_gabungan.kmz"):
    # simpan doc.kml sementara
    with open("doc.kml", "wb") as f:
        f.write(kml_str.encode("utf-8"))
    # bungkus jadi KMZ
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("doc.kml", "doc.kml")
    os.remove("doc.kml")
    return output_kmz

# ==========================
# Menu
# ==========================
menu = st.sidebar.radio("Menu", [
    "Rapikan HP ke Boundary & Urutkan POLE Global",
    "Rename NN di HP"
])

uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

if uploaded_file:
    kml_bytes = extract_kml_from_kmz(uploaded_file)
    if kml_bytes is None:
        st.error("KML tidak ditemukan di dalam KMZ")
    else:
        root = ET.fromstring(kml_bytes)

        if menu == "Rapikan HP ke Boundary & Urutkan POLE Global":
            # Buat folder hasil
            kml_doc = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            document = ET.SubElement(kml_doc, "Document")

            # Folder HP Cover A–D
            hp_folders = {ch: ET.SubElement(document, "Folder") for ch in ["A", "B", "C", "D"]}
            for ch in hp_folders:
                ET.SubElement(hp_folders[ch], "name").text = f"HP COVER {ch}"

            # Folder LINE A–D
            line_folders = {ch: ET.SubElement(document, "Folder") for ch in ["A", "B", "C", "D"]}
            for ch in line_folders:
                ET.SubElement(line_folders[ch], "name").text = f"LINE {ch}"

            # Masukkan placemark sesuai nama folder sumber
            for pm in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
                parent = pm.find("../{http://www.opengis.net/kml/2.2}name")
                if parent is not None:
                    pname = parent.text.upper()
                    if "HP" in pname:
                        # contoh logika assign
                        hp_folders["A"].append(pm)
                    elif "POLE" in pname:
                        line_folders["A"].append(pm)

            # Simpan ke KMZ
            kml_str = ET.tostring(kml_doc, encoding="utf-8", xml_declaration=True).decode("utf-8")
            result = save_kmz(kml_str)

            # Download
            with open(result, "rb") as f:
                st.download_button("Download Hasil Gabungan", f, file_name=result,
                                   mime="application/vnd.google-earth.kmz")

        elif menu == "Rename NN di HP":
            # Contoh rename sederhana
            count = 1
            for pm in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
                name_tag = pm.find("{http://www.opengis.net/kml/2.2}name")
                if name_tag is not None and name_tag.text.startswith("NN"):
                    name_tag.text = f"HP-{count:03d}"
                    count += 1

            kml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
            result = save_kmz(kml_str, "hasil_rename.kmz")

            with open(result, "rb") as f:
                st.download_button("Download Hasil Rename", f, file_name=result,
                                   mime="application/vnd.google-earth.kmz")
