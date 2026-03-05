#!/usr/bin/env python3
"""
.github/scripts/modify.py
Patches the checked-out Metrolist source so it can be built as
"Metrolist Neo" with a custom package ID.

What this script does
─────────────────────
1. process_icon()           — generate adaptive + legacy launcher icons
2. gen_google_services()    — write a dummy google-services.json
3. patch_gradle_properties()— merge CI-friendly JVM / build settings
4. patch_proguard()         — append -dontwarn rules
5. write_app_name()         — deduplicate app_name → strings.xml
6. patch_build_gradle()     — change applicationId; disable GMS/Firebase plugins
7. patch_manifest()         — update label / icon / roundIcon attributes
8. replace_message_codec()  — overwrite the broken MessageCodec.kt with a correct
                              kotlinx.serialization-based implementation

Root cause analysis (v13.2.1)
──────────────────────────────
The upstream removed the protobuf Gradle plugin AND the proto-generated Java/Kotlin
sources, but left MessageCodec.kt referencing the old proto outer class
"Listentogether" and the generated "proto" package.  All other files in the
listentogether/ package were rewritten to use plain @Serializable Kotlin data
classes — only MessageCodec.kt was missed.

Previous fix attempts (injecting the protobuf Gradle plugin) all failed because:
  • The TOML version "4.33.5" is the protobuf *library* version, not the plugin
  • The Gradle plugin com.google.protobuf.gradle.plugin has a separate 0.9.x version
  • There is no [plugins] entry for protobuf in libs.versions.toml at all
  • Injecting bare id("com.google.protobuf") fails (no version, not in root)
  • Injecting with version "4.33.5" fails (that artifact does not exist)

Correct fix: replace MessageCodec.kt entirely.  The new implementation uses
kotlinx.serialization JSON (already a project dependency) to encode/decode
messages — matching exactly the data-class API that all the other
listentogether/ files expose.
"""

import json as _json
import os
import re
import shutil
import sys
import textwrap

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
APP_NAME = "Metrolist Neo"
APP_ID   = "com.metrolist.clone"

ICON_SRC       = "icon.png"
BASE_DIR       = "app"
RES_DIR        = os.path.join(BASE_DIR, "src/main/res")
GRADLE_FILE    = os.path.join(BASE_DIR, "build.gradle.kts")
MANIFEST_FILE  = os.path.join(BASE_DIR, "src/main/AndroidManifest.xml")
PROGUARD_FILE  = os.path.join(BASE_DIR, "proguard-rules.pro")

MESSAGE_CODEC_PATH = os.path.join(
    BASE_DIR,
    "src/main/kotlin/com/metrolist/music/listentogether/MessageCodec.kt",
)
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


# ── 1. Icon ───────────────────────────────────────────────────
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
        _json.dump(data, fh, indent=2)


# ── 3. gradle.properties ──────────────────────────────────────
def patch_gradle_properties() -> None:
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


# ── 6. app/build.gradle.kts ───────────────────────────────────
# Only disable GMS/Firebase — do NOT touch protobuf at all.
# The protobuf Gradle plugin is not needed because we replace MessageCodec.kt
# with a pure kotlinx.serialization implementation.

_GMS_PATTERNS = [
    r'alias\s*\(\s*libs\.plugins\.google\.services\s*\)',
    r'id\s*\(\s*["\']com\.google\.gms\.google-services["\']\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.crashlytics\s*\)',
    r'alias\s*\(\s*libs\.plugins\.firebase\.perf\s*\)',
    r'id\s*\(\s*["\']com\.google\.firebase\.[^"\']+["\']\s*\)',
]


def patch_build_gradle() -> None:
    log(f"Patching {GRADLE_FILE}...")
    if not os.path.exists(GRADLE_FILE):
        die(f"File not found: {GRADLE_FILE}")

    txt = open(GRADLE_FILE, "r").read()
    original = txt

    # applicationId
    txt = re.sub(
        r'(applicationId\s*=\s*)"[^"]*"',
        r'\g<1>"' + APP_ID + '"',
        txt,
    )

    # Diagnostics
    plugins_m = re.search(r'plugins\s*\{([^}]*)\}', txt, re.DOTALL)
    if plugins_m:
        log("  plugins{} block found:")
        for line in plugins_m.group(1).splitlines():
            if line.strip():
                log(f"    {line.strip()}")
    else:
        log("  WARNING: no plugins{} block found")

    # Disable GMS/Firebase only — leave everything else untouched
    in_block = False
    brace_depth = 0
    lines, out = txt.splitlines(keepends=True), []

    for line in lines:
        stripped = line.lstrip()
        if re.match(r'plugins\s*\{', stripped):
            in_block = True
            brace_depth = 1
            out.append(line)
            continue
        if in_block:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                in_block = False
                out.append(line)
                continue
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
        log(f"{GRADLE_FILE} — no changes needed.")


# ── 7. AndroidManifest.xml ────────────────────────────────────
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


# ── 8. Replace broken MessageCodec.kt ────────────────────────
#
# Root cause:
#   In v13.2.1 the upstream removed all proto-generated sources and rewrote
#   the listentogether/ package to use plain @Serializable Kotlin data classes.
#   However, MessageCodec.kt was accidentally left with the old protobuf-based
#   implementation that references the now-deleted outer class "Listentogether"
#   and the "proto" import package.
#
# Fix:
#   Replace the file entirely with a correct implementation that uses
#   kotlinx.serialization JSON — the same serialization library already used
#   throughout the rest of the project. The public API surface (function names
#   and parameter/return types) matches exactly what the other files expect.

_MESSAGE_CODEC_SOURCE = textwrap.dedent("""\
    package com.metrolist.music.listentogether

    import kotlinx.serialization.encodeToString
    import kotlinx.serialization.json.Json
    import kotlinx.serialization.json.JsonElement
    import kotlinx.serialization.json.decodeFromJsonElement
    import kotlinx.serialization.json.encodeToJsonElement
    import kotlinx.serialization.json.jsonObject
    import kotlinx.serialization.json.jsonPrimitive

    /**
     * MessageCodec — encodes and decodes ListenTogether wire messages.
     *
     * Replaced the old protobuf-based implementation (Listentogether.Message /
     * com.metrolist.music.listentogether.proto.*) which was removed in v13.2.1.
     * Uses kotlinx.serialization JSON over UTF-8 ByteArray.
     * Wire envelope: { "type": "...", "payload": { ... } }
     */
    object MessageCodec {

        private val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = false
            isLenient = true
        }

        // ── Wire envelope ─────────────────────────────────────────────────

        fun encode(type: String, payload: JsonElement): ByteArray =
            json.encodeToString(
                mapOf("type" to json.encodeToJsonElement(type), "payload" to payload)
            ).toByteArray(Charsets.UTF_8)

        fun decode(bytes: ByteArray): Pair<String, JsonElement>? = runCatching {
            val root = json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            val type = root["type"]?.jsonPrimitive?.content ?: return null
            val payload = root["payload"] ?: return null
            type to payload
        }.getOrNull()

        // ── Encode helpers ────────────────────────────────────────────────

        fun encodePlaybackAction(payload: PlaybackActionPayload): ByteArray =
            encode("PLAYBACK_ACTION", json.encodeToJsonElement(payload))

        fun encodeSyncState(payload: SyncStatePayload): ByteArray =
            encode("SYNC_STATE", json.encodeToJsonElement(payload))

        fun encodeSuggestionRejected(payload: SuggestionRejectedPayload): ByteArray =
            encode("SUGGESTION_REJECTED", json.encodeToJsonElement(payload))

        fun encodeRoomState(state: RoomState): ByteArray =
            encode("ROOM_STATE", json.encodeToJsonElement(state))

        // ── Decode helpers ────────────────────────────────────────────────

        fun decodePlaybackAction(bytes: ByteArray): PlaybackActionPayload? =
            decodePayload(bytes)

        fun decodeSyncState(bytes: ByteArray): SyncStatePayload? =
            decodePayload(bytes)

        fun decodeSuggestionRejected(bytes: ByteArray): SuggestionRejectedPayload? =
            decodePayload(bytes)

        fun decodeRoomState(bytes: ByteArray): RoomState? =
            decodePayload(bytes)

        // ── Conversion helpers ────────────────────────────────────────────

        fun trackInfoToBytes(track: TrackInfo): ByteArray =
            encode("TRACK_INFO", json.encodeToJsonElement(track))

        fun trackInfoFromBytes(bytes: ByteArray): TrackInfo? =
            decodePayload(bytes)

        fun roomStateToBytes(state: RoomState): ByteArray =
            encodeRoomState(state)

        fun roomStateFromBytes(bytes: ByteArray): RoomState? =
            decodeRoomState(bytes)

        private inline fun <reified T> decodePayload(bytes: ByteArray): T? =
            runCatching {
                val (_, payload) = decode(bytes) ?: return null
                json.decodeFromJsonElement<T>(payload)
            }.getOrNull()
    }
""")


def replace_message_codec() -> None:
    """
    Overwrite MessageCodec.kt with a kotlinx.serialization-based implementation.

    The upstream file at v13.2.1 references:
      - import com.metrolist.music.listentogether.proto.*  (package deleted)
      - Listentogether.Message / Listentogether.PlaybackAction etc. (class deleted)
      - Proto builder/parser methods (parseFrom, newBuilder, build, etc.)
      - Proto field accessors with legacy names (usersList, queueList, userId, etc.)

    None of these exist in v13.2.1; the replacement uses the Kotlin data classes
    that are already correctly defined in the other listentogether/ source files.
    """
    if not os.path.exists(MESSAGE_CODEC_PATH):
        log(f"  WARNING: {MESSAGE_CODEC_PATH} not found — skipping replacement.")
        log("  (This is unexpected; the build may have other issues.)")
        return

    # Verify the file actually needs replacing (contains the broken proto import)
    existing = open(MESSAGE_CODEC_PATH, "r", encoding="utf-8").read()
    if "listentogether.proto" in existing or "Listentogether" in existing:
        open(MESSAGE_CODEC_PATH, "w", encoding="utf-8").write(_MESSAGE_CODEC_SOURCE)
        log(f"  Replaced broken proto-based {MESSAGE_CODEC_PATH} with")
        log("  kotlinx.serialization JSON implementation.")
    elif "MessageCodec" in existing and "kotlinx.serialization" in existing:
        log(f"  {MESSAGE_CODEC_PATH} already uses kotlinx.serialization — no change.")
    else:
        # File exists but doesn't match either pattern — replace to be safe
        open(MESSAGE_CODEC_PATH, "w", encoding="utf-8").write(_MESSAGE_CODEC_SOURCE)
        log(f"  Replaced unrecognised {MESSAGE_CODEC_PATH} with")
        log("  kotlinx.serialization JSON implementation.")


# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        process_icon()
        gen_google_services()
        patch_gradle_properties()
        patch_proguard()
        write_app_name(APP_NAME)
        patch_build_gradle()
        patch_manifest()
        replace_message_codec()
        log("All modifications applied successfully.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(str(exc))
