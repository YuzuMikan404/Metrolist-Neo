#!/usr/bin/env python3
"""
scripts/modify.py  —  Metrolist Neo build patcher

【設計方針】
  アプリ名・applicationId の変更は build.gradle.kts の既存の仕組みを使う。

    build.gradle.kts には以下の環境変数サポートが既に実装されている:
      METROLIST_APPLICATION_ID → applicationId を上書き
      METROLIST_APP_NAME       → resValue("string", "app_name", ...) を上書き

    resValue() はビルド時に string/app_name を自動生成するため、
    app_name.xml が同時に存在すると「Duplicate resources」エラーになる。
    → app_name.xml は必ず削除する。modify.py で XML を直接書き換えない。

  namespace は絶対に触らない。
    namespace = "com.metrolist.music" のまま維持。
    R クラス・BuildConfig の Java パッケージに使われるため、
    ソースコード全体と一致させる必要がある。

やること:
  1. app_name.xml を削除（resValue と重複するため）
  2. アイコン色変更（グラデーション背景・前景の strokeColor）
  3. MessageCodec.kt を修正
       アップストリームは proto API (Listentogether.*) を参照しているが、
       proto ファイルも protobuf gradle プラグインも存在しないため
       ビルドが通らない。Protocol.kt の @Serializable クラスを使う
       kotlinx.serialization 実装に置き換える。
  4. gradle.properties に CI 用 JVM 設定をマージ

やらないこと（理由付き）:
  - app_name.xml の書き換え → resValue と重複するため削除のみ
  - strings.xml への app_name 追記 → 同上
  - AndroidManifest の書き換え → label は既に @string/app_name 参照済み
  - namespace の変更 → R/BuildConfig のパッケージに使われるため禁止
  - applicationId の直接書き換え → 環境変数で制御するため不要
"""

import os
import re
import sys
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────
ICON_BG_START = "#0055AA"
ICON_BG_END   = "#00ACEE"
ICON_FG_COLOR = "#FFFFFFFF"

BASE_DIR = "app"
RES_DIR  = os.path.join(BASE_DIR, "src/main/res")

MESSAGE_CODEC_PATH = os.path.join(
    BASE_DIR,
    "src/main/kotlin/com/metrolist/music/listentogether/MessageCodec.kt",
)
# ─────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[modify.py] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[modify.py] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def read_file(path: str, encoding: str = "utf-8") -> str:
    try:
        with open(path, encoding=encoding) as f:
            return f.read()
    except OSError as e:
        die(f"Cannot read {path}: {e}")


def write_file(path: str, content: str, encoding: str = "utf-8") -> None:
    try:
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
    except OSError as e:
        die(f"Cannot write {path}: {e}")


# ── 1. app_name.xml を削除 ────────────────────────────────────
#
# build.gradle.kts は resValue("string", "app_name", ...) でアプリ名を
# ビルド時に生成する。app_name.xml が残っていると Duplicate resources エラー。
# 環境変数 METROLIST_APP_NAME の値が resValue に使われる。
#
# values-xx/ 配下に app_name を持つ翻訳ファイルがある場合も同様に削除する。
# （実際には values/ にしか存在しないが、念のため全探索する）
def remove_app_name_xml() -> None:
    log("Removing app_name.xml to avoid resValue conflict...")
    removed = 0

    for root, _dirs, files in os.walk(RES_DIR):
        dirname = os.path.basename(root)
        if not dirname.startswith("values"):
            continue
        target = os.path.join(root, "app_name.xml")
        if os.path.exists(target):
            os.remove(target)
            log(f"  Deleted: {target}")
            removed += 1

    if removed == 0:
        log("  app_name.xml not found — nothing to delete.")
    else:
        log(f"  Removed {removed} file(s).")

    # strings.xml に app_name エントリが紛れ込んでいる場合も除去する。
    # （前回の modify.py が追記してしまったケースへの保険）
    _purge_app_name_from_strings()


def _purge_app_name_from_strings() -> None:
    """strings.xml 内の app_name エントリを除去する（追記済み対策）。"""
    for root, _dirs, files in os.walk(RES_DIR):
        dirname = os.path.basename(root)
        if not dirname.startswith("values"):
            continue
        for fname in files:
            if not fname.endswith(".xml"):
                continue
            fp = os.path.join(root, fname)
            txt = read_file(fp)
            if 'name="app_name"' not in txt:
                continue
            # app_name.xml 以外のファイル（strings.xml 等）から除去
            if fname == "app_name.xml":
                continue  # 上で削除済み
            new = re.sub(
                r'\s*<string\s+name="app_name"[^>]*>[^<]*</string>',
                "",
                txt,
            )
            if new != txt:
                write_file(fp, new)
                log(f"  Purged app_name entry from: {fp}")


# ── 2. アイコン色変更 ──────────────────────────────────────────
#
# 変更対象:
#   drawable/ic_launcher_background_v31.xml      — API 30 以下向けフォールバック
#   drawable-v31/ic_launcher_background_v31.xml  — API 31 以上向け（adaptive icon）
#   values/ic_launcher_background.xml            — 色リソース定義
#   drawable/ic_launcher_foreground.xml          — 前景 strokeColor
#   drawable/ic_launcher_foreground_v31.xml      — 前景 strokeColor（v31）
def patch_icon_colors() -> None:
    log(f"Patching icon colors (bg: {ICON_BG_START}→{ICON_BG_END}, fg: {ICON_FG_COLOR})...")

    # API 30 以下向けフォールバック背景（固定色グラデーション）
    bg_gradient_legacy = (
        '<!-- Fallback gradient for API < 31 -->\n'
        '<shape xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <gradient\n'
        '        android:angle="45.0"\n'
        f'        android:startColor="{ICON_BG_START}"\n'
        f'        android:endColor="{ICON_BG_END}"\n'
        '        android:type="linear" />\n'
        '</shape>'
    )

    # API 31 以上向け背景（同じグラデーション — システムカラーは使わない）
    bg_gradient_v31 = (
        '<shape xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <gradient\n'
        '        android:angle="45.0"\n'
        f'        android:startColor="{ICON_BG_START}"\n'
        f'        android:endColor="{ICON_BG_END}"\n'
        '        android:type="linear" />\n'
        '</shape>'
    )

    patch_map = {
        "drawable/ic_launcher_background_v31.xml":     bg_gradient_legacy,
        "drawable-v31/ic_launcher_background_v31.xml": bg_gradient_v31,
    }
    for rel, content in patch_map.items():
        path = os.path.join(RES_DIR, rel)
        if os.path.exists(path):
            write_file(path, content)
            log(f"  Updated: {rel}")
        else:
            log(f"  Skipped (not found): {rel}")

    # ic_launcher_background カラーリソース
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

    # 前景アイコン strokeColor
    for rel in (
        "drawable/ic_launcher_foreground.xml",
        "drawable/ic_launcher_foreground_v31.xml",
    ):
        path = os.path.join(RES_DIR, rel)
        if not os.path.exists(path):
            log(f"  Skipped (not found): {rel}")
            continue
        txt = read_file(path)
        if 'android:strokeColor=' not in txt:
            log(f"  Warning: strokeColor attribute not found in {rel} — skipping.")
            continue
        new = re.sub(
            r'android:strokeColor="[^"]*"',
            f'android:strokeColor="{ICON_FG_COLOR}"',
            txt,
        )
        if new != txt:
            write_file(path, new)
            log(f"  Updated: {rel}")
        else:
            log(f"  Already correct ({ICON_FG_COLOR}): {rel}")


# ── 3. MessageCodec.kt の置き換え ────────────────────────────
#
# アップストリームの MessageCodec.kt は proto API
# (com.metrolist.music.listentogether.proto.Listentogether) を使っているが、
# .proto ファイルも protobuf gradle プラグインも存在しないためビルドが通らない。
#
# Protocol.kt は kotlinx.serialization の @Serializable クラスで定義されており、
# MessageCodec.kt だけが proto API を使う不整合な状態になっている。
#
# 修正版: kotlinx.serialization + JSON エンコード/デコードに統一する。
# インターフェース（encode/decode/decodePayload のシグネチャ）は維持し、
# ListenTogetherClient.kt は無変更で動く。
_MESSAGE_CODEC_REPLACEMENT = '''\
/**
 * Metrolist Project (C) 2026
 * Licensed under GPL-3.0 | See git history for contributors
 *
 * [Patched by Metrolist Neo build system]
 * Upstream MessageCodec.kt referenced proto-generated classes
 * (com.metrolist.music.listentogether.proto.Listentogether) that do not
 * exist in the source tree (no .proto files, no protobuf Gradle plugin).
 * This replacement uses kotlinx.serialization / JSON, consistent with
 * Protocol.kt, while keeping the same public API so ListenTogetherClient
 * requires no changes.
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
 *
 * Wire format (JSON):
 *   { "type": "<TYPE>", "compressed": <bool>, "payload": "<JSON string>" }
 *
 * Compression is applied per-message when [compressionEnabled] is true and
 * the serialised payload exceeds [COMPRESSION_THRESHOLD] bytes.
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
        coerceInputValues = true
    }

    // ── Encode ────────────────────────────────────────────────

    fun encode(msgType: String, payload: Any?): ByteArray {
        var payloadBytes: ByteArray = if (payload != null) {
            json.encodeToString(toJsonElement(payload))
                .toByteArray(Charsets.UTF_8)
        } else {
            ByteArray(0)
        }

        var compressed = false
        if (compressionEnabled && payloadBytes.size > COMPRESSION_THRESHOLD) {
            val c = compress(payloadBytes)
            if (c.size < payloadBytes.size) {
                payloadBytes = c
                compressed = true
            }
        }

        val envelope = buildJsonObject {
            put("type", msgType)
            put("compressed", compressed)
            put("payload", payloadBytes.toString(Charsets.UTF_8))
        }
        return json.encodeToString(envelope).toByteArray(Charsets.UTF_8)
    }

    // ── Decode ────────────────────────────────────────────────

    fun decode(data: ByteArray): Pair<String, ByteArray> {
        val root       = json.parseToJsonElement(data.toString(Charsets.UTF_8)).jsonObject
        val msgType    = root["type"]?.jsonPrimitive?.content.orEmpty()
        val compressed = root["compressed"]?.jsonPrimitive?.content
                             ?.toBooleanStrictOrNull() ?: false
        var payload    = (root["payload"]?.jsonPrimitive?.content.orEmpty())
                             .toByteArray(Charsets.UTF_8)
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
                else -> {
                    Timber.tag(TAG).w("Unknown message type: %s", msgType)
                    null
                }
            }
        } catch (e: Exception) {
            Timber.tag(TAG).e(e, "Failed to decode payload for type: %s", msgType)
            null
        }
    }

    // ── Private helpers ───────────────────────────────────────

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


def replace_message_codec() -> None:
    log(f"Checking {MESSAGE_CODEC_PATH}...")

    if not os.path.exists(MESSAGE_CODEC_PATH):
        log("  Not found — skipping.")
        return

    existing = read_file(MESSAGE_CODEC_PATH)

    # proto API を使っているかどうかをチェック
    needs_replace = (
        "listentogether.proto" in existing
        or "Listentogether." in existing
        or "com.google.protobuf" in existing
    )

    if not needs_replace:
        log("  Already up to date (no proto references) — skipping.")
        return

    write_file(MESSAGE_CODEC_PATH, _MESSAGE_CODEC_REPLACEMENT)
    log("  Replaced (was proto-based → kotlinx.serialization).")


# ── 4. gradle.properties ──────────────────────────────────────
#
# CI 環境向けの JVM・Gradle 設定をマージする。
# 既存のキーは上書き、存在しないキーは末尾に追記。
def patch_gradle_properties() -> None:
    log("Patching gradle.properties...")
    desired: dict[str, str] = {
        "org.gradle.jvmargs": (
            "-Xmx4096m -XX:MaxMetaspaceSize=1g "
            "-XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8"
        ),
        "kotlin.daemon.jvmargs": "-Xmx4096m -XX:MaxMetaspaceSize=1g",
        "org.gradle.parallel":    "true",
        "org.gradle.caching":     "false",   # SNAPSHOT deps があるため false
        "android.enableJetifier": "false",
    }

    prop_path = "gradle.properties"
    lines: list[str] = []
    if os.path.exists(prop_path):
        with open(prop_path, encoding="utf-8") as f:
            lines = f.readlines()

    result: list[str] = []
    replaced: set[str] = set()

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

    for k, v in desired.items():
        if k not in replaced:
            result.append(f"{k}={v}\n")

    with open(prop_path, "w", encoding="utf-8") as f:
        f.writelines(result)
    log("  gradle.properties patched.")


# ── 事前チェック ──────────────────────────────────────────────
def preflight_checks() -> None:
    """必須ファイル・ディレクトリの存在を確認する。"""
    log("Running preflight checks...")

    required = [
        BASE_DIR,
        RES_DIR,
        os.path.join(BASE_DIR, "build.gradle.kts"),
        os.path.join(BASE_DIR, "src/main/AndroidManifest.xml"),
    ]
    missing = [p for p in required if not os.path.exists(p)]
    if missing:
        die(
            "Required paths not found. "
            "Run this script from the project root.\n  "
            + "\n  ".join(missing)
        )

    # resValue の仕組みが build.gradle.kts に存在するか確認
    gradle_txt = read_file(os.path.join(BASE_DIR, "build.gradle.kts"))
    if 'resValue("string", "app_name"' not in gradle_txt:
        log(
            "  WARNING: resValue(\"string\", \"app_name\", ...) not found in "
            "build.gradle.kts.\n"
            "  App name may not be applied. Check METROLIST_APP_NAME env var."
        )
    else:
        log("  build.gradle.kts resValue check: OK")

    log("  Preflight checks passed.")


# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        preflight_checks()
        remove_app_name_xml()       # resValue との重複を防ぐ（最重要）
        patch_icon_colors()
        replace_message_codec()     # proto → kotlinx.serialization
        patch_gradle_properties()
        log("All modifications applied successfully.")
        log("")
        log("NOTE: App name and applicationId are controlled via env vars:")
        log("  METROLIST_APP_NAME       (default: Metrolist)")
        log("  METROLIST_APPLICATION_ID (default: com.metrolist.music)")
        log("Set these in the GitHub Actions workflow or local.properties.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        die(str(exc))
