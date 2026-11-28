# Preserve Firestore models annotated with @Keep
-keep @androidx.annotation.Keep class * { *; }

# Preserve Firebase Core, Auth, Firestore & gRPC/Protobuf transport (CRITICAL for release Cloud Sync!)
-keep class com.google.firebase.** { *; }
-keep interface com.google.firebase.** { *; }
-keep class com.google.firestore.** { *; }
-keep class io.grpc.** { *; }
-keep class com.google.protobuf.** { *; }
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.firebase.**
-dontwarn com.google.firestore.**
-dontwarn io.grpc.**
-dontwarn com.google.protobuf.**
-dontwarn com.google.android.gms.**

# Preserve Llamatik (llama.cpp JNI + reflection bridge)
-keep class com.llamatik.** { *; }
-keep interface com.llamatik.** { *; }
-dontwarn com.llamatik.**

# Preserve MediaPipe Tasks GenAI native JNI bindings
-keep class com.google.mediapipe.** { *; }
-dontwarn com.google.mediapipe.**

# Preserve LiteRT / TensorFlow Lite (openWakeWord)
-keep class org.tensorflow.lite.** { *; }
-dontwarn org.tensorflow.lite.**

# Preserve Shizuku AIDL & UserService
-keep class rikka.shizuku.** { *; }
-keep class com.henny.cellium.shizuku.** { *; }
-keep interface com.henny.cellium.shizuku.** { *; }
-dontwarn rikka.shizuku.**

# Preserve Kotlinx Serialization & Backup/Data models
-keepattributes *Annotation*, InnerClasses, Signature
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

# Preserve Jetpack CredentialManager & Google Sign-In
-keep class androidx.credentials.** { *; }
-keep interface androidx.credentials.** { *; }
-keep class com.google.android.libraries.identity.googleid.** { *; }
-keep class com.google.android.gms.auth.** { *; }
-dontwarn androidx.credentials.**
-dontwarn com.google.android.libraries.identity.googleid.**

# Preserve Default Digital Assistant, VoiceInteractionSession & Overlay Services
-keep class com.henny.cellium.assistant.** { *; }
-keep class * extends android.service.voice.VoiceInteractionService { *; }
-keep class * extends android.service.voice.VoiceInteractionSessionService { *; }
-keep class * extends android.service.voice.VoiceInteractionSession { *; }
-keep class * extends android.speech.RecognitionService { *; }

# Strip verbose debug logging in release builds for lower runtime overhead
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
}

# Preserve OkHttp & Kotlin Coroutines
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn javax.annotation.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
