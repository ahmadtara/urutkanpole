# streamlit_app.py
import streamlit as st
import zipfile
import os
import tempfile
import re
import io
import simplekml
from lxml import etree as LET
from shapely.geometry import Point, LineString, Polygon

# Default ambang batas jarak pole ke kabel (meter)
DEFAULT_DIST_THRESHOLD = 30

st.set_page_config(page_title="Urutkan POLE ke LINE", page_icon="📍", layout="wide")


# -------------------------
# Utilities: parse & clean
# -------------------------
def find_kml_in_kmz(kmz_path, tmpdir):
    """Extract KMZ contents and return path to first .kml found."""
    with zipfile.ZipFile(kmz_path, 'r') as zf:
        zf.extractall(tmpdir)
        names = zf.namelist()
    for n in names:
        if n.lower().endswith(".kml"):
            return os.path.join(tmpdir, n)
    return None


def clean_kml_text(raw_bytes):
    """
    Clean text bytes read from a KML file to remove problematic namespace prefixes
    and duplicate xml declarations, return cleaned bytes.
    """
    # decode tolerant
    txt = raw_bytes.decode("utf-8", errors="ignore")

    # remove problematic xmlns:nsX="..." declarations
    txt = re.sub(r'\s+xmlns:ns\d+="[^"]*"', '', txt)

    # remove other vendor namespaces (gx:, atom:, kml: prefixes on tags/attributes)
    # keep default xmlns="..." intact
    txt = re.sub(r'\s+xmlns:(gx|atom|kml)=\"[^\"]*\"', '', txt)
    # remove prefixes like ns1:, ns2:, gx:, atom:, kml:
    txt = re.sub(r'\b(ns\d+|gx|atom|kml):', '', txt)

    # remove duplicate XML declarations (keep at most one)
    txt = re.sub(r'<\?xml.*?\?>', '', txt)
    txt = '<?xml version="1.0" encoding="UTF-8"?>\n' + txt.strip()

    return txt.encode("utf-8")


def safe_parse_kml_bytes(kml_bytes):
    """
    Try parsing KML bytes robustly:
     - clean text, parse with lxml recover
     - if fails, fallback to xml.etree.ElementTree
    Returns parsed ElementTree (lxml or stdlib).
    """
    cleaned = clean_kml_text(kml_bytes)

    # Try lxml with recover
    try:
        parser = LET.XMLParser(recover=True, encoding="utf-8")
        root = LET.fromstring(cleaned, parser=parser)
        tree = LET.ElementTree(root)
        return tree
    except Exception as e_lxml:
        # Fallback to stdlib
        try:
            import xml.etree.ElementTree as ET_std
            root = ET_std.fromstring(cleaned)
            tree = ET_std.ElementTree(root)
            return tree
        except Exception as e_std:
            # re-raise combined info
            raise RuntimeError(f"Failed to parse KML with lxml ({e_lxml}) and fallback ({e_std})")


# -------------------------
# Geometry extraction
# -------------------------
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def extract_geometry_from_placemark(pm):
    """Given a placemark element (either lxml or stdlib element), return Point/LineString/Polygon or None."""
    # Try both lxml and stdlib style finds (works since element supports namespaces)
    def find_text(el, xpath):
        try:
            res = el.find(xpath, KML_NS)
            return res.text if res is not None else None
        except Exception:
            # fallback: iterate children (stdlib sometimes requires namespace-explicit tag)
            for child in el.iter():
                if child.tag.endswith(xpath.split('/')[-1]):
                    return child.text
            return None

    # Point
    try:
        coord_text = None
        pt = pm.find(".//{http://www.opengis.net/kml/2.2}Point")
        if pt is not None:
            coord_el = pt.find("{http://www.opengis.net/kml/2.2}coordinates")
            if coord_el is not None and coord_el.text:
                coord_text = coord_el.text.strip()
        else:
            coord_text = find_text(pm, ".//kml:Point/kml:coordinates")
        if coord_text:
            lon, lat, *_ = map(float, coord_text.split(","))
            return Point(lon, lat)
    except Exception:
        pass

    # LineString
    try:
        coord_text = None
        ls = pm.find(".//{http://www.opengis.net/kml/2.2}LineString")
        if ls is not None:
            coord_el = ls.find("{http://www.opengis.net/kml/2.2}coordinates")
            if coord_el is not None and coord_el.text:
                coord_text = coord_el.text.strip()
        else:
            coord_text = find_text(pm, ".//kml:LineString/kml:coordinates")
        if coord_text:
            coords = []
            for c in coord_text.split():
                lon, lat, *_ = map(float, c.split(","))
                coords.append((lon, lat))
            return LineString(coords)
    except Exception:
        pass

    # Polygon
    try:
        coord_text = None
        poly = pm.find(".//{http://www.opengis.net/kml/2.2}Polygon")
        if poly is not None:
            coord_el = poly.find(".//{http://www.opengis.net/kml/2.2}outerBoundaryIs/{http://www.opengis.net/kml/2.2}LinearRing/{http://www.opengis.net/kml/2.2}coordinates")
            if coord_el is not None and coord_el.text:
                coord_text = coord_el.text.strip()
        else:
            coord_text = find_text(pm, ".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates")
        if coord_text:
            coords = []
            for c in coord_text.split():
                lon, lat, *_ = map(float, c.split(","))
                coords.append((lon, lat))
            return Polygon(coords)
    except Exception:
        pass

    return None


# -------------------------
# Core logic: classify & export
# -------------------------
def classify_poles_from_tree(tree, dist_threshold_m=DEFAULT_DIST_THRESHOLD):
    """
    Input: parsed ElementTree (lxml or stdlib)
    Returns: dict lines_data with keys: "LINE A", "LINE B", ... each {"cable": LineString|None, "boundaries": [(bname, Polygon)], "poles":[(name, Point, proj_val_or_x)]}
    Order of poles follows the order found in KML (global).
    """
    # unify root access for both lxml and stdlib trees
    root = tree.getroot()

    # collect global POLE placemarks in order
    poles = []
    # find all POLE folder placemarks
    # Try namespace xpath; fallback to manual traversal if needed
    try:
        pms = root.findall(".//kml:Folder[kml:name='POLE']//kml:Placemark", KML_NS)
    except Exception:
        pms = [el for el in root.iter() if el.tag.endswith("Placemark")]

    for pm in pms:
        # name
        nm = None
        try:
            nm = pm.findtext("kml:name", namespaces=KML_NS)
        except Exception:
            # fallback
            for child in pm:
                if child.tag.endswith("name"):
                    nm = child.text
                    break
        name = (nm or "Unnamed").strip()
        geom = extract_geometry_from_placemark(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    # collect lines & boundaries per LINE folder
    lines_data = {}
    # Find all top-level folders; then pick ones starting with "LINE"
    try:
        folder_elems = root.findall(".//kml:Folder", KML_NS)
    except Exception:
        folder_elems = [el for el in root.iter() if el.tag.endswith("Folder")]

    for fld in folder_elems:
        fname = None
        try:
            fname = fld.findtext("kml:name", namespaces=KML_NS)
        except Exception:
            for child in fld:
                if child.tag.endswith("name"):
                    fname = child.text
                    break
        if not fname:
            continue
        fname_text = fname.strip()
        if not fname_text.upper().startswith("LINE"):
            continue

        # within this line folder, find placemarks and extract cable and boundaries
        cable = None
        boundaries = []
        # find placemarks under this folder
        try:
            pm_list = fld.findall(".//kml:Placemark", KML_NS)
        except Exception:
            pm_list = [el for el in fld.iter() if el.tag.endswith("Placemark")]

        for pm in pm_list:
            pname = None
            try:
                pname = pm.findtext("kml:name", namespaces=KML_NS)
            except Exception:
                for child in pm:
                    if child.tag.endswith("name"):
                        pname = child.text
                        break
            pname_text = (pname or "").upper()
            geom = extract_geometry_from_placemark(pm)
            if geom is None:
                continue
            if "DISTRIBUTION CABLE" in pname_text and isinstance(geom, LineString):
                cable = geom
            if "BOUNDARY" in pname_text and isinstance(geom, Polygon):
                boundaries.append((pname or "BOUNDARY", geom))

        lines_data[fname_text.upper()] = {"cable": cable, "boundaries": boundaries, "poles": []}

    # Assign each pole to a line following global pole order
    for name, p in poles:
        assigned_line = None
        proj_val = None
        for line_name, content in lines_data.items():
            cable = content["cable"]
            boundaries = content["boundaries"]

            # check cable proximity first
            if cable and isinstance(cable, LineString):
                try:
                    d_deg = p.distance(cable)  # in degrees (approx)
                    if d_deg <= (dist_threshold_m / 111320.0):
                        assigned_line = line_name
                        proj_val = cable.project(p)
                        break
                except Exception:
                    pass

            # fallback to boundaries
            if boundaries:
                for bname, boundary in boundaries:
                    if isinstance(boundary, Polygon):
                        try:
                            if p.within(boundary):
                                # validate boundary name's first letter matches line letter
                                if (bname or "") and (bname[0].upper() in line_name.upper()):
                                    assigned_line = line_name
                                    proj_val = p.x
                                    break
                        except Exception:
                            pass
                if assigned_line:
                    break

        if assigned_line:
            lines_data[assigned_line]["poles"].append((name, p, proj_val))

    return lines_data


def export_classified_to_kmz(classified, out_path, prefix="MR.OATKRP.P", padding=3):
    """
    Export classified dict to KMZ using simplekml.
    The numbering is global across LINE order (sorted by key).
    """
    k = simplekml.Kml()
    line_order = sorted(classified.keys())
    counter = 1
    for line_name in line_order:
        f_line = k.newfolder(name=line_name)
        f_pole_folder = f_line.newfolder(name="POLE")
        poles = classified[line_name].get("poles", [])
        for (old_name, p, _) in poles:
            new_name = f"{prefix}{str(counter).zfill(padding)}"
            f_pole_folder.newpoint(name=new_name, coords=[(p.x, p.y)])
            counter += 1
    k.savekmz(out_path)


# -------------------------
# Streamlit UI
# -------------------------
st.markdown("## 📍 Urutkan POLE ke LINE (KMZ → KMZ)")
st.markdown("Upload KMZ berisi struktur KML: folder LINE A/B/C/D, folder POLE. Aplikasi akan mengklasifikasikan POLE ke LINE sesuai aturan.")

uploaded = st.file_uploader("Upload file KMZ", type=["kmz"])

st.sidebar.header("Pengaturan")
dist_thresh = st.sidebar.number_input("Ambang jarak ke kabel (meter)", min_value=1, max_value=500, value=DEFAULT_DIST_THRESHOLD, step=1)
prefix_inp = st.sidebar.text_input("Prefix nama baru", value="MR.OATKRP.P")
pad_inp = st.sidebar.number_input("Padding digit", min_value=1, max_value=5, value=3, step=1)
show_preview = st.sidebar.checkbox("Tampilkan preview tabel", value=True)

if uploaded is not None:
    # simpan sementara
    with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmpf:
        tmpf.write(uploaded.read())
        tmp_kmz_path = tmpf.name

    st.success(f"✅ File '{uploaded.name}' di-upload")

    # ekstrak dan cari kml, baca bytes and parse with cleaning
    tmpdir = tempfile.mkdtemp()
    try:
        kml_path = find_kml_in_kmz(tmp_kmz_path, tmpdir)
        if not kml_path:
            st.error("❌ Tidak ditemukan file .kml di dalam KMZ")
        else:
            # read raw bytes
            with open(kml_path, "rb") as fh:
                raw = fh.read()

            # parse safely
            try:
                tree = safe_parse_kml_bytes(raw)
            except Exception as e:
                st.error(f"❌ Gagal parse KML: {e}")
                st.stop()

            # classify poles
            classified = classify_poles_from_tree(tree, dist_threshold_m=dist_thresh)

            # preview dataframe
            rows = []
            counter = 1
            for line in sorted(classified.keys()):
                for (old_name, p, _) in classified[line]["poles"]:
                    new_name = f"{prefix_inp}{str(counter).zfill(pad_inp)}"
                    rows.append({"LINE": line, "OLD_NAME": old_name, "NEW_NAME": new_name, "LON": p.x, "LAT": p.y})
                    counter += 1

            import pandas as pd
            df = pd.DataFrame(rows, columns=["LINE", "OLD_NAME", "NEW_NAME", "LON", "LAT"])

            if show_preview:
                st.subheader("Preview hasil (urutan global preserved)")
                st.dataframe(df, use_container_width=True)

            # export KMZ and Excel
            out_kmz = os.path.join(tmpdir, "output_pole_per_line.kmz")
            export_classified_to_kmz(classified, out_kmz, prefix=prefix_inp, padding=pad_inp)

            # excel
            excel_io = io.BytesIO()
            df.to_excel(excel_io, index=False, sheet_name="POLE")
            excel_io.seek(0)

            # download buttons
            with open(out_kmz, "rb") as f_kmz:
                st.download_button("⬇️ Download KMZ hasil", data=f_kmz, file_name="output_pole_per_line.kmz",
                                   mime="application/vnd.google-earth.kmz")
            st.download_button("⬇️ Download Excel hasil", data=excel_io.getvalue(), file_name="output_pole_per_line.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.success("✅ Selesai. Hasil diklasifikasikan dan siap diunduh.")

    except Exception as e:
        st.error(f"❌ Error saat memproses file: {e}")
