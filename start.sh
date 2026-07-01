#!/usr/bin/env bash

set -e

set -a
source .env
set +a

# which python
# python --version
# python -m pip show requests

# ls -l venv/bin/python
# venv/bin/python --version
# venv/bin/python -m pip show requests
# venv/bin/python -m pip show gradio

# venv/bin/python -m pip install -r requirements.txt
# venv/bin/python -m pip install --upgrade pip
# venv/bin/python -m pip install requests

echo $OUTPUT_DIR

./venv/bin/python app.py