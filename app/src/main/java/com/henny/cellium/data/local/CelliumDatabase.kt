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
    version = 3,
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

        fun getInstance(context: Context): CelliumDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    CelliumDatabase::class.java,
                    "cel_cellium_local.db",
                ).addMigrations(MIGRATION_2_3)
                    .fallbackToDestructiveMigration(dropAllTables = true)
                    .build()
                    .also { INSTANCE = it }
            }
        }
    }
}
