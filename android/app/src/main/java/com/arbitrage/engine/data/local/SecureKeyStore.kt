package com.arbitrage.engine.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Local-only encrypted storage for session material (session tokens, the
 * client-derived K_session wrapping key, biometric-unlocked handles, etc.).
 *
 * Per docs/ARCHITECTURE.md section 2 (Zero-Knowledge Application Secret
 * Storage): the exchange API secret is NEVER persisted here in plaintext.
 * The raw secret only ever exists in memory long enough to be AES-256-GCM
 * sealed client-side before being sent to the backend over TLS 1.3; this
 * class is for the *derived* session-scoped material used to drive that
 * flow (e.g. the wrapped session key, short-lived JWTs), not for exchange
 * credentials themselves.
 *
 * Backed by the Android KeyStore (via [MasterKey], StrongBox-backed where
 * available) + Jetpack Security's [EncryptedSharedPreferences], so values
 * are encrypted at rest with AES-256-GCM and the key material never leaves
 * secure hardware.
 */
class SecureKeyStore(context: Context) {

    private val appContext = context.applicationContext

    private val masterKey: MasterKey by lazy {
        MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
    }

    private val prefs: SharedPreferences by lazy {
        EncryptedSharedPreferences.create(
            appContext,
            PREFS_FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    /** Persists [value] under [key], encrypted at rest. Overwrites any existing value. */
    fun saveEncrypted(key: String, value: String) {
        prefs.edit().putString(key, value).apply()
    }

    /** Returns the decrypted value stored under [key], or null if absent. */
    fun readEncrypted(key: String): String? = prefs.getString(key, null)

    /** Removes the value stored under [key], if any. */
    fun clear(key: String) {
        prefs.edit().remove(key).apply()
    }

    /** Wipes all session material held by this store (e.g. on logout / kill switch). */
    fun clearAll() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val PREFS_FILE_NAME = "arbitrage_secure_prefs"

        // Well-known key names used across the app for session material.
        const val KEY_SESSION_TOKEN = "session_token"
        const val KEY_SESSION_WRAP_KEY = "session_wrap_key"
        const val KEY_ACTIVE_USER_ID = "active_user_id"
    }
}
