#!/usr/bin/env bash
# Builds build/lambda.zip: handler.py + its dependencies (cryptography, a
# compiled/C-extension package) built for the Lambda runtime's platform
# rather than whatever this machine happens to be.
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build/package build/lambda.zip
mkdir -p build/package

python3 -m pip install \
  --platform manylinux2014_x86_64 \
  --target build/package \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  -r lambda/requirements.txt

cp lambda/handler.py build/package/

(cd build/package && zip -r ../lambda.zip . -x '*.pyc' -x '__pycache__/*')

echo "Built build/lambda.zip"
