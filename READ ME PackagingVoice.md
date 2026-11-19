
Windows & Linux: Mic Privacy Indicators & Battery Optimization
1. Microphone Privacy Indicators
 * Windows 11: Windows displays a microphone icon in the system tray (taskbar notification area) whenever any desktop app or Win32 process accesses the default audio endpoint via WASAPI or DirectSound. Unlike Android, there is no system assistant role that suppresses this tray icon for third-party software; if Cellium is listening in the background, the taskbar mic icon will remain visible.
 * Linux (Linux Mint / PipeWire / PulseAudio): Linux desktop environments (such as Cinnamon or GNOME) display a microphone icon on the system panel as long as a recording stream is registered in the audio server. Linux does not restrict background recording or require specialized assistant roles, but the panel icon will stay active whenever the audio device is in use.
2. Battery & Performance Bottlenecks
 * Deep Sleep (C-States): On laptop hardware, continuous audio capture prevents the CPU from dropping into its lowest package C-states (deep power-saving idle). While this will not drain a laptop battery as aggressively as a smartphone, continuous 16 kHz audio streaming can reduce overall battery life by 10–15% if unoptimized.
 * Buffer Chunking: To minimize CPU wake-ups, audio capture should never process single samples. OpenWakeWord operates on 80 ms (1280 samples at 16 kHz) chunks. Capturing audio in 80 ms blocks allows the worker thread to sleep between buffers, keeping background CPU consumption below 1.5%.
 * VAD Gating (Voice Activity Detection): Running WebRTC VAD or a simple energy threshold before the neural network saves substantial power. If room noise is below the threshold, bypass the embedding model completely; only run the OpenWakeWord inference graph when speech is detected.
Kotlin_Android_VoiceAssist.md
Save the following specification and share it with Muse Spark:
# 📱 Android Voice Assistant Implementation Guide

## 1. Architectural Overview: Bypassing the Persistent Green Privacy Dot
Starting in Android 12 (API 31), the platform displays a persistent green indicator in the status bar whenever `AudioRecord` or `MediaRecorder` is actively receiving input.

To run a persistent wake word listener without a continuous privacy indicator:
1. Implement Android's native `VoiceInteractionService` and `HotwordDetector` APIs.
2. The user must manually configure the application as the **Default Digital Assistant** under Android Settings.
3. Once designated as the default assistant, the OS provides a trusted isolated sandbox (`HotwordDetectionService`) that captures audio buffers without keeping the software mic indicator continuously active.

---

## 2. Default Assistant Settings Switcher (Kotlin)
Because Android prohibits applications from silently changing the default digital assistant programmatically, trigger the system configuration screen via an explicit Intent from a Settings menu:

```kotlin
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings

fun openDefaultAssistantSettings(context: Context) {
    val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        // Direct route to the Default Apps selector screen
        Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)
    } else {
        // Fallback route to Voice Input / Assistant selection
        Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)
    }
    intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK
    context.startActivity(intent)
}

3. Cellium-to-Gemini Pass-Through Architecture
Instead of completely replacing conversational engines, Cellium acts as a zero-latency, local acoustic gatekeeper that delegates complex natural language queries to Gemini.
[Raw Audio Stream]
       │
       ▼
[OpenWakeWord TFLite] ──(Detects "okay cel")──► [Trigger Audio Capture]
                                                        │
                                                        ▼
                                             [Speech-To-Text / Whisper]
                                                        │
                                                        ▼
                                             [Gemini API Dispatcher]
                                                        │
                                                        ▼
                                             [TTS Audio Playback]

Kotlin Pass-Through Orchestrator:
package com.cellium.assistant

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

class AssistantOrchestrator(
    private val geminiApiKey: String,
    private val client: OkHttpClient = OkHttpClient()
) {
    fun onWakeWordDetected(userQueryText: String, onResponse: (String) -> Unit) {
        CoroutineScope(Dispatchers.IO).launch {
            val responseText = forwardToGemini(userQueryText)
            launch(Dispatchers.Main) {
                onResponse(responseText)
            }
        }
    }

    private fun forwardToGemini(prompt: String): String {
        val endpoint = "[https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=$geminiApiKey](https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=$geminiApiKey)"
        
        val payload = JSONObject().apply {
            put("contents", org.json.JSONArray().put(
                JSONObject().put("parts", org.json.JSONArray().put(
                    JSONObject().put("text", prompt)
                ))
            ))
        }

        val request = Request.Builder()
            .url(endpoint)
            .post(payload.toString().toRequestBody("application/json".toMediaType()))
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return "Error: Server returned code ${response.code}"
            
            val json = JSONObject(response.body?.string() ?: "{}")
            return json.getJSONArray("candidates")
                .getJSONObject(0)
                .getJSONObject("content")
                .getJSONArray("parts")
                .getJSONObject(0)
                .getString("text")
        }
    }
}

4. Model Deployment Specs
 * Model File: oh_kay_sell.tflite
 * Input Tensor: Mel-spectrogram embeddings matching OpenWakeWord audio frontend (80 ms chunk window, 16 kHz mono PCM).
 * Activation Threshold: Recommended start value 0.5, dynamic scalar up to 0.75 for high-noise rejection.


