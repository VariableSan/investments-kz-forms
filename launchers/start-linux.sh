#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose --profile web up --build