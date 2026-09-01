"""
Find broken layers and tables across .aprx projects, write results to CSV.
"""

import csv
import glob
import os
import sys
import arcpy

def main():
    if len(sys.argv) != 3:
        print("Usage: python audit_aprx_projects.py <root_directory> <output_csv>")
        sys.exit(1)

    root_dir, output_csv = sys.argv[1], sys.argv[2]
    aprx_files = glob.glob(os.path.join(root_dir, "**", "*.aprx"), recursive = True)

    total_broken = 0
    with open(output_csv, "w", newline = "", encoding = "utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Project Path", "Map Name", "Layer/Table Name", "Type", "Is Broken"])

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
                        writer.writerow([aprx_path, m.name, lyr.name, "Layer", "Yes"])
                        total_broken += 1

                for tbl in m.listTables():
                    if tbl.isBroken:
                        writer.writerow([aprx_path, m.name, tbl.name, "Table", "Yes"])
                        total_broken += 1

        del aprx

    print(f"\nScanned {len(aprx_files)} project(s). Found {total_broken} broken source(s).")
    print(f"Report: {output_csv}")

if __name__ == "__main__":
    main()
