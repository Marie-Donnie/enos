#!/usr/bin/env bash

set -xe

if [[ -z "$1" ]]; then
    echo "Missing reservation file"
    echo "e.g: ./launch.sh <reservation file>"
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
BASE_DIR="${SCRIPT_DIR}/../../../.."

cd $SCRIPT_DIR

# shellcheck disable=SC1091
. ../utils.sh

virtualenv venv
# shellcheck disable=SC1091
. venv/bin/activate

pip install -e "$BASE_DIR"
pip install -e "$BASE_DIR"[openstack]
#pip install -U git+https://github.com/BeyondTheClouds/enoslib
pip install -U -e /home/msimonin/workspace/repos/enoslib
pip install ipdb

# some cleaning
enos deploy -f $1 # --force-deploy
sanity_check "$BASE_DIR"
enos destroy
enos destroy --hard
