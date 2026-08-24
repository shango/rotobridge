"""RotoBridge menu registration.

Put this directory on NUKE_PATH, or copy the contents into an existing menu.py.
The Windows installer does the former by appending one line to ~/.nuke/init.py.
"""

import nuke

menubar = nuke.menu("Nuke")
menu = menubar.addMenu("RotoBridge")
menu.addCommand("Export to .rbj",
                "import rotobridge_export; rotobridge_export.main()")
menu.addCommand("Import .rbj",
                "import rotobridge_import; rotobridge_import.main()")
# The version is in every dialog this tool raises, but a tester asked which
# build they have has nowhere to look when no dialog is open - After Effects
# has the panel footer for that and Nuke has nothing. One menu entry is
# cheaper than the round trip of asking them to run an export first.
menu.addCommand("About", "import rotobridge_nuke; rotobridge_nuke.about()")
