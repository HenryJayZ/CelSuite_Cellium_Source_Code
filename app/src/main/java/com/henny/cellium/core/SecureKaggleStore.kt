package com.henny.cellium.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class SecureKaggleSecrets(
    val username: String = "",
    val apiKey: String = "",
    val hfToken: String = "",
    val civitaiToken: String = "",
) {
    val hasCredentials: Boolean
        get() = username.isNotBlank() && apiKey.isNotBlank()
}

/**
 * Hardware-backed Android Keystore (AES-256-GCM) credential vault for Kaggle BYOK secrets
 * (kaggle username/key, optional HuggingFace token, optional Civitai token).
 * Never writes plaintext keys to logs or backup files.
 */
class SecureKaggleStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun getOrCreateMasterKey(): SecretKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        val existing = (ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey
        if (existing != null) return existing
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
            .apply { init(spec) }
            .generateKey()
    }

    private fun encrypt(plain: String): String {
        if (plain.isEmpty()) return ""
        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateMasterKey())
            val iv = cipher.iv
            val enc = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
            val combined = ByteArray(1 + iv.size + enc.size)
            combined[0] = iv.size.toByte()
            System.arraycopy(iv, 0, combined, 1, iv.size)
            System.arraycopy(enc, 0, combined, 1 + iv.size, enc.size)
            Base64.encodeToString(combined, Base64.NO_WRAP)
        }.getOrDefault("")
    }

    private fun decrypt(encoded: String?): String {
        if (encoded.isNullOrBlank()) return ""
        return runCatching {
            val combined = Base64.decode(encoded, Base64.NO_WRAP)
            if (combined.size < 14) return@runCatching ""
            val ivLen = combined[0].toInt() and 0xFF
            if (ivLen < 12 || combined.size <= 1 + ivLen) return@runCatching ""
            val iv = combined.copyOfRange(1, 1 + ivLen)
            val ct = combined.copyOfRange(1 + ivLen, combined.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateMasterKey(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(ct), Charsets.UTF_8)
        }.getOrDefault("")
    }

    fun save(secrets: SecureKaggleSecrets) {
        prefs.edit()
            .putString(K_USER, encrypt(secrets.username.trim()))
            .putString(K_API_KEY, encrypt(secrets.apiKey.trim()))
            .putString(K_HF_TOKEN, encrypt(secrets.hfToken.trim()))
            .putString(K_CIVITAI_TOKEN, encrypt(secrets.civitaiToken.trim()))
            .apply()
    }

    fun load(fallbackUser: String = "", fallbackKey: String = ""): SecureKaggleSecrets {
        val user = decrypt(prefs.getString(K_USER, null)).ifBlank { fallbackUser.trim() }
        val key = decrypt(prefs.getString(K_API_KEY, null)).ifBlank { fallbackKey.trim() }
        val hf = decrypt(prefs.getString(K_HF_TOKEN, null))
        val civ = decrypt(prefs.getString(K_CIVITAI_TOKEN, null))
        return SecureKaggleSecrets(
            username = user,
            apiKey = key,
            hfToken = hf,
            civitaiToken = civ,
        )
    }

    fun getUsername(): String = decrypt(prefs.getString(K_USER, null))

    fun getApiKey(): String = decrypt(prefs.getString(K_API_KEY, null))

    fun getHfToken(): String = decrypt(prefs.getString(K_HF_TOKEN, null))

    fun getCivitaiToken(): String = decrypt(prefs.getString(K_CIVITAI_TOKEN, null))

    fun saveCredentials(username: String, apiKey: String) {
        prefs.edit()
            .putString(K_USER, encrypt(username.trim()))
            .putString(K_API_KEY, encrypt(apiKey.trim()))
            .apply()
    }

    fun saveHfToken(token: String) {
        prefs.edit().putString(K_HF_TOKEN, encrypt(token.trim())).apply()
    }

    fun saveCivitaiToken(token: String) {
        prefs.edit().putString(K_CIVITAI_TOKEN, encrypt(token.trim())).apply()
    }

    fun updateTokens(hfToken: String? = null, civitaiToken: String? = null) {
        val cur = load()
        save(
            cur.copy(
                hfToken = hfToken ?: cur.hfToken,
                civitaiToken = civitaiToken ?: cur.civitaiToken,
            )
        )
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "cellium_kaggle_aes256_gcm_v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val PREFS_NAME = "cellium_kaggle_vault_v1"
        private const val K_USER = "enc_u"
        private const val K_API_KEY = "enc_k"
        private const val K_HF_TOKEN = "enc_hf"
        private const val K_CIVITAI_TOKEN = "enc_cv"
    }
}
