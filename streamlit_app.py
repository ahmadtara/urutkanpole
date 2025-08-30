import streamlit as st
import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 10  


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

    # Hapus semua prefix namespace yang bikin error
    for bad_ns in ["ns1:", "ns2:", "gx:", "atom:", "kml:"]:
        content = content.replace(bad_ns, "")

    fixed_file = kml_file + "_fixed.kml"
    with open(fixed_file, "w", encoding="utf-8") as f:
        f.write(content)

    tree = ET.parse(fixed_file)
    return tree, tmpdir



def extract_geometry(placemark):
    """Ambil Point / LineString / Polygon dari Placemark"""
    geom = placemark.find(".//Point/coordinates")
    if geom is not None:
        lon, lat, *_ = map(float, geom.text.strip().split(","))
        return Point(lon, lat)

    geom = placemark.find(".//LineString/coordinates")
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
        return LineString(coords)

    geom = placemark.find(".//Polygon/outerBoundaryIs/LinearRing/coordinates")
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
        return Polygon(coords)

    return None


def classify_poles(tree):
    """Klasifikasikan POLE ke dalam masing-masing LINE"""
    doc = tree.getroot()

    # ambil semua POLE global (urutan sesuai KML asli)
    poles = []
    for pm in doc.findall(".//Folder[name='POLE']//Placemark"):
        name = pm.find("name").text
        geom = extract_geometry(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    # Simpan semua kabel & boundary per LINE
    lines_data = {}
    for line_folder in doc.findall(".//Folder"):
        line_name_el = line_folder.find("name")
        if line_name_el is None:
            continue
        line_name = line_name_el.text
        if not line_name or not line_name.upper().startswith("LINE"):
            continue

        # cari distribution cable
        cable = None
        for pm in line_folder.findall(".//Placemark"):
            nm = (pm.find("name").text or "").upper()
            if "DISTRIBUTION CABLE" in nm:
                cable = extract_geometry(pm)

        # cari boundary
        boundaries = []
        for pm in line_folder.findall(".//Placemark"):
            nm = (pm.find("name").text or "").upper()
            if "BOUNDARY" in nm:
                boundaries.append((nm, extract_geometry(pm)))

        lines_data[line_name.upper()] = {
            "cable": cable,
            "boundaries": boundaries,
            "poles": []
        }

    # Assign setiap POLE ke line terdekat
    for name, p in poles:
        assigned_line = None
        proj_val = None

        for line_name, content in lines_data.items():
            cable = content["cable"]
            boundaries = content["boundaries"]

            # cek ke kabel
            if cable and isinstance(cable, LineString):
                d = p.distance(cable)
                if d <= DIST_THRESHOLD / 111320:  # meter → degree approx
                    assigned_line = line_name
                    proj_val = cable.project(p)
                    break

            # kalau tidak kena kabel, cek boundary
            if not assigned_line and boundaries:
                for bname, boundary in boundaries:
                    if isinstance(boundary, Polygon) and p.within(boundary):
                        line_key = bname[0].upper()  # huruf depan boundary
                        if line_key in line_name.upper():
                            assigned_line = line_name
                            proj_val = p.x
                            break
            if assigned_line:
                break

        if assigned_line:
            lines_data[assigned_line]["poles"].append((name, p, proj_val))

    return lines_data


def export_kmz(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    """Export hasil ke KMZ baru, folder per LINE dengan urutan global"""
    kml = simplekml.Kml()

    # urutan line A→D
    line_order = sorted(classified.keys())

    counter = 1
    for line_name in line_order:
        f_line = kml.newfolder(name=line_name)
        f_pole = f_line.newfolder(name="POLE")

        poles = classified[line_name]["poles"]
        for (old_name, p, _) in poles:
            new_name = f"{prefix}{str(counter).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
            counter += 1

    kml.savekmz(output_path)


# ----------------
# STREAMLIT APP
# ----------------
def main():
    st.title("📍 Urutkan POLE per LINE dari KMZ")

    uploaded = st.file_uploader("Upload file KMZ", type=["kmz"])
    if uploaded:
        with st.spinner("🔍 Memproses KMZ..."):
            try:
                tree, tmpdir = parse_kmz(uploaded)
                classified = classify_poles(tree)

                # export hasil
                out_path = os.path.join(tmpdir, "output_pole_per_line.kmz")
                export_kmz(classified, out_path)

                with open(out_path, "rb") as f:
                    st.download_button(
                        label="⬇️ Download hasil KMZ",
                        data=f,
                        file_name="output_pole_per_line.kmz",
                        mime="application/vnd.google-earth.kmz"
                    )
                st.success("Selesai ✔")
            except Exception as e:
                st.error(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
