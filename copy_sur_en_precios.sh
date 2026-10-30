#!/usr/bin/env bash
set -euo pipefail

# Configuration
SOURCE_FILE="/home/dberns/Info/sur_en_precios.tar.gz"
REMOTE_USER="danielwaltherberns"
REMOTE_HOST="192.168.176.140"
REMOTE_DIR="/home/dberns/Info"

# Validate that the local source file exists
if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Error: Source file '$SOURCE_FILE' does not exist." >&2
  exit 1
fi

# Ensure remote destination directory exists
echo "Ensuring destination directory exists on ${REMOTE_HOST}..."
ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}'"

# Copy the file using scp
echo "Copying ${SOURCE_FILE} to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/ ..."
scp "$SOURCE_FILE" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

echo "File transfer completed successfully."
