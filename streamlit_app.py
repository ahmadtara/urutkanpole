import zipfile
import os
import tempfile
import simplekml
from lxml import etree as ET
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import nearest_points

# Ambang batas jarak pole ke kabel (meter)
DIST_THRESHOLD = 30  

def parse_kmz(kmz_path):
    """Extract KMZ ke folder sementara dan parse KML utama"""
    tmpdir = tempfile.mkdtemp()
    with zipfile.ZipFile(kmz_path, 'r') as zf:
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

    tree = ET.parse(kml_file)
    return tree, tmpdir


def extract_geometry(placemark):
    """Ambil Point / LineString / Polygon dari Placemark"""
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    geom = placemark.find(".//kml:Point/kml:coordinates", ns)
    if geom is not None:
        lon, lat, *_ = map(float, geom.text.strip().split(","))
        return Point(lon, lat)

    geom = placemark.find(".//kml:LineString/kml:coordinates", ns)
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
        return LineString(coords)

    geom = placemark.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    if geom is not None:
        coords = []
        for c in geom.text.strip().split():
            lon, lat, *_ = map(float, c.split(","))
            coords.append((lon, lat))
        return Polygon(coords)

    return None


def classify_poles(tree):
    """Klasifikasikan POLE ke dalam masing-masing LINE"""
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    doc = tree.getroot()

    # ambil semua POLE global
    poles = []
    for pm in doc.findall(".//kml:Folder[kml:name='POLE']//kml:Placemark", ns):
        name = pm.find("kml:name", ns).text
        geom = extract_geometry(pm)
        if isinstance(geom, Point):
            poles.append((name, geom))

    result = {}
    # loop setiap LINE utama (A, B, C, D)
    for line_folder in doc.findall(".//kml:Folder", ns):
        line_name = line_folder.find("kml:name", ns).text
        if not line_name or not line_name.upper().startswith("LINE"):
            continue

        # cari distribution cable di line ini
        cable = None
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "DISTRIBUTION CABLE" in nm:
                cable = extract_geometry(pm)

        # cari boundary di line ini
        boundaries = []
        for pm in line_folder.findall(".//kml:Placemark", ns):
            nm = (pm.find("kml:name", ns).text or "").upper()
            if "BOUNDARY" in nm:
                boundaries.append((nm, extract_geometry(pm)))

        assigned = []
        for name, p in poles:
            ok = False
            # cek ke kabel dulu
            if cable and isinstance(cable, LineString):
                d = p.distance(cable)
                if d <= DIST_THRESHOLD / 111320:  # approx degree to meter
                    assigned.append((name, p, cable.project(p)))
                    ok = True
            # kalau tidak kena kabel, cek boundary
            if not ok and boundaries:
                for bname, boundary in boundaries:
                    if isinstance(boundary, Polygon) and p.within(boundary):
                        # contoh bname = "A01 BOUNDARY"
                        line_key = bname[0].upper()  # huruf depannya A/B/C/D
                        if line_key in line_name.upper():
                            assigned.append((name, p, p.x))  # pakai X utk urut
                            ok = True
                            break

        # urutkan sesuai kabel kalau ada, kalau tidak pakai X
        if cable and isinstance(cable, LineString):
            assigned.sort(key=lambda x: x[2])
        else:
            assigned.sort(key=lambda x: x[2])

        result[line_name] = {"POLE": assigned}

    return result


def export_kmz(classified, output_path, prefix="MR.OATKRP.P", padding=3):
    """Export hasil ke KMZ baru, folder per LINE"""
    kml = simplekml.Kml()
    for line_name, content in classified.items():
        f_line = kml.newfolder(name=line_name)
        poles = content.get("POLE", [])
        f_pole = f_line.newfolder(name="POLE")
        for i, (old_name, p, _) in enumerate(poles, 1):
            new_name = f"{prefix}{str(i).zfill(padding)}"
            f_pole.newpoint(name=new_name, coords=[(p.x, p.y)])
    kml.savekmz(output_path)


# ----------------
# CONTOH PEMAKAIAN
# ----------------
if __name__ == "__main__":
    tree, _ = parse_kmz("PKB001962.kmz")  # ganti path ke file KMZ Anda
    classified = classify_poles(tree)
    export_kmz(classified, "output_pole_per_line.kmz")
    print("Selesai ✔")
