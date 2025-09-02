elif menu == "Urutkan POLE Global":
    uploaded_file = st.file_uploader("Upload file KMZ", type=["kmz"])
    if uploaded_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".kmz") as tmp:
            tmp.write(uploaded_file.read())
            kmz_file = tmp.name
        st.success(f"✅ File berhasil diupload: {uploaded_file.name}")

        extract_dir = tempfile.mkdtemp()
        with zipfile.ZipFile(kmz_file, 'r') as z:
            z.extractall(extract_dir)
            files = z.namelist()
            kml_name = next((f for f in files if f.lower().endswith(".kml")), None)

        if not kml_name:
            st.error("❌ Tidak ada file .kml di dalam KMZ")
            st.stop()
        kml_file = os.path.join(extract_dir, kml_name)

        # 🧹 Bersihkan tag gx:, ns1:, dll sebelum parsing
        import re
        def clean_invalid_tags(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Hapus tag gx:, ns1:, dan atribut dengan prefix tidak valid
            content = re.sub(r"<(/?)(gx|ns1):[^>]+>", "", content)
            content = re.sub(r"\s+(gx|ns1):[^=]+=\"[^\"]*\"", "", content)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        clean_invalid_tags(kml_file)  # bersihkan sebelum parse

        # Parsing KML
        parser = ET.XMLParser(recover=True, encoding="utf-8")
        tree = ET.parse(kml_file, parser=parser)
        root = tree.getroot()
        ns = {"kml": "http://www.opengis.net/kml/2.2"}

        # Input prefix manual
        prefix = st.text_input("Prefix nama POLE (boleh dikosongkan)", value="MR.PTSTP.P")
        st.caption("💡 Jika dikosongkan, nama POLE akan berupa angka berurutan (contoh: 001, 002, dst)")
        pad_width = st.number_input("Jumlah digit penomoran", min_value=2, max_value=6, value=3, step=1)

        # Ambil Distribution Cable (LineString)
        cables = {}
        for folder in root.findall(".//kml:Folder", ns):
            fname = folder.find("kml:name", ns)
            if fname is not None and fname.text.startswith("LINE "):
                line_name = fname.text
                for placemark in folder.findall(".//kml:Placemark", ns):
                    line = placemark.find(".//kml:LineString", ns)
                    if line is not None:
                        coords_text = line.find("kml:coordinates", ns).text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        cables[line_name] = LineString(coords)

        # Ambil Boundary (Polygon)
        boundaries = {}
        for folder in root.findall(".//kml:Folder", ns):
            fname = folder.find("kml:name", ns)
            if fname is not None and fname.text.startswith("LINE "):
                line_name = fname.text
                boundaries[line_name] = {}
                for placemark in folder.findall(".//kml:Placemark", ns):
                    pname = placemark.find("kml:name", ns)
                    polygon = placemark.find(".//kml:Polygon", ns)
                    if pname is not None and polygon is not None:
                        coords_text = polygon.find(".//kml:coordinates", ns).text
                        coords = [(float(x.split(",")[0]), float(x.split(",")[1]))
                                  for x in coords_text.strip().split()]
                        boundaries[line_name][pname.text] = Polygon(coords)

        # Ambil POLE (Point)
        poles = []
        for folder in root.findall(".//kml:Folder", ns):
            fname = folder.find("kml:name", ns)
            if fname is not None and fname.text == "POLE":
                for placemark in folder.findall("kml:Placemark", ns):
                    pname = placemark.find("kml:name", ns)
                    point = placemark.find(".//kml:Point", ns)
                    if pname is not None and point is not None:
                        coords_text = point.find("kml:coordinates", ns).text.strip()
                        lon, lat, *_ = map(float, coords_text.split(","))
                        poles.append((pname, placemark, Point(lon, lat)))

        # Assign POLE ke line (cek cable dulu, fallback boundary)
        assignments = {ln: [] for ln in boundaries.keys()}
        for pname, pm, pt in poles:
            assigned_line = None
            # cek distribution cable terdekat
            for line_name, cable in cables.items():
                if cable.distance(pt) < 0.0001:  # threshold ~30m
                    assigned_line = line_name
                    break
            # fallback ke boundary
            if not assigned_line:
                for line_name, bdict in boundaries.items():
                    for poly in bdict.values():
                        if poly.contains(pt):
                            assigned_line = line_name
                            break
                    if assigned_line:
                        break
            if assigned_line:
                assignments[assigned_line].append(pm)

        # Susun ulang KML dengan penomoran global
        document = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        doc_el = ET.SubElement(document, "Document")
        counter = 1
        for line in sorted(assignments.keys()):  # LINE A → LINE D
            line_folder = ET.SubElement(doc_el, "Folder")
            ET.SubElement(line_folder, "name").text = line
            for pm in assignments[line]:
                nm = pm.find("kml:name", ns)
                if nm is not None:
                    if prefix.strip():
                        nm.text = f"{prefix}{str(counter).zfill(int(pad_width))}"
                    else:
                        nm.text = str(counter).zfill(int(pad_width))
                line_folder.append(pm)
                counter += 1

        # Simpan hasil
        new_kml = os.path.join(extract_dir, "poles_global.kml")
        ET.ElementTree(document).write(new_kml, encoding="utf-8", xml_declaration=True)
        output_kmz = os.path.join(extract_dir, "poles_global.kmz")
        with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(new_kml, "doc.kml")

        with open(output_kmz, "rb") as f:
            st.download_button("📥 Download POLE Global", f,
                               file_name="poles_global.kmz",
                               mime="application/vnd.google-earth.kmz")
