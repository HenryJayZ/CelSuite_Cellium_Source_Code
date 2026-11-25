package com.henny.cellium.ai

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.henny.cellium.core.DevLogBuffer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class WebSearchResult(
    val title: String,
    val url: String,
    val snippet: String,
)

data class WebImageResult(
    val title: String,
    val imageUrl: String,
    val sourceUrl: String = "",
)

/**
 * Built-in keyless Web Search (/web & autonomous [WEB_SEARCH]), URL Reader (/url),
 * and Free Keyless Web/Stock Image Search ([WEB_IMAGE] via Wikimedia Commons API)
 * for Cel.Cellium. Zero API keys required.
 */
class WebToolsClient {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    suspend fun searchWeb(query: String, maxResults: Int = 5): Result<List<WebSearchResult>> = withContext(Dispatchers.IO) {
        val cleanQuery = query.trim()
        if (cleanQuery.isBlank()) return@withContext Result.failure(IllegalArgumentException("Search query is empty."))
        val encoded = URLEncoder.encode(cleanQuery, "UTF-8")
        val url = "https://lite.duckduckgo.com/lite/?q=$encoded"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36")
            .get()
            .build()
        val ddgRes = runCatching {
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("Search HTTP ${resp.code}")
                val html = resp.body?.string().orEmpty()
                val linkRegex = Regex(
                    """<a[^>]*class=['"]result-link['"][^>]*href=['"]([^'"]+)['"][^>]*>([\s\S]*?)</a>""",
                    RegexOption.IGNORE_CASE,
                )
                val snippetRegex = Regex(
                    """<td[^>]*class=['"]result-snippet['"][^>]*>([\s\S]*?)</td>""",
                    RegexOption.IGNORE_CASE,
                )
                val links = linkRegex.findAll(html).toList()
                val snippets = snippetRegex.findAll(html).map { stripHtml(it.groupValues[1]) }.toList()
                links.take(maxResults).mapIndexed { idx, match ->
                    WebSearchResult(
                        title = stripHtml(match.groupValues[2]).ifBlank { "Result ${idx + 1}" },
                        url = match.groupValues[1].trim(),
                        snippet = snippets.getOrNull(idx).orEmpty(),
                    )
                }
            }
        }
        val ddgList = ddgRes.getOrNull().orEmpty()
        if (ddgList.isNotEmpty()) {
            DevLogBuffer.add("INFO", "WebTools", "Search '$cleanQuery' -> ${ddgList.size} results")
            return@withContext Result.success(ddgList)
        }

        // Keyless Wikipedia Search API fallback when DDG Lite rate-limits or returns 0 hits
        val wikiRes = searchWikipediaFallback(cleanQuery, maxResults)
        if (wikiRes.isNotEmpty()) {
            DevLogBuffer.add("INFO", "WebTools", "Wikipedia fallback '$cleanQuery' -> ${wikiRes.size} results")
            return@withContext Result.success(wikiRes)
        }

        ddgRes.onFailure { err ->
            DevLogBuffer.add("ERROR", "WebTools", "Search failed: ${err.localizedMessage}")
        }
        if (ddgRes.isSuccess) Result.success(emptyList()) else ddgRes
    }

    private fun searchWikipediaFallback(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=$encoded&srlimit=$maxResults&format=json"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Cel.Cellium-Android/2611.25.0 (https://github.com/HenryJayZ)")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@runCatching emptyList()
            val body = resp.body?.string().orEmpty()
            val root = json.parseToJsonElement(body).jsonObject
            val arr = root["query"]?.jsonObject?.get("search")?.jsonArray ?: return@runCatching emptyList()
            arr.mapNotNull { el ->
                val obj = el as? JsonObject ?: return@mapNotNull null
                val title = obj["title"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
                if (title.isBlank()) return@mapNotNull null
                val snippet = stripHtml(obj["snippet"]?.jsonPrimitive?.contentOrNull.orEmpty())
                val wikiUrl = "https://en.wikipedia.org/wiki/" + URLEncoder.encode(title.replace(" ", "_"), "UTF-8")
                WebSearchResult(title = title, url = wikiUrl, snippet = snippet)
            }
        }
    }.getOrDefault(emptyList())

    /**
     * Free, keyless web/stock photo search powered by Wikimedia Commons public MediaWiki API.
     * Filters strictly for real raster photos (JPEG/PNG/WebP), skipping SVGs/PDFs/audio.
     */
    suspend fun searchWebImages(query: String, maxResults: Int = 3): Result<List<WebImageResult>> = withContext(Dispatchers.IO) {
        val cleanQuery = query.trim()
        if (cleanQuery.isBlank()) return@withContext Result.success(emptyList())
        runCatching {
            val encoded = URLEncoder.encode(cleanQuery, "UTF-8")
            val apiUrl = "https://commons.wikimedia.org/w/api.php" +
                "?action=query&generator=search&gsrnamespace=6&gsrsearch=$encoded" +
                "&gsrlimit=${(maxResults * 4).coerceAtLeast(10)}" +
                "&prop=imageinfo&iiprop=url|mime&iiurlwidth=960&format=json"
            val req = Request.Builder()
                .url(apiUrl)
                .header("User-Agent", "Cel.Cellium-Android/2611.25.0 (https://github.com/HenryJayZ)")
                .get()
                .build()
            val hits = mutableListOf<WebImageResult>()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("Wikimedia HTTP ${resp.code}")
                val body = resp.body?.string().orEmpty()
                val root = json.parseToJsonElement(body).jsonObject
                val pages = root["query"]?.jsonObject?.get("pages")?.jsonObject ?: return@use
                for ((_, pageEl) in pages) {
                    val page = pageEl as? JsonObject ?: continue
                    val title = page["title"]?.jsonPrimitive?.contentOrNull.orEmpty().removePrefix("File:")
                    val info = page["imageinfo"]?.jsonArray?.firstOrNull() as? JsonObject ?: continue
                    val mime = info["mime"]?.jsonPrimitive?.contentOrNull.orEmpty().lowercase()
                    if (mime != "image/jpeg" && mime != "image/png" && mime != "image/webp") continue
                    val imgUrl = info["thumburl"]?.jsonPrimitive?.contentOrNull
                        ?: info["url"]?.jsonPrimitive?.contentOrNull
                        ?: continue
                    val descUrl = info["descriptionurl"]?.jsonPrimitive?.contentOrNull.orEmpty()
                    hits.add(WebImageResult(title = title, imageUrl = imgUrl, sourceUrl = descUrl))
                    if (hits.size >= maxResults) break
                }
            }
            DevLogBuffer.add("INFO", "WebTools", "Web images '$cleanQuery' -> ${hits.size} photos")
            hits
        }.onFailure { err ->
            DevLogBuffer.add("WARN", "WebTools", "Web image search failed: ${err.localizedMessage}")
        }
    }

    /**
     * Downloads a remote web image URL to a local file as clean PNG/JPEG so it displays offline
     * and supports fullscreen zoom + Save to Downloads/Cellium.
     */
    suspend fun downloadImageToFile(imageUrl: String, destDir: File, filePrefix: String = "web_img"): Result<File> =
        withContext(Dispatchers.IO) {
            runCatching {
                destDir.mkdirs()
                val req = Request.Builder()
                    .url(imageUrl)
                    .header("User-Agent", "Cel.Cellium-Android/2611.25.0 (https://github.com/HenryJayZ)")
                    .get()
                    .build()
                val bytes = client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) throw IllegalStateException("Image HTTP ${resp.code}")
                    resp.body?.bytes() ?: throw IllegalStateException("Empty image body")
                }
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    ?: throw IllegalStateException("Invalid image format")
                val outFile = File(destDir, "${filePrefix}_${System.currentTimeMillis()}_${(100..999).random()}.jpg")
                FileOutputStream(outFile).use { fos ->
                    bmp.compress(Bitmap.CompressFormat.JPEG, 88, fos)
                }
                bmp.recycle()
                outFile
            }
        }

    suspend fun readUrl(rawUrl: String): Result<String> = withContext(Dispatchers.IO) {
        val normalized = rawUrl.trim().let {
            if (it.startsWith("http://") || it.startsWith("https://")) it else "https://$it"
        }
        val req = Request.Builder()
            .url(normalized)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36")
            .get()
            .build()
        runCatching {
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("URL HTTP ${resp.code}")
                val raw = resp.body?.string().orEmpty()
                val cleaned = stripHtml(raw).take(6500)
                DevLogBuffer.add("INFO", "WebTools", "Read $normalized (${cleaned.length} chars)")
                cleaned
            }
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "WebTools", "URL read failed: ${err.localizedMessage}")
        }
    }

    private fun stripHtml(html: String): String {
        return html
            .replace(Regex("<script[\\s\\S]*?</script>", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("<style[\\s\\S]*?</style>", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("<noscript[\\s\\S]*?</noscript>", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("<[^>]+>"), " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
