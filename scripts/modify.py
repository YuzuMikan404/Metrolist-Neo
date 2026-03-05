#!/usr/bin/env python3
"""
scripts/modify.py  —  Metrolist Neo build patcher

やること（最小限）:
  1. アイコン差し替え（icon.png があれば）
  2. applicationId を APP_ID に変更
  3. アプリ名を APP_NAME に変更
  4. AndroidManifest の label/icon を更新
  5. MessageCodec.kt を修正
     → v13.2.1 で protobuf が削除されたのに MessageCodec.kt だけ
       旧 proto API のままになっているバグを修正する
  6. gradle.properties に CI 用 JVM 設定をマージ

やらないこと:
  - google-services.json の生成（v13.2.1 では不要）
  - Firebase/Crashlytics の無効化（v13.2.1 では元から存在しない）
  - protobuf プラグインの注入（不要）
"""

import os
import re
import shutil
import sys

# ── CONFIG ────────────────────────────────────────────────────
APP_NAME = "Metrolist Neo"
APP_ID   = "com.metrolist.clone"

ICON_SRC      = "icon.png"
BASE_DIR      = "app"
RES_DIR       = os.path.join(BASE_DIR, "src/main/res")
GRADLE_FILE   = os.path.join(BASE_DIR, "build.gradle.kts")
MANIFEST_FILE = os.path.join(BASE_DIR, "src/main/AndroidManifest.xml")
PROGUARD_FILE = os.path.join(BASE_DIR, "proguard-rules.pro")

MESSAGE_CODEC_PATH = os.path.join(
    BASE_DIR,
    "src/main/kotlin/com/metrolist/music/listentogether/MessageCodec.kt",
)
# ─────────────────────────────────────────────────────────────

try:
    from PIL import Image, ImageOps
    PIL_OK = True
except ImportError:
    PIL_OK = False


def log(msg):
    print(f"[modify.py] {msg}", flush=True)

def die(msg):
    print(f"[modify.py] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ── 1. アイコン ───────────────────────────────────────────────
def process_icon():
    log("Processing icon...")
    if not PIL_OK or not os.path.exists(ICON_SRC):
        log("Skipping — PIL unavailable or no icon.png found.")
        return
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
            f"<resources><color name=\"ic_launcher_background\">{bg}</color></resources>"
        )
        xhd = os.path.join(RES_DIR, "mipmap-xxxhdpi")
        drw = os.path.join(RES_DIR, "drawable")
        shutil.copy("_ic_fg.png", os.path.join(xhd, "ic_launcher_foreground.png"))
        shutil.copy("_ic_fg.png", os.path.join(drw, "ic_launcher_foreground.png"))
        shutil.copy("_ic_lg.png", os.path.join(xhd, "ic_launcher.png"))
        shutil.copy("_ic_lg.png", os.path.join(xhd, "ic_launcher_round.png"))
        log(f"Icon done. Background: {bg}")
    except Exception as exc:
        log(f"Icon processing failed: {exc}")


# ── 2. applicationId ─────────────────────────────────────────
def patch_application_id():
    log(f"Patching applicationId → {APP_ID}...")
    if not os.path.exists(GRADLE_FILE):
        die(f"Not found: {GRADLE_FILE}")
    txt = open(GRADLE_FILE).read()
    new = re.sub(r'(applicationId\s*=\s*)"[^"]*"', rf'\1"{APP_ID}"', txt)
    if new != txt:
        open(GRADLE_FILE, "w").write(new)
        log("  applicationId patched.")
    else:
        log("  applicationId unchanged (already correct?).")


# ── 3. アプリ名 ───────────────────────────────────────────────
def write_app_name():
    log(f"Writing app_name: {APP_NAME!r}...")
    pattern = re.compile(r'\s*<string\s+name="app_name"[^>]*>[^<]*</string>', re.MULTILINE)
    entry   = f'<string name="app_name">{APP_NAME}</string>'

    # 既存の app_name エントリを全 values* ディレクトリから除去
    for root, _, files in os.walk(RES_DIR):
        if not os.path.basename(root).startswith("values"):
            continue
        for fname in files:
            if not fname.endswith(".xml"):
                continue
            fp = os.path.join(root, fname)
            try:
                txt = open(fp, encoding="utf-8").read()
                if 'name="app_name"' not in txt:
                    continue
                cleaned = pattern.sub("", txt)
                body = re.sub(r"<\?xml[^?]*\?>|</?resources[^>]*>", "", cleaned).strip()
                if not body:
                    os.remove(fp)
                    log(f"  Removed empty: {fp}")
                else:
                    open(fp, "w", encoding="utf-8").write(cleaned)
                    log(f"  Cleaned: {fp}")
            except Exception as exc:
                log(f"  Warning: {fp}: {exc}")

    # values/strings.xml に書き込む
    os.makedirs(os.path.join(RES_DIR, "values"), exist_ok=True)
    sp = os.path.join(RES_DIR, "values", "strings.xml")
    if os.path.exists(sp):
        txt = open(sp, encoding="utf-8").read()
        if 'name="app_name"' in txt:
            txt = re.sub(r'<string\s+name="app_name"[^>]*>[^<]*</string>', entry, txt)
        else:
            txt = re.sub(r"(<resources[^>]*>)", rf"\1\n    {entry}", txt, count=1)
        open(sp, "w", encoding="utf-8").write(txt)
    else:
        open(sp, "w", encoding="utf-8").write(
            f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    {entry}\n</resources>'
        )
    log(f"  app_name written to {sp}")


# ── 4. AndroidManifest ────────────────────────────────────────
def patch_manifest():
    log(f"Patching {MANIFEST_FILE}...")
    if not os.path.exists(MANIFEST_FILE):
        die(f"Not found: {MANIFEST_FILE}")
    txt = open(MANIFEST_FILE).read()
    txt = re.sub(r'android:label="[^"]*"',  'android:label="@string/app_name"', txt)
    txt = re.sub(r'android:icon="[^"]*"',   'android:icon="@mipmap/ic_launcher"', txt)
    if "android:roundIcon=" in txt:
        txt = re.sub(r'android:roundIcon="[^"]*"', 'android:roundIcon="@mipmap/ic_launcher_round"', txt)
    else:
        txt = txt.replace("<application", '<application android:roundIcon="@mipmap/ic_launcher_round"', 1)
    open(MANIFEST_FILE, "w").write(txt)


# ── 5. MessageCodec.kt の修正 ─────────────────────────────────
#
# 問題: v13.2.1 で upstream が listentogether/ パッケージを
#       protobuf → kotlinx.serialization に書き直したが、
#       MessageCodec.kt だけ旧 proto API のまま残ってしまった。
#
# 修正: 公開 API（クラス名・メソッドシグネチャ）を完全に維持したまま
#       kotlinx.serialization JSON + GZIP 圧縮で再実装する。
#       ListenTogetherClient.kt 側は一切変更不要。

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
 *
 * v13.2.1 で削除された protobuf (Listentogether.* / proto パッケージ) の
 * 代替実装。kotlinx.serialization JSON + オプション GZIP 圧縮を使用。
 * 公開 API は元のクラスと完全に同一。
 *
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
        else -> throw IllegalArgumentException("Unsupported payload type: ${payload::class.simpleName}")
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
    existing = open(MESSAGE_CODEC_PATH, encoding="utf-8").read()
    if "Listentogether" in existing or "listentogether.proto" in existing:
        open(MESSAGE_CODEC_PATH, "w", encoding="utf-8").write(_MESSAGE_CODEC_SOURCE)
        log("  Replaced (was proto-based).")
    else:
        log("  Already up to date — no change.")


# ── 6. gradle.properties（CI 用 JVM 設定のみ） ────────────────
def patch_gradle_properties():
    log("Patching gradle.properties...")
    desired = {
        "org.gradle.jvmargs":
            "-Xmx4096m -XX:MaxMetaspaceSize=1g -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8",
        "kotlin.daemon.jvmargs": "-Xmx4096m -XX:MaxMetaspaceSize=1g",
        "org.gradle.parallel":       "true",
        "org.gradle.caching":        "true",
        "android.enableJetifier":    "false",
    }
    path = "gradle.properties"
    lines = open(path).readlines() if os.path.exists(path) else []
    result, replaced = [], set()
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            result.append(line); continue
        key = s.split("=", 1)[0].strip()
        if key in desired:
            result.append(f"{key}={desired[key]}\n"); replaced.add(key)
        else:
            result.append(line)
    for k, v in desired.items():
        if k not in replaced:
            result.append(f"{k}={v}\n")
    open(path, "w").writelines(result)
    log("  gradle.properties patched.")


# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        process_icon()
        patch_application_id()
        write_app_name()
        patch_manifest()
        replace_message_codec()
        patch_gradle_properties()
        log("All modifications applied successfully.")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback; traceback.print_exc()
        die(str(exc))
