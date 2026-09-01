"""
Scan a directory tree for .aprx files and report broken data sources to CSV.

Usage:
    python audit_aprx_projects.py <root_directory> <output_csv>

Only broken layers and tables are written. Projects that fail to open are logged and skipped.
"""

import csv
import glob
import os
import sys
import traceback

import arcpy

CSV_HEADER = [
    "Project Path",
    "Map Name",
    "Layer/Table Name",
    "Type",
    "Layer Type",
    "Workspace Type",
    "Connection String",
    "Is Broken",
]

LAYER_TYPE_FLAGS = [
    ("isBasemapLayer", "Basemap Layer"),
    ("isFeatureLayer", "Feature Layer"),
    ("isRasterLayer", "Raster Layer"),
    ("isSceneLayer", "Scene Layer"),
    ("isServiceLayer", "Service Layer"),
    ("isWebLayer", "Web Layer"),
]


def describe_layer_type(lyr):
    for attr, label in LAYER_TYPE_FLAGS:
        if getattr(lyr, attr, False):
            return label
    return "Other"


def extract_source_info(properties):
    if not properties:
        return "Unknown", "Unable to Retrieve"

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
    return workspace_type, database or "Unable to Retrieve"


def read_connection_properties(item):
    try:
        return item.connectionProperties
    except AttributeError:
        return None


def audit_project(aprx_path, writer):
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
            # their own connection info, bur they're still worth logging
            if lyr.isGroupLayer:
                writer.writerow(
                    [
                        aprx_path,
                        m.name,
                        lyr.name,
                        "Layer",
                        "Group Layer",
                        "",
                        "",
                        "Yes",
                    ]
                )
                broken_count += 1
                continue

            ws, conn = extract_source_info(read_connection_properties(lyr))
            writer.writerow(
                [
                    aprx_path,
                    m.name,
                    lyr.name,
                    "Layer",
                    describe_layer_type(lyr),
                    ws,
                    conn,
                    "Yes",
                ]
            )
            broken_count += 1

        for tbl in m.listTables():
            if not tbl.isBroken:
                continue

            ws, conn = extract_source_info(read_connection_properties(tbl))
            writer.writerow(
                [
                    aprx_path,
                    m.name,
                    tbl.name,
                    "Table",
                    "Standalone Table",
                    ws,
                    conn,
                    "Yes",
                ]
            )
            broken_count += 1

    del project
    return broken_count


def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    root_dir, output_csv = sys.argv[1], sys.argv[2]

    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive=True)
    print(f"Found {len(aprx_files)} project(s) in {root_dir}\n")

    total_broken = 0
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        for aprx_path in aprx_files:
            print(f"Auditing {aprx_path}")
            total_broken += audit_project(aprx_path, writer)

    print(
        f"\nScanned {len(aprx_files)} project(s). Found {total_broken} broken source(s)."
    )
    print(f"Report: {output_csv}")


if __name__ == "__main__":
    main()
