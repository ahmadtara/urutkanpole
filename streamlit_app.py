import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
import tempfile
import re

st.set_page_config(page_title="Urutkan POLE per LINE dari KMZ", page_icon="📍", layout="centered")

st.title("📍 Urutkan POLE per LINE dari KMZ")

uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"], help="Limit 200MB per file • KMZ")

def clean_kml_namespaces(kml_text):
    """
    Membersihkan prefix nsX: (ns1, ns2, ns3, ...) dari file KML agar tidak error.
    """
    # hapus namespace seperti ns1:, ns2:, ns3:
    kml_text = re.sub(r'\s*ns\d+:', '', kml_text)
    # hapus juga deklarasi xmlns:nsX="..."
    kml_text = re.sub(r'xmlns:ns\d+="[^"]+"', '', kml_text)
    return kml_text

def process_kmz(file_bytes):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(BytesIO(file_bytes), 'r') as kmz:
                kmz.extractall(tmpdir)

            # cari doc.kml
            kml_path = tmpdir + "/doc.kml"
            with open(kml_path, "r", encoding="utf-8", errors="ignore") as f:
                kml_text = f.read()

            # bersihkan prefix namespace
            kml_text = clean_kml_namespaces(kml_text)

            # simpan ulang
            fixed_kml_path = tmpdir + "/doc_fixed.kml"
            with open(fixed_kml_path, "w", encoding="utf-8") as f:
                f.write(kml_text)

            # parse KML
            tree = ET.parse(fixed_kml_path)
            root = tree.getroot()

            # ambil semua placemark dengan koordinat
            placemarks = []
            for pm in root.iter():
                if pm.tag.endswith("Placemark"):
                    name = None
                    coords = None
                    for child in pm:
                        if child.tag.endswith("name"):
                            name = child.text
                        if child.tag.endswith("Point"):
                            coord_el = child.find(".//{*}coordinates")
                            if coord_el is not None:
                                coords = coord_el.text.strip()
                    if name and coords:
                        placemarks.append((name, coords))

            return placemarks

    except Exception as e:
        st.error(f"❌ Error: {e}")
        return None

if uploaded_file:
    file_bytes = uploaded_file.read()
    placemarks = process_kmz(file_bytes)

    if placemarks:
        st.success(f"✅ Berhasil membaca {len(placemarks)} titik dari KMZ")
        for name, coords in placemarks[:20]:  # tampilkan max 20 pertama
            st.write(f"📌 {name} → {coords}")
