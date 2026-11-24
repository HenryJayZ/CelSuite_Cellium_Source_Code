package com.henny.cellium.core

import android.app.Activity
import android.content.Context
import android.util.Log
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential.Companion.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
import com.google.firebase.Firebase
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseUser
import com.google.firebase.auth.GoogleAuthProvider
import com.google.firebase.auth.auth
import com.henny.cellium.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext

private const val AUTH_TAG = "Auth"

fun FirebaseAuth.authStateFlow(): Flow<FirebaseUser?> = callbackFlow {
    val listener = FirebaseAuth.AuthStateListener { auth ->
        trySend(auth.currentUser)
    }
    addAuthStateListener(listener)
    awaitClose { removeAuthStateListener(listener) }
}

fun attemptAutoSignIn(
    context: Context,
    credentialManager: CredentialManager,
    scope: CoroutineScope,
    onAuthSuccess: () -> Unit,
    onUnauthenticated: () -> Unit,
) {
    if (Firebase.auth.currentUser != null) {
        onAuthSuccess()
        return
    }
    val clientId = try {
        context.getString(R.string.default_web_client_id)
    } catch (_: Exception) {
        onUnauthenticated()
        return
    }
    val googleIdOption = GetGoogleIdOption.Builder()
        .setFilterByAuthorizedAccounts(true)
        .setServerClientId(clientId)
        .setAutoSelectEnabled(true)
        .build()
    val request = GetCredentialRequest.Builder()
        .addCredentialOption(googleIdOption)
        .build()

    scope.launch {
        try {
            val cred = credentialManager.getCredential(context, request).credential
            if (cred is CustomCredential && cred.type == TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                val token = GoogleIdTokenCredential.createFrom(cred.data).idToken
                Firebase.auth.signInWithCredential(GoogleAuthProvider.getCredential(token, null)).await()
                DevLogBuffer.add("INFO", "Auth", "Silent Google Sign-In succeeded.")
                onAuthSuccess()
            } else {
                onUnauthenticated()
            }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            onUnauthenticated()
        }
    }
}

fun onGoogleSignInClicked(
    context: Context,
    credentialManager: CredentialManager,
    scope: CoroutineScope,
    onAuthSuccess: () -> Unit,
    onAuthError: (String) -> Unit,
    onAuthCancelled: () -> Unit,
) {
    val clientId = try {
        context.getString(R.string.default_web_client_id)
    } catch (_: Exception) {
        onAuthError("Google Sign-In configuration missing: default_web_client_id not found.")
        return
    }

    val signInOption = GetSignInWithGoogleOption.Builder(serverClientId = clientId).build()
    val request = GetCredentialRequest.Builder()
        .addCredentialOption(signInOption)
        .build()

    scope.launch {
        try {
            val activityContext = context as? Activity ?: context
            val cred = credentialManager.getCredential(activityContext, request).credential
            if (cred is CustomCredential && cred.type == TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                val token = GoogleIdTokenCredential.createFrom(cred.data).idToken
                Firebase.auth.signInWithCredential(GoogleAuthProvider.getCredential(token, null)).await()
                DevLogBuffer.add("INFO", "Auth", "Interactive Google Sign-In succeeded.")
                onAuthSuccess()
            } else {
                onAuthError("Unexpected credential type returned.")
            }
        } catch (e: GetCredentialCancellationException) {
            Log.w(AUTH_TAG, "Google Sign-In flow cancelled or dismissed: ${e.message}", e)
            DevLogBuffer.add("WARN", "Auth", "Sign-In cancelled: ${e.message}")
            onAuthCancelled()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(AUTH_TAG, "Google Sign-In failed", e)
            DevLogBuffer.add("ERROR", "Auth", e.localizedMessage ?: "Sign in failed")
            onAuthError(e.localizedMessage ?: "Sign in failed. Please try again.")
        }
    }
}

fun signOutFromCellium(
    credentialManager: CredentialManager,
    scope: CoroutineScope,
    onSignOutComplete: () -> Unit = {},
) {
    scope.launch {
        withContext(NonCancellable) {
            try {
                credentialManager.clearCredentialState(ClearCredentialStateRequest())
            } catch (e: Exception) {
                Log.w(AUTH_TAG, "Failed to clear credential state: ${e.message}")
            } finally {
                Firebase.auth.signOut()
                DevLogBuffer.add("INFO", "Auth", "User signed out.")
                onSignOutComplete()
            }
        }
    }
}

data class UserProfile(
    val uid: String,
    val email: String?,
    val displayName: String?,
)

class AuthManager {
    private val auth: FirebaseAuth = Firebase.auth

    val currentUser: UserProfile?
        get() = auth.currentUser?.toProfile()

    val currentUserFlow: Flow<UserProfile?> = callbackFlow {
        val listener = FirebaseAuth.AuthStateListener { a ->
            trySend(a.currentUser?.toProfile())
        }
        auth.addAuthStateListener(listener)
        awaitClose { auth.removeAuthStateListener(listener) }
    }

    suspend fun signInWithGoogle(activity: Activity): Result<UserProfile> {
        val clientId = try {
            activity.getString(R.string.default_web_client_id).trim()
        } catch (_: Exception) {
            return Result.failure(IllegalStateException("Google Sign-In configuration missing: default_web_client_id not found."))
        }
        if (clientId.isBlank()) {
            return Result.failure(IllegalStateException("Google Sign-In Web Client ID is blank."))
        }

        val credentialManager = CredentialManager.create(activity)

        // Tier 1: Standard "Sign in with Google" bottom sheet
        val tier1Start = android.os.SystemClock.elapsedRealtime()
        try {
            val signInOption = GetSignInWithGoogleOption.Builder(serverClientId = clientId).build()
            val request = GetCredentialRequest.Builder().addCredentialOption(signInOption).build()
            val cred = credentialManager.getCredential(activity, request).credential
            if (cred is CustomCredential && cred.type == TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                val token = GoogleIdTokenCredential.createFrom(cred.data).idToken
                val res = auth.signInWithCredential(GoogleAuthProvider.getCredential(token, null)).await()
                val profile = res.user?.toProfile()
                    ?: return Result.failure(IllegalStateException("Google Sign-In returned empty user."))
                DevLogBuffer.add("INFO", "Auth", "Google Sign-In (Tier 1) succeeded: ${profile.email}")
                return Result.success(profile)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: GetCredentialCancellationException) {
            val elapsed = android.os.SystemClock.elapsedRealtime() - tier1Start
            val msg = e.message.orEmpty()
            val likelyConfigError = elapsed < 2500L ||
                msg.contains("Developer console", ignoreCase = true) ||
                msg.contains("28444") ||
                msg.contains("[16]") ||
                msg.contains("[10]") ||
                msg.contains("reauth", ignoreCase = true)
            DevLogBuffer.add("WARN", "Auth", "Tier 1 cancelled after ${elapsed}ms (likelyConfig=$likelyConfigError): $msg")
            if (!likelyConfigError) {
                return Result.failure(IllegalStateException("Google Sign-In cancelled."))
            }
        } catch (e: Exception) {
            DevLogBuffer.add("WARN", "Auth", "Tier 1 GetSignInWithGoogleOption failed: ${e.javaClass.simpleName}: ${e.localizedMessage}")
        }

        // Tier 2: CredentialManager GetGoogleIdOption (works on older Play Services / non-GMS sheets)
        try {
            val googleIdOption = GetGoogleIdOption.Builder()
                .setFilterByAuthorizedAccounts(false)
                .setServerClientId(clientId)
                .setAutoSelectEnabled(false)
                .build()
            val request = GetCredentialRequest.Builder().addCredentialOption(googleIdOption).build()
            val cred = credentialManager.getCredential(activity, request).credential
            if (cred is CustomCredential && cred.type == TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
                val token = GoogleIdTokenCredential.createFrom(cred.data).idToken
                val res = auth.signInWithCredential(GoogleAuthProvider.getCredential(token, null)).await()
                val profile = res.user?.toProfile()
                    ?: return Result.failure(IllegalStateException("Google Sign-In returned empty user."))
                DevLogBuffer.add("INFO", "Auth", "Google Sign-In (Tier 2) succeeded: ${profile.email}")
                return Result.success(profile)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DevLogBuffer.add("WARN", "Auth", "Tier 2 GetGoogleIdOption failed: ${e.javaClass.simpleName}: ${e.localizedMessage}")
        }

        // Tier 3: Firebase Auth Chrome Custom Tab OAuth fallback
        val webFallback = signInWithGoogleWebFallback(activity)
        if (webFallback.isSuccess) return webFallback

        val fallbackErr = webFallback.exceptionOrNull()?.localizedMessage.orEmpty()
        return Result.failure(
            IllegalStateException(
                if (fallbackErr.contains("INVALID_CERT_HASH", ignoreCase = true) || fallbackErr.isBlank()) {
                    "Google Sign-In needs SHA-1 8E:18:75:8C:E3:ED:AA:8A:00:CB:DF:D5:E6:D3:4E:57:8C:7C:E6:D1 added to Firebase Console -> Project Settings -> CelSuite.HenryJayz.Cellium."
                } else {
                    "Google Sign-In failed: $fallbackErr"
                }
            )
        )
    }

    private suspend fun signInWithGoogleWebFallback(activity: Activity): Result<UserProfile> {
        return try {
            val provider = com.google.firebase.auth.OAuthProvider.newBuilder("google.com")
                .addCustomParameter("prompt", "select_account")
                .build()
            val pending = auth.pendingAuthResult
            val res = if (pending != null) {
                pending.await()
            } else {
                auth.startActivityForSignInWithProvider(activity, provider).await()
            }
            val profile = res.user?.toProfile()
                ?: return Result.failure(IllegalStateException("Google browser sign-in returned empty user."))
            DevLogBuffer.add("INFO", "Auth", "Google browser fallback sign-in succeeded: ${profile.email}")
            Result.success(profile)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DevLogBuffer.add("WARN", "Auth", "Google browser fallback failed: ${e.localizedMessage}")
            Result.failure(e)
        }
    }

    suspend fun signOut(context: Context) {
        withContext(NonCancellable) {
            runCatching {
                CredentialManager.create(context).clearCredentialState(ClearCredentialStateRequest())
            }
            auth.signOut()
            DevLogBuffer.add("INFO", "Auth", "Signed out to Guest Mode.")
        }
    }

    private fun FirebaseUser.toProfile(): UserProfile =
        UserProfile(uid = uid, email = email, displayName = displayName)
}

