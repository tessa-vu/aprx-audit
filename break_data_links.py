"""
Relocate breakable data sources to simulate broken links in .aprx projects.

The projects keep pointing at the old paths, so moving the data is enough to
reproduce exactly what happens in the real world when someone reorganizes a
network drive. Nothing is deleted, the data is moved into data/_moved_to_break
and can be moved back.

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
    data_dir = os.path.join(root, "data")
    shp_dir = os.path.join(data_dir, "shapefiles")
    broken_dir = os.path.join(data_dir, "_moved_to_break")
    proj_dir = os.path.join(root, "Projects")

    targets = [
        os.path.join(data_dir, "breakable_sources.gdb"),
        os.path.join(shp_dir, "wetlands.shp"),
    ]

    # A partially populated break folder means a prior run already moved some
    # of these, so the "expected broken counts" below can no longer be trusted.
    if os.path.exists(broken_dir) and os.listdir(broken_dir):
        print(f"WARNING: {broken_dir} already has files (previous run?)")
        print("     Clear it before re-running for a clean state.\n")

    movable = [t for t in targets if os.path.exists(t)]
    if not movable:
        print("Nothing to move, targets already relocated or not yet created.")
        print("Re-run create_test_fixtures.py if starting fresh.")
        sys.exit(1)

    os.makedirs(broken_dir, exist_ok=True)

    for src in movable:
        dst = os.path.join(broken_dir, os.path.basename(src))
        shutil.move(src, dst)

        if src.endswith(".shp"):
            # Moving only the .shp would leave a half-valid dataset, the
            # sidecar files have to go with it.
            base = os.path.splitext(src)[0]
            for ext in (".dbf", ".prj", ".shx", ".cpg", ".sbn", ".sbx"):
                sidecar = base + ext
                if os.path.exists(sidecar):
                    shutil.move(
                        sidecar, os.path.join(broken_dir, os.path.basename(sidecar))
                    )

    print(f"Relocated {len(movable)} target(s) to {broken_dir}\n")
    print("Expected broken counts:")
    print("    all_valid.aprx: 0 (parcels, streets, parks)")
    print("    mixed_sources.aprx: 2 (zoning, wetlands broken)")
    print("    all_broken.aprx: 3 (zoning, flood_zones, wetlands)")
    print(f"\nVerify:\n    python audit_aprx_projects.py {proj_dir} report.csv")


if __name__ == "__main__":
    main()

"""
Disclaimers and Copyright

Copyright © 2026 Esri

All rights reserved under the copyright laws of the United States and applicable
international laws, treaties, and conventions. You may freely redistribute and use
this sample code, with or without modification, provided you include the original
copyright notice and use restrictions.

Disclaimer: THE SAMPLE CODE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL ESRI OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) SUSTAINED BY YOU OR A THIRD PARTY, HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT ARISING IN ANY WAY OUT OF THE
USE OF THIS SAMPLE CODE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Esri
Attn: Contracts and Legal Services Department
380 New York Street
Redlands, California, 92373-8100 USA
email: contracts@esri.com


Additional Disclaimers

    - This code snippet is not maintained and/or supported by Esri Technical Support or Staff
    - This code is not guaranteed for stability or accuracy 
    - Esri & its staff cannot be held liable for any direct or indirect damages incurred by running this code 
    - Use at Your Own Risk
    
Please make sure to thoroughly review this Code Sample and seek appropriate legal and technical advice before using it in any environment. 
You are encouraged to customize and adapt this Code Sample to meet your specific needs and requirements.
"""
