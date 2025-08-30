import os
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from shapely.geometry import Point, LineString, Polygon

DIST_THRESHOLD = 10  # meter, batas jarak pole ke kabel

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
