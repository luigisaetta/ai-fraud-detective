#!/usr/bin/env bash
#
# Author: L. Saetta
# Date Last Modified: 2026-11-25
# License: MIT
# Description: Removes the code that Codex builds in a lab, so the lab can be
#     done again from the start. Only files created during the labs are
#     removed: the provided code, the acceptance tests and the reference
#     solutions are never touched.
#
# Usage:
#     ./clean.sh lab1     # fraud_detective/tools.py and tests/lab1/test_extra.py
#     ./clean.sh lab2     # fraud_detective/agent.py, tests/lab2/test_extra.py, try_agent.py
#     ./clean.sh lab3     # fraud_detective/report.py, fraud_detective/cli.py, tests/lab3/test_extra.py
#     ./clean.sh lab4     # fraud_detective/decisions.py, tests/lab4/test_extra.py
#     ./clean.sh all      # all the labs, plus out/ and the generated bundles

set -euo pipefail

cd "$(dirname "$0")"

usage() {
    echo "Usage: ./clean.sh lab1|lab2|lab3|lab4|all"
    exit 1
}

[[ $# -eq 1 ]] || usage

case "$1" in
    lab1) files=(fraud_detective/tools.py tests/lab1/test_extra.py) ;;
    lab2) files=(fraud_detective/agent.py tests/lab2/test_extra.py try_agent.py) ;;
    lab3) files=(fraud_detective/report.py fraud_detective/cli.py tests/lab3/test_extra.py) ;;
    lab4) files=(fraud_detective/decisions.py tests/lab4/test_extra.py) ;;
    all)
        files=(
            fraud_detective/tools.py tests/lab1/test_extra.py
            fraud_detective/agent.py tests/lab2/test_extra.py try_agent.py
            fraud_detective/report.py fraud_detective/cli.py tests/lab3/test_extra.py
            fraud_detective/decisions.py tests/lab4/test_extra.py
            out bundles/*.zip
        )
        ;;
    *) usage ;;
esac

removed=0
for path in "${files[@]}"; do
    if [[ -e "$path" ]]; then
        rm -rf -- "$path"
        echo "removed  $path"
        removed=$((removed + 1))
    fi
done
find fraud_detective tests -name __pycache__ -type d -prune -exec rm -rf {} +

if [[ $removed -eq 0 ]]; then
    echo "nothing to remove for $1"
fi
