#!/bin/bash
# Build "Buds Sidekick.app" and a .dmg (unsigned). Usage: packaging/build_app.sh   ->  dist/Buds-Sidekick-<version>.dmg
# The app is a small launcher that installs the bundled wheel into its own virtualenv on first run, then starts Sidekick in Terminal.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
VERSION=$($PY - <<'PYV'
import re;print(re.search(r'version = "([^"]+)"', open("pyproject.toml").read()).group(1))
PYV
)
OUT=dist; APP="$OUT/Buds Sidekick.app"; STAGE="$OUT/dmg"
rm -rf "$APP" "$STAGE" "$OUT"/*.whl; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$STAGE"
$PY -m pip wheel . --no-deps -q -w "$APP/Contents/Resources"
cp packaging/launcher.sh "$APP/Contents/MacOS/BudsSidekick"; chmod +x "$APP/Contents/MacOS/BudsSidekick"
sed "s/__VERSION__/$VERSION/" packaging/Info.plist > "$APP/Contents/Info.plist"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
cp packaging/README-install.txt "$STAGE/Read me first.txt"
hdiutil create -quiet -volname "Buds Sidekick" -srcfolder "$STAGE" -ov -format UDZO "$OUT/Buds-Sidekick-$VERSION.dmg"
rm -rf "$STAGE"; echo "Built $OUT/Buds-Sidekick-$VERSION.dmg"
