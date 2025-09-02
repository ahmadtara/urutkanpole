import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
import streamlit as st

# Hapus prefix ns supaya bersih
def clean_namespace(tree):
    for elem in tree.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.split('}', 1)[1]
    return tree

# Fungsi untuk rapikan HP dan POLE ke boundary
def process_hp_pole(kmz_file):
    with zipfile.ZipFile(kmz_file, 'r') as kmz:
        with tempfile.TemporaryDirectory() as tmpdirname:
            kmz.extractall(tmpdirname)
            kml_path = None
            for root, _, files in os.walk(tmpdirname):
                for f in files:
                    if f.endswith(".kml"):
                        kml_path = os.path.join(root, f)
                        break
            if not kml_path:
                st.error("KML file tidak ditemukan di dalam KMZ")
                return None

            tree = ET.parse(kml_path)
            root = tree.getroot()
            tree = clean_namespace(tree)

            document = root.find("Document")

            # Buat folder hasil
            hp_covers = {x: ET.Element("Folder") for x in ["A", "B", "C", "D"]}
            pole_lines = {x: ET.Element("Folder") for x in ["A", "B", "C", "D"]}

            for k, v in hp_covers.items():
                name = ET.SubElement(v, "name")
                name.text = f"HP COVER {k}"

            for k, v in pole_lines.items():
                name = ET.SubElement(v, "name")
                name.text = f"LINE {k}"

            # Cari folder HP
            for folder in document.findall("Folder"):
                fname = folder.find("name")
                if fname is not None and fname.text.upper() == "HP":
                    for pm in folder.findall("Placemark"):
                        # sementara random assign ke A
                        hp_covers["A"].append(pm)

                if fname is not None and fname.text.upper() == "POLE":
                    for pm in folder.findall("Placemark"):
                        # sementara random assign ke A
                        pole_lines["A"].append(pm)

            # Bersihkan document lama → masukkan hasil
            for f in list(document):
                document.remove(f)

            for v in hp_covers.values():
                document.append(v)

            for v in pole_lines.values():
                document.append(v)

            # Simpan KML hasil
            output_kml = os.path.join(tmpdirname, "doc.kml")
            tree.write(output_kml, encoding="utf-8", xml_declaration=True)

            # Kompres jadi KMZ
            output_kmz = os.path.join(tmpdirname, "hasil_gabungan.kmz")
            with zipfile.ZipFile(output_kmz, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(output_kml, "doc.kml")

            return output_kmz

# Fungsi rename NN di HP
def rename_nn(kmz_file):
    with zipfile.ZipFile(kmz_file, 'r') as kmz:
        with tempfile.TemporaryDirectory() as tmpdirname:
            kmz.extractall(tmpdirname)
            kml_path = None
            for root, _, files in os.walk(tmpdirname):
                for f in files:
                    if f.endswith(".kml"):
                        kml_path = os.path.join(root, f)
                        break
            if not kml_path:
                st.error("KML file tidak ditemukan di dalam KMZ")
                return None

            tree = ET.parse(kml_path)
            root = tree.getroot()
            tree = clean_namespace(tree)
            document = root.find("Document")

            counter = 1
            for folder in document.findall("Folder"):
                fname = folder.find("name")
                if fname is not None and fname.text.upper() == "HP":
                    for pm in folder.findall("Placemark"):
                        name_tag = pm.find("name")
                        if name_tag is not None and name_tag.text.startswith("NN"):
                            name_tag.text = f"HP{counter:02d}"
                            counter += 1

            # Simpan hasil
            output_kml = os.path.join(tmpdirname, "doc.kml")
            tree.write(output_kml, encoding="utf-8", xml_declaration=True)

            output_kmz = os.path.join(tmpdirname, "hasil_rename.kmz")
            with zipfile.ZipFile(output_kmz, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(output_kml, "doc.kml")

            return output_kmz

# Streamlit UI
st.title("KMZ Processor")

menu = st.sidebar.radio("Pilih Menu", ["Gabungan (HP + POLE)", "Rename NN di HP"])

uploaded_file = st.file_uploader("Upload KMZ", type=["kmz"])

if uploaded_file is not None:
    if menu == "Gabungan (HP + POLE)":
        result = process_hp_pole(uploaded_file)
        if result:
            with open(result, "rb") as f:
                st.download_button("Download hasil_gabungan.kmz", f, file_name="hasil_gabungan.kmz")

    elif menu == "Rename NN di HP":
        result = rename_nn(uploaded_file)
        if result:
            with open(result, "rb") as f:
                st.download_button("Download hasil_rename.kmz", f, file_name="hasil_rename.kmz")
