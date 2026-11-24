# Preserve Firestore models annotated with @Keep
-keep @androidx.annotation.Keep class * { *; }

# Preserve Llamatik (llama.cpp JNI + reflection bridge)
-keep class com.llamatik.** { *; }
-keep interface com.llamatik.** { *; }
-dontwarn com.llamatik.**

# Preserve MediaPipe Tasks GenAI native JNI bindings
-keep class com.google.mediapipe.** { *; }
-dontwarn com.google.mediapipe.**

# Preserve Shizuku AIDL & UserService
-keep class rikka.shizuku.** { *; }
-keep class com.henny.cellium.shizuku.** { *; }
-keep interface com.henny.cellium.shizuku.** { *; }
-dontwarn rikka.shizuku.**

# Preserve Kotlinx Serialization & Backup/Data models
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.henny.cellium.**$$serializer { *; }
-keepclassmembers class com.henny.cellium.** {
    *** Companion;
}
-keepclasseswithmembers class com.henny.cellium.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep class com.henny.cellium.data.** { *; }

# Preserve Jetpack CredentialManager & Google Sign-In (prevents R8 stripping reflection-loaded providers in release APKs!)
-keep class androidx.credentials.** { *; }
-keep interface androidx.credentials.** { *; }
-keep class com.google.android.libraries.identity.googleid.** { *; }
-keep class com.google.firebase.auth.** { *; }
-keep class com.google.android.gms.auth.** { *; }
-dontwarn androidx.credentials.**
-dontwarn com.google.android.libraries.identity.googleid.**

# Preserve OkHttp & Kotlin Coroutines
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
