package com.henny.cellium.shizuku

import android.content.Context
import android.os.Process
import java.util.concurrent.TimeUnit
import kotlin.system.exitProcess

/**
 * Privileged Shizuku UserService executing inside Shizuku's UID (2000 ADB shell or 0 Root).
 * Bound dynamically via Shizuku.bindUserService for Agent Mode shell tools and RAM anti-kill guard.
 */
class ShizukuShellService : IShizukuShellService.Stub {

    constructor() : super()

    @Suppress("unused")
    constructor(@Suppress("UNUSED_PARAMETER") context: Context) : super()

    override fun execCommand(command: String, timeoutSec: Int): String {
        val safeTimeout = timeoutSec.coerceIn(2, 60).toLong()
        return try {
            val pb = ProcessBuilder("sh", "-c", command)
            pb.redirectErrorStream(true)
            val proc = pb.start()
            val finished = proc.waitFor(safeTimeout, TimeUnit.SECONDS)
            if (!finished) {
                proc.destroyForcibly()
                return "[TIMEOUT after ${safeTimeout}s]"
            }
            val output = proc.inputStream.bufferedReader().use { it.readText() }
            val exitCode = proc.exitValue()
            if (exitCode == 0) {
                output.take(16_000).ifBlank { "(exit 0 — no output)" }
            } else {
                "[exit $exitCode]\n${output.take(16_000)}".trim()
            }
        } catch (e: Exception) {
            "[Shizuku exec error] ${e.localizedMessage ?: e.javaClass.simpleName}"
        }
    }

    override fun getServerUid(): Int = Process.myUid()

    override fun destroy() {
        exitProcess(0)
    }
}
