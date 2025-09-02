import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import io
from collections import defaultdict

# ==============================
# Fungsi untuk bersihkan prefix
# ==============================
def clean_prefixes(root):
    for elem in root.iter():
        # Hilangkan namespace di tag
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        # Hilangkan namespace di atribut
        new_attrib = {}
        for k, v in elem.attrib.items():
            if "}" in k:
                k = k.split("}", 1)[1]
            new_attrib[k] = v
        elem.attrib.clear()
        elem.attrib.update(new_attrib)


# ==============================
# Fungsi rapikan HP & POLE + rename POLE
# ==============================
def process_hp_pole(kmz_file):
    with zipfile.ZipFile(kmz_file, "r") as z:
        with z.open("doc.kml") as kml_file:
            parser = ET.XMLParser(encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            root = tree.getroot()
            clean_prefixes(root)

            # Ambil semua Folder
            folders = root.findall(".//Folder")

            hp_points = defaultdict(list)
            pole_points = defaultdict(list)

            for folder in folders:
                name = folder.find("name")
                if name is None:
                    continue
                folder_name = name.text.strip().upper()

                # HP Cover
                if folder_name.startswith("HP"):
                    for pm in folder.findall(".//Placemark"):
                        hp_points[folder_name].append(pm)

                # POLE
                elif folder_name.startswith("POLE"):
                    for pm in folder.findall(".//Placemark"):
                        pole_points[folder_name].append(pm)

            # Buat struktur baru
            new_root = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
            document = ET.SubElement(new_root, "Document")

            # HP Cover A-D
            for line in ["A", "B", "C", "D"]:
                folder_hp = ET.SubElement(document, "Folder")
                ET.SubElement(folder_hp, "name").text = f"HP COVER {line}"
                for k, v in hp_points.items():
                    if k.endswith(line):
                        for pm in v:
                            folder_hp.append(pm)

            # POLE A-D dengan rename otomatis
            for line in ["A", "B", "C", "D"]:
                folder_pole = ET.SubElement(document, "Folder")
                ET.SubElement(folder_pole, "name").text = f"LINE {line}"
                count = 1
                for k, v in pole_points.items():
                    if k.endswith(line):
                        for pm in v:
                            name_tag = pm.find("name")
                            if name_tag is None:
                                name_tag = ET.SubElement(pm, "name")
                            name_tag.text = f"POLE-{line}{count}"
                            count += 1
                            folder_pole.append(pm)

            # Simpan hasil ke KMZ baru
            new_tree = ET.ElementTree(new_root)
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
                kml_bytes = io.BytesIO()
                new_tree.write(kml_bytes, encoding="utf-8", xml_declaration=True)
                zout.writestr("doc.kml", kml_bytes.getvalue())

            return output


# ==============================
# Fungsi rename NN di HP
# ==============================
def rename_nn(kmz_file):
    with zipfile.ZipFile(kmz_file, "r") as z:
        with z.open("doc.kml") as kml_file:
            parser = ET.XMLParser(encoding="utf-8")
            tree = ET.parse(kml_file, parser=parser)
            root = tree.getroot()
            clean_prefixes(root)

            placemarks = root.findall(".//Placemark")

            count = 1
            for pm in placemarks:
                name = pm.find("name")
                if name is not None and name.text and "NN" in name.text:
                    name.text = f"NN-{count}"
                    count += 1

            # Simpan hasil ke KMZ baru
            new_tree = ET.ElementTree(root)
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zout:
                kml_bytes = io.BytesIO()
                new_tree.write(kml_bytes, encoding="utf-8", xml_declaration=True)
                zout.writestr("doc.kml", kml_bytes.getvalue())

            return output


# ==============================
# Streamlit UI
# ==============================
st.title("KMZ Tools - HP & POLE Organizer")

menu = st.sidebar.selectbox("Pilih Menu", ["Rapikan HP & POLE", "Rename NN di HP"])

uploaded_file = st.file_uploader("Upload KMZ", type="kmz")

if uploaded_file:
    if menu == "Rapikan HP & POLE":
        if st.button("Proses"):
            result = process_hp_pole(uploaded_file)
            st.success("Selesai! HP & POLE sudah dirapikan dan POLE sudah diinput otomatis.")
            st.download_button("Download Hasil KMZ", result.getvalue(), "rapikan_hp_pole.kmz")

    elif menu == "Rename NN di HP":
        if st.button("Proses"):
            result = rename_nn(uploaded_file)
            st.success("Selesai! Nama NN sudah diubah.")
            st.download_button("Download Hasil KMZ", result.getvalue(), "rename_nn.kmz")
