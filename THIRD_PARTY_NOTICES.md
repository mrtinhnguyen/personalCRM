# Third-party notices

The project-level MIT license applies to the project's own code. Dependencies
and bundled third-party material retain their respective licenses.

## Bundled browser assets

- **D3.js 7.9.0** — ISC; copyright Mike Bostock. Source:
  <https://github.com/d3/d3>. Full notice:
  [`apps/web/public/vendor/d3.LICENSE.txt`](apps/web/public/vendor/d3.LICENSE.txt).
- **TopoJSON Client 3.1.0** — ISC; copyright Michael Bostock. Source:
  <https://github.com/topojson/topojson-client>. Full notice:
  [`apps/web/public/vendor/topojson-client.LICENSE.txt`](apps/web/public/vendor/topojson-client.LICENSE.txt).
- **World Atlas** — ISC for the distribution; copyright Michael Bostock. Source:
  <https://github.com/topojson/world-atlas>. Full notice:
  [`apps/web/public/vendor/world-atlas.LICENSE.txt`](apps/web/public/vendor/world-atlas.LICENSE.txt).
  The bundled `countries-110m.json` and derived `world.geojson` contain geographic
  data based on Natural Earth, which is public domain:
  <https://www.naturalearthdata.com/about/terms-of-use/>.

## Geographic services and reference data

- **OpenStreetMap** map data is © OpenStreetMap contributors and available under
  ODbL. The interface retains visible map attribution. Public tile service usage
  is subject to its own policy: <https://operations.osmfoundation.org/policies/tiles/>.
- **GeoNames** reference data is used through `geonamescache`; GeoNames data is
  available under CC BY 4.0. The interface retains attribution:
  <https://www.geonames.org/export/>.

Other dependencies (including Next.js, React, FastAPI, Leaflet, PostgreSQL, and
Lucide) are installed through package managers or container images and include
their own license metadata. Consult the lockfiles and installed distributions
when redistributing a build. Social platform names identify supported archive
sources and do not imply affiliation or endorsement.
