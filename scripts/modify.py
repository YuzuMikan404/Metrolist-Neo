#!/usr/bin/env python3
"""
.github/scripts/modify.py
Patches the checked-out Metrolist source so it can be built as
"Metrolist Neo" with a custom package ID.

What this script does
─────────────────────
1. process_icon()          — generate adaptive + legacy launcher icons from icon.png
2. gen_google_services()   — write a dummy google-services.json (GMS plugin is disabled)
3. patch_gradle_properties()— merge CI-friendly JVM / build settings (never overwrite)
4. patch_proguard()        — append -dontwarn rules for common missing desktop classes
5. write_app_name()        — deduplicate app_name across all values* dirs → strings.xml
6. patch_build_gradle()    — change applicationId; comment out google-services /
                             firebase plugins only (protobuf is intentionally untouched)
7. patch_manifest()        — update label / icon / roundIcon attributes

Edit the CONFIG section below to customise the build.
"""

import json
import os
import re
import shutil
import sys

# ──────────────────────────────────────────────────────────────
# CONFIG  ← only section you normally need to edit
# ──────────────────────────────────────────────────────────────
APP_NAME = "Metrolist Neo"
APP_ID   = "com.metrolist.clone"

ICON_SRC      = "icon.png"          # custom icon in repo root (optional)
BASE_DIR      = "app"
RES_DIR       = os.path.join(BASE_DIR, "src/main/res")
GRADLE_FILE   = os.path.join(BASE_DIR, "build.gradle.kts")
MANIFEST_FILE = os.path.join(BASE_DIR, "src/main/AndroidManifest.xml")
PROGUARD_FILE = os.path.join(BASE_DIR, "proguard-rules.pro")
# ──────────────────────────────────────────────────────────────

try:
    from PIL import Image, ImageOps
    PIL_OK = True
except ImportError:
    PIL_OK = False


def log(msg: str) -> None:
    print(f"[modify.py] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[modify.py] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ── 1. Icon ────────────────────────────────────────────────────
def process_icon() -> str:
    """
    Generate adaptive + legacy launcher icons from icon.png.
    Returns the hex background colour extracted from the image.
    Falls back to #000000 if PIL is unavailable or icon.png is absent.
    """
    log("Processing icon...")
    if not PIL_OK or not os.path.exists(ICON_SRC):
        log("Skipping — PIL unavailable or no icon.png found.")
        return "#000000"

    try:
        img = Image.open(ICON_SRC).convert("RGBA")
        pixel = img.resize((1, 1)).getpixel((0, 0))
        bg = "#{:02x}{:02x}{:02x}".format(*pixel[:3]) if pixel[3] > 0 else "#000000"

        # Build foreground canvas (65 % of 1080 px)
        sz, tg = 1080, int(1080 * 0.65)
        canvas = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        resized = ImageOps.fit(img, (tg, tg), centering=(0.5, 0.5))
        off = (sz - tg) // 2
        canvas.paste(resized, (off, off), resized)
        canvas.save("_ic_fg.png")
        img.save("_ic_lg.png")

        # Remove old launcher icons
        for root, _, files in os.walk(RES_DIR):
            for f in files:
                if "ic_launcher" in f:
                    os.remove(os.path.join(root, f))

        # Ensure output directories exist
        for d in (
            os.path.join(RES_DIR, "mipmap-anydpi-v26"),
            os.path.join(RES_DIR, "mipmap-xxxhdpi"),
            os.path.join(RES_DIR, "values"),
            os.path.join(RES_DIR, "drawable"),
        ):
            os.makedirs(d, exist_ok=True)

        # Adaptive icon XML
        adaptive_xml = "\n".join([
            '<?xml version="1.0" encoding="utf-8"?>',
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">',
            '    <background android:drawable="@color/ic_launcher_background" />',
            '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />',
            "</adaptive-icon>",
        ])
        anydpi = os.path.join(RES_DIR, "mipmap-anydpi-v26")
        for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
            open(os.path.join(anydpi, name), "w").write(adaptive_xml)

        # Background colour resource
        open(os.path.join(RES_DIR, "values", "ic_launcher_background.xml"), "w").write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<resources>"
            '<color name="ic_launcher_background">' + bg + "</color>"
            "</resources>"
        )

        # Copy images
        xhd = os.path.join(RES_DIR, "mipmap-xxxhdpi")
        drw = os.path.join(RES_DIR, "drawable")
        shutil.copy("_ic_fg.png", os.path.join(xhd, "ic_launcher_foreground.png"))
        shutil.copy("_ic_fg.png", os.path.join(drw, "ic_launcher_foreground.png"))
        shutil.copy("_ic_lg.png", os.path.join(xhd, "ic_launcher.png"))
        shutil.copy("_ic_lg.png", os.path.join(xhd, "ic_launcher_round.png"))

        log(f"Icon done. Background: {bg}")
        return bg

    except Exception as exc:
        log(f"Icon processing failed: {exc}")
        return "#000000"


# ── 2. Dummy google-services.json ─────────────────────────────
def gen_google_services() -> None:
    """
    Write a minimal google-services.json so the google-services Gradle
    plugin does not crash during configuration — even though the plugin
    itself is commented out by patch_build_gradle().
    """
    log("Writing dummy google-services.json...")
    data = {
        "project_info": {"project_number": "0", "project_id": "dummy"},
        "client": [{
            "client_info": {
                "mobilesdk_app_id": "1:0:android:0",
                "android_client_info": {"package_name": APP_ID},
            },
            "api_key": [{"current_key": "dummy"}],
            "services": {},
        }],
        "configuration_version": "1",
    }
    with open(os.path.join(BASE_DIR, "google-services.json"), "w") as fh:
        json.dump(data, fh, indent=2)


# ── 3. gradle.properties (merge, never overwrite) ─────────────
def patch_gradle_properties() -> None:
    """
    Merge CI-friendly settings into gradle.properties.
    Keys that already exist are updated in-place; new keys are appended.
    Keys not listed here are left untouched (preserves protobuf etc.).

    android.enableJetifier is set to FALSE deliberately:
      Jetifier can corrupt protobuf-generated class names, causing
      'Unresolved reference: proto' compilation errors.
    """
    log("Patching gradle.properties...")
    desired = {
        "org.gradle.jvmargs": (
            "-Xmx4096m -XX:MaxMetaspaceSize=1g "
            "-XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
        ),
        "kotlin.daemon.jvmargs": "-Xmx4096m -XX:MaxMetaspaceSize=1g",
        "org.gradle.parallel":       "true",
        "org.gradle.caching":        "true",
        "android.useAndroidX":       "true",
        "android.enableJetifier":    "false",   # must stay false — see docstring
        "android.enableR8.fullMode": "false",
    }

    path = "gradle.properties"
    lines = open(path).readlines() if os.path.exists(path) else []
    result, replaced = [], set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            result.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in desired:
            result.append(f"{key}={desired[key]}\n")
            replaced.add(key)
        else:
            result.append(line)

    # Append any keys not already present
    for key, val in desired.items():
        if key not in replaced:
            result.append(f"{key}={val}\n")

    open(path, "w").writelines(result)
    log("gradle.properties patched.")


# ── 4. ProGuard rules ──────────────────────────────────────────
def patch_proguard() -> None:
    """Append -dontwarn rules for common missing desktop/JVM classes."""
    log("Patching proguard-rules.pro...")
    rules = (
        "\n# --- Added by Metrolist Neo builder (modify.py) ---\n"
        "-dontwarn java.beans.**\n"
        "-dontwarn java.awt.**\n"
        "-dontwarn javax.security.**\n"
        "-dontwarn javax.naming.**\n"
        "-dontwarn javax.xml.**\n"
        "-dontwarn sun.misc.**\n"
        "-dontwarn kotlin.reflect.**\n"
        "# ---------------------------------------------------\n"
    )
    mode = "a" if os.path.exists(PROGUARD_FILE) else "w"
    open(PROGUARD_FILE, mode).write(rules)


# ── 5. app_name string resource ───────────────────────────────
def write_app_name(name: str) -> None:
    """
    Ensure exactly one app_name entry exists, in strings.xml.

    Strategy:
      Step A — Walk every values* directory; remove all existing app_name
               entries. Delete the file if it becomes empty afterwards.
      Step B — Write the new entry into values/strings.xml (create if needed).
    """
    log(f"Writing app_name: {name!r}")
    pattern = re.compile(
        r'\s*<string\s+name="app_name"[^>]*>[^<]*</string>', re.MULTILINE
    )

    # Step A: purge duplicates
    for root, _, files in os.walk(RES_DIR):
        if not os.path.basename(root).startswith("values"):
            continue
        for fname in files:
            if not fname.endswith(".xml"):
                continue
            fp = os.path.join(root, fname)
            try:
                txt = open(fp, "r", encoding="utf-8").read()
                if 'name="app_name"' not in txt:
                    continue
                cleaned = pattern.sub("", txt)
                # Check whether the file is now empty of real content
                body = re.sub(r"<\?xml[^?]*\?>", "", cleaned)
                body = re.sub(r"<resources[^>]*>", "", body)
                body = re.sub(r"</resources>", "", body)
                if not body.strip():
                    os.remove(fp)
                    log(f"  Removed now-empty file: {fp}")
                else:
                    open(fp, "w", encoding="utf-8").write(cleaned)
                    log(f"  Removed app_name entry from: {fp}")
            except Exception as exc:
                log(f"  Warning — could not process {fp}: {exc}")

    # Step B: write into strings.xml
    os.makedirs(os.path.join(RES_DIR, "values"), exist_ok=True)
    sp = os.path.join(RES_DIR, "values", "strings.xml")
    entry = f'<string name="app_name">{name}</string>'

    if os.path.exists(sp):
        txt = open(sp, "r", encoding="utf-8").read()
        if 'name="app_name"' in txt:
            txt = re.sub(
                r'<string\s+name="app_name"[^>]*>[^<]*</string>', entry, txt
            )
        else:
            txt = re.sub(r"(<resources[^>]*>)", r"\1\n    " + entry, txt, count=1)
        open(sp, "w", encoding="utf-8").write(txt)
    else:
        open(sp, "w", encoding="utf-8").write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<resources>\n"
            f"    {entry}\n"
            "</resources>"
        )
    log(f"app_name written to {sp}")


# ── 6. build.gradle.kts ───────────────────────────────────────
#
# Plugin handling strategy
# ────────────────────────
# google-services / firebase  →  add "apply false" (keeps plugin in registry,
#                                  prevents runtime crash without secrets)
# protobuf                    →  REMOVE "apply false" if present
#                                  (upstream sometimes ships protobuf as
#                                   apply false; without active protobuf the
#                                   generateProto task never appears and
#                                   MessageCodec.kt fails to compile)
#
# We never use comment-out (//) for plugin lines because that removes the
# plugin from the registry entirely, which can break dependency resolution
# for sibling plugins.

# Lines that get " apply false" appended (if not already disabled).
_GMS_PATTERNS = [
    r'alias\s*\(\s*libs\.plugins\.google\.services\s*\)',
    r'id\s*\(\s*["\']com\.google\.gms\.google-services["\']\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.crashlytics\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.perf\s*\)',
    r'id\s*\(\s*["\']com\.google\.firebase\.[^"\']+["\']\s*\)',
]

# Lines where "apply false" must be REMOVED so the plugin becomes active.
_MUST_ENABLE_PATTERNS = [
    r'protobuf',   # any line referencing protobuf in plugins{} block
]


def patch_build_gradle() -> None:
    """
    1. Dump plugins{} block for diagnostics.
    2. Replace applicationId with APP_ID.
    3. Ensure protobuf plugin is ACTIVE (remove 'apply false' if present).
    4. Add 'apply false' to google-services / firebase lines.
    """
    log(f"Patching {GRADLE_FILE}...")
    if not os.path.exists(GRADLE_FILE):
        die(f"File not found: {GRADLE_FILE}")

    txt = open(GRADLE_FILE, "r").read()
    original = txt

    # ── Diagnostics: dump plugins{} block ───────────────────────
    plugins_m = re.search(r'plugins\s*\{([^}]*)\}', txt, re.DOTALL)
    if plugins_m:
        log("  plugins{} block found:")
        for l in plugins_m.group(1).splitlines():
            if l.strip():
                log(f"    {l.strip()}")
    else:
        log("  WARNING: no plugins{} block found in build.gradle.kts")

    # ── 1. applicationId ────────────────────────────────────────
    txt = re.sub(
        r'(applicationId\s*=\s*)"[^"]*"',
        r'\g<1>"' + APP_ID + '"',
        txt,
    )

    # ── Process plugins{} block line by line ────────────────────
    in_plugins_block = False
    brace_depth = 0
    lines, out = txt.splitlines(keepends=True), []

    for line in lines:
        stripped = line.lstrip()

        # Track entry/exit of plugins{} block
        if re.match(r'plugins\s*\{', stripped):
            in_plugins_block = True
            brace_depth = 1
            out.append(line)
            continue
        if in_plugins_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_plugins_block = False
                out.append(line)
                continue

            # ── 2. Ensure protobuf is ACTIVE ──────────────────
            if any(re.search(p, line) for p in _MUST_ENABLE_PATTERNS):
                if re.search(r'\bapply\s+false\b', line):
                    # Strip " apply false" to activate the plugin
                    fixed = re.sub(r'\s*apply\s+false', '', line)
                    out.append(fixed)
                    log(f"  Enabled protobuf plugin: {line.strip()} → {fixed.strip()}")
                else:
                    out.append(line)
                    log(f"  protobuf already active: {line.strip()}")
                continue

            # ── 3. Disable GMS/Firebase with apply false ──────
            if not stripped.startswith("//") and not re.search(r'\bapply\s+false\b', line):
                for pat in _GMS_PATTERNS:
                    if re.search(pat, line):
                        new_line = line.rstrip("\n").rstrip() + " apply false\n"
                        out.append(new_line)
                        log(f"  apply false → {line.strip()}")
                        break
                else:
                    out.append(line)
            else:
                out.append(line)
            continue

        out.append(line)

    txt = "".join(out)

    if txt != original:
        open(GRADLE_FILE, "w").write(txt)
        log(f"{GRADLE_FILE} patched.")
    else:
        log(f"WARNING: {GRADLE_FILE} unchanged — verify plugin patterns if build fails.")


# ── 7. AndroidManifest.xml ────────────────────────────────────
def patch_manifest() -> None:
    """Update label, icon and roundIcon attributes in the app manifest."""
    log(f"Patching {MANIFEST_FILE}...")
    if not os.path.exists(MANIFEST_FILE):
        die(f"File not found: {MANIFEST_FILE}")

    txt = open(MANIFEST_FILE, "r").read()
    txt = re.sub(r'android:label="[^"]*"', 'android:label="@string/app_name"', txt)
    txt = re.sub(r'android:icon="[^"]*"',  'android:icon="@mipmap/ic_launcher"',  txt)
    if "android:roundIcon=" in txt:
        txt = re.sub(
            r'android:roundIcon="[^"]*"',
            'android:roundIcon="@mipmap/ic_launcher_round"',
            txt,
        )
    else:
        txt = txt.replace(
            "<application",
            '<application android:roundIcon="@mipmap/ic_launcher_round"',
            1,
        )
    open(MANIFEST_FILE, "w").write(txt)


# ── Main ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        process_icon()
        gen_google_services()
        patch_gradle_properties()
        patch_proguard()
        write_app_name(APP_NAME)
        patch_build_gradle()
        patch_manifest()
        log("All modifications applied successfully.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(str(exc))
