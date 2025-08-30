import streamlit as st
import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 10  

# ==============================
# Fungsi Parsing KMZ
# ==============================
def parse_kmz(kmz_file):
    """Extract KMZ dari upload dan parse KML utama"""
    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_file, 'r') as zf:
        zf.extractall(tmpdir)

    # Cari file .kml
    kml_file = None
    for root, dirs, files in os.walk(tmpdir):
        for f in files:
            if f.endswith('.kml'):
                kml_file = os.path.join(root, f)
                break
    if not kml_file:
        raise FileNotFoundError("KML file tidak ditemukan dalam KMZ")

    # --- FIX NAMESPACE ERROR ---
    with open(kml_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Hapus deklarasi xmlns yang bikin error
    content = re.sub(r"\s+xmlns:ns\d+=\"[^\"]*\"", "", content)  # ns1, ns2, dst
    content = re.sub(r"\s+xmlns:gx=\"[^\"]*\"", "", content)
    content = re.sub(r"\s+xmlns:atom=\"[^\"]*\"", "", content)
    content = re.sub(r"\s+xmlns:kml=\"[^\"]*\"", "", content)

    # Hapus prefix di tag
    for bad_ns in ["ns1:", "ns2:", "gx:", "atom:", "kml:"]:
        content = content.replace(bad_ns, "")

    fixed_file = kml_file + "_fixed.kml"
    with open(fixed_file, "w", encoding="utf-8") as f:
        f.write(content)

    tree = ET.parse(fixed_file)
    return tree, tmpdir


# ==============================
# Ekstrak koordinat dari KML
# ==============================
def extract_geometry(tree):
    """Ambil koordinat POLE (Point) dan LINE (LineString)"""
    root = tree.getroot()
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    poles = []
    lines = []

    for pm in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
        name = pm.find("{http://www.opengis.net/kml/2.2}name")
        name = name.text if name is not None else "Unnamed"

        point = pm.find(".//{http://www.opengis.net/kml/2.2}Point")
        linestring = pm.find(".//{http://www.opengis.net/kml/2.2}LineString")

        if point is not None:
            coords_text = point.find("{http://www.opengis.net/kml/2.2}coordinates").text.strip()
            lon, lat, *_ = map(float, coords_text.split(","))
            poles.append({"name": name, "point": Point(lon, lat)})

        elif linestring is not None:
            coords_text = linestring.find("{http://www.opengis.net/kml/2.2}coordinates").text.strip()
            coords = []
            for c in coords_text.split():
                lon, lat, *_ = map(float, c.split(","))
                coords.append((lon, lat))
            lines.append({"name": name, "line": LineString(coords)})

    return poles, lines


# ==============================
# Urutkan POLE ke sepanjang LINE
# ==============================
def classify_poles(poles, lines):
    results = []
    for line in lines:
        for pole in poles:
            dist_along = line["line"].project(pole["point"])
            results.append({
                "line": line["name"],
                "pole": pole["name"],
                "coord": (pole["point"].x, pole["point"].y),
                "distance": dist_along
            })
    results.sort(key=lambda x: (x["line"], x["distance"]))
    return results


# ==============================
# Export hasil ke KMZ
# ==============================
def export_kmz(results, output_file):
    kml = simplekml.Kml()
    last_line = None
    folder = None
    for r in results:
        if r["line"] != last_line:
            folder = kml.newfolder(name=f"Line {r['line']}")
            last_line = r["line"]
        folder.newpoint(name=f"POLE {r['pole']}", coords=[r["coord"]])
    kml.savekmz(output_file)


# ==============================
# Streamlit UI
# ==============================
st.title("📍 Urutkan POLE ke Line dari KMZ")

uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])

if uploaded_file:
    try:
        st.success(f"✅ File `{uploaded_file.name}` berhasil diupload")

        tree, tmpdir = parse_kmz(uploaded_file)
        poles, lines = extract_geometry(tree)

        st.write(f"📌 Ditemukan {len(poles)} POLE dan {len(lines)} LINE di dalam KMZ")

        if st.button("Urutkan POLE"):
            results = classify_poles(poles, lines)

            st.write("### Hasil Urutan:")
            for r in results[:20]:  # tampilkan 20 pertama
                st.write(f"Line {r['line']} - POLE {r['pole']} - Dist {r['distance']:.2f}")

            out_kmz = os.path.join(tmpdir, "POLE_URUTAN.kmz")
            export_kmz(results, out_kmz)

            with open(out_kmz, "rb") as f:
                st.download_button("⬇️ Download KMZ Hasil", f, file_name="POLE_URUTAN.kmz")

    except Exception as e:
        st.error(f"❌ Error: {e}")
