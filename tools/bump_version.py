#!/usr/bin/env python3
"""Set the build version in all three files that spell it.

    python3 tools/bump_version.py 0.9.1

Three files, because `ae/rotobridge_panel.jsx` includes nothing by design and
cannot share the port's constant. Editing one by hand is caught by
`TestEs3CrossCheck.test_every_copy_of_the_build_version_agrees`, but being
caught after a zip has gone out is no use, so this exists to make the
consistent edit the easy one.

It rewrites nothing unless every file matches exactly once, so a half-bumped
tree is not a state this can leave behind.
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (path, pattern with one group around the version, replacement template)
SITES = [
    ("core/version.py", r'^VERSION = "([^"]+)"$', 'VERSION = "%s"'),
    ("ae/lib/rotobridge_core.jsx", r'^    RB\.VERSION = "([^"]+)";$',
     '    RB.VERSION = "%s";'),
    ("ae/rotobridge_panel.jsx", r'^    var VERSION = "([^"]+)";$',
     '    var VERSION = "%s";'),
]


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    new = argv[1]
    if not re.match(r"^\d+\.\d+\.\d+$", new):
        sys.stderr.write("%r is not major.minor.patch\n" % new)
        return 2

    edits = []
    for name, pattern, template in SITES:
        path = os.path.join(REPO, name)
        with open(path) as fh:
            text = fh.read()
        found = re.findall(pattern, text, re.M)
        if len(found) != 1:
            sys.stderr.write("%s: matched %d version lines, expected 1\n"
                             % (name, len(found)))
            return 1
        edits.append((path, name, found[0],
                      re.sub(pattern, template % new, text, count=1, flags=re.M)))

    was = edits[0][2]
    for _, name, old, _ in edits:
        if old != was:
            sys.stderr.write("already out of step: %s says %s, %s says %s\n"
                             % (edits[0][1], was, name, old))
            return 1

    for path, name, old, text in edits:
        with open(path, "w") as fh:
            fh.write(text)
        print("%s: %s -> %s" % (name, old, new))
    print("\nNow run `bash test/run.sh`, commit, and `bash tools/package.sh`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
