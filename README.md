# aprx-audit
Bulk broken-link checker for ArcGIS Pro projects. Recursively scans .aprx files, inventories data sources across all maps, and reports broken layer and table connections with source type and connection details. Outputs to CSV.

## Requirements
- ArcGIS Pro 3.6 / Python 3.13

## Usage
Meant to be run from OOTB ArcGIS folder.

Example:

    C:/Users/<your_username>/Documents/ArcGIS/<these_scripts>

Command:

```
python audit_aprx_projects.py <root_directory> <output_csv>
```

Progress is printed per project as it goes, and the CSV is flushed after each
one, so an interrupted run still leaves a usable report.

### Exit Codes

| Code | Meaning                                                           |
|------|-------------------------------------------------------------------|
| `0`  | Scan completed, every project and layer was readable              |
| `1`  | Bad arguments, or one or more projects failed to open or read     |

A non-zero exit doesn't mean the report is empty. Everything that could be
read is still written, it's there so the user isn't quietly handed back a partial report.

## Output

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
| Layer/Table Name   | `zoning`                                    |
| Type               | `Layer`                                     |
| Layer Type         | `Feature Layer`                             |
| Workspace Type     | `FileGDB`                                   |
| Connection String  | `data/breakable_sources.gdb/zoning`         |
| Status             | `Broken`                                    |

Context columns fall back to `Unknown` when unavailable and Portal URL and Portal User will do it on an unauthenticated machine.

### Status Values

| Status                | Meaning                                                |
|-----------------------|--------------------------------------------------------|
| `Broken`              | Layer or table read but its data source is unreachable |
| `Project Open Failed` | The .aprx could not be opened                          |
| `Layer Read Failed`   | A map, layer, or table threw while being inspected     |

Failures are pretty isolated so one unreadable layer doesn't cost the rest of its map, and one unreadable map doesn't cost the rest of the project. Whatever context available at the point of failure is recorded, with `Unknown` in fields that couldn't be read.

**Healthy layers and tables aren't written, only the three statuses above appear in the report.**

### Layer Type

Web-backed layers get a compound label, e.g. `Feature Layer (Web)`. Broken
group layers report as `Group Layer` with no connection details since they have no source. Joined and related layers report both sides in the Connection String, separated by `---joined to--->`.

## Tests
Initially created test fixtures for a number of simple Pro projects, but later testing used existing company projects.

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