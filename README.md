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

CSV has one row per broken layer or table:

| Column            | Example                                     |
|-------------------|---------------------------------------------|
| Project Path      | `Projects/mixed_sources/mixed_sources.aprx` |
| Map Name          | `Map`                                       |
| Layer/Table Name  | `zoning`                                    |
| Type              | `Layer`                                     |
| Layer Type        | `Feature Layer`                             |
| Workspace Type    | `FileGDB`                                   |
| Connection String | `data/breakable_sources.gdb/zoning`         |
| Is Broken         | `Yes`                                       |

## Tests
Populate blank `.aprx` projects with known-state data sources:

```
python create_test_fixtures.py <root_directory>
# exit Python to release file locks
python break_data_links.py <root_directory>
```

**Projects must be created manually in ArcGIS Pro first, `arcpy` has no**
**project creation function before 3.7.**

**Repo comes with base `.aprx` files in Projects/ folder.**

---

*AI-assisted coding was used for debugging this project.*
