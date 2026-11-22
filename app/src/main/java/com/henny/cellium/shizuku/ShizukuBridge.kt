package com.henny.cellium.shizuku

import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.IBinder
import android.os.Process
import com.henny.cellium.core.DevLogBuffer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import rikka.shizuku.Shizuku

enum class ShizukuStatus {
    NOT_RUNNING,
    PERMISSION_REQUIRED,
    BINDING,
    CONNECTED_SHELL,
    CONNECTED_ROOT,
}

class ShizukuBridge(private val context: Context) {
    private val appContext = context.applicationContext

    private val _status = MutableStateFlow(ShizukuStatus.NOT_RUNNING)
    val status: StateFlow<ShizukuStatus> = _status.asStateFlow()

    private val _antiKillApplied = MutableStateFlow(false)
    val antiKillApplied: StateFlow<Boolean> = _antiKillApplied.asStateFlow()

    private val _lastReport = MutableStateFlow("Shizuku standby")
    val lastReport: StateFlow<String> = _lastReport.asStateFlow()

    @Volatile
    private var shellService: IShizukuShellService? = null

    private val userServiceArgs by lazy {
        val isDebug = (appContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        Shizuku.UserServiceArgs(ComponentName(appContext, ShizukuShellService::class.java))
            .daemon(false)
            .processNameSuffix("cel_shizuku")
            .tag("cel_cellium_shell_v1")
            .debuggable(isDebug)
            .version(1)
    }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val stub = IShizukuShellService.Stub.asInterface(service)
            shellService = stub
            val uid = runCatching { stub.serverUid }.getOrDefault(2000)
            _status.value = if (uid == 0) ShizukuStatus.CONNECTED_ROOT else ShizukuStatus.CONNECTED_SHELL
            _lastReport.value = if (uid == 0) "Connected (Root UID 0)" else "Connected (ADB Shell UID $uid)"
            DevLogBuffer.add("INFO", "Shizuku", "UserService bound: ${_lastReport.value}")
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            shellService = null
            _antiKillApplied.value = false
            refreshStatus()
            DevLogBuffer.add("WARN", "Shizuku", "UserService disconnected.")
        }
    }

    private val binderReceivedListener = Shizuku.OnBinderReceivedListener {
        refreshStatus()
        if (hasPermission()) bindService()
    }

    private val binderDeadListener = Shizuku.OnBinderDeadListener {
        shellService = null
        _antiKillApplied.value = false
        _status.value = ShizukuStatus.NOT_RUNNING
        _lastReport.value = "Shizuku binder disconnected"
    }

    private val permissionResultListener = Shizuku.OnRequestPermissionResultListener { requestCode, grantResult ->
        if (requestCode == REQ_CODE_SHIZUKU) {
            if (grantResult == PackageManager.PERMISSION_GRANTED) {
                DevLogBuffer.add("INFO", "Shizuku", "Permission granted by user.")
                bindService()
            } else {
                _status.value = ShizukuStatus.PERMISSION_REQUIRED
                _lastReport.value = "Shizuku permission denied"
            }
        }
    }

    fun registerListeners() {
        runCatching {
            Shizuku.addBinderReceivedListenerSticky(binderReceivedListener)
            Shizuku.addBinderDeadListener(binderDeadListener)
            Shizuku.addRequestPermissionResultListener(permissionResultListener)
        }
        refreshStatus()
        if (isBinderAlive() && hasPermission() && shellService == null) {
            bindService()
        }
    }

    fun unregisterListeners() {
        runCatching {
            Shizuku.removeBinderReceivedListener(binderReceivedListener)
            Shizuku.removeBinderDeadListener(binderDeadListener)
            Shizuku.removeRequestPermissionResultListener(permissionResultListener)
        }
    }

    fun isBinderAlive(): Boolean = runCatching { Shizuku.pingBinder() }.getOrDefault(false)

    fun hasPermission(): Boolean = runCatching {
        if (!isBinderAlive()) return false
        if (Shizuku.isPreV11()) return false
        Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    fun refreshStatus() {
        if (!isBinderAlive()) {
            _status.value = ShizukuStatus.NOT_RUNNING
            _lastReport.value = "Shizuku app not running"
            return
        }
        if (!hasPermission()) {
            _status.value = ShizukuStatus.PERMISSION_REQUIRED
            _lastReport.value = "Tap to grant Shizuku access"
            return
        }
        if (shellService != null) {
            val uid = runCatching { shellService?.serverUid ?: 2000 }.getOrDefault(2000)
            _status.value = if (uid == 0) ShizukuStatus.CONNECTED_ROOT else ShizukuStatus.CONNECTED_SHELL
        } else {
            _status.value = ShizukuStatus.BINDING
            bindService()
        }
    }

    fun requestPermission() {
        if (!isBinderAlive()) {
            _status.value = ShizukuStatus.NOT_RUNNING
            _lastReport.value = "Start Shizuku service first"
            return
        }
        if (hasPermission()) {
            bindService()
            return
        }
        runCatching {
            Shizuku.requestPermission(REQ_CODE_SHIZUKU)
        }.onFailure { err ->
            _lastReport.value = err.localizedMessage ?: "Could not request Shizuku permission"
            DevLogBuffer.add("ERROR", "Shizuku", _lastReport.value)
        }
    }

    fun bindService() {
        if (!isBinderAlive() || !hasPermission()) {
            refreshStatus()
            return
        }
        if (shellService != null) return
        _status.value = ShizukuStatus.BINDING
        runCatching {
            Shizuku.bindUserService(userServiceArgs, connection)
        }.onFailure { err ->
            _lastReport.value = "Bind failed: ${err.localizedMessage}"
            DevLogBuffer.add("ERROR", "Shizuku", _lastReport.value)
        }
    }

    suspend fun runCommand(command: String, timeoutSec: Int = 20): Result<String> = withContext(Dispatchers.IO) {
        val svc = shellService
        if (svc == null) {
            if (isBinderAlive() && hasPermission()) {
                bindService()
            }
            return@withContext Result.failure(
                IllegalStateException("Shizuku UserService is not connected. Open Settings → Shizuku to authorize.")
            )
        }
        runCatching {
            DevLogBuffer.add("INFO", "ShizukuShell", "$ $command")
            val out = svc.execCommand(command, timeoutSec)
            out
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "ShizukuShell", err.localizedMessage ?: "Command failed")
        }
    }

    /**
     * Instructs Android (via Shizuku privileged shell) to keep Cel.Cellium alive under heavy
     * on-device LLM memory load (>1.5GB RAM): Doze whitelist, background ops, active standby bucket,
     * phantom process killer disable, and best-effort oom_score_adj adjustment.
     */
    suspend fun applyAntiKillProtection(reason: String = ">1.5GB RAM guard"): Result<String> {
        val pkg = appContext.packageName
        val pid = Process.myPid()
        val script = buildString {
            append("cmd deviceidle whitelist +$pkg 2>&1; ")
            append("cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow 2>&1; ")
            append("cmd appops set $pkg RUN_IN_BACKGROUND allow 2>&1; ")
            append("cmd activity set-standby-bucket $pkg active 2>&1; ")
            append("device_config set_sync_disabled_for_tests persistent 2>/dev/null; ")
            append("device_config put activity_manager max_phantom_processes 2147483647 2>/dev/null; ")
            append("if [ -w /proc/$pid/oom_score_adj ]; then echo -900 > /proc/$pid/oom_score_adj && echo 'oom_score_adj=-900'; else echo 'oom_score_adj=shell_protected'; fi")
        }
        val res = runCommand(script, timeoutSec = 12)
        res.onSuccess { out ->
            _antiKillApplied.value = true
            _lastReport.value = "Anti-Kill Active ($reason)"
            DevLogBuffer.add("INFO", "RAMGuard", "Shizuku keep-alive applied [$reason]: ${out.take(180)}")
        }.onFailure { err ->
            DevLogBuffer.add("WARN", "RAMGuard", "Shizuku keep-alive unavailable: ${err.localizedMessage}")
        }
        return res
    }

    fun release() {
        unregisterListeners()
        runCatching {
            if (shellService != null) {
                Shizuku.unbindUserService(userServiceArgs, connection, true)
            }
        }
        shellService = null
    }

    companion object {
        private const val REQ_CODE_SHIZUKU = 9401
    }
}
