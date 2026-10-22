#!/bin/sh
# Build ~/Applications/GH Notify Spike.app
set -e
APP="$HOME/Applications/GH Notify Spike.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
clang -O2 -o "$APP/Contents/MacOS/gh-notify-spike" "$(dirname "$0")/launcher.c"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.gillespied.gh-notify-spike</string>
<key>CFBundleName</key><string>GH Notify Spike</string>
<key>CFBundleExecutable</key><string>gh-notify-spike</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$APP"
echo "$APP"
