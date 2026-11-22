package com.henny.cellium.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

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
    version = 2,
    exportSchema = false,
)
abstract class CelliumDatabase : RoomDatabase() {
    abstract fun dao(): CelliumDao

    companion object {
        @Volatile
        private var INSTANCE: CelliumDatabase? = null

        fun getInstance(context: Context): CelliumDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    CelliumDatabase::class.java,
                    "cel_cellium_local.db",
                ).fallbackToDestructiveMigration(dropAllTables = true)
                    .build()
                    .also { INSTANCE = it }
            }
        }
    }
}
