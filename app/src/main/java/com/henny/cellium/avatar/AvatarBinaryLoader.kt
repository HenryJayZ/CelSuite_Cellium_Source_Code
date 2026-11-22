package com.henny.cellium.avatar

import android.content.Context
import android.util.Log
import java.io.BufferedInputStream
import java.io.DataInputStream

private const val TAG = "AvatarBinaryLoader"
private const val CX = 300f
private const val CY = 200f

class AvatarLibrary private constructor(
    private val byGender: Map<String, Map<String, AvatarExpression>>,
) {
    val genders: List<String> = AVATAR_GENDERS.filter { byGender.containsKey(it) }

    fun baseNames(gender: String): List<String> =
        byGender[gender]?.keys?.sorted() ?: emptyList()

    fun totalMatrixCount(): Int =
        byGender.values.sumOf { it.size * (1 + STYLE_MODIFIERS.size) }

    fun get(gender: String, name: String, modifier: String? = null): AvatarExpression? {
        val genderMap = byGender[gender] ?: byGender["Female"] ?: byGender.values.firstOrNull()
            ?: return null
        val base = genderMap[name]
            ?: genderMap.entries.firstOrNull { it.key.equals(name, ignoreCase = true) }?.value
            ?: genderMap["Happy"]
            ?: genderMap.values.firstOrNull()
            ?: return null
        return if (modifier.isNullOrBlank() || modifier == "Base") {
            base
        } else {
            applyModifier(base, modifier)
        }
    }

    fun getForMood(gender: String, mood: String): AvatarExpression? {
        val candidates = AVATAR_MOODS[mood] ?: AVATAR_MOODS["idle"]!!
        for (c in candidates) {
            val found = byGender[gender]?.get(c)
            if (found != null) return found
        }
        return get(gender, "Happy")
    }

    companion object {
        @Volatile
        private var cached: AvatarLibrary? = null

        fun load(context: Context): AvatarLibrary {
            cached?.let { return it }
            synchronized(this) {
                cached?.let { return it }
                val loaded = readBinary(context)
                cached = loaded
                return loaded
            }
        }

        fun clearCache() {
            synchronized(this) {
                cached = null
            }
        }

        private fun readBinary(context: Context): AvatarLibrary {
            val result = mutableMapOf<String, MutableMap<String, AvatarExpression>>()
            try {
                context.assets.open("cel_expressions.bin").use { raw ->
                    DataInputStream(BufferedInputStream(raw, 32768)).use { dis ->
                        val magic = ByteArray(4)
                        dis.readFully(magic)
                        if (String(magic, Charsets.US_ASCII) != "CEL1") {
                            Log.e(TAG, "Invalid cel_expressions.bin magic header")
                            return AvatarLibrary(emptyMap())
                        }
                        val count = dis.readInt()
                        repeat(count) {
                            val genderIdx = dis.readUnsignedByte()
                            val flags = dis.readUnsignedByte()
                            val nameLen = dis.readUnsignedShort()
                            val nameBytes = ByteArray(nameLen)
                            dis.readFully(nameBytes)
                            val name = String(nameBytes, Charsets.UTF_8)
                            val leftDepth = dis.readFloat()
                            val rightDepth = dis.readFloat()
                            val leftDip = dis.readFloat()
                            val rightDip = dis.readFloat()
                            val fadeOpacity = dis.readFloat()
                            val ptCount = dis.readUnsignedShort()
                            val pts = ArrayList<AvatarPoint>(ptCount)
                            repeat(ptCount) {
                                val x = dis.readShort() / 10f
                                val y = dis.readShort() / 10f
                                val ks = dis.readUnsignedByte()
                                val kind = AvatarKind.fromIndex(ks and 0x7F)
                                val left = (ks and 0x80) != 0
                                pts.add(AvatarPoint(x, y, kind, left))
                            }
                            val gender = AVATAR_GENDERS.getOrElse(genderIdx) { "Female" }
                            val expr = AvatarExpression(
                                name = name,
                                gender = gender,
                                points = pts,
                                blinkEnabled = (flags and 1) != 0,
                                blinkLeft = (flags and 2) != 0,
                                blinkRight = (flags and 4) != 0,
                                leftDepth = leftDepth,
                                rightDepth = rightDepth,
                                leftEyebrowDip = leftDip,
                                rightEyebrowDip = rightDip,
                                fadeOpacity = fadeOpacity,
                            )
                            result.getOrPut(gender) { linkedMapOf() }[name] = expr
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to unpack cel_expressions.bin", e)
            }
            return AvatarLibrary(result)
        }

        private fun scaled(p: AvatarPoint, sx: Float, sy: Float) =
            p.copy(x = CX + (p.x - CX) * sx, y = CY + (p.y - CY) * sy)

        private fun moved(p: AvatarPoint, dx: Float, dy: Float) =
            p.copy(x = p.x + dx, y = p.y + dy)

        fun applyModifier(base: AvatarExpression, modifier: String): AvatarExpression {
            val eyeKinds = setOf(AvatarKind.EYELID, AvatarKind.EYEBROW)
            val mouthKinds = setOf(AvatarKind.STEM, AvatarKind.BOTTOM_BAR, AvatarKind.MID_BAR)
            val transformed: List<AvatarPoint> = when (modifier) {
                "Chibi" -> base.points.map { p ->
                    when {
                        p.kind == AvatarKind.EYELID -> scaled(p, 1.10f, 1.22f)
                        p.kind in eyeKinds -> scaled(p, 1.06f, 1.14f)
                        p.kind == AvatarKind.BLUSH || p.kind == AvatarKind.PERM_BLUSH -> scaled(p, 1.18f, 1.18f)
                        else -> scaled(p, 1.04f, 1.04f)
                    }
                }
                "Cocky" -> base.points.map { p ->
                    when {
                        p.kind == AvatarKind.EYEBROW && p.left -> moved(p, 0f, -7f)
                        p.kind in mouthKinds && p.left -> moved(p, 0f, 2.5f)
                        else -> p
                    }
                }
                "Downcast" -> base.points.map { p ->
                    when {
                        p.kind in eyeKinds -> moved(p, 0f, 4.5f)
                        p.kind in mouthKinds -> moved(p, 0f, 2.0f)
                        else -> p
                    }
                }
                "Intense" -> base.points.map { p ->
                    when {
                        p.kind == AvatarKind.EYELID -> scaled(p, 0.84f, 0.80f)
                        p.kind == AvatarKind.EYEBROW -> moved(p, 0f, 3.0f)
                        p.kind in mouthKinds -> scaled(p, 0.92f, 0.92f)
                        else -> p
                    }
                }
                "Left Glance" -> base.points.map { p ->
                    if (p.kind in eyeKinds) moved(p, -11f, 0f) else p
                }
                "Right Glance" -> base.points.map { p ->
                    if (p.kind in eyeKinds) moved(p, 11f, 0f) else p
                }
                "Subtle" -> {
                    val groups = base.points.groupBy { it.kind }
                    val centroids = groups.mapValues { (_, list) ->
                        val avgX = list.map { it.x }.average().toFloat()
                        val avgY = list.map { it.y }.average().toFloat()
                        avgX to avgY
                    }
                    base.points.map { p ->
                        val (cx, cy) = centroids[p.kind] ?: (CX to CY)
                        p.copy(x = p.x + (cx - p.x) * 0.40f, y = p.y + (cy - p.y) * 0.40f)
                    }
                }
                "Unhinged" -> base.points.map { p ->
                    if (p.kind in eyeKinds || p.kind in mouthKinds) {
                        if (p.left) moved(p, -5f, -5f) else moved(p, 5f, 5f)
                    } else p
                }
                "Upward" -> base.points.map { p ->
                    if (p.kind in eyeKinds) moved(p, 0f, -6f) else p
                }
                else -> base.points
            }
            return base.copy(name = "${base.baseName} - $modifier", points = transformed)
        }

        /** Non-mutating mouth openness modulation for Live Mode speech sync. */
        fun talkingExpression(base: AvatarExpression, openness: Float): AvatarExpression {
            val clamped = openness.coerceIn(0f, 1f)
            if (clamped < 0.01f) return base
            val pts = base.points.map { p ->
                when {
                    p.kind == AvatarKind.STEM && !p.left -> p.copy(y = p.y + 11f * clamped)
                    p.kind == AvatarKind.BOTTOM_BAR -> p.copy(y = p.y + 9f * clamped)
                    p.kind == AvatarKind.MID_BAR -> p.copy(y = p.y + 5f * clamped)
                    else -> p
                }
            }
            return base.copy(points = pts)
        }
    }
}
