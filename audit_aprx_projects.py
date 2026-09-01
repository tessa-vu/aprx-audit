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
import arcpy

CSV_HEADER = [
    "Project Path",
    "Map Name",
    "Layer/Table Name",
    "Type",
    "Layer Type",
    "Workspace Type",
    "Connection String",
    "Is Broken"
]

LAYER_TYPE_FLAGS = [
    ("isBasemapLayer", "Basemap Layer"),
    ("isFeatureLayer", "Feature Layer"),
    ("isRasterLayer", "Raster Layer"),
    ("isSceneLayer", "Scene Layer"),
    ("isServiceLayer", "Service Layer"),
    ("isWebLayer", "Web Layer")
]

def describe_layer_type(lyr):
    for attr, label in LAYER_TYPE_FLAGS:
        if getattr(lyr, attr, False):
            return label
    return "Other"

def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    root_dir, output_csv = sys.argv[1], sys.argv[2]
    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive = True)

    total_broken = 0
    with open(output_csv, "w", newline = "", encoding = "utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        for aprx_path in aprx_files:
            print(f"Auditing {aprx_path}")
            try:
                aprx = arcpy.mp.ArcGISProject(aprx_path)
            except (OSError, RuntimeError) as e:
                print(f"    WARNING: Could not open ({e})")
                continue

            for m in aprx.listMaps():
                for lyr in m.listLayers():
                    if lyr.isGroupLayer:
                        continue
                    if lyr.isBroken:
                        writer.writerow([aprx_path, m.name, lyr.name, "Layer",
                                         describe_layer_type(lyr), "", "", "Yes"])
                        total_broken += 1

                for tbl in m.listTables():
                    if tbl.isBroken:
                        writer.writerow([aprx_path, m.name, tbl.name, "Table",
                                         "Standalone Table", "", "","Yes"])
                        total_broken += 1

        del aprx

    print(f"\nScanned {len(aprx_files)} project(s). Found {total_broken} broken source(s).")
    print(f"Report: {output_csv}")

if __name__ == "__main__":
    main()
