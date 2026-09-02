"""
Scan a directory tree for .aprx files and report broken data sources to CSV.

Usage:
    python audit_aprx_projects.py <root_directory> <output_csv>

Only broken layers and tables are written. Web-backed feature layers show as
"Feature Layer (Web)" etc. Joined layers report both sides. Projects that
fail to open are logged and skipped.
"""

import csv
import getpass
import glob
import os
import socket
import sys
import time
import traceback
from datetime import datetime, timezone

import arcpy

CSV_HEADER = [
    "Run Timestamp UTC",
    "Hostname",
    "OS User",
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
    "Is Broken",
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
        value_or_unknown(socket.gethostname),
        value_or_unknown(getpass.getuser),
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
    except (OSError, arcpy.ExecuteError) as e:
        print(f"    WARNING: Could not open project ({e})")
        traceback.print_exc()
        return 0

    broken_count = 0
    for m in project.listMaps():
        for lyr in m.listLayers():
            if not lyr.isBroken:
                continue

            # Broken group layers (e.g. service-backed composites) don't carry
            # their own connection info, but they're still worth logging
            if lyr.isGroupLayer:
                write_csv_row(
                    writer,
                    run_context,
                    [
                        aprx_path,
                        m.name,
                        lyr.name,
                        "Layer",
                        "Group Layer",
                        "",
                        "",
                        "Yes",
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
                    m.name,
                    lyr.name,
                    "Layer",
                    describe_layer_type(lyr),
                    ws,
                    conn,
                    "Yes",
                ],
            )
            broken_count += 1

        for tbl in m.listTables():
            if not tbl.isBroken:
                continue

            ws, conn = extract_source_info(read_connection_properties(tbl))
            write_csv_row(
                writer,
                run_context,
                [
                    aprx_path,
                    m.name,
                    tbl.name,
                    "Table",
                    "Standalone Table",
                    ws,
                    conn,
                    "Yes",
                ],
            )
            broken_count += 1

    del project
    return broken_count


def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    root_dir, output_csv = sys.argv[1], sys.argv[2]
    run_context = get_run_context()

    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive=True)
    print(f"Found {len(aprx_files)} project(s) in {root_dir}\n")

    total_broken = 0
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        for aprx_path in aprx_files:
            start_time = time.perf_counter()
            broken_count = audit_project(aprx_path, writer, run_context)
            elapsed_time = time.perf_counter() - start_time

            total_broken += broken_count
            print(
                f"Auditing {aprx_path} | "
                f"{format_file_size(aprx_path)} | "
                f"{format_elapsed_time(elapsed_time)}"
            )

    print(
        f"\nScanned {len(aprx_files)} project(s). Found {total_broken} broken source(s)."
    )
    print(f"Report: {output_csv}")


if __name__ == "__main__":
    main()
