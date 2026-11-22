package com.henny.cellium.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface CelliumDao {
    // ── Providers ────────────────────────────────────────────────────────
    @Query("SELECT * FROM providers ORDER BY requiresKey ASC, isCustom ASC, name ASC")
    fun observeProviders(): Flow<List<ProviderProfileEntity>>

    @Query("SELECT * FROM providers")
    suspend fun getAllProviders(): List<ProviderProfileEntity>

    @Query("SELECT * FROM providers WHERE id = :id LIMIT 1")
    suspend fun getProvider(id: String): ProviderProfileEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertProvider(provider: ProviderProfileEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertProvidersIfMissing(providers: List<ProviderProfileEntity>)

    @Query("DELETE FROM providers WHERE id = :id")
    suspend fun deleteProvider(id: String)

    // ── Sessions ─────────────────────────────────────────────────────────
    @Query("SELECT * FROM sessions ORDER BY pinned DESC, updatedAtMs DESC")
    fun observeSessions(): Flow<List<SessionEntity>>

    @Query("SELECT * FROM sessions ORDER BY updatedAtMs DESC")
    suspend fun getAllSessionsOnce(): List<SessionEntity>

    @Query("SELECT * FROM sessions WHERE id = :id LIMIT 1")
    suspend fun getSession(id: String): SessionEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertSession(session: SessionEntity)

    @Query("DELETE FROM sessions WHERE id = :id")
    suspend fun deleteSession(id: String)

    // ── Tree Messages ────────────────────────────────────────────────────
    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY createdAtMs ASC")
    fun observeMessagesForSession(sessionId: String): Flow<List<MessageEntity>>

    @Query("SELECT * FROM messages WHERE sessionId = :sessionId ORDER BY createdAtMs ASC")
    suspend fun getMessagesForSessionOnce(sessionId: String): List<MessageEntity>

    @Query("SELECT * FROM messages ORDER BY createdAtMs ASC")
    suspend fun getAllMessagesOnce(): List<MessageEntity>

    @Query("SELECT DISTINCT sessionId FROM messages WHERE content LIKE '%' || :query || '%'")
    suspend fun searchSessionIdsByMessageContent(query: String): List<String>

    @Query("SELECT COUNT(*) FROM messages")
    fun observeTotalMessageCount(): Flow<Int>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertMessage(message: MessageEntity)

    @Query("DELETE FROM messages WHERE id = :id")
    suspend fun deleteMessage(id: String)

    @Query("DELETE FROM messages WHERE sessionId = :sessionId")
    suspend fun deleteMessagesForSession(sessionId: String)

    // ── Custom Personas ──────────────────────────────────────────────────
    @Query("SELECT * FROM custom_personas ORDER BY createdAtMs DESC")
    fun observePersonas(): Flow<List<CustomPersonaEntity>>

    @Query("SELECT * FROM custom_personas")
    suspend fun getAllPersonasOnce(): List<CustomPersonaEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertPersona(persona: CustomPersonaEntity)

    @Query("DELETE FROM custom_personas WHERE id = :id")
    suspend fun deletePersona(id: String)

    // ── Persistent Memories ──────────────────────────────────────────────
    @Query("SELECT * FROM memories ORDER BY createdAtMs DESC")
    fun observeMemories(): Flow<List<MemoryEntity>>

    @Query("SELECT * FROM memories")
    suspend fun getAllMemoriesOnce(): List<MemoryEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertMemory(memory: MemoryEntity)

    @Query("DELETE FROM memories WHERE id = :id")
    suspend fun deleteMemory(id: String)

    // ── Prompt Templates ─────────────────────────────────────────────────
    @Query("SELECT * FROM prompt_templates ORDER BY slashKey ASC")
    fun observePromptTemplates(): Flow<List<PromptTemplateEntity>>

    @Query("SELECT * FROM prompt_templates")
    suspend fun getAllPromptTemplatesOnce(): List<PromptTemplateEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertPromptTemplate(template: PromptTemplateEntity)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertPromptTemplatesIfMissing(templates: List<PromptTemplateEntity>)

    @Query("DELETE FROM prompt_templates WHERE id = :id")
    suspend fun deletePromptTemplate(id: String)

    // ── Imagine Artworks ─────────────────────────────────────────────────
    @Query("SELECT * FROM artworks ORDER BY createdAtMs DESC")
    fun observeArtworks(): Flow<List<ArtworkEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertArtwork(artwork: ArtworkEntity)

    @Query("DELETE FROM artworks WHERE id = :id")
    suspend fun deleteArtwork(id: String)
}
