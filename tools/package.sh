#!/bin/sh
# Build the zip that goes to testers.
#
#     bash tools/package.sh
#
# Everything a Windows tester needs and nothing else: no tests, no spec, no
# handoff notes, no git history. The version in the zip name and in the READ ME
# comes from `core/version.py`, so a build cannot be named one thing and
# report itself as another.
#
# Refuses to build from a dirty tree. A zip that does not correspond to a
# commit is one nobody can reproduce when the bug report comes back, and the
# recurring failure in this project is already a stale deployment nobody could
# tell apart from a fresh one.

set -e
cd "$(dirname "$0")/.."

VERSION=$(python3 -c 'import sys; sys.path.insert(0, "."); from core import version; print(version.VERSION)')

if [ -n "$(git status --porcelain)" ]; then
    echo "the tree is dirty; commit first so this build names a commit" >&2
    git status --short >&2
    exit 1
fi

COMMIT=$(git rev-parse --short HEAD)
NAME="RotoBridge-${VERSION}"
STAGE="dist/${NAME}"

echo "== building ${NAME} from ${COMMIT} =="
rm -rf dist
mkdir -p "${STAGE}/after_effects/lib" "${STAGE}/nuke/rotobridge"

# The panel alone at the top, so the one file a tester opens is the only file
# they see. The five it evaluates go in `lib`, which is where the panel looks
# first and where the repo keeps them; a test holds those two names equal.
cp ae/rotobridge_panel.jsx "${STAGE}/after_effects/"
cp ae/lib/*.jsx "${STAGE}/after_effects/lib/"
# The installer keeps its repo layout - payload beside it - so the staged
# copy works exactly like `ae/install.jsx` run from the repo. LF endings are
# fine here: ExtendScript reads it, not cmd.exe.
cp ae/install.jsx "${STAGE}/after_effects/Install for After Effects.jsx"

# core/ must stay beside nuke/: rotobridge_nuke.py walks up one level and loads
# core from there by path, under a private module name.
cp -r core "${STAGE}/nuke/rotobridge/core"
cp -r nuke "${STAGE}/nuke/rotobridge/nuke"
find "${STAGE}" -name '__pycache__' -type d -exec rm -rf {} +
find "${STAGE}" -name '*.pyc' -delete

# CRLF on everything Windows opens directly. cmd.exe tolerates bare newlines
# in most batch files but not all of them, and a tester meeting a wall of text
# in one line has been given a reason to stop reading before step 1.
crlf() { sed 's/$/\r/' "$1" > "$2"; }

crlf tools/install_nuke.bat "${STAGE}/nuke/Install for Nuke.bat"

# The commit is not in the READ ME - a tester has no use for it - but it is in
# the zip, so a returned bug report can be tied to a tree.
printf '%s built from %s\r\n' "${NAME}" "${COMMIT}" > "${STAGE}/build.txt"

(cd dist && zip -qr "${NAME}.zip" "${NAME}")
rm -rf "${STAGE}"

# The tester-facing instructions are a Google Doc, not a file in the zip, so
# these two sit BESIDE the zip: they are what the Doc gets pasted from, for
# whoever cuts the drop rather than for the tester. The HTML keeps its
# headings and picture through a copy-paste; the text is the same words with
# none of that. The screenshot travels next to the HTML so the paste carries
# the image.
sed "s/@VERSION@/${VERSION}/g" tools/tester_readme.html > dist/tester_readme.html
sed "s/@VERSION@/${VERSION}/" tools/tester_readme.txt > "dist/READ ME FIRST.txt"
cp docs/ae-scripting-preference.png dist/

echo
echo "paste one of these into the Google Doc:"
echo "  dist/tester_readme.html   (headings and the screenshot survive)"
echo "  dist/READ ME FIRST.txt    (same words, plain)"
echo
echo "dist/${NAME}.zip"
# Fields 1-3 are size, date and time; the name is everything after, and two
# of the names in here have spaces in them.
unzip -l "dist/${NAME}.zip" | tail -n +4 | head -n -2 \
    | awk '{ $1 = $2 = $3 = ""; sub(/^ +/, ""); print "  " $0 }'
