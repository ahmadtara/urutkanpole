import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

# Namespace standar KML
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)

def parse_kml_from_kmz(kmz_bytes):
    """Ambil doc.kml dari KMZ dan parsing ke ElementTree"""
    with zipfile.ZipFile(BytesIO(kmz_bytes), "r") as kmz:
        with kmz.open("doc.kml") as kml_file:
            tree = ET.parse(kml_file)
            return tree

def build_new_kml(hp_list, pole_list):
    """Buat doc.kml baru berisi folder HP COVER A-D & LINE A-D"""
    kml = ET.Element("{%s}kml" % KML_NS)
    document = ET.SubElement(kml, "Document")

    # HP COVER A/B/C/D
    for key, elements in hp_list.items():
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = f"HP COVER {key.upper()}"
        for idx, el in enumerate(elements, start=1):
            # Rename supaya konsisten
            name_el = el.find("{%s}name" % KML_NS)
            if name_el is not None:
                name_el.text = f"HP {key.upper()}-{idx}"
            folder.append(el)

    # LINE A/B/C/D
    for key, elements in pole_list.items():
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = f"LINE {key.upper()}"
        for idx, el in enumerate(elements, start=1):
            name_el = el.find("{%s}name" % KML_NS)
            if name_el is not None:
                name_el.text = f"POLE {key.upper()}-{idx}"
            folder.append(el)

    return ET.ElementTree(kml)

def clean_and_group(tree):
    """Ambil semua Placemark lalu kelompokkan ke HP/Pole A-D"""
    root = tree.getroot()
    hp_list = {"a": [], "b": [], "c": [], "d": []}
    pole_list = {"a": [], "b": [], "c": [], "d": []}

    for pm in root.findall(".//{%s}Placemark" % KML_NS):
        name_el = pm.find("{%s}name" % KML_NS)
        if name_el is None or not name_el.text:
            continue
        name = name_el.text.lower()

        # Grouping HP
        if "hp" in name:
            for key in hp_list.keys():
                if key in name:
                    hp_list[key].append(pm)
                    break

        # Grouping POLE
        if "pole" in name:
            for key in pole_list.keys():
                if key in name:
                    pole_list[key].append(pm)
                    break

    return hp_list, pole_list

def update_kmz_strict(kmz_bytes, new_kml_tree):
    """Overwrite doc.kml di KMZ dengan hasil baru"""
    new_kml_bytes = BytesIO()
    new_kml_tree.write(new_kml_bytes, encoding="utf-8", xml_declaration=True)

    out_buffer = BytesIO()
    with zipfile.ZipFile(BytesIO(kmz_bytes), "r") as old_kmz:
        with zipfile.ZipFile(out_buffer, "w") as new_kmz:
            for item in old_kmz.infolist():
                # Copy semua file kecuali doc.kml
                if item.filename != "doc.kml":
                    new_kmz.writestr(item, old_kmz.read(item.filename))
            # Overwrite doc.kml dengan yang baru
            new_kmz.writestr("doc.kml", new_kml_bytes.getvalue().decode("utf-8"))

    return out_buffer.getvalue()

# ================== STREAMLIT APP ==================

st.title("📂 KMZ Rapikan HP & POLE (Folder Baru)")

uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

if uploaded_file:
    kmz_bytes = uploaded_file.read()

    # Parse doc.kml lama
    tree = parse_kml_from_kmz(kmz_bytes)

    # Bersihkan & Group
    hp_list, pole_list = clean_and_group(tree)

    # Bangun KML baru (full dari nol)
    new_kml_tree = build_new_kml(hp_list, pole_list)

    # Update ke KMZ lama (overwrite doc.kml)
    new_kmz_bytes = update_kmz_strict(kmz_bytes, new_kml_tree)

    st.success("KMZ berhasil dirapikan ✅")

    # Preview isi
    st.write("### 📊 Preview hasil struktur")
    for key, els in hp_list.items():
        st.write(f"HP COVER {key.upper()}: {len(els)} titik")
    for key, els in pole_list.items():
        st.write(f"LINE {key.upper()}: {len(els)} titik")

    st.download_button(
        "⬇️ Download KMZ hasil",
        data=new_kmz_bytes,
        file_name="rapikan.kmz",
        mime="application/vnd.google-earth.kmz"
    )
