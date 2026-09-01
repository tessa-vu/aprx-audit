"""
Relocate breakable data sources to simulate broken links in .aprx projects.

Run this in a separate Python session after create_test_fixtures.py, arcpy
holds schema locks on geodatabases and shapefiles until the process exits.

Usage:
    python break_data_links.py <root_directory>
"""

import os
import shutil
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: python break_data_links.py <root_directory>")
        sys.exit(1)

    root = sys.argv[1]
    #root = os.path.abspath(sys.argv[1])
    data_dir = os.path.join(root, "data")
    shp_dir = os.path.join(data_dir, "shapefiles")
    broken_dir = os.path.join(data_dir, "_moved_to_break")
    proj_dir = os.path.join(root, "Projects")

    targets = [
        os.path.join(data_dir, "breakable_sources.gdb"),
        os.path.join(shp_dir, "wetlands.shp")
    ]

    if os.path.exists(broken_dir) and os.listdir(broken_dir):
        print(f"WARNING: {broken_dir} already has files (previous run?)")
        print("     Clear it before re-running for a clean state.\n")

    movable = [t for t in targets if os.path.exists(t)]
    if not movable:
        print("Nothing to move, targets already relocated or not yet created.")
        print("Re-run create_test_fixtures.py if starting fresh.")
        sys.exit(1)

    os.makedirs(broken_dir, exist_ok = True)

    for src in movable:
        dst = os.path.join(broken_dir, os.path.basename(src))
        shutil.move(src, dst)

        if src.endswith(".shp"):
            base = os.path.splitext(src)[0]
            for ext in (".dbf", ".prj", ".shx", ".cpg", ".sbn", ".sbx"):
                sidecar = base + ext
                if os.path.exists(sidecar):
                    shutil.move(sidecar, os.path.join(broken_dir, os.path.basename(sidecar)))

    print(f"Relocated {len(movable)} target(s) to {broken_dir}\n")
    print("Expected broken counts:")
    print("    all_valid.aprx: 0 (parcels, streets, parks)")
    print("    mixed_sources.aprx: 2 (zoning, wetlands broken)")
    print("    all_broken.aprx: 3 (zoning, flood_zones, wetlands)")
    print(f"\nVerify:\n    python audit_aprx_projects.py {proj_dir} report.csv")

if __name__ == "__main__":
    main()
