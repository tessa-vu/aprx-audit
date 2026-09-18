"""
Scan a directory tree for .aprx files and report broken data sources to CSV.

Background for non-GIS readers: an ArcGIS Pro project (.aprx) does not contain
the data it draws. It stores "pointers" ("data sources") to feature classes,
rasters, tables, and web services that live elsewhere, like on a network share, in a
file geodatabase, in an enterprise database, or on a portal. If any of those
are moved, renamed, deleted, or taken offline, the project still opens, but the
layer shows a red exclamation mark in Pro. That is a "broken" layer, and that
is what this script hunts for in bulk without anyone opening Pro by hand.

Usage:
    python audit_aprx_projects.py <root_directory> <output_csv>

Only broken layers and tables are written. Web-backed feature layers show as
"Feature Layer (Web)" etc. Joined layers report both sides. Projects that
fail to open are logged and skipped.
"""

import csv
import glob
import os
import sys
import time
import traceback
from datetime import datetime, timezone

# arcpy ships with ArcGIS Pro. This script must be run with Pro's own Python,
# a plain python.org install cannot import it.
import arcpy

# Column order of the output CSV. The first four columns describe the "run"
# (who/when/where) and repeat on every row so reports from several analysts or
# portals can be concatenated without losing provenance.
CSV_HEADER = [
    "Run Timestamp UTC",
    "ArcGIS Pro Version",
    "Portal URL",
    "Portal User",
    "Project Path",
    "Map Name",
    "Layer/Table Name",
    "Type",
    "Layer Type",
    "Workspace Type",
    "Connection String",
    "Status",
]

# arcpy exposes layer kind as a set of independent boolean properties rather
# than one "type" value, so we test them in order and take the first hit.
# isWebLayer is handled separately to produce compound labels like
# "Feature Layer (Web)" so it's not in this list.
LAYER_TYPE_FLAGS = [
    ("isBasemapLayer", "Basemap Layer"),
    ("isFeatureLayer", "Feature Layer"),
    ("isRasterLayer", "Raster Layer"),
    ("isSceneLayer", "Scene Layer"),
    ("isServiceLayer", "Service Layer"),
    ("isWebLayer", "Web Layer"),
]


def describe_layer_type(lyr):
    """Return a human-readable label for a layer, e.g. "Raster Layer (Web)".

    getattr(..., False) is used because not every layer object exposes every
    flag, a missing property is treated as "no".
    """
    is_web = getattr(lyr, "isWebLayer", False)
    for attr, label in LAYER_TYPE_FLAGS:
        if attr == "isWebLayer":
            continue
        if getattr(lyr, attr, False):
            return f"{label} (Web)" if is_web else label
    return "Web Layer" if is_web else "Other"


def extract_source_info(properties):
    """Reduce arcpy's connectionProperties dict to (workspace type, location).

    "Workspace type" is the storage format the layer points at (FileGDB,
    Shapefile, SDE for an enterprise database, etc). The second value is a
    best-effort, readable description of "where" that data is, a path for file
    based data, a URL for services, or server/instance/database for SDE.
    """
    # Handles flat dicts (file/SDE/web) and nested shape that
    # joined or related layers produce (source + destination keys).
    if not properties:
        return "Unknown", "Unable to Retrieve"

    # A joined layer carries two connections. Recurse into both so the report
    # shows which half of the join is at fault.
    if "source" in properties and "destination" in properties:
        src_ws, src_conn = extract_source_info(properties["source"])
        _, dst_conn = extract_source_info(properties["destination"])
        return src_ws, f"{src_conn} ---joined to--> {dst_conn}"

    workspace_type = properties.get("workspace_factory", "Unknown")
    connection_info = properties.get("connection_info") or {}
    dataset = properties.get("dataset", "")

    # Web services (feature/map/WMS) have a URL instead of a path.
    if "url" in connection_info:
        return workspace_type, connection_info["url"]

    # Enterprise geodatabase, no single path exists, so summarize the
    # connection instead. Credentials are deliberately not included.
    if workspace_type == "SDE":
        keys = ("server", "instance", "database", "version")
        parts = [f"{k} = {connection_info[k]}" for k in keys if k in connection_info]
        if dataset:
            parts.append(f"dataset = {dataset}")
        return workspace_type, "; ".join(parts) if parts else "Unable to Retrieve"

    database = connection_info.get("database", "")
    if database and dataset:
        return workspace_type, os.path.join(database, dataset)
    return workspace_type, database or dataset or "Unable to Retrieve"


def read_connection_properties(item):
    """Safely fetch .connectionProperties, some layer types lack it."""
    try:
        return item.connectionProperties
    except AttributeError:
        return None


def format_file_size(path):
    """Human-readable size of a file, used only for progress output."""
    size = os.path.getsize(path)

    if size < 1024:
        return f"{size} bytes"

    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}"


def format_elapsed_time(seconds):
    """Human-readable duration, used only for progress output."""
    if seconds < 1:
        return f"{round(seconds * 1000)} ms"

    if seconds < 60:
        return f"{seconds:.2f} sec"

    minutes = seconds / 60
    return f"{minutes:.2f} min"


def get_run_context():
    """Build the four provenance columns stamped onto every CSV row.

    Portal details depend on the machine being signed in to ArcGIS Online or
    Enterprise, on an unauthenticated machine they fall back to "Unknown"
    rather than failing the run.
    """

    def value_or_unknown(getter):
        try:
            value = getter()
        except Exception:
            return "Unknown"
        return value if value else "Unknown"

    portal_url = value_or_unknown(arcpy.GetActivePortalURL)

    def get_portal_user():
        portal = arcpy.GetPortalDescription()
        user = portal.get("user") or {}
        return user.get("username")

    return [
        datetime.datetime.now(timezone.utc).isoformat(timespec="seconds"),
        value_or_unknown(lambda: arcpy.GetInstallInfo()["Version"]),
        portal_url,
        value_or_unknown(get_portal_user),
    ]


def sanitize_csv_cell(value):
    """Neutralize CSV injection: Excel would otherwise treat a cell starting
    with = + - or @ as a formula to execute."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def write_csv_row(writer, run_context, item_fields):
    """Write one row: the shared run columns followed by the item's columns."""
    writer.writerow(
        [sanitize_csv_cell(value) for value in [*run_context, *item_fields]]
    )


def audit_project(aprx_path, writer, run_context):
    """Inspect every map, layer and standalone table in one project.

    Returns the number of broken items found, or None if the project itself
    could not be opened.

    Failure is contained at each level: an unreadable layer does not abort its
    map, and an unreadable map does not abort the project. Whatever context
    was known at the point of failure is still written out, with "Unknown" in
    the fields that could not be read.
    """
    try:
        project = arcpy.mp.ArcGISProject(aprx_path)
    except (OSError, RuntimeError, arcpy.ExecuteError) as e:
        print(f"    WARNING: Could not open project ({e})")
        write_csv_row(
            writer,
            run_context,
            [
                aprx_path,
                "Unknown",
                "Unknown",
                "Project",
                "Unknown",
                "",
                str(e),
                "Project Open Failed",
            ],
        )
        traceback.print_exc()
        return None

    broken_count = 0
    try:
        try:
            maps = project.listMaps()
        except (OSError, RuntimeError, arcpy.ExecuteError) as e:
            print(f"    WARNING: Could not list maps ({e})")
            write_csv_row(
                writer,
                run_context,
                [
                    aprx_path,
                    "Unknown",
                    "Unknown",
                    "Layer",
                    "Unknown",
                    "",
                    str(e),
                    "Layer Read Failed",
                ],
            )
            return broken_count

        for m in maps:
            try:
                map_name = m.name
                layers = m.listLayers()
            except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                print(f"    WARNING: Could not read map ({e})")
                write_csv_row(
                    writer,
                    run_context,
                    [
                        aprx_path,
                        getattr(m, "name", "Unknown"),
                        "Unknown",
                        "Layer",
                        "Unknown",
                        "",
                        str(e),
                        "Layer Read Failed",
                    ],
                )
                continue

            for lyr in layers:
                try:
                    is_broken = lyr.isBroken
                    layer_name = lyr.name
                except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                    print(f"    WARNING: Could not read layer ({e})")
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            "Unknown",
                            "Layer",
                            "Unknown",
                            "",
                            str(e),
                            "Layer Read Failed",
                        ],
                    )
                    continue

                # Healthy layers are intentionally not reported.
                if not is_broken:
                    continue

                try:
                    # A group layer is just a folder in the table of contents,
                    # it has no data source of its own to describe.
                    if lyr.isGroupLayer:
                        write_csv_row(
                            writer,
                            run_context,
                            [
                                aprx_path,
                                map_name,
                                layer_name,
                                "Layer",
                                "Group Layer",
                                "",
                                "",
                                "Broken",
                            ],
                        )
                        broken_count += 1
                        continue

                    ws, conn = extract_source_info(read_connection_properties(lyr))
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            layer_name,
                            "Layer",
                            describe_layer_type(lyr),
                            ws,
                            conn,
                            "Broken",
                        ],
                    )
                    broken_count += 1
                except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                    print(f"    WARNING: Could not read layer ({e})")
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            layer_name,
                            "Layer",
                            "Unknown",
                            "",
                            str(e),
                            "Layer Read Failed",
                        ],
                    )

            try:
                tables = m.listTables()
            except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                print(f"    WARNING: Could not list tables in map {map_name} ({e})")
                write_csv_row(
                    writer,
                    run_context,
                    [
                        aprx_path,
                        map_name,
                        "Unknown",
                        "Table",
                        "Standalone Table",
                        "",
                        str(e),
                        "Layer Read Failed",
                    ],
                )
                continue

            for tbl in tables:
                try:
                    is_broken = tbl.isBroken
                    table_name = tbl.name
                except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                    print(f"    WARNING: Could not read table ({e})")
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            "Unknown",
                            "Table",
                            "Standalone Table",
                            "",
                            str(e),
                            "Layer Read Failed",
                        ],
                    )
                    continue

                if not is_broken:
                    continue

                try:
                    ws, conn = extract_source_info(read_connection_properties(tbl))
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            table_name,
                            "Table",
                            "Standalone Table",
                            ws,
                            conn,
                            "Broken",
                        ],
                    )
                    broken_count += 1
                except (OSError, RuntimeError, arcpy.ExecuteError) as e:
                    print(f"    WARNING: Could not read table ({e})")
                    write_csv_row(
                        writer,
                        run_context,
                        [
                            aprx_path,
                            map_name,
                            table_name,
                            "Table",
                            "Standalone Table",
                            "",
                            str(e),
                            "Layer Read Failed",
                        ],
                    )

        return broken_count
    finally:
        # Releases the project object so Pro/arcpy drops its file lock before
        # the next project is opened.
        del project


def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    class ProjectErrorTrackingWriter:
        """Thin wrapper around csv.writer that notes whether the project
        currently being audited produced any read errors."""

        def __init__(self, csv_writer):
            self.csv_writer = csv_writer
            self.had_read_error = False

        def writerow(self, row):
            if row[-1] == "Layer Read Failed":
                self.had_read_error = True
            self.csv_writer.writerow(row)

    root_dir, output_csv = sys.argv[1], sys.argv[2]
    run_context = get_run_context()

    # Recursive search, so pointing at a team share picks up every project
    # underneath it, however deeply nested.
    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive=True)
    print(f"Found {len(aprx_files)} project(s) in {root_dir}\n")

    total_broken = 0
    failed_to_open = 0
    projects_with_read_errors = 0

    # utf-8-sig writes a BOM so Excel renders accented/non-ASCII layer names
    # correctly instead of as unreadable text.
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(CSV_HEADER)

        for aprx_path in aprx_files:
            print(f"Auditing {aprx_path}", flush=True)

            writer = ProjectErrorTrackingWriter(csv_writer)
            start_time = time.perf_counter()
            broken_count = audit_project(aprx_path, writer, run_context)
            elapsed_time = time.perf_counter() - start_time
            # Flush per project so an interrupted run still leaves a usable CSV.
            f.flush()

            if broken_count is None:
                failed_to_open += 1
            else:
                total_broken += broken_count

            if writer.had_read_error:
                projects_with_read_errors += 1

            print(
                f"    {format_file_size(aprx_path)} | "
                f"{format_elapsed_time(elapsed_time)}"
            )

    failed_projects = failed_to_open + projects_with_read_errors

    print(
        f"\nScanned {len(aprx_files)} project(s). Found {total_broken} broken source(s)."
    )
    print(
        f"Projects with Errors: {failed_projects} "
        f"({failed_to_open} open failed, "
        f"{projects_with_read_errors} read errors)"
    )
    print(f"Report: {output_csv}")

    # 1 means "this report may be incomplete", not "nothing was written".
    # Broken layers alone are a successful result and still exit 0.
    sys.exit(1 if failed_projects else 0)


if __name__ == "__main__":
    main()
