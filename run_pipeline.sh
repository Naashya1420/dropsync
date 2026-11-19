#!/usr/bin/env bash
# DropSync: full nightly-batch pipeline, from the Geofabrik India extract to published profiles.
# Usage: ./run_pipeline.sh [path/to/india-YYMMDD.osm.pbf]
# Needs: python env with requirements.txt, osmium-tool (native or docker image dropsync-osmium).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python}
PBF=${1:-$(ls data/raw/india-*.osm.pbf | tail -1)}
export DROPSYNC_WORKERS=${DROPSYNC_WORKERS:-12}

step() { echo; echo "=== $* ==="; }
step "1/9 cut city extracts + campus from $PBF";   $PY -m pipeline.extract_cities "$PBF"
step "2/9 measure OSM coverage, choose city + zone"; $PY -m pipeline.city_select
step "3/9 extract OSM layer: study zone + campus";   $PY -m pipeline.osm_extract && $PY -m pipeline.osm_extract --campus
step "4/9 download real OSM public GPS traces";      $PY -m pipeline.traces
step "5/9 measure GPS noise from real traces";       $PY -m pipeline.noise
step "6/9 simulate delivery history on real map";    $PY -m pipeline.simulate
step "7/9 evaluate (out of sample)";                 $PY -m pipeline.evaluate
step "8/9 publish profiles (+PostGIS if DATABASE_URL)"; $PY -m pipeline.publish
step "9/9 field-trial analysis (if trips recorded)"; $PY -m pipeline.field
