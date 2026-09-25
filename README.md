# aprx-audit

Bulk data-source inventory and broken-link checker for ArcGIS Pro projects. Recursively scans `.aprx` files, inventories data sources across all maps, and reports every layer and table connection, healthy or broken, with source type and connection details. Outputs to CSV.

## Problem

An ArcGIS Pro project (`.aprx`) does not contain the data it draws. It stores **pointers** to feature classes, rasters, tables and web services that live somewhere else, a network share, a file geodatabase, an enterprise database, or a portal.

When that data is moved, renamed, deleted, or taken offline, the project still opens but the layer shows a red exclamation mark. The project is **broken**.

Finding those one project at a time means opening each in Pro and waiting, but this tool does it for a whole folder tree and hands back a spreadsheet.

Typical Uses:

- Auditing a team or department share before or after a data migration.
- Checking which projects depend on a server that is being deprecated.
- Producing evidence of project health for a handover or an inventory.

## Requirements

- ArcGIS Pro 3.6 (Python 3.13).
- Must be run with **ArcGIS Pro's own Python**, `arcpy` cannot be installed into a normal python.org environment.
- Read access to every project scanned, and ideally to the data those projects point at.
- Sign in to your portal before running if you want the Portal columns populated.

## Scripts Overview

| Script | Purpose | Needs `arcpy` |
|--------|---------|---------------|
| [audit_aprx_projects.py](audit_aprx_projects.py) | The actual audit tool. | Yes |
| [create_test_fixtures.py](create_test_fixtures.py) | Builds known-state test projects and data. | Yes |
| [break_data_links.py](break_data_links.py) | Moves test data to deliberately break links. | No |

The last two are development aids only, you don't need them to audit real projects.

---

## 1. `audit_aprx_projects.py`

The main script. Walks a folder tree, opens every `.aprx` it finds, and writes a CSV row for every layer and standalone table, plus a row for anything that's unreadable.

### Usage

Meant to be run from the OOTB ArcGIS folder, for example:

    C:/Users/<your_username>/Documents/ArcGIS/<these_scripts>

```
python audit_aprx_projects.py <root_directory> <output_csv>
```

| Argument | Meaning |
|----------|---------|
| `<root_directory>` | Folder to search. Searched **recursively**, so nested project folders are included. |
| `<output_csv>` | File to write. **Overwritten** if it already exists. |

Example:

```
python audit_aprx_projects.py "\\server\gis\Projects" broken_sources.csv
```

### What It Does

1. Captures run context once (timestamp, Pro version, portal URL, portal user).
2. Finds every `.aprx` under the root directory.
3. Opens each project, then for every map inspects every layer, and every standalone table.
4. Writes a row for each item, marked `OK` or `Broken` from its `isBroken` flag, plus a row for anything that could not be opened or read.
5. Prints per-project progress with file size and elapsed time.

Progress is printed per project as it goes, and the CSV is flushed after each
one, so an interrupted run still leaves a usable report.

### Exit Codes

| Code | Meaning                                                            |
|------|--------------------------------------------------------------------|
| `0`  | Scan completed, every project and layer was readable.              |
| `1`  | Bad arguments, or one or more projects failed to open or read.     |

A `1` exit doesn't mean the report is empty. Everything that could be
read is still written, it's there so the user isn't quietly handed back a partial report.

**Broken layers on their own are a successful run and still exit `0`.** Broken links are the expected finding, unreadable projects are the problem. Because the two are separated, the script drops straight into a scheduled task or CI job, treat `1` as "investigate the run", not "no results".

### Output

The CSV is written so non-ASCII layer names open correctly in Excel (could be useful for accented/foreign characters), and cells beginning with `=`, `+`, `-` or `@` are quoted so they aren't evaluated as formulas.

Every row has info of the run that produced it, so reports collected from multiple analysts or portals can be combined without losing track of where each row came from.

| Column             | Example                                     |
|--------------------|---------------------------------------------|
| Run Timestamp UTC  | `2026-09-02T14:31:07+00:00`                 |
| ArcGIS Pro Version | `3.6`                                       |
| Portal URL         | `https://www.arcgis.com/`                   |
| Portal User        | `jdoe_org`                                  |
| Project Path       | `Projects/mixed_sources/mixed_sources.aprx` |
| Map Name           | `Map`                                       |
| Parent Group       | `Water\Water body`                          |
| Layer/Table Name   | `zoning`                                    |
| Type               | `Layer`                                     |
| Layer Type         | `Feature Layer`                             |
| Workspace Type     | `FileGDB`                                   |
| Connection String  | `data/breakable_sources.gdb/zoning`         |
| Status             | `Broken`                                    |

Context columns fall back to `Unknown` when unavailable and Portal URL and Portal User will do it on an unauthenticated machine.

**Every layer and standalone table is written, healthy ones included, so the report doubles as a full data-source inventory.** Filter on the Status column to isolate the problems. An empty report (header row only) means no projects, maps or layers were found.

### Status Values

| Status                | Meaning                                                 |
|-----------------------|---------------------------------------------------------|
| `OK`                  | Layer or table read and its data source resolved.       |
| `Broken`              | Layer or table read but its data source is unreachable. |
| `Project Open Failed` | The .aprx couldn't be opened.                           |
| `Layer Read Failed`   | A map, layer, or table threw while being inspected.     |

Failures are pretty isolated so one unreadable layer doesn't cost the rest of its map, and one unreadable map doesn't cost the rest of the project. Whatever context available at the point of failure is recorded, with `Unknown` in fields that couldn't be read.

### Layer Type

Derived from arcpy's boolean layer flags, first match wins:

`Basemap Layer` → `Feature Layer` → `Raster Layer` → `Scene Layer` → `Service Layer` → `Web Layer` → `Other`

Web-backed layers get a compound label, e.g. `Feature Layer (Web)`. Group
layers report as `Group Layer` with no connection details since they have no source. Joined and related layers report both sides in the Connection String, separated by `---joined to--->`.

### Parent Group

Layers inside a group are listed as their own rows, so a group contributes one row for itself plus one for each child. Parent Group is the full table-of-contents path of the groups a layer sits in, backslash-separated for nesting (`Contour Lines\New Group Layer`), and blank for top-level layers and standalone tables.

This matters because group and layer names are rarely unique, a project can easily contain six different `New Group Layer` groups. Rows appear in table-of-contents order, but Parent Group is what actually tells you where a layer lives.

### Workspace Type and Connection String

| Source Kind | Workspace Type | Connection String |
|-------------|----------------|-------------------|
| File Geodatabase / Shapefile / Folder Data | `FileGDB`, `Shapefile`, ... | `<database path>\<dataset>` |
| Enterprise Geodatabase | `SDE` | `server = ..., instance = ..., database = ..., version = ...` |
| Web Service (Feature / Map / WMS) | Varies | Service URL |
| Vector Tile Layer | `Unknown` | Style `root.json` URL, or `.vtpk` path |
| Unavailable | `Unknown` | `Unable to Retrieve` |

Vector tile layers report no workspace type because arcpy gives them a bare `uri` rather than the usual workspace/dataset pair.

Credentials are never written to the report.

---

## 2. `create_test_fixtures.py`

Populates three otherwise-empty projects with layers pointing at freshly created test data, producing a known starting state for testing the auditor.

```
python create_test_fixtures.py <root_directory>
```

**Projects must be created manually in ArcGIS Pro first, `arcpy` has no project creation function before Pro 3.7.** The repo ships with base `.aprx` files in `Projects/`.

Expects:

```
Projects/all_valid/all_valid.aprx
Projects/mixed_sources/mixed_sources.aprx
Projects/all_broken/all_broken.aprx
```

Creates:

```
data/valid_sources.gdb      parcels, streets          (stay put)
data/breakable_sources.gdb  zoning, flood_zones       (moved away later)
data/shapefiles/            parks.shp, wetlands.shp   (wetlands moved later)
```

All datasets are empty, schema only. The auditor only cares whether a source resolves, not what's in it. Layers are added via temporary `.lyrx` layer files in `_lyrx_temp/`, which is deleted at the end, this is the only supported route since arcpy's `addLayer` takes a layer object rather than a path.

After it finishes, **exit the Python session.** `arcpy` holds schema locks on geodatabases and shapefiles until the process exits, so the next step will fail otherwise.

## 3. `break_data_links.py`

Simulates the real-world failure by moving data out from under the projects. Nothing is deleted.

```
python break_data_links.py <root_directory>
```

Moves `data/breakable_sources.gdb` and `data/shapefiles/wetlands.shp` (with all its sidecar files) into `data/_moved_to_break/`. Restore the original state by moving them back.

Resulting expected counts:

| Project | Broken | Layers |
|---------|--------|--------|
| `all_valid.aprx` | 0 | parcels, streets, parks |
| `mixed_sources.aprx` | 2 | zoning, wetlands |
| `all_broken.aprx` | 3 | zoning, flood_zones, wetlands |

Then verify:

```
python audit_aprx_projects.py Projects report.csv
```

Exits `1` if there's nothing left to move, which usually means the script has already been run. If `data/_moved_to_break/` already contains files it warns, clear it before re-running for a clean state.

### Web Service Layers

These can't be scripted and must be added manually in ArcGIS Pro:

> Map Tab → Add Data → Data From Path

Examples:

- WMS: `https://nowcoast.noaa.gov/geoserver/observations/weather_radar/wms?SERVICE=WMS&REQUEST=GetCapabilities`
- REST: `https://services.arcgis.com/P3ePLMYs2RVChkJx/ArcGIS/rest/services/ACS_Children_in_Immigrant_Families_Boundaries/FeatureServer/2`

To simulate a broken web service, unzip the `.aprx`, corrupt the URL in `maps/<map>.json`, re-zip with the `.aprx` extension.

---

## Gaps and Limitations

Worth knowing before relying on the output.

**Scope**

- Only `.aprx` files are scanned. Map packages (`.mpkx`), standalone layer files (`.lyrx`), toolboxes, and ArcMap documents (`.mxd`) are ignored.
- Only layers and standalone tables inside maps are checked. Layouts, charts, reports, locators, and geoprocessing history are not.
- A group layer yields no connection details, since a group has no source of its own.

**Accuracy of "Broken"**

- The script trusts arcpy's `isBroken` flag, so it reflects what Pro itself would show.
- A source can be *reachable but wrong*, e.g. pointing at a stale copy with the right name. That's not broken and won't be reported.
- Results depend on the account and machine running the scan. A layer on a share you can't reach reads as broken even though it's fine for someone else, so run the audit as a user with representative access.
- Web and enterprise layers can be reported as broken simply because a service was briefly down, or because you weren't signed in.
- Being signed in to a different portal than a project expects can change the outcome.

**Performance and Environment**

- Each project is fully opened, which is slow and dominated by network latency. Large shares take a while, per-project timings are printed so you can see where the time goes.
- Broken *network* sources are often the slowest, since each is waited on until it times out.
- Projects locked or open in Pro elsewhere may fail to open and be logged as `Project Open Failed`.
- Projects authored in a newer version of Pro than the one running the script may not open.
- Single-threaded and sequential by design, `arcpy` isn't safe to share across threads.

**Output**

- The CSV is overwritten each run, there's no append or history mode. Use dated filenames if you want a trail.
- Every layer is recorded, so a share with many large projects produces a correspondingly large CSV.
- Connection strings are best-effort. Unusual or plug-in workspace types may fall back to `Unknown` / `Unable to Retrieve`.
- Nothing is repaired. This is a read-only report, fixing sources is a separate exercise.

## Tests

Initially created test fixtures for a number of simple Pro projects, but later testing used existing company projects, which test joins, web services and enterprise connections in ways the fixtures don't.

Populate blank `.aprx` projects with known-state data sources:

```
python create_test_fixtures.py <root_directory>
# exit Python to release file locks
python break_data_links.py <root_directory>
```

**Projects must be created manually in ArcGIS Pro first, `arcpy` has no project creation function before 3.7.**

**Repo comes with base `.aprx` files in Projects/ folder.**

---

*AI-assisted coding was used for debugging this project.*

---

### Disclaimers and Copyright

#### Copyright © 2026 Esri

#### All rights reserved under the copyright laws of the United States and applicable international laws, treaties, and conventions. You may freely redistribute and use this sample code, with or without modification, provided you include the original copyright notice and use restrictions.

#### Disclaimer: THE SAMPLE CODE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ESRI OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) SUSTAINED BY YOU OR A THIRD PARTY, HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT ARISING IN ANY WAY OUT OF THE USE OF THIS SAMPLE CODE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

##### Esri <p>Attn: Contracts and Legal Services Department</p><p>380 New York Street</p><p>Redlands, California, 92373-8100 USA</p><p>email: contracts@esri.com</p>


#### Additional Disclaimers

    - This code snippet is not maintained and/or supported by Esri Technical Support or Staff
    - This code is not guaranteed for stability or accuracy 
    - Esri & its staff cannot be held liable for any direct or indirect damages incurred by running this code 
    - Use at Your Own Risk
    
#### Please make sure to thoroughly review this Code Sample and seek appropriate legal and technical advice before using it in any environment. 
#### You are encouraged to customize and adapt this Code Sample to meet your specific needs and requirements.