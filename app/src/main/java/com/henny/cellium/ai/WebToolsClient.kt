package com.henny.cellium.ai

import com.henny.cellium.core.DevLogBuffer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class WebSearchResult(
    val title: String,
    val url: String,
    val snippet: String,
)

/**
 * Built-in keyless Web Search (/web) and URL Reader (/url) tools for Cel.Cellium Chat.
 * Uses DuckDuckGo HTML Lite (no API key needed) and strips HTML cleanly into Markdown context.
 */
class WebToolsClient {
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
        runCatching {
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
                val results = links.take(maxResults).mapIndexed { idx, match ->
                    WebSearchResult(
                        title = stripHtml(match.groupValues[2]).ifBlank { "Result ${idx + 1}" },
                        url = match.groupValues[1].trim(),
                        snippet = snippets.getOrNull(idx).orEmpty(),
                    )
                }
                DevLogBuffer.add("INFO", "WebTools", "Search '$cleanQuery' -> ${results.size} results")
                results
            }
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "WebTools", "Search failed: ${err.localizedMessage}")
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
