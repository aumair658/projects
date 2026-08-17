#!/usr/bin/env bash
# Builds build/layer/tfsec-layer.zip: the real tfsec binary, packaged as a
# Lambda layer. A file at bin/tfsec in the zip is exposed at
# /opt/bin/tfsec at runtime, matching TFSEC_PATH in main.tf.
#
# Requires: curl, jq, unzip/tar (whichever the release asset needs), zip.
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build/layer
mkdir -p build/layer/bin

echo "Looking up latest tfsec release..."
ASSET_URL=$(curl -s https://api.github.com/repos/aquasecurity/tfsec/releases/latest \
  | jq -r '.assets[] | select(.name == "tfsec-linux-amd64") | .browser_download_url')

if [ -z "$ASSET_URL" ]; then
  echo "Could not find a tfsec-linux-amd64 asset on the latest release." >&2
  echo "Check https://github.com/aquasecurity/tfsec/releases and adjust this script." >&2
  exit 1
fi

echo "Downloading $ASSET_URL"
curl -sL "$ASSET_URL" -o build/layer/bin/tfsec
chmod +x build/layer/bin/tfsec

(cd build/layer && zip -r tfsec-layer.zip bin)

echo "Built build/layer/tfsec-layer.zip"
