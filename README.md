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

## Tests
Populate blank `.aprx` projects with known-state data sources:

```
python create_test_fixtures.py <root_directory>
# exit Python to release file locks
python break_data_links.py <root_directory>
```

**Projects must be created manually in ArcGIS Pro first.**

**Repo comes with base `.aprx` files in Projects/ folder.**

---

*AI-assisted coding was used for debugging this project.*
