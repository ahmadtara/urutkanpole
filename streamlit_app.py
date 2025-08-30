import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from shapely.geometry import Point, LineString, Polygon

DIST_THRESHOLD = 5  # meter, batas jarak pole ke kabel

def extract_geometry(pm):
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    point = pm.find(".//kml:Point/kml:coordinates", ns)
    linestring = pm.find(".//kml:LineString/kml:coordinates", ns)
    polygon = pm.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)

    def parse_coords(coord_text):
        coords = []
        for c in coord_text.strip().split():
            parts = c.split(",")
            if len(parts) >= 2:
                lon, lat = map(float, parts[:2])
                coords.append((lon, lat))
        return coords

    if point is not None and point.text:
        lon, lat = map(float, point.text.strip().split(",")[:2])
        return Point(lon, lat)
    elif linestring is not None and linestring.text:
        return LineString(parse_coords(linestring.text))
    elif polygon is not None and polygon.text:
        return Polygon(parse_coords(polygon.text))
    return None

def export_kmz(result, output_path, prefix="POLE"):
    import simplekml
    kml = simplekml.Kml()

    for line_name, content in result.items():
        folder_line = kml.newfolder(name=line_name)
        poles = content.get("POLE", [])
        for idx, (name, geom, _) in enumerate(poles, 1):
            if isinstance(geom, Point):
                folder_line.newpoint(
                    name=f"{prefix} {idx}",
                    coords=[(geom.x, geom.y)]
                )

    tmp_kml = output_path.replace(".kmz", ".kml")
    kml.save(tmp_kml)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_kml, os.path.basename(tmp_kml))
    os.remove(tmp_kml)

if selected_menu == "Urutkan POLE ke Line":
    st.header("📍 Urutkan POLE ke Line")
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    custom_prefix = st.text_input("Prefix nama POLE", "POLE")

    if uploaded_file:
        tmp_path = os.path.join(tempfile.gettempdir(), uploaded_file.name)
        with open(tmp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        if st.button("Proses"):
            try:
                # Ekstrak KMZ → ambil KML
                extract_dir = tempfile.mkdtemp()
                with zipfile.ZipFile(tmp_path, 'r') as z:
                    z.extractall(extract_dir)
                    files = z.namelist()
                    kml_name = next((f for f in files if f.lower().endswith(".kml")), None)

                if kml_name is None:
                    st.error("❌ Tidak ada file .kml di dalam KMZ")
                    st.stop()

                kml_file = os.path.join(extract_dir, kml_name)

                # Parse KML
                parser = ET.XMLParser(recover=True, encoding="utf-8")
                tree = ET.parse(kml_file, parser=parser)
                ns = {"kml": "http://www.opengis.net/kml/2.2"}
                doc = tree.getroot()
                result = {}

                # loop setiap LINE
                for line_folder in doc.findall(".//kml:Folder", ns):
                    line_name_el = line_folder.find("kml:name", ns)
                    if line_name_el is None:
                        continue
                    line_name = line_name_el.text
                    if not line_name or not line_name.upper().startswith("LINE"):
                        continue

                    # Ambil POLE di dalam LINE ini
                    poles = []
                    for subfolder in line_folder.findall("kml:Folder", ns):
                        sf_name = subfolder.find("kml:name", ns)
                        if sf_name is not None and "POLE" in sf_name.text.upper():
                            for pm in subfolder.findall("kml:Placemark", ns):
                                name_el = pm.find("kml:name", ns)
                                name = name_el.text if name_el is not None else "Unnamed"
                                geom = extract_geometry(pm)
                                if isinstance(geom, Point):
                                    poles.append((name, geom))

                    # cari distribution cable
                    cable = None
                    for pm in line_folder.findall("kml:Placemark", ns):
                        nm = (pm.find("kml:name", ns).text or "").upper()
                        if "DISTRIBUTION CABLE" in nm:
                            cable = extract_geometry(pm)

                    # cari boundary
                    boundaries = []
                    for pm in line_folder.findall("kml:Placemark", ns):
                        nm = (pm.find("kml:name", ns).text or "").upper()
                        if "BOUNDARY" in nm:
                            boundaries.append((nm, extract_geometry(pm)))

                    # assign POLE ke kabel / boundary
                    assigned = []
                    for name, p in poles:
                        ok = False
                        if cable and isinstance(cable, LineString):
                            d = p.distance(cable)
                            if d <= DIST_THRESHOLD / 111320:  # derajat ~ meter
                                assigned.append((name, p, cable.project(p)))
                                ok = True
                        if not ok and boundaries:
                            for bname, boundary in boundaries:
                                if isinstance(boundary, Polygon) and p.within(boundary):
                                    assigned.append((name, p, p.x))
                                    ok = True
                                    break

                    # urutkan
                    if cable and isinstance(cable, LineString):
                        assigned.sort(key=lambda x: x[2])
                    else:
                        assigned.sort(key=lambda x: x[2])

                    result[line_name] = {"POLE": assigned}

                # export hasil
                output_kmz = os.path.join(tempfile.gettempdir(), "output_pole_per_line.kmz")
                export_kmz(result, output_kmz, prefix=custom_prefix)

                st.success("✅ Selesai diurutkan dan diekspor ke KMZ")
                with open(output_kmz, "rb") as f:
                    st.download_button("📥 Download Hasil KMZ", f, file_name="output_pole_per_line.kmz")

            except Exception as e:
                st.error(f"❌ Error: {e}")
