#!/usr/bin/env python3
"""
scripts/modify.py  —  Metrolist Neo build patcher

【設計方針】
  Android では namespace と applicationId は独立した設定。
    - namespace    = Rクラス・BuildConfigのJavaパッケージ名
                     → com.metrolist.music のまま維持
                     → ソースコード全体がこのパッケージで R/BuildConfig を参照している
    - applicationId = APKのアプリ識別子（インストール時・Play Storeで使われる）
                     → com.metrolist.clone に変更

  namespace を変えようとしたことが過去のエラーの根本原因だった。
  applicationId だけ変更すれば R/BuildConfig の import は一切触る必要がない。

やること:
  1. アイコン色変更
  2. applicationId を com.metrolist.clone に変更（namespace は触らない）
  3. アプリ名を Metrolist Neo に変更
  4. AndroidManifest の label/icon を更新
  5. MessageCodec.kt を修正（proto API → kotlinx.serialization）
  6. gradle.properties に CI 用 JVM 設定をマージ
  7. buildFeatures.buildConfig = true を保証
"""

import os
import re
import sys
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────
APP_NAME       = "Metrolist Neo"
APPLICATION_ID = "com.metrolist.clone"   # APK識別子のみ変更

# namespace = "com.metrolist.music" は変更しない
# （R/BuildConfig のパッケージに使われるため、ソースと一致させる必要がある）

ICON_BG_START  = "#0055AA"
ICON_BG_END    = "#00ACEE"
ICON_FG_COLOR  = "#FFFFFFFF"

BASE_DIR      = "app"
RES_DIR       = os.path.join(BASE_DIR, "src/main/res")
GRADLE_FILE   = os.path.join(BASE_DIR, "build.gradle.kts")
MANIFEST_FILE = os.path.join(BASE_DIR, "src/main/AndroidManifest.xml")

MESSAGE_CODEC_PATH = os.path.join(
    BASE_DIR,
    "src/main/kotlin/com/metrolist/music/listentogether/MessageCodec.kt",
)
# ─────────────────────────────────────────────────────────────


def log(msg):
    print(f"[modify.py] {msg}", flush=True)


def die(msg):
    print(f"[modify.py] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def read_file(path, encoding="utf-8"):
    try:
        with open(path, encoding=encoding) as f:
            return f.read()
    except OSError as e:
        die(f"Cannot read {path}: {e}")


def write_file(path, content, encoding="utf-8"):
    try:
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
    except OSError as e:
        die(f"Cannot write {path}: {e}")


# ── 1. アイコン色変更 ──────────────────────────────────────────
def patch_icon_colors():
    log(f"Patching icon colors (bg: {ICON_BG_START}→{ICON_BG_END}, fg: {ICON_FG_COLOR})...")

    bg_gradient_xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<shape xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <gradient\n'
        '        android:angle="45.0"\n'
        f'        android:startColor="{ICON_BG_START}"\n'
        f'        android:endColor="{ICON_BG_END}"\n'
        '        android:type="linear" />\n'
        '</shape>'
    )

    for rel in ("drawable/ic_launcher_background_v31.xml",
                "drawable-v31/ic_launcher_background_v31.xml"):
        path = os.path.join(RES_DIR, rel)
        if os.path.exists(path):
            write_file(path, bg_gradient_xml)
            log(f"  Updated: {rel}")
        else:
            log(f"  Skipped (not found): {rel}")

    bg_color_path = os.path.join(RES_DIR, "values/ic_launcher_background.xml")
    if os.path.exists(bg_color_path):
        txt = read_file(bg_color_path)
        new = re.sub(
            r'<color name="ic_launcher_background">[^<]*</color>',
            f'<color name="ic_launcher_background">{ICON_BG_START}</color>',
            txt,
        )
        if new != txt:
            write_file(bg_color_path, new)
            log("  Updated: values/ic_launcher_background.xml")
        else:
            log("  Warning: ic_launcher_background color pattern not found.")
    else:
        log("  Skipped (not found): values/ic_launcher_background.xml")

    for rel in ("drawable/ic_launcher_foreground.xml",
                "drawable/ic_launcher_foreground_v31.xml"):
        path = os.path.join(RES_DIR, rel)
        if os.path.exists(path):
            txt = read_file(path)
            new = re.sub(
                r'android:strokeColor="[^"]*"',
                f'android:strokeColor="{ICON_FG_COLOR}"',
                txt,
            )
            if new != txt:
                write_file(path, new)
                log(f"  Updated: {rel}")
            else:
                log(f"  Warning: strokeColor pattern not found in {rel}.")
        else:
            log(f"  Skipped (not found): {rel}")


# ── 2. applicationId のみ変更（namespace は絶対に触らない） ──
#
# Android の正規設計:
#   namespace    = Rクラス・BuildConfig の Java パッケージ → ソースと一致させる
#   applicationId = APK の識別子 → 自由に変更可能
#
# v13.4.0+ パターン: val baseApplicationId = "..."
# 旧パターン:        applicationId = "..." (文字列リテラル)
def patch_application_id():
    log(f"Patching applicationId → {APPLICATION_ID} (namespace unchanged)...")
    if not os.path.exists(GRADLE_FILE):
        die(f"Not found: {GRADLE_FILE}")

    txt = read_file(GRADLE_FILE)
    new = txt
    patched = False

    # パターン1: v13.4.0+ — val baseApplicationId = "..."
    new, n = re.subn(
        r'(val\s+baseApplicationId\s*=\s*)"[^"]*"',
        rf'\1"{APPLICATION_ID}"',
        new,
    )
    if n:
        log(f"  baseApplicationId patched ({n} occurrence(s)).")
        patched = True

    # パターン2: 旧スタイル直接代入 — applicationId = "..."
    # applicationIdSuffix / applicationIdOverride は除外
    new, n = re.subn(
        r'(?<!\w)(applicationId\s*=\s*)"[^"]*"',
        rf'\1"{APPLICATION_ID}"',
        new,
    )
    if n:
        log(f"  applicationId (literal) patched ({n} occurrence(s)).")
        patched = True

    # namespace は触らない ← ここが過去の失敗の根本原因

    if not patched:
        log("  WARNING: applicationId pattern not found. Manual check needed.")
        return

    if new != txt:
        write_file(GRADLE_FILE, new)
        log("  build.gradle.kts written.")
    else:
        log("  applicationId already correct — no change.")


# ── 3. buildConfig = true を保証 ─────────────────────────────
def ensure_build_config_enabled():
    log("Ensuring buildFeatures.buildConfig = true...")
    if not os.path.exists(GRADLE_FILE):
        die(f"Not found: {GRADLE_FILE}")

    txt = read_file(GRADLE_FILE)

    if re.search(r'buildConfig\s*=\s*true', txt):
        log("  buildConfig = true already present — skipping.")
        return

    if "buildFeatures" in txt:
        new = re.sub(
            r'(buildFeatures\s*\{)',
            r'\1\n        buildConfig = true',
            txt,
            count=1,
        )
        if new != txt:
            write_file(GRADLE_FILE, new)
            log("  buildConfig = true injected into existing buildFeatures block.")
            return

    new = re.sub(
        r'(android\s*\{)',
        r'\1\n    buildFeatures {\n        buildConfig = true\n    }',
        txt,
        count=1,
    )
    if new != txt:
        write_file(GRADLE_FILE, new)
        log("  buildFeatures { buildConfig = true } block inserted.")
    else:
        log("  WARNING: Could not inject buildFeatures block. Manual check needed.")


# ── 4. アプリ名 ───────────────────────────────────────────────
def write_app_name():
    log(f"Writing app_name: {APP_NAME!r}...")
    pattern = re.compile(r'\s*<string\s+name="app_name"[^>]*>[^<]*</string>', re.MULTILINE)
    entry   = f'<string name="app_name">{APP_NAME}</string>'

    for root, _, files in os.walk(RES_DIR):
        if not os.path.basename(root).startswith("values"):
            continue
        for fname in files:
            if not fname.endswith(".xml"):
                continue
            fp = os.path.join(root, fname)
            try:
                txt = read_file(fp)
                if 'name="app_name"' not in txt:
                    continue
                cleaned = pattern.sub("", txt)
                body = re.sub(r"<\?xml[^?]*\?>|</?resources[^>]*>", "", cleaned).strip()
                if not body:
                    os.remove(fp)
                    log(f"  Removed empty: {fp}")
                else:
                    write_file(fp, cleaned)
                    log(f"  Cleaned: {fp}")
            except Exception as exc:
                log(f"  Warning: {fp}: {exc}")

    os.makedirs(os.path.join(RES_DIR, "values"), exist_ok=True)
    sp = os.path.join(RES_DIR, "values", "strings.xml")
    if os.path.exists(sp):
        txt = read_file(sp)
        if 'name="app_name"' in txt:
            txt = re.sub(r'<string\s+name="app_name"[^>]*>[^<]*</string>', entry, txt)
        else:
            txt = re.sub(r"(<resources[^>]*>)", rf"\1\n    {entry}", txt, count=1)
        write_file(sp, txt)
    else:
        write_file(
            sp,
            f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    {entry}\n</resources>',
        )
    log(f"  app_name written to {sp}")


# ── 5. AndroidManifest ────────────────────────────────────────
def patch_manifest():
    log(f"Patching {MANIFEST_FILE}...")
    if not os.path.exists(MANIFEST_FILE):
        die(f"Not found: {MANIFEST_FILE}")
    txt = read_file(MANIFEST_FILE)
    txt = re.sub(r'android:label="[^"]*"',  'android:label="@string/app_name"', txt)
    txt = re.sub(r'android:icon="[^"]*"',   'android:icon="@mipmap/ic_launcher"', txt)
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
    write_file(MANIFEST_FILE, txt)
    log("  AndroidManifest patched.")


# ── 6. MessageCodec.kt の修正 ─────────────────────────────────
_MESSAGE_CODEC_SOURCE = '''\
/**
 * Metrolist Project (C) 2026
 * Licensed under GPL-3.0 | See git history for contributors
 */

package com.metrolist.music.listentogether

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import timber.log.Timber
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

/**
 * Codec for encoding and decoding ListenTogether wire messages.
 * Wire format: {"type":"<TYPE>","compressed":<bool>,"payload":"<JSON>"}
 */
class MessageCodec(
    var compressionEnabled: Boolean = false
) {
    companion object {
        private const val TAG = "MessageCodec"
        private const val COMPRESSION_THRESHOLD = 100
    }

    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = false
        isLenient = true
    }

    fun encode(msgType: String, payload: Any?): ByteArray {
        var payloadBytes = if (payload != null)
            json.encodeToString(toJsonElement(payload)).toByteArray(Charsets.UTF_8)
        else byteArrayOf()

        var compressed = false
        if (compressionEnabled && payloadBytes.size > COMPRESSION_THRESHOLD) {
            val c = compress(payloadBytes)
            if (c.size < payloadBytes.size) { payloadBytes = c; compressed = true }
        }

        return json.encodeToString(buildJsonObject {
            put("type", msgType)
            put("compressed", compressed)
            put("payload", if (payloadBytes.isEmpty()) "" else payloadBytes.toString(Charsets.UTF_8))
        }).toByteArray(Charsets.UTF_8)
    }

    fun decode(data: ByteArray): Pair<String, ByteArray> {
        val root       = json.parseToJsonElement(data.toString(Charsets.UTF_8)).jsonObject
        val msgType    = root["type"]?.jsonPrimitive?.content ?: ""
        val compressed = root["compressed"]?.jsonPrimitive?.content?.toBoolean() ?: false
        var payload    = (root["payload"]?.jsonPrimitive?.content ?: "").toByteArray(Charsets.UTF_8)
        if (compressed) payload = decompress(payload) ?: payload
        return Pair(msgType, payload)
    }

    fun decodePayload(msgType: String, payloadBytes: ByteArray): Any? {
        if (payloadBytes.isEmpty()) return null
        return try {
            val el = json.parseToJsonElement(payloadBytes.toString(Charsets.UTF_8))
            when (msgType) {
                MessageTypes.ROOM_CREATED        -> json.decodeFromJsonElement<RoomCreatedPayload>(el)
                MessageTypes.JOIN_REQUEST        -> json.decodeFromJsonElement<JoinRequestPayload>(el)
                MessageTypes.JOIN_APPROVED       -> json.decodeFromJsonElement<JoinApprovedPayload>(el)
                MessageTypes.JOIN_REJECTED       -> json.decodeFromJsonElement<JoinRejectedPayload>(el)
                MessageTypes.USER_JOINED         -> json.decodeFromJsonElement<UserJoinedPayload>(el)
                MessageTypes.USER_LEFT           -> json.decodeFromJsonElement<UserLeftPayload>(el)
                MessageTypes.SYNC_PLAYBACK       -> json.decodeFromJsonElement<PlaybackActionPayload>(el)
                MessageTypes.BUFFER_WAIT         -> json.decodeFromJsonElement<BufferWaitPayload>(el)
                MessageTypes.BUFFER_COMPLETE     -> json.decodeFromJsonElement<BufferCompletePayload>(el)
                MessageTypes.ERROR               -> json.decodeFromJsonElement<ErrorPayload>(el)
                MessageTypes.HOST_CHANGED        -> json.decodeFromJsonElement<HostChangedPayload>(el)
                MessageTypes.KICKED              -> json.decodeFromJsonElement<KickedPayload>(el)
                MessageTypes.SYNC_STATE          -> json.decodeFromJsonElement<SyncStatePayload>(el)
                MessageTypes.RECONNECTED         -> json.decodeFromJsonElement<ReconnectedPayload>(el)
                MessageTypes.USER_RECONNECTED    -> json.decodeFromJsonElement<UserReconnectedPayload>(el)
                MessageTypes.USER_DISCONNECTED   -> json.decodeFromJsonElement<UserDisconnectedPayload>(el)
                MessageTypes.SUGGESTION_RECEIVED -> json.decodeFromJsonElement<SuggestionReceivedPayload>(el)
                MessageTypes.SUGGESTION_APPROVED -> json.decodeFromJsonElement<SuggestionApprovedPayload>(el)
                MessageTypes.SUGGESTION_REJECTED -> json.decodeFromJsonElement<SuggestionRejectedPayload>(el)
                else -> null
            }
        } catch (e: Exception) {
            Timber.tag(TAG).e(e, "Failed to decode payload for type: $msgType")
            null
        }
    }

    private fun toJsonElement(payload: Any): JsonElement = when (payload) {
        is CreateRoomPayload        -> json.encodeToJsonElement(payload)
        is JoinRoomPayload          -> json.encodeToJsonElement(payload)
        is ApproveJoinPayload       -> json.encodeToJsonElement(payload)
        is RejectJoinPayload        -> json.encodeToJsonElement(payload)
        is PlaybackActionPayload    -> json.encodeToJsonElement(payload)
        is BufferReadyPayload       -> json.encodeToJsonElement(payload)
        is KickUserPayload          -> json.encodeToJsonElement(payload)
        is TransferHostPayload      -> json.encodeToJsonElement(payload)
        is ChatPayload              -> json.encodeToJsonElement(payload)
        is SuggestTrackPayload      -> json.encodeToJsonElement(payload)
        is ApproveSuggestionPayload -> json.encodeToJsonElement(payload)
        is RejectSuggestionPayload  -> json.encodeToJsonElement(payload)
        is ReconnectPayload         -> json.encodeToJsonElement(payload)
        else -> throw IllegalArgumentException(
            "Unsupported payload type: ${payload::class.simpleName}"
        )
    }

    private fun compress(data: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(data) }
        return out.toByteArray()
    }

    private fun decompress(data: ByteArray): ByteArray? = try {
        GZIPInputStream(ByteArrayInputStream(data)).use { it.readBytes() }
    } catch (e: Exception) {
        Timber.tag(TAG).e(e, "Failed to decompress data")
        null
    }
}
'''


def replace_message_codec():
    log(f"Checking {MESSAGE_CODEC_PATH}...")
    if not os.path.exists(MESSAGE_CODEC_PATH):
        log("  Not found — skipping.")
        return
    existing = read_file(MESSAGE_CODEC_PATH)
    if "Listentogether" in existing or "listentogether.proto" in existing:
        write_file(MESSAGE_CODEC_PATH, _MESSAGE_CODEC_SOURCE)
        log("  Replaced (was proto-based).")
    else:
        log("  Already up to date — no change.")


# ── 7. gradle.properties ─────────────────────────────────────
def patch_gradle_properties():
    log("Patching gradle.properties...")
    desired = {
        "org.gradle.jvmargs":
            "-Xmx4096m -XX:MaxMetaspaceSize=1g -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8",
        "kotlin.daemon.jvmargs": "-Xmx4096m -XX:MaxMetaspaceSize=1g",
        "org.gradle.parallel":    "true",
        "org.gradle.caching":     "true",
        "android.enableJetifier": "false",
    }
    path = "gradle.properties"
    lines = open(path).readlines() if os.path.exists(path) else []
    result, replaced = [], set()
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            result.append(line)
            continue
        key = s.split("=", 1)[0].strip()
        if key in desired:
            result.append(f"{key}={desired[key]}\n")
            replaced.add(key)
        else:
            result.append(line)
    for k, v in desired.items():
        if k not in replaced:
            result.append(f"{k}={v}\n")
    with open(path, "w") as f:
        f.writelines(result)
    log("  gradle.properties patched.")


# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        patch_icon_colors()
        patch_application_id()       # applicationId のみ変更、namespace は触らない
        ensure_build_config_enabled()
        write_app_name()
        patch_manifest()
        replace_message_codec()
        patch_gradle_properties()
        log("All modifications applied successfully.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(str(exc))
