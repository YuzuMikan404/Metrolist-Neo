#!/usr/bin/env python3
"""
.github/scripts/modify.py
Patches the checked-out Metrolist source so it can be built as
"Metrolist Neo" with a custom package ID.

What this script does
─────────────────────
1. process_icon()              — generate adaptive + legacy launcher icons
2. gen_google_services()       — write a dummy google-services.json
3. patch_gradle_properties()   — merge CI-friendly JVM / build settings
4. patch_proguard()            — append -dontwarn rules
5. write_app_name()            — deduplicate app_name → strings.xml
6. patch_root_build_gradle()   — ensure protobuf is declared with apply false
                                 at the ROOT level (required for alias resolution)
7. patch_build_gradle()        — change applicationId; activate protobuf plugin;
                                 disable google-services / firebase plugins
8. patch_manifest()            — update label / icon / roundIcon attributes

Root cause (v13.2.1 regression) + fix
──────────────────────────────────────
upstream v13.2.1 removed the `protobuf` plugin from BOTH:
  • the root build.gradle.kts plugins{} block (apply false declaration)
  • the app/build.gradle.kts plugins{} block (active use declaration)

Without these declarations:
  • generateProto never runs
  • MessageCodec.kt fails: "Unresolved reference: proto / Listentogether"

Fix applied in two steps:
  Step 1 (patch_root_build_gradle): inject
      alias(libs.plugins.protobuf) apply false
    into the ROOT plugins{} block so Gradle can resolve the plugin from the
    version catalogue without requiring an inline version number.

  Step 2 (patch_build_gradle): inject
      alias(libs.plugins.protobuf)
    into the APP plugins{} block so the generateProto task is registered.

  Fallback: if the version catalogue alias cannot be confirmed, falls back to
      id("com.google.protobuf") version "<detected-or-default>"
    using the version parsed from gradle/libs.versions.toml.

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

ICON_SRC        = "icon.png"
BASE_DIR        = "app"
RES_DIR         = os.path.join(BASE_DIR, "src/main/res")
GRADLE_FILE     = os.path.join(BASE_DIR, "build.gradle.kts")
ROOT_GRADLE     = "build.gradle.kts"
VERSIONS_TOML   = os.path.join("gradle", "libs.versions.toml")
MANIFEST_FILE   = os.path.join(BASE_DIR, "src/main/AndroidManifest.xml")
PROGUARD_FILE   = os.path.join(BASE_DIR, "proguard-rules.pro")

# Fallback protobuf plugin version if TOML cannot be parsed
_PROTOBUF_FALLBACK_VERSION = "0.9.4"
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


# ── Helper: read protobuf plugin info from version catalogue ──
def _protobuf_plugin_info() -> dict:
    """
    Parse gradle/libs.versions.toml to find the protobuf plugin alias and version.
    Returns dict with keys:
      'alias'   — e.g. 'libs.plugins.protobuf'  (None if not found)
      'version' — e.g. '0.9.4'                  (fallback if not found)
    """
    alias = None
    version = _PROTOBUF_FALLBACK_VERSION

    if not os.path.exists(VERSIONS_TOML):
        log(f"  {VERSIONS_TOML} not found — using fallback version {version}")
        return {"alias": alias, "version": version}

    try:
        txt = open(VERSIONS_TOML, "r", encoding="utf-8").read()

        # ── Find version ──────────────────────────────────────
        # Patterns like:  protobuf = "0.9.4"
        #                 protobuf-plugin = "0.9.4"
        #                 protobufPlugin = "0.9.4"
        vm = re.search(
            r'^\s*protobuf[^\s=]*\s*=\s*"([0-9][^"]+)"',
            txt, re.MULTILINE | re.IGNORECASE
        )
        if vm:
            version = vm.group(1)
            log(f"  TOML protobuf version: {version}")
        else:
            log(f"  protobuf version not found in TOML — using fallback {version}")

        # ── Find [plugins] alias ──────────────────────────────
        # Look for a plugins section entry referencing com.google.protobuf
        # Pattern: someAlias = { id = "com.google.protobuf", ... }
        # OR:      someAlias = "com.google.protobuf:..."
        pm = re.search(
            r'^\s*([a-zA-Z0-9_-]+)\s*=\s*\{[^}]*id\s*=\s*"com\.google\.protobuf"[^}]*\}',
            txt, re.MULTILINE
        )
        if not pm:
            pm = re.search(
                r'^\s*([a-zA-Z0-9_-]+)\s*=\s*"com\.google\.protobuf[^"]*"',
                txt, re.MULTILINE
            )
        if pm:
            # Convert TOML key (dashes/underscores) to Gradle alias dot notation
            raw = pm.group(1).replace("-", ".").replace("_", ".")
            alias = f"libs.plugins.{raw}"
            log(f"  TOML protobuf plugin alias: {alias}")
        else:
            log("  protobuf plugin alias not found in TOML [plugins] section")

    except Exception as exc:
        log(f"  Warning — could not parse {VERSIONS_TOML}: {exc}")

    return {"alias": alias, "version": version}


def _protobuf_active_line(info: dict) -> str:
    """Return the plugins{} line to ACTIVATE protobuf (no apply false)."""
    if info["alias"]:
        return f'    alias({info["alias"]})\n'
    return f'    id("com.google.protobuf") version "{info["version"]}"\n'


def _protobuf_disabled_line(info: dict) -> str:
    """Return the plugins{} line to DECLARE protobuf with apply false (root level)."""
    if info["alias"]:
        return f'    alias({info["alias"]}) apply false\n'
    return f'    id("com.google.protobuf") version "{info["version"]}" apply false\n'


def _block_has_protobuf(block_content: str) -> bool:
    return bool(re.search(r'protobuf', block_content, re.IGNORECASE))


# ── 1. Icon ────────────────────────────────────────────────────
def process_icon() -> str:
    log("Processing icon...")
    if not PIL_OK or not os.path.exists(ICON_SRC):
        log("Skipping — PIL unavailable or no icon.png found.")
        return "#000000"
    try:
        img = Image.open(ICON_SRC).convert("RGBA")
        pixel = img.resize((1, 1)).getpixel((0, 0))
        bg = "#{:02x}{:02x}{:02x}".format(*pixel[:3]) if pixel[3] > 0 else "#000000"
        sz, tg = 1080, int(1080 * 0.65)
        canvas = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        resized = ImageOps.fit(img, (tg, tg), centering=(0.5, 0.5))
        off = (sz - tg) // 2
        canvas.paste(resized, (off, off), resized)
        canvas.save("_ic_fg.png")
        img.save("_ic_lg.png")
        for root, _, files in os.walk(RES_DIR):
            for f in files:
                if "ic_launcher" in f:
                    os.remove(os.path.join(root, f))
        for d in (
            os.path.join(RES_DIR, "mipmap-anydpi-v26"),
            os.path.join(RES_DIR, "mipmap-xxxhdpi"),
            os.path.join(RES_DIR, "values"),
            os.path.join(RES_DIR, "drawable"),
        ):
            os.makedirs(d, exist_ok=True)
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
        open(os.path.join(RES_DIR, "values", "ic_launcher_background.xml"), "w").write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<resources>"
            '<color name="ic_launcher_background">' + bg + "</color>"
            "</resources>"
        )
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


# ── 3. gradle.properties ──────────────────────────────────────
def patch_gradle_properties() -> None:
    """
    Merge CI-friendly settings. android.enableJetifier must stay FALSE:
    Jetifier corrupts protobuf-generated class names.
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
        "android.enableJetifier":    "false",
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
    for key, val in desired.items():
        if key not in replaced:
            result.append(f"{key}={val}\n")
    open(path, "w").writelines(result)
    log("gradle.properties patched.")


# ── 4. ProGuard rules ──────────────────────────────────────────
def patch_proguard() -> None:
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
    log(f"Writing app_name: {name!r}")
    pattern = re.compile(
        r'\s*<string\s+name="app_name"[^>]*>[^<]*</string>', re.MULTILINE
    )
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
    os.makedirs(os.path.join(RES_DIR, "values"), exist_ok=True)
    sp = os.path.join(RES_DIR, "values", "strings.xml")
    entry = f'<string name="app_name">{name}</string>'
    if os.path.exists(sp):
        txt = open(sp, "r", encoding="utf-8").read()
        if 'name="app_name"' in txt:
            txt = re.sub(r'<string\s+name="app_name"[^>]*>[^<]*</string>', entry, txt)
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


# ── 6. ROOT build.gradle.kts ──────────────────────────────────
#
# WHY this is needed (v13.2.1 regression):
#   In Gradle's plugins{} DSL, a plugin referenced by id() without a version
#   MUST be declared in the ROOT build.gradle.kts with `apply false` first.
#   In v13.2.1, protobuf was removed from BOTH the root AND app build files,
#   breaking plugin resolution entirely.
#
#   By re-adding it to the root with `apply false`, Gradle can resolve the
#   plugin from the version catalogue and the app-level plugins{} block can
#   reference it without repeating the version number.

def patch_root_build_gradle(info: dict) -> None:
    """
    Ensure the ROOT build.gradle.kts declares the protobuf plugin with apply false.
    This is a prerequisite for the app-level plugins{} block to reference it
    without an inline version number.
    """
    log(f"Patching {ROOT_GRADLE} (root)...")
    if not os.path.exists(ROOT_GRADLE):
        log(f"  {ROOT_GRADLE} not found — skipping root patch.")
        return

    txt = open(ROOT_GRADLE, "r").read()
    original = txt

    # Check if protobuf is already declared at root level
    if _block_has_protobuf(txt):
        log(f"  protobuf already present in {ROOT_GRADLE} — no change needed.")
        return

    inject_line = _protobuf_disabled_line(info)
    log(f"  Injecting into root plugins{{}}: {inject_line.strip()}")

    # Find the root plugins{} block and inject before its closing brace
    in_block = False
    brace_depth = 0
    lines, out = txt.splitlines(keepends=True), []
    injected = False

    for line in lines:
        stripped = line.lstrip()
        if re.match(r'plugins\s*\{', stripped) and not in_block:
            in_block = True
            brace_depth = 1
            out.append(line)
            continue
        if in_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                out.append(inject_line)
                in_block = False
                injected = True
                out.append(line)
                continue
        out.append(line)

    if not injected:
        log(f"  WARNING: could not find plugins{{}} block in {ROOT_GRADLE}")
        return

    txt = "".join(out)
    if txt != original:
        open(ROOT_GRADLE, "w").write(txt)
        log(f"  {ROOT_GRADLE} patched.")
    else:
        log(f"  WARNING: {ROOT_GRADLE} unchanged.")


# ── 7. app/build.gradle.kts ───────────────────────────────────
#
# Plugin handling strategy
# ────────────────────────
# google-services / firebase  →  add "apply false"
# protobuf (present)          →  remove "apply false" to activate
# protobuf (absent)           →  INJECT active line (alias or versioned id)
#
# The injection uses alias(libs.plugins.protobuf) if the alias was found in
# the version catalogue, otherwise id("com.google.protobuf") version "X.Y.Z".

_GMS_PATTERNS = [
    r'alias\s*\(\s*libs\.plugins\.google\.services\s*\)',
    r'id\s*\(\s*["\']com\.google\.gms\.google-services["\']\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.crashlytics\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.perf\s*\)',
    r'id\s*\(\s*["\']com\.google\.firebase\.[^"\']+["\']\s*\)',
]

_MUST_ENABLE_PATTERNS = [r'protobuf']


def patch_build_gradle(info: dict) -> None:
    """
    1. Dump plugins{} block for diagnostics.
    2. Replace applicationId with APP_ID.
    3. Ensure protobuf plugin is ACTIVE (remove 'apply false' if present,
       or INJECT if completely absent).
    4. Add 'apply false' to google-services / firebase lines.
    5. Post-patch validation.
    """
    log(f"Patching {GRADLE_FILE}...")
    if not os.path.exists(GRADLE_FILE):
        die(f"File not found: {GRADLE_FILE}")

    txt = open(GRADLE_FILE, "r").read()
    original = txt

    # Diagnostics
    plugins_m = re.search(r'plugins\s*\{([^}]*)\}', txt, re.DOTALL)
    if plugins_m:
        block_content = plugins_m.group(1)
        log("  plugins{} block found:")
        for l in block_content.splitlines():
            if l.strip():
                log(f"    {l.strip()}")
        log(f"  protobuf present in plugins{{}}: {_block_has_protobuf(block_content)}")
    else:
        log("  WARNING: no plugins{} block found")

    # applicationId
    txt = re.sub(
        r'(applicationId\s*=\s*)"[^"]*"',
        r'\g<1>"' + APP_ID + '"',
        txt,
    )

    # Process plugins{} block line by line
    in_plugins_block = False
    brace_depth = 0
    lines, out = txt.splitlines(keepends=True), []
    protobuf_handled = False
    inject_line = _protobuf_active_line(info)

    for line in lines:
        stripped = line.lstrip()

        if re.match(r'plugins\s*\{', stripped):
            in_plugins_block = True
            brace_depth = 1
            protobuf_handled = False
            out.append(line)
            continue

        if in_plugins_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                if not protobuf_handled:
                    log(
                        f"  protobuf NOT in plugins{{}} — injecting: {inject_line.strip()}"
                    )
                    out.append(inject_line)
                    protobuf_handled = True
                in_plugins_block = False
                out.append(line)
                continue

            # Ensure protobuf is active
            if any(re.search(p, line) for p in _MUST_ENABLE_PATTERNS):
                protobuf_handled = True
                if re.search(r'\bapply\s+false\b', line):
                    fixed = re.sub(r'\s*apply\s+false', '', line)
                    out.append(fixed)
                    log(f"  Enabled protobuf: {line.strip()} → {fixed.strip()}")
                else:
                    out.append(line)
                    log(f"  protobuf already active: {line.strip()}")
                continue

            # Disable GMS/Firebase
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
        log(f"WARNING: {GRADLE_FILE} unchanged.")

    # Post-patch validation
    final_m = re.search(r'plugins\s*\{([^}]*)\}', open(GRADLE_FILE).read(), re.DOTALL)
    if final_m:
        if not _block_has_protobuf(final_m.group(1)):
            die("VALIDATION FAILED: protobuf still absent from app plugins{} after patching.")
        log("  VALIDATION OK: protobuf active in app plugins{} block.")
    else:
        log("  WARNING: could not re-validate app plugins{} block.")


# ── 8. AndroidManifest.xml ────────────────────────────────────
def patch_manifest() -> None:
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
        # Resolve protobuf plugin info once; share across both gradle patches
        proto_info = _protobuf_plugin_info()
        patch_root_build_gradle(proto_info)
        patch_build_gradle(proto_info)
        patch_manifest()
        log("All modifications applied successfully.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(str(exc))
