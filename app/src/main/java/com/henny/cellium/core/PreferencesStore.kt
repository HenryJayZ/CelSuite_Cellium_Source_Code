package com.henny.cellium.core

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

private val Context.celliumDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "cellium_prefs_v2"
)

@Serializable
data class RegisteredLocalModel(
    val uriOrPath: String,
    val displayName: String,
    val sizeBytes: Long = 0L,
    val isContentUri: Boolean = false,
)

@Serializable
data class StarredModelEntry(
    val providerId: String,
    val providerName: String,
    val modelName: String,
)

data class ContextModifyConfig(
    val includePersona: Boolean = true,
    val includeMemories: Boolean = true,
    val includeIllumeInstructions: Boolean = true,
    val includeAgentInstructions: Boolean = true,
    val includeMoodInstructions: Boolean = true,
    val historyLimit: Int = 12,
    val ggufContextLength: Int = 1024,
    val ggufMaxTokens: Int = 512,
    val ggufTemperature: Float = 0.7f,
    val ggufTopP: Float = 0.90f,
    val ggufTopK: Int = 40,
    val ggufRepeatPenalty: Float = 1.12f,
    val ggufThreads: Int = 4,
    val ggufUseMmap: Boolean = true,
    val ggufFlashAttention: Boolean = false,
    val ggufGpuLayers: Int = 0,
)

data class CelliumPreferences(
    // Onboarding & Profile
    val termsAccepted: Boolean = false,
    val guestMode: Boolean = true,
    val onboardingCompleted: Boolean = false,
    val personasSeeded: Boolean = false,

    // Defaults (Pollinations keyless free provider by default so instant testing works)
    val avatarGender: String = "Female",
    val defaultPersonaId: String = "default",
    val activeProviderId: String = "preset_pollinations_free",

    // Theme & Liquid Glass Visuals
    val themePresetId: String = "neon_violet",
    val customPrimaryHex: String = "#A855F7",
    val customWallpaperUri: String = "",
    val wallpaperDim: Float = 0.50f,
    val glassOpacity: Float = 0.84f,
    val borderGlow: Float = 0.62f,
    val particlesEnabled: Boolean = true,
    val particleDensity: Int = 18,
    val highFpsMode: Boolean = true,
    val fontScale: Float = 1.0f,
    val floatingMiniCel: Boolean = false,
    val codeWordWrap: Boolean = true,

    // Shizuku, Agent & Tools
    val shizukuAutoGuard: Boolean = true,
    val ramGuardThresholdMb: Int = 1536,
    val agentModeEnabled: Boolean = false,
    val agentAutoApproveSafe: Boolean = false,
    val agentWorkspacePath: String = "/sdcard/Documents/CelliumProjects",
    val agentWorkspacePrompted: Boolean = false,
    val webSearchAutoEnabled: Boolean = false,
    val notificationsEnabled: Boolean = true,

    // Mood Engine, Retry & Providers UX
    val moodMethod: String = "inline_tag", // "inline_tag" (Method 1 default) or "background_ai" (Method 2)
    val maxAutoRetries: Int = 10,
    val hiddenProviderIds: Set<String> = emptySet(),
    val starredModelsJson: String = "[]",

    // Voice, TTS, SFX, Haptics & Wake Word
    val soundsEnabled: Boolean = true,
    val animaleseEnabled: Boolean = true,
    val typingSoundStyle: String = "animal_crossing", // "animal_crossing" or "scratchin_melodii"
    val hapticsEnabled: Boolean = true,
    val sfxVolume: Float = 0.80f,
    val ttsVoiceName: String = "",
    val ttsPitch: Float = 1.06f,
    val ttsSpeechRate: Float = 1.04f,
    val autoReadReplies: Boolean = false,
    val liveHandsFreeLoop: Boolean = true,
    val wakeWordEnabled: Boolean = false,
    val wakeWordCustomPath: String = "",
    val wakeWordSensitivity: Float = 0.55f,

    // Multi-Provider Illume Image Studio + Kaggle GPU Notebook (.json)
    val imagineProvider: String = "pollinations",
    val imagineModel: String = "sana",
    val imagineApiKey: String = "",
    val imagineCustomUrl: String = "",
    val kaggleUsername: String = "",
    val kaggleKey: String = "",
    val kaggleKernelSlug: String = "cellium-gpu-imagine",
    val kaggleModelId: String = "stabilityai/sdxl-turbo",

    // On-Device Local Model Path & Zero-Copy Mounted Registry
    val localModelPath: String = "",
    val localModelName: String = "",
    val localMaxTokens: Int = 512,
    val localUseGpu: Boolean = true,
    val registeredLocalModelsJson: String = "[]",

    // Context & GGUF Modify Menu
    val contextModify: ContextModifyConfig = ContextModifyConfig(),
)

class PreferencesStore(context: Context) {
    private val appContext = context.applicationContext
    private val dataStore = appContext.celliumDataStore
    private val bootCache = appContext.getSharedPreferences("cellium_boot_cache", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true }

    fun readCachedInitialPreferences(): CelliumPreferences = CelliumPreferences(
        termsAccepted = bootCache.getBoolean("terms_accepted", false),
        guestMode = bootCache.getBoolean("guest_mode", true),
        onboardingCompleted = bootCache.getBoolean("onboarding_completed", false),
        activeProviderId = bootCache.getString("active_provider_id", "preset_pollinations_free") ?: "preset_pollinations_free",
        themePresetId = bootCache.getString("theme_preset", "neon_violet") ?: "neon_violet",
    )

    private object Keys {
        val TERMS_ACCEPTED = booleanPreferencesKey("terms_accepted")
        val GUEST_MODE = booleanPreferencesKey("guest_mode")
        val ONBOARDING_COMPLETED = booleanPreferencesKey("onboarding_completed")
        val PERSONAS_SEEDED = booleanPreferencesKey("personas_seeded")
        val AVATAR_GENDER = stringPreferencesKey("avatar_gender")
        val DEFAULT_PERSONA = stringPreferencesKey("default_persona")
        val ACTIVE_PROVIDER_ID = stringPreferencesKey("active_provider_id")
        val THEME_PRESET = stringPreferencesKey("theme_preset")
        val CUSTOM_PRIMARY_HEX = stringPreferencesKey("custom_primary_hex")
        val CUSTOM_WALLPAPER_URI = stringPreferencesKey("custom_wallpaper_uri")
        val WALLPAPER_DIM = floatPreferencesKey("wallpaper_dim")
        val GLASS_OPACITY = floatPreferencesKey("glass_opacity")
        val BORDER_GLOW = floatPreferencesKey("border_glow")
        val PARTICLES_ENABLED = booleanPreferencesKey("particles_enabled")
        val PARTICLE_DENSITY = intPreferencesKey("particle_density")
        val HIGH_FPS = booleanPreferencesKey("high_fps")
        val FONT_SCALE = floatPreferencesKey("font_scale")
        val FLOATING_MINI_CEL = booleanPreferencesKey("floating_mini_cel")
        val CODE_WORD_WRAP = booleanPreferencesKey("code_word_wrap")
        val SHIZUKU_AUTO_GUARD = booleanPreferencesKey("shizuku_auto_guard")
        val RAM_GUARD_THRESHOLD_MB = intPreferencesKey("ram_guard_threshold_mb")
        val AGENT_MODE = booleanPreferencesKey("agent_mode")
        val AGENT_AUTO_APPROVE_SAFE = booleanPreferencesKey("agent_auto_approve_safe")
        val AGENT_WORKSPACE_PATH = stringPreferencesKey("agent_workspace_path")
        val AGENT_WORKSPACE_PROMPTED = booleanPreferencesKey("agent_workspace_prompted")
        val WEB_SEARCH_AUTO = booleanPreferencesKey("web_search_auto")
        val NOTIFICATIONS_ENABLED = booleanPreferencesKey("notifications_enabled")
        val MOOD_METHOD = stringPreferencesKey("mood_method")
        val MAX_AUTO_RETRIES = intPreferencesKey("max_auto_retries")
        val HIDDEN_PROVIDER_IDS = stringSetPreferencesKey("hidden_provider_ids")
        val STARRED_MODELS_JSON = stringPreferencesKey("starred_models_json")
        val SOUNDS_ENABLED = booleanPreferencesKey("sounds_enabled")
        val ANIMALESE_ENABLED = booleanPreferencesKey("animalese_enabled")
        val TYPING_SOUND_STYLE = stringPreferencesKey("typing_sound_style")
        val HAPTICS_ENABLED = booleanPreferencesKey("haptics_enabled")
        val SFX_VOLUME = floatPreferencesKey("sfx_volume")
        val TTS_VOICE = stringPreferencesKey("tts_voice")
        val TTS_PITCH = floatPreferencesKey("tts_pitch")
        val TTS_RATE = floatPreferencesKey("tts_rate")
        val AUTO_READ = booleanPreferencesKey("auto_read")
        val LIVE_HANDS_FREE = booleanPreferencesKey("live_hands_free")
        val WAKE_WORD_ENABLED = booleanPreferencesKey("wake_word_enabled")
        val WAKE_WORD_CUSTOM_PATH = stringPreferencesKey("wake_word_custom_path")
        val WAKE_WORD_SENSITIVITY = floatPreferencesKey("wake_word_sensitivity")
        val IMAGINE_PROVIDER = stringPreferencesKey("imagine_provider")
        val IMAGINE_MODEL = stringPreferencesKey("imagine_model")
        val IMAGINE_API_KEY = stringPreferencesKey("imagine_api_key")
        val IMAGINE_CUSTOM_URL = stringPreferencesKey("imagine_custom_url")
        val KAGGLE_USERNAME = stringPreferencesKey("kaggle_username")
        val KAGGLE_KEY = stringPreferencesKey("kaggle_key")
        val KAGGLE_SLUG = stringPreferencesKey("kaggle_slug")
        val KAGGLE_MODEL = stringPreferencesKey("kaggle_model")
        val LOCAL_MODEL_PATH = stringPreferencesKey("local_model_path")
        val LOCAL_MODEL_NAME = stringPreferencesKey("local_model_name")
        val LOCAL_MAX_TOKENS = intPreferencesKey("local_max_tokens")
        val LOCAL_USE_GPU = booleanPreferencesKey("local_use_gpu")
        val REGISTERED_LOCAL_MODELS = stringPreferencesKey("registered_local_models_json")

        // Context Modify & GGUF Params
        val CTX_PERSONA = booleanPreferencesKey("ctx_persona")
        val CTX_MEMORIES = booleanPreferencesKey("ctx_memories")
        val CTX_ILLUME = booleanPreferencesKey("ctx_illume")
        val CTX_AGENT = booleanPreferencesKey("ctx_agent")
        val CTX_MOOD = booleanPreferencesKey("ctx_mood")
        val CTX_HISTORY_LIMIT = intPreferencesKey("ctx_history_limit")
        val GGUF_CTX_LEN = intPreferencesKey("gguf_ctx_len")
        val GGUF_MAX_TOKENS = intPreferencesKey("gguf_max_tokens")
        val GGUF_TEMP = floatPreferencesKey("gguf_temp")
        val GGUF_TOP_P = floatPreferencesKey("gguf_top_p")
        val GGUF_TOP_K = intPreferencesKey("gguf_top_k")
        val GGUF_REPEAT_PENALTY = floatPreferencesKey("gguf_repeat_penalty")
        val GGUF_THREADS = intPreferencesKey("gguf_threads")
        val GGUF_USE_MMAP = booleanPreferencesKey("gguf_use_mmap")
        val GGUF_FLASH_ATTN = booleanPreferencesKey("gguf_flash_attn")
        val GGUF_GPU_LAYERS = intPreferencesKey("gguf_gpu_layers")
    }

    val preferencesFlow: Flow<CelliumPreferences> = dataStore.data.map { p ->
        val rawImagineModel = p[Keys.IMAGINE_MODEL]
        val safeImagineModel = if (rawImagineModel.isNullOrBlank() || (rawImagineModel == "flux" && (p[Keys.IMAGINE_PROVIDER] ?: "pollinations") == "pollinations" && p[Keys.IMAGINE_API_KEY].isNullOrBlank())) {
            "sana"
        } else {
            rawImagineModel
        }
        CelliumPreferences(
            termsAccepted = p[Keys.TERMS_ACCEPTED] ?: false,
            guestMode = p[Keys.GUEST_MODE] ?: true,
            onboardingCompleted = p[Keys.ONBOARDING_COMPLETED] ?: false,
            personasSeeded = p[Keys.PERSONAS_SEEDED] ?: false,
            avatarGender = p[Keys.AVATAR_GENDER] ?: "Female",
            defaultPersonaId = p[Keys.DEFAULT_PERSONA] ?: "default",
            activeProviderId = p[Keys.ACTIVE_PROVIDER_ID] ?: "preset_pollinations_free",
            themePresetId = p[Keys.THEME_PRESET] ?: "neon_violet",
            customPrimaryHex = p[Keys.CUSTOM_PRIMARY_HEX] ?: "#A855F7",
            customWallpaperUri = p[Keys.CUSTOM_WALLPAPER_URI] ?: "",
            wallpaperDim = p[Keys.WALLPAPER_DIM] ?: 0.50f,
            glassOpacity = p[Keys.GLASS_OPACITY] ?: 0.84f,
            borderGlow = p[Keys.BORDER_GLOW] ?: 0.62f,
            particlesEnabled = p[Keys.PARTICLES_ENABLED] ?: true,
            particleDensity = p[Keys.PARTICLE_DENSITY] ?: 18,
            highFpsMode = p[Keys.HIGH_FPS] ?: true,
            fontScale = p[Keys.FONT_SCALE] ?: 1.0f,
            floatingMiniCel = p[Keys.FLOATING_MINI_CEL] ?: false,
            codeWordWrap = p[Keys.CODE_WORD_WRAP] ?: true,
            shizukuAutoGuard = p[Keys.SHIZUKU_AUTO_GUARD] ?: true,
            ramGuardThresholdMb = p[Keys.RAM_GUARD_THRESHOLD_MB] ?: 1536,
            agentModeEnabled = p[Keys.AGENT_MODE] ?: false,
            agentAutoApproveSafe = p[Keys.AGENT_AUTO_APPROVE_SAFE] ?: false,
            agentWorkspacePath = p[Keys.AGENT_WORKSPACE_PATH] ?: "/sdcard/Documents/CelliumProjects",
            agentWorkspacePrompted = p[Keys.AGENT_WORKSPACE_PROMPTED] ?: false,
            webSearchAutoEnabled = p[Keys.WEB_SEARCH_AUTO] ?: false,
            notificationsEnabled = p[Keys.NOTIFICATIONS_ENABLED] ?: true,
            moodMethod = p[Keys.MOOD_METHOD] ?: "inline_tag",
            maxAutoRetries = (p[Keys.MAX_AUTO_RETRIES] ?: 10).coerceIn(0, 15),
            hiddenProviderIds = p[Keys.HIDDEN_PROVIDER_IDS] ?: emptySet(),
            starredModelsJson = p[Keys.STARRED_MODELS_JSON] ?: "[]",
            soundsEnabled = p[Keys.SOUNDS_ENABLED] ?: true,
            animaleseEnabled = p[Keys.ANIMALESE_ENABLED] ?: true,
            typingSoundStyle = p[Keys.TYPING_SOUND_STYLE] ?: "animal_crossing",
            hapticsEnabled = p[Keys.HAPTICS_ENABLED] ?: true,
            sfxVolume = p[Keys.SFX_VOLUME] ?: 0.80f,
            ttsVoiceName = p[Keys.TTS_VOICE] ?: "",
            ttsPitch = p[Keys.TTS_PITCH] ?: 1.06f,
            ttsSpeechRate = p[Keys.TTS_RATE] ?: 1.04f,
            autoReadReplies = p[Keys.AUTO_READ] ?: false,
            liveHandsFreeLoop = p[Keys.LIVE_HANDS_FREE] ?: true,
            wakeWordEnabled = p[Keys.WAKE_WORD_ENABLED] ?: false,
            wakeWordCustomPath = p[Keys.WAKE_WORD_CUSTOM_PATH] ?: "",
            wakeWordSensitivity = p[Keys.WAKE_WORD_SENSITIVITY] ?: 0.55f,
            imagineProvider = p[Keys.IMAGINE_PROVIDER] ?: "pollinations",
            imagineModel = safeImagineModel,
            imagineApiKey = p[Keys.IMAGINE_API_KEY] ?: "",
            imagineCustomUrl = p[Keys.IMAGINE_CUSTOM_URL] ?: "",
            kaggleUsername = p[Keys.KAGGLE_USERNAME] ?: "",
            kaggleKey = p[Keys.KAGGLE_KEY] ?: "",
            kaggleKernelSlug = p[Keys.KAGGLE_SLUG] ?: "cellium-gpu-imagine",
            kaggleModelId = p[Keys.KAGGLE_MODEL] ?: "stabilityai/sdxl-turbo",
            localModelPath = p[Keys.LOCAL_MODEL_PATH] ?: "",
            localModelName = p[Keys.LOCAL_MODEL_NAME] ?: "",
            localMaxTokens = p[Keys.LOCAL_MAX_TOKENS] ?: 512,
            localUseGpu = p[Keys.LOCAL_USE_GPU] ?: true,
            registeredLocalModelsJson = p[Keys.REGISTERED_LOCAL_MODELS] ?: "[]",
            contextModify = ContextModifyConfig(
                includePersona = p[Keys.CTX_PERSONA] ?: true,
                includeMemories = p[Keys.CTX_MEMORIES] ?: true,
                includeIllumeInstructions = p[Keys.CTX_ILLUME] ?: true,
                includeAgentInstructions = p[Keys.CTX_AGENT] ?: true,
                includeMoodInstructions = p[Keys.CTX_MOOD] ?: true,
                historyLimit = (p[Keys.CTX_HISTORY_LIMIT] ?: 12).coerceIn(2, 48),
                ggufContextLength = (p[Keys.GGUF_CTX_LEN] ?: 1024).coerceIn(256, 8192),
                ggufMaxTokens = (p[Keys.GGUF_MAX_TOKENS] ?: 512).coerceIn(64, 4096),
                ggufTemperature = (p[Keys.GGUF_TEMP] ?: 0.7f).coerceIn(0f, 2f),
                ggufTopP = (p[Keys.GGUF_TOP_P] ?: 0.90f).coerceIn(0.1f, 1f),
                ggufTopK = (p[Keys.GGUF_TOP_K] ?: 40).coerceIn(1, 128),
                ggufRepeatPenalty = (p[Keys.GGUF_REPEAT_PENALTY] ?: 1.12f).coerceIn(1.0f, 1.5f),
                ggufThreads = (p[Keys.GGUF_THREADS] ?: 4).coerceIn(1, 8),
                ggufUseMmap = p[Keys.GGUF_USE_MMAP] ?: true,
                ggufFlashAttention = p[Keys.GGUF_FLASH_ATTN] ?: false,
                ggufGpuLayers = (p[Keys.GGUF_GPU_LAYERS] ?: 0).coerceIn(0, 32),
            ),
        )
    }

    fun decodeStarredModels(raw: String): List<StarredModelEntry> =
        runCatching { json.decodeFromString<List<StarredModelEntry>>(raw) }.getOrDefault(emptyList())

    fun encodeStarredModels(list: List<StarredModelEntry>): String =
        runCatching { json.encodeToString(list) }.getOrDefault("[]")

    fun decodeRegisteredLocalModels(raw: String): List<RegisteredLocalModel> =
        runCatching { json.decodeFromString<List<RegisteredLocalModel>>(raw) }.getOrDefault(emptyList())

    fun encodeRegisteredLocalModels(list: List<RegisteredLocalModel>): String =
        runCatching { json.encodeToString(list) }.getOrDefault("[]")

    suspend fun acceptTerms() {
        bootCache.edit().putBoolean("terms_accepted", true).apply()
        dataStore.edit { it[Keys.TERMS_ACCEPTED] = true }
    }
    suspend fun setGuestMode(guest: Boolean) {
        bootCache.edit().putBoolean("guest_mode", guest).apply()
        dataStore.edit { it[Keys.GUEST_MODE] = guest }
    }
    suspend fun completeOnboarding() {
        bootCache.edit()
            .putBoolean("terms_accepted", true)
            .putBoolean("onboarding_completed", true)
            .apply()
        dataStore.edit {
            it[Keys.TERMS_ACCEPTED] = true
            it[Keys.ONBOARDING_COMPLETED] = true
        }
    }
    suspend fun markPersonasSeeded() { dataStore.edit { it[Keys.PERSONAS_SEEDED] = true } }
    suspend fun updateAvatarGender(gender: String) { dataStore.edit { it[Keys.AVATAR_GENDER] = gender } }
    suspend fun updateDefaultPersona(id: String) { dataStore.edit { it[Keys.DEFAULT_PERSONA] = id } }
    suspend fun updateActiveProviderId(id: String) {
        bootCache.edit().putString("active_provider_id", id).apply()
        dataStore.edit { it[Keys.ACTIVE_PROVIDER_ID] = id }
    }
    suspend fun updateThemePreset(id: String) {
        bootCache.edit().putString("theme_preset", id).apply()
        dataStore.edit { it[Keys.THEME_PRESET] = id }
    }
    suspend fun updateCustomPrimaryHex(hex: String) { dataStore.edit { it[Keys.CUSTOM_PRIMARY_HEX] = hex } }
    suspend fun updateCustomWallpaperUri(uri: String) { dataStore.edit { it[Keys.CUSTOM_WALLPAPER_URI] = uri } }
    suspend fun updateGlassVisuals(dim: Float, opacity: Float, glow: Float, density: Int, fontScale: Float) {
        dataStore.edit {
            it[Keys.WALLPAPER_DIM] = dim.coerceIn(0.15f, 0.88f)
            it[Keys.GLASS_OPACITY] = opacity.coerceIn(0.35f, 0.96f)
            it[Keys.BORDER_GLOW] = glow.coerceIn(0.15f, 1.0f)
            it[Keys.PARTICLE_DENSITY] = density.coerceIn(0, 48)
            it[Keys.FONT_SCALE] = fontScale.coerceIn(0.85f, 1.30f)
        }
    }
    suspend fun updateParticlesEnabled(enabled: Boolean) { dataStore.edit { it[Keys.PARTICLES_ENABLED] = enabled } }
    suspend fun updateHighFpsMode(enabled: Boolean) { dataStore.edit { it[Keys.HIGH_FPS] = enabled } }
    suspend fun updateFloatingMiniCel(enabled: Boolean) { dataStore.edit { it[Keys.FLOATING_MINI_CEL] = enabled } }
    suspend fun updateCodeWordWrap(enabled: Boolean) { dataStore.edit { it[Keys.CODE_WORD_WRAP] = enabled } }
    suspend fun updateMoodMethod(method: String) { dataStore.edit { it[Keys.MOOD_METHOD] = method } }
    suspend fun updateMaxAutoRetries(count: Int) { dataStore.edit { it[Keys.MAX_AUTO_RETRIES] = count.coerceIn(0, 15) } }
    suspend fun updateHiddenProviderIds(ids: Set<String>) { dataStore.edit { it[Keys.HIDDEN_PROVIDER_IDS] = ids } }
    suspend fun updateStarredModelsJson(rawJson: String) { dataStore.edit { it[Keys.STARRED_MODELS_JSON] = rawJson } }
    suspend fun updateRegisteredLocalModelsJson(rawJson: String) { dataStore.edit { it[Keys.REGISTERED_LOCAL_MODELS] = rawJson } }
    suspend fun updateAgentWorkspace(path: String, prompted: Boolean = true) {
        dataStore.edit {
            it[Keys.AGENT_WORKSPACE_PATH] = path.trim().ifBlank { "/sdcard/Documents/CelliumProjects" }
            it[Keys.AGENT_WORKSPACE_PROMPTED] = prompted
        }
    }
    suspend fun updateContextModify(cfg: ContextModifyConfig) {
        dataStore.edit {
            it[Keys.CTX_PERSONA] = cfg.includePersona
            it[Keys.CTX_MEMORIES] = cfg.includeMemories
            it[Keys.CTX_ILLUME] = cfg.includeIllumeInstructions
            it[Keys.CTX_AGENT] = cfg.includeAgentInstructions
            it[Keys.CTX_MOOD] = cfg.includeMoodInstructions
            it[Keys.CTX_HISTORY_LIMIT] = cfg.historyLimit.coerceIn(2, 48)
            it[Keys.GGUF_CTX_LEN] = cfg.ggufContextLength.coerceIn(256, 8192)
            it[Keys.GGUF_MAX_TOKENS] = cfg.ggufMaxTokens.coerceIn(64, 4096)
            it[Keys.GGUF_TEMP] = cfg.ggufTemperature.coerceIn(0f, 2f)
            it[Keys.GGUF_TOP_P] = cfg.ggufTopP.coerceIn(0.1f, 1f)
            it[Keys.GGUF_TOP_K] = cfg.ggufTopK.coerceIn(1, 128)
            it[Keys.GGUF_REPEAT_PENALTY] = cfg.ggufRepeatPenalty.coerceIn(1.0f, 1.5f)
            it[Keys.GGUF_THREADS] = cfg.ggufThreads.coerceIn(1, 8)
            it[Keys.GGUF_USE_MMAP] = cfg.ggufUseMmap
            it[Keys.GGUF_FLASH_ATTN] = cfg.ggufFlashAttention
            it[Keys.GGUF_GPU_LAYERS] = cfg.ggufGpuLayers.coerceIn(0, 32)
        }
    }
    suspend fun updateShizukuSettings(autoGuard: Boolean, thresholdMb: Int, autoApproveSafe: Boolean) {
        dataStore.edit {
            it[Keys.SHIZUKU_AUTO_GUARD] = autoGuard
            it[Keys.RAM_GUARD_THRESHOLD_MB] = thresholdMb.coerceIn(512, 4096)
            it[Keys.AGENT_AUTO_APPROVE_SAFE] = autoApproveSafe
        }
    }
    suspend fun updateAgentMode(enabled: Boolean) { dataStore.edit { it[Keys.AGENT_MODE] = enabled } }
    suspend fun updateWebSearchAuto(enabled: Boolean) { dataStore.edit { it[Keys.WEB_SEARCH_AUTO] = enabled } }
    suspend fun updateNotificationsEnabled(enabled: Boolean) { dataStore.edit { it[Keys.NOTIFICATIONS_ENABLED] = enabled } }
    suspend fun updateAudioSettings(
        sounds: Boolean,
        animalese: Boolean,
        haptics: Boolean,
        volume: Float,
        typingStyle: String? = null,
    ) {
        dataStore.edit {
            it[Keys.SOUNDS_ENABLED] = sounds
            it[Keys.ANIMALESE_ENABLED] = animalese
            it[Keys.HAPTICS_ENABLED] = haptics
            it[Keys.SFX_VOLUME] = volume.coerceIn(0f, 1f)
            if (typingStyle != null) it[Keys.TYPING_SOUND_STYLE] = typingStyle
        }
    }
    suspend fun updateWakeWordSettings(enabled: Boolean, customPath: String? = null, sensitivity: Float? = null) {
        dataStore.edit {
            it[Keys.WAKE_WORD_ENABLED] = enabled
            if (customPath != null) it[Keys.WAKE_WORD_CUSTOM_PATH] = customPath
            if (sensitivity != null) it[Keys.WAKE_WORD_SENSITIVITY] = sensitivity.coerceIn(0.20f, 0.95f)
        }
    }
    suspend fun updateVoiceSettings(voice: String, pitch: Float, rate: Float, autoRead: Boolean, handsFree: Boolean) {
        dataStore.edit {
            it[Keys.TTS_VOICE] = voice
            it[Keys.TTS_PITCH] = pitch.coerceIn(0.65f, 1.55f)
            it[Keys.TTS_RATE] = rate.coerceIn(0.65f, 1.65f)
            it[Keys.AUTO_READ] = autoRead
            it[Keys.LIVE_HANDS_FREE] = handsFree
        }
    }
    suspend fun updateImagineConfig(provider: String, model: String, apiKey: String, customUrl: String) {
        dataStore.edit {
            it[Keys.IMAGINE_PROVIDER] = provider
            it[Keys.IMAGINE_MODEL] = model
            it[Keys.IMAGINE_API_KEY] = apiKey
            it[Keys.IMAGINE_CUSTOM_URL] = customUrl
        }
    }
    suspend fun updateKaggleConfig(username: String, key: String, slug: String, modelId: String) {
        dataStore.edit {
            it[Keys.KAGGLE_USERNAME] = username.trim()
            it[Keys.KAGGLE_KEY] = key.trim()
            it[Keys.KAGGLE_SLUG] = slug.trim().ifBlank { "cellium-gpu-imagine" }
            it[Keys.KAGGLE_MODEL] = modelId.trim().ifBlank { "stabilityai/sdxl-turbo" }
        }
    }
    suspend fun updateLocalModel(path: String, name: String, maxTokens: Int, useGpu: Boolean) {
        dataStore.edit {
            it[Keys.LOCAL_MODEL_PATH] = path
            it[Keys.LOCAL_MODEL_NAME] = name
            it[Keys.LOCAL_MAX_TOKENS] = maxTokens.coerceIn(256, 4096)
            it[Keys.LOCAL_USE_GPU] = useGpu
        }
    }

    suspend fun applyCloudSnapshot(
        activeProviderId: String?,
        defaultPersonaId: String?,
        themePresetId: String?,
        customPrimaryHex: String?,
        avatarGender: String?,
        imagineProvider: String?,
        imagineModel: String?,
        imagineApiKey: String?,
        imagineCustomUrl: String?,
        kaggleUsername: String?,
        kaggleKey: String?,
        kaggleKernelSlug: String?,
        kaggleModelId: String?,
        soundsEnabled: Boolean?,
        animaleseEnabled: Boolean?,
        hapticsEnabled: Boolean?,
        notificationsEnabled: Boolean?,
        starredModelsJson: String? = null,
        hiddenProviderIds: Set<String>? = null,
        moodMethod: String? = null,
        typingSoundStyle: String? = null,
        maxAutoRetries: Int? = null,
        codeWordWrap: Boolean? = null,
    ) {
        if (!activeProviderId.isNullOrBlank()) {
            bootCache.edit().putString("active_provider_id", activeProviderId).apply()
        }
        if (!themePresetId.isNullOrBlank()) {
            bootCache.edit().putString("theme_preset", themePresetId).apply()
        }
        dataStore.edit { p ->
            if (!activeProviderId.isNullOrBlank()) p[Keys.ACTIVE_PROVIDER_ID] = activeProviderId
            if (!defaultPersonaId.isNullOrBlank()) p[Keys.DEFAULT_PERSONA] = defaultPersonaId
            if (!themePresetId.isNullOrBlank()) p[Keys.THEME_PRESET] = themePresetId
            if (!customPrimaryHex.isNullOrBlank()) p[Keys.CUSTOM_PRIMARY_HEX] = customPrimaryHex
            if (!avatarGender.isNullOrBlank()) p[Keys.AVATAR_GENDER] = avatarGender
            if (!imagineProvider.isNullOrBlank()) p[Keys.IMAGINE_PROVIDER] = imagineProvider
            if (!imagineModel.isNullOrBlank()) p[Keys.IMAGINE_MODEL] = imagineModel
            if (!imagineApiKey.isNullOrBlank()) p[Keys.IMAGINE_API_KEY] = imagineApiKey
            if (!imagineCustomUrl.isNullOrBlank()) p[Keys.IMAGINE_CUSTOM_URL] = imagineCustomUrl
            if (!kaggleUsername.isNullOrBlank()) p[Keys.KAGGLE_USERNAME] = kaggleUsername
            if (!kaggleKey.isNullOrBlank()) p[Keys.KAGGLE_KEY] = kaggleKey
            if (!kaggleKernelSlug.isNullOrBlank()) p[Keys.KAGGLE_SLUG] = kaggleKernelSlug
            if (!kaggleModelId.isNullOrBlank()) p[Keys.KAGGLE_MODEL] = kaggleModelId
            if (soundsEnabled != null) p[Keys.SOUNDS_ENABLED] = soundsEnabled
            if (animaleseEnabled != null) p[Keys.ANIMALESE_ENABLED] = animaleseEnabled
            if (hapticsEnabled != null) p[Keys.HAPTICS_ENABLED] = hapticsEnabled
            if (notificationsEnabled != null) p[Keys.NOTIFICATIONS_ENABLED] = notificationsEnabled
            if (!starredModelsJson.isNullOrBlank()) p[Keys.STARRED_MODELS_JSON] = starredModelsJson
            if (hiddenProviderIds != null) p[Keys.HIDDEN_PROVIDER_IDS] = hiddenProviderIds
            if (!moodMethod.isNullOrBlank()) p[Keys.MOOD_METHOD] = moodMethod
            if (!typingSoundStyle.isNullOrBlank()) p[Keys.TYPING_SOUND_STYLE] = typingSoundStyle
            if (maxAutoRetries != null) p[Keys.MAX_AUTO_RETRIES] = maxAutoRetries.coerceIn(0, 15)
            if (codeWordWrap != null) p[Keys.CODE_WORD_WRAP] = codeWordWrap
        }
    }
}
