package com.henny.cellium.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        ProviderProfileEntity::class,
        SessionEntity::class,
        MessageEntity::class,
        CustomPersonaEntity::class,
        MemoryEntity::class,
        PromptTemplateEntity::class,
        ArtworkEntity::class,
    ],
    version = 4,
    exportSchema = false,
)
abstract class CelliumDatabase : RoomDatabase() {
    abstract fun dao(): CelliumDao

    companion object {
        @Volatile
        private var INSTANCE: CelliumDatabase? = null

        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE providers ADD COLUMN usageCount INTEGER NOT NULL DEFAULT 0")
                db.execSQL("ALTER TABLE messages ADD COLUMN isCompactSummary INTEGER NOT NULL DEFAULT 0")
            }
        }

        private val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE sessions ADD COLUMN isLocked INTEGER NOT NULL DEFAULT 0")
            }
        }

        private val INDEX_CALLBACK = object : RoomDatabase.Callback() {
            override fun onOpen(db: SupportSQLiteDatabase) {
                super.onOpen(db)
                runCatching {
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(sessionId, createdAtMs)")
                    db.execSQL("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updatedAtMs DESC)")
                }
            }
        }

        fun getInstance(context: Context): CelliumDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    CelliumDatabase::class.java,
                    "cel_cellium_local.db",
                ).addMigrations(MIGRATION_2_3, MIGRATION_3_4)
                    .addCallback(INDEX_CALLBACK)
                    .fallbackToDestructiveMigration(dropAllTables = true)
                    .build()
                    .also { INSTANCE = it }
            }
        }
    }
}
