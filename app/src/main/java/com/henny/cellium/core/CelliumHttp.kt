package com.henny.cellium.core

import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * Shared OkHttp singleton providing a single connection pool, HTTP/2 multiplexer,
 * TLS session cache, and bounded thread dispatcher across LLM, STT, TTS, WebTools,
 * and Image clients. Derived clients call [clientWithTimeouts] so they reuse the
 * exact same socket pool and threads with zero duplicate overhead.
 */
object CelliumHttp {

    private val sharedConnectionPool = ConnectionPool(
        maxIdleConnections = 8,
        keepAliveDuration = 3,
        timeUnit = TimeUnit.MINUTES,
    )

    private val sharedDispatcher = Dispatcher().apply {
        maxRequests = 32
        maxRequestsPerHost = 8
    }

    val baseClient: OkHttpClient = OkHttpClient.Builder()
        .connectionPool(sharedConnectionPool)
        .dispatcher(sharedDispatcher)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    fun clientWithTimeouts(
        connectSec: Long = 20L,
        readSec: Long = 60L,
        writeSec: Long = 30L,
        callSec: Long? = null,
        followRedirects: Boolean = true,
    ): OkHttpClient = baseClient.newBuilder()
        .connectTimeout(connectSec, TimeUnit.SECONDS)
        .readTimeout(readSec, TimeUnit.SECONDS)
        .writeTimeout(writeSec, TimeUnit.SECONDS)
        .apply {
            if (callSec != null) callTimeout(callSec, TimeUnit.SECONDS)
            followRedirects(followRedirects)
            followSslRedirects(followRedirects)
        }
        .build()
}
