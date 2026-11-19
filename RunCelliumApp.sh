#!/bin/bash
# 1. Find out where this script lives so paths don't break
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 2. Boot it up using your specific venv python!
/home/henry/Documents/Projects/Python/venv/bin/python -m cellium.main "$@"
