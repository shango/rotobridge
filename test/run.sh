#!/bin/sh
# Every suite that runs without a host application.
#
# The two that need one are not here and cannot be: test_nuke_roundtrip.py
# needs a Nuke licence, and the After Effects adapters have no headless mode at
# all. See test/probe/README.md for how to run those by hand.

set -e
cd "$(dirname "$0")/.."

echo "== core, Python =="
python3 test/test_core.py

for suite in test_ae_core test_ae_export test_ae_import test_ae_crossapp; do
    echo "== ${suite}, node =="
    node "test/${suite}.js"
done
