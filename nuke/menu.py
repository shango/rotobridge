"""RotoBridge menu registration.

Put this directory on NUKE_PATH, or copy the contents into an existing menu.py.
"""

import nuke

menubar = nuke.menu("Nuke")
menu = menubar.addMenu("RotoBridge")
menu.addCommand("Export to .rbj",
                "import rotobridge_export; rotobridge_export.main()")
menu.addCommand("Import .rbj",
                "import rotobridge_import; rotobridge_import.main()")
