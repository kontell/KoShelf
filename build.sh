#!/usr/bin/env bash
set -euo pipefail

ADDON_ID="plugin.audio.koshelf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/../builds"

# Extract version from addon.xml (matches the addon element's version attribute)
VERSION=$(grep -oP '^\s+version="\K[^"]+' "$SCRIPT_DIR/addon.xml")
ZIP_NAME="${ADDON_ID}-${VERSION}.zip"

echo "Building ${ZIP_NAME}..."

mkdir -p "$BUILD_DIR"

# Build in a temp directory
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

DEST="$TMPDIR/$ADDON_ID"
mkdir -p "$DEST/resources"

# Copy addon files
cp "$SCRIPT_DIR/addon.xml" "$DEST/"
cp "$SCRIPT_DIR/main.py" "$DEST/"
cp "$SCRIPT_DIR/abs_api.py" "$DEST/"
cp "$SCRIPT_DIR/service.py" "$DEST/"
cp "$SCRIPT_DIR/resources/settings.xml" "$DEST/resources/"
cp "$SCRIPT_DIR/resources/icon.png" "$DEST/resources/"

# Syntax check
python3 -c "
import py_compile, sys
for f in ['main.py', 'abs_api.py', 'service.py']:
    try:
        py_compile.compile('$DEST/' + f, doraise=True)
    except py_compile.PyCompileError as e:
        print(f'Syntax error in {f}: {e}', file=sys.stderr)
        sys.exit(1)
print('Syntax check passed')
"

# Create zip (exclude pycache and other junk)
(cd "$TMPDIR" && zip -r "$BUILD_DIR/$ZIP_NAME" "$ADDON_ID/" -x "*__pycache__*" "*.pyc")

echo "Built: ${BUILD_DIR}/${ZIP_NAME}"
