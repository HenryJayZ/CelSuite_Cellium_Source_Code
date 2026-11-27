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
import java.net.URLDecoder
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
 *
 * Uses a multi-tier keyless waterfall (Bing Web RSS -> Google News RSS -> DuckDuckGo HTML/Lite
 * -> Wikipedia last resort) so live patch numbers, news, and current facts return reliably
 * without DDG CAPTCHA failures collapsing into generic encyclopedia intros.
 */
class WebToolsClient {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .followRedirects(true)
        .build()

    private val freshQueryHints = listOf(
        "latest", "current", "news", "today", "2025", "2026", "version", "release",
        "patch", "update", "price", "score", "weather", "debut", "announced", "new",
    )

    suspend fun searchWeb(query: String, maxResults: Int = 6): Result<List<WebSearchResult>> = withContext(Dispatchers.IO) {
        val cleanQuery = query.trim()
        if (cleanQuery.isBlank()) {
            return@withContext Result.failure(IllegalArgumentException("Search query is empty."))
        }

        val combined = LinkedHashMap<String, WebSearchResult>()
        val lowQ = cleanQuery.lowercase()
        val wantsFresh = freshQueryHints.any { it in lowQ }

        // Tier 1: Bing Web RSS (live web index, keyless, XML, never CAPTCHAs mobile clients)
        val bingHits = searchBingWebRss(cleanQuery, maxResults)
        bingHits.forEach { hit -> combined.putIfAbsent(hit.url, hit) }

        // Tier 2: Google News RSS (injected for fresh/current/news/version queries, or when Bing is sparse)
        if (wantsFresh || combined.size < 3) {
            val newsHits = searchGoogleNewsRss(cleanQuery, if (wantsFresh) 4 else maxResults)
            newsHits.forEach { hit -> combined.putIfAbsent(hit.url, hit) }
        }

        // Tier 3: DuckDuckGo HTML & Lite (fallback when Bing/News returned too few hits)
        if (combined.size < 3) {
            val ddgHtml = searchDuckDuckGoHtml(cleanQuery, maxResults)
            ddgHtml.forEach { hit -> combined.putIfAbsent(hit.url, hit) }
        }
        if (combined.size < 2) {
            val ddgLite = searchDuckDuckGoLite(cleanQuery, maxResults)
            ddgLite.forEach { hit -> combined.putIfAbsent(hit.url, hit) }
        }

        if (combined.isNotEmpty()) {
            val results = combined.values.take(maxResults)
            DevLogBuffer.add("INFO", "WebTools", "Live search '$cleanQuery' -> ${results.size} results (bing=${bingHits.size})")
            return@withContext Result.success(results)
        }

        // Tier 4: Wikipedia API strictly as last resort when live web search yielded zero results
        val wikiRes = searchWikipediaFallback(cleanQuery, maxResults)
        if (wikiRes.isNotEmpty()) {
            DevLogBuffer.add("WARN", "WebTools", "Live web empty for '$cleanQuery'; Wikipedia last-resort -> ${wikiRes.size}")
            return@withContext Result.success(wikiRes)
        }

        DevLogBuffer.add("ERROR", "WebTools", "All search tiers returned 0 hits for '$cleanQuery'")
        Result.success(emptyList())
    }

    private fun searchBingWebRss(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://www.bing.com/search?q=$encoded&format=rss&count=${(maxResults + 2).coerceAtMost(10)}"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")
            .header("Accept", "application/rss+xml, application/xml, text/xml, */*")
            .header("Accept-Language", "en-US,en;q=0.9")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@runCatching emptyList()
            val xml = resp.body?.string().orEmpty()
            parseRssItems(xml, maxResults)
        }
    }.getOrDefault(emptyList())

    private fun searchGoogleNewsRss(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://news.google.com/rss/search?q=$encoded&hl=en-US&gl=US&ceid=US:en"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36")
            .header("Accept", "application/rss+xml, application/xml, text/xml")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@runCatching emptyList()
            val xml = resp.body?.string().orEmpty()
            parseRssItems(xml, maxResults, tagPrefix = "[News] ")
        }
    }.getOrDefault(emptyList())

    private fun parseRssItems(xml: String, maxResults: Int, tagPrefix: String = ""): List<WebSearchResult> {
        val itemRegex = Regex("""<item\b[^>]*>([\s\S]*?)</item>""", RegexOption.IGNORE_CASE)
        val results = mutableListOf<WebSearchResult>()
        for (match in itemRegex.findAll(xml)) {
            if (results.size >= maxResults) break
            val block = match.groupValues[1]
            val title = extractXmlTag(block, "title").let { stripHtml(it) }
            val link = extractXmlTag(block, "link").trim()
            val desc = extractXmlTag(block, "description").let { stripHtml(it) }
            val pubDate = extractXmlTag(block, "pubDate").trim()
            if (title.isBlank() || link.isBlank()) continue
            val snippet = buildString {
                if (tagPrefix.isNotEmpty()) append(tagPrefix)
                if (pubDate.isNotBlank()) append("($pubDate) ")
                append(desc.ifBlank { title })
            }.trim()
            results.add(WebSearchResult(title = title, url = link, snippet = snippet.take(360)))
        }
        return results
    }

    private fun extractXmlTag(block: String, tag: String): String {
        val rx = Regex("""<$tag\b[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:]]>)?</$tag>""", RegexOption.IGNORE_CASE)
        return rx.find(block)?.groupValues?.get(1)?.trim().orEmpty()
    }

    private fun searchDuckDuckGoHtml(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://html.duckduckgo.com/html/?q=$encoded"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36")
            .header("Accept-Language", "en-US,en;q=0.9")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@runCatching emptyList()
            val html = resp.body?.string().orEmpty()
            val linkRegex = Regex(
                """<a[^>]*class=['"][^'"]*result__a[^'"]*['"][^>]*href=['"]([^'"]+)['"][^>]*>([\s\S]*?)</a>""",
                RegexOption.IGNORE_CASE,
            )
            val snippetRegex = Regex(
                """<(?:a|div)[^>]*class=['"][^'"]*result__snippet[^'"]*['"][^>]*>([\s\S]*?)</(?:a|div)>""",
                RegexOption.IGNORE_CASE,
            )
            val links = linkRegex.findAll(html).toList()
            val snippets = snippetRegex.findAll(html).map { stripHtml(it.groupValues[1]) }.toList()
            links.take(maxResults).mapIndexedNotNull { idx, match ->
                val rawHref = match.groupValues[1].trim()
                val realUrl = unwrapDdgRedirect(rawHref)
                val title = stripHtml(match.groupValues[2])
                if (title.isBlank() || realUrl.isBlank()) null
                else WebSearchResult(
                    title = title,
                    url = realUrl,
                    snippet = snippets.getOrNull(idx).orEmpty(),
                )
            }
        }
    }.getOrDefault(emptyList())

    private fun searchDuckDuckGoLite(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://lite.duckduckgo.com/lite/?q=$encoded"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@runCatching emptyList()
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
                    url = unwrapDdgRedirect(match.groupValues[1].trim()),
                    snippet = snippets.getOrNull(idx).orEmpty(),
                )
            }
        }
    }.getOrDefault(emptyList())

    private fun unwrapDdgRedirect(rawUrl: String): String {
        val match = Regex("""[?&]uddg=([^&]+)""").find(rawUrl)
        if (match != null) {
            return runCatching { URLDecoder.decode(match.groupValues[1], "UTF-8") }.getOrDefault(rawUrl)
        }
        return if (rawUrl.startsWith("//")) "https:$rawUrl" else rawUrl
    }

    private fun searchWikipediaFallback(query: String, maxResults: Int): List<WebSearchResult> = runCatching {
        val encoded = URLEncoder.encode(query, "UTF-8")
        val url = "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=$encoded&srlimit=$maxResults&format=json"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Cel.Cellium-Android/2611.27.0 (https://github.com/HenryJayZ)")
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
                WebSearchResult(
                    title = title,
                    url = wikiUrl,
                    snippet = "[Wikipedia fallback] $snippet",
                )
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
                .header("User-Agent", "Cel.Cellium-Android/2611.27.0 (https://github.com/HenryJayZ)")
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
     * Downloads a remote web image URL to a local file as clean JPEG so it displays offline
     * and supports fullscreen zoom + Save to Downloads/Cellium.
     */
    suspend fun downloadImageToFile(imageUrl: String, destDir: File, filePrefix: String = "web_img"): Result<File> =
        withContext(Dispatchers.IO) {
            runCatching {
                destDir.mkdirs()
                val req = Request.Builder()
                    .url(imageUrl)
                    .header("User-Agent", "Cel.Cellium-Android/2611.27.0 (https://github.com/HenryJayZ)")
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
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36")
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
            .replace("&apos;", "'")
            .replace("&nbsp;", " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
