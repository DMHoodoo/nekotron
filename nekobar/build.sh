#!/bin/bash
# build nekobar (no Xcode/SwiftPM — bare swiftc, SMD-style)
set -e
cd "$(dirname "$0")"
swiftc -O -o nekobar nekobar.swift -framework AppKit
codesign -s - -f nekobar 2>/dev/null || true
echo "built: $(pwd)/nekobar"
