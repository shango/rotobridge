"""The build version, and the one place it is authored.

This is **not** the `.rbj` format version. `rbj.VERSION` is an integer saying
what a reader must implement to open a file, and it moves only when an old
reader would break. This one is the build a tester installed, and it moves
every time one is handed out.

Testers report bugs by screenshotting a dialog, so the label below is what
identifies a build in practice. It appears in the panel footer, in the title of
every After Effects alert, in the body of every Nuke message, in the `source`
block of every file written, and in the import record - which means a report
can be as thin as one screenshot and still name the build that produced it.

Three files spell the number, because `ae/rotobridge_panel.jsx` includes
nothing by design: it evaluates the adapters the way `Run Script File...` does
rather than importing them, so it cannot share the port's constant.
`tools/bump_version.py` rewrites all three at once, and
`TestEs3CrossCheck.test_every_copy_of_the_build_version_agrees` fails if one is
edited by hand. A stale copy would be worse than no version at all: it names a
build that was never shipped.
"""

NAME = "RotoBridge"

VERSION = "0.9.4"

LABEL = "%s %s" % (NAME, VERSION)
