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

    # --- FIX NAMESPACE ERROR ---
    with open(kml_file, "r", encoding="utf-8") as f:
        content = f.read()

    # hapus semua ns1: atau gx: atau atom: dll
    for bad_ns in ["ns1:", "gx:", "atom:", "kml:"]:
        content = content.replace(bad_ns, "")

    # tulis ulang
    fixed_file = kml_file + "_fixed.kml"
    with open(fixed_file, "w", encoding="utf-8") as f:
        f.write(content)

    tree = ET.parse(fixed_file)
    return tree, tmpdir
