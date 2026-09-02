"""
Scan a directory tree for .aprx files and report broken data sources to CSV.

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

import arcpy

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

# isWebLayer is handled separately to produce compound labels like
# "Feature Layer (Web)" so it's not in this list
LAYER_TYPE_FLAGS = [
    ("isBasemapLayer", "Basemap Layer"),
    ("isFeatureLayer", "Feature Layer"),
    ("isRasterLayer", "Raster Layer"),
    ("isSceneLayer", "Scene Layer"),
    ("isServiceLayer", "Service Layer"),
    ("isWebLayer", "Web Layer"),
]


def describe_layer_type(lyr):
    is_web = getattr(lyr, "isWebLayer", False)
    for attr, label in LAYER_TYPE_FLAGS:
        if attr == "isWebLayer":
            continue
        if getattr(lyr, attr, False):
            return f"{label} (Web)" if is_web else label
    return "Web Layer" if is_web else "Other"


def extract_source_info(properties):
    # Handles flat dicts (file/SDE/web) and nested shape that
    # joined or related layers produce (source + destination keys)
    if not properties:
        return "Unknown", "Unable to Retrieve"

    if "source" in properties and "destination" in properties:
        src_ws, src_conn = extract_source_info(properties["source"])
        _, dst_conn = extract_source_info(properties["destination"])
        return src_ws, f"{src_conn} ---joined to--> {dst_conn}"

    workspace_type = properties.get("workspace_factory", "Unknown")
    connection_info = properties.get("connection_info") or {}
    dataset = properties.get("dataset", "")

    if "url" in connection_info:
        return workspace_type, connection_info["url"]

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
    try:
        return item.connectionProperties
    except AttributeError:
        return None


def format_file_size(path):
    size = os.path.getsize(path)

    if size < 1024:
        return f"{size} bytes"

    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}"


def format_elapsed_time(seconds):
    if seconds < 1:
        return f"{round(seconds * 1000)} ms"

    if seconds < 60:
        return f"{seconds:.2f} sec"

    minutes = seconds / 60
    return f"{minutes:.2f} min"


def get_run_context():
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
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def write_csv_row(writer, run_context, item_fields):
    writer.writerow(
        [sanitize_csv_cell(value) for value in [*run_context, *item_fields]]
    )


def audit_project(aprx_path, writer, run_context):
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

                if not is_broken:
                    continue

                try:
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
        del project


def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    class ProjectErrorTrackingWriter:
        def __init__(self, csv_writer):
            self.csv_writer = csv_writer
            self.had_read_error = False

        def writerow(self, row):
            if row[-1] == "Layer Read Failed":
                self.had_read_error = True
            self.csv_writer.writerow(row)

    root_dir, output_csv = sys.argv[1], sys.argv[2]
    run_context = get_run_context()

    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive=True)
    print(f"Found {len(aprx_files)} project(s) in {root_dir}\n")

    total_broken = 0
    failed_to_open = 0
    projects_with_read_errors = 0

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        csv_writer = csv.writer(f)
        csv_writer.writerow(CSV_HEADER)

        for aprx_path in aprx_files:
            print(f"Auditing {aprx_path}", flush=True)

            writer = ProjectErrorTrackingWriter(csv_writer)
            start_time = time.perf_counter()
            broken_count = audit_project(aprx_path, writer, run_context)
            elapsed_time = time.perf_counter() - start_time
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

    sys.exit(1 if failed_projects else 0)


if __name__ == "__main__":
    main()
