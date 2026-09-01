"""
Add test layers to pre-existing .aprx projects.

Empty projects must be created manually in ArcGIS Pro first, arcpy has no project
creation function before Pro 3.7. Expected layout:

    Projects/all_valid/all_valid.aprx
    Projects/mixed_sources/mixed_sources.aprx
    Projects/all_broken/all_broken.aprx

After running this script, exist Python to release file locks, then run
break_data_links.py to relocate the breakable sources.

Usage:
    python create_test_fixtures.py <root_directory>
"""

import os
import shutil
import sys
import time
import arcpy

def make_gdb(parent, name):
    path = os.path.join(parent, name)
    if not arcpy.Exists(path):
        arcpy.management.CreateFileGDB(parent, name)
    return path

def make_feature_class(gdb, name, geometry = "POINT"):
    fc = os.path.join(gdb, name)
    if not arcpy.Exists(fc):
        arcpy.management.CreateFeatureclass(gdb, name, geometry, spatial_reference = 4326)
    return fc

def make_shapefile(folder, name, geometry = "POLYGON"):
    out = os.path.join(folder, name + ".shp")
    if not arcpy.Exists(out):
        arcpy.management.CreateFeatureclass(folder, name, geometry, spatial_reference = 4326)
    return out

def make_lyrx(source, lyrx_path):
    tmp = f"_tmp_{os.path.splitext(os.path.basename(lyrx_path))[0]}"
    arcpy.management.MakeFeatureLayer(source, tmp)
    arcpy.management.SaveToLayerFile(tmp, lyrx_path)
    arcpy.management.Delete(tmp)

def add_layers(aprx_path, lyrx_paths):
    aprx = arcpy.mp.ArcGISProject(aprx_path)
    m = aprx.listMaps()[0]
    for lyrx in lyrx_paths:
        m.addLayer(arcpy.mp.LayerFile(lyrx))
    aprx.save()
    del aprx

def main():
    if len(sys.argv) != 2:
        print("Usage: python create_test_fixtures.py <root_directory>")
        sys.exit(1)

    root = os.path.abspath(sys.argv[1])
    proj_dir = os.path.join(root, "Projects")
    data_dir = os.path.join(root, "data")
    shp_dir = os.path.join(data_dir, "shapefiles")
    lyrx_dir = os.path.join(root, "_lyrx_temp")

    expected = {
        "all_valid": os.path.join(proj_dir, "all_valid", "all_valid.aprx"),
        "mixed": os.path.join(proj_dir, "mixed_sources", "mixed_sources.aprx"),
        "all_broken": os.path.join(proj_dir, "all_broken", "all_broken.aprx")
    }

    missing = [n for n, p in expected.items() if not os.path.exists(p)]

    if missing:
        print("Missing projects (create these in ArcGIS Pro first):")
        for n in missing:
            print(f"    {expected[n]}")
        sys.exit(1)

    for d in (data_dir, shp_dir, lyrx_dir):
        os.makedirs(d, exist_ok = True)

    print("Creating source data...")
    gdb_valid = make_gdb(data_dir, "valid_sources.gdb")
    gdb_breakable = make_gdb(data_dir, "breakable_sources.gdb")

    fc_parcels = make_feature_class(gdb_valid, "parcels", geometry = "POLYGON")
    fc_streets = make_feature_class(gdb_valid, "streets", geometry = "POLYLINE")
    fc_zoning = make_feature_class(gdb_breakable, "zoning", geometry = "POLYGON")
    fc_flood = make_feature_class(gdb_breakable, "flood_zones", geometry = "POLYGON")
    shp_parks = make_shapefile(shp_dir, "parks")
    shp_wetlands = make_shapefile(shp_dir, "wetlands")

    print("Creating layer files...")
    lyrx_parcels = os.path.join(lyrx_dir, "parcels.lyrx")
    lyrx_streets = os.path.join(lyrx_dir, "streets.lyrx")
    lyrx_zoning = os.path.join(lyrx_dir, "zoning.lyrx")
    lyrx_flood = os.path.join(lyrx_dir, "flood_zones.lyrx")
    lyrx_parks = os.path.join(lyrx_dir, "parks.lyrx")
    lyrx_wetlands = os.path.join(lyrx_dir, "wetlands.lyrx")

    make_lyrx(fc_parcels, lyrx_parcels)
    make_lyrx(fc_streets, lyrx_streets)
    make_lyrx(fc_zoning, lyrx_zoning)
    make_lyrx(fc_flood, lyrx_flood)
    make_lyrx(shp_parks, lyrx_parks)
    make_lyrx(shp_wetlands, lyrx_wetlands)

    print("Adding layers to projects...")
    add_layers(expected["all_valid"], [lyrx_parcels, lyrx_streets, lyrx_parks])
    add_layers(expected["mixed"], [lyrx_parcels, lyrx_zoning, lyrx_wetlands])
    add_layers(expected["all_broken"], [lyrx_zoning, lyrx_flood, lyrx_wetlands])

    shutil.rmtree(lyrx_dir)

    print(f"""
Done. Source data created and layers added.

Exit this Python session to release file locks, then break data links:
    python _break_data_links.py {root}
    """)

if __name__ == "__main__":
    main()
