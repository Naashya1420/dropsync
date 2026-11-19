"""Cut per-city extracts out of the Geofabrik India .osm.pbf in one pass.

Runs osmium-tool (native if on PATH, else docker image `dropsync-osmium`)
with strategy 'smart' so multipolygon relations (large societies, campuses)
are complete.

Usage: python -m pipeline.extract_cities data/raw/india-YYMMDD.osm.pbf
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .city_select import CITIES, bbox_of
from .config import CAMPUS, RAW
from .osm_extract import osmium_cmd


def main():
    src = Path(sys.argv[1]).resolve()
    out = RAW / "extracts"
    out.mkdir(parents=True, exist_ok=True)
    extracts = []
    for c in CITIES:
        s, w, n, e = bbox_of(c)
        extracts.append({"output": f"{c}.osm.pbf", "bbox": [w, s, e, n]})
    s, w, n, e = CAMPUS.bbox
    extracts.append({"output": "campus_iiita.osm.pbf", "bbox": [w - 0.01, s - 0.01, e + 0.01, n + 0.01]})
    cfg = {"directory": str(out.resolve()), "extracts": extracts}
    (out / "extracts.json").write_text(json.dumps(cfg, indent=1))
    osmium_cmd(["extract", "--overwrite", "-s", "smart", "-c", str((out / "extracts.json").resolve()),
                str(src)], [src.parent, out])
    for p in sorted(out.glob("*.osm.pbf")):
        print(f"{p.name}: {p.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
