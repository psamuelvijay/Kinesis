package com.kinesis.core.runtime

import androidx.datastore.core.DataStore
import androidx.datastore.core.okio.OkioStorage
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.PreferencesSerializer
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.kinesis.core.model.PersistedCounting
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import okio.FileSystem
import okio.Path.Companion.toPath
import java.io.File

/**
 * Persists [PersistedCounting] in a Preferences DataStore.
 *
 * Every mutation is one `DataStore.edit` transaction: read, apply the pure reducer, write back.
 * DataStore serialises edits, so sensor events, Reset and Stop can never interleave a half update.
 */
class CountingStore(private val dataStore: DataStore<Preferences>) {

    val data: Flow<PersistedCounting> = dataStore.data.map { it.toPersisted() }.distinctUntilChanged()

    suspend fun update(transform: (PersistedCounting) -> PersistedCounting) {
        dataStore.edit { prefs ->
            val next = transform(prefs.toPersisted())
            prefs.clear()
            next.encode().forEach { (key, value) -> prefs[stringPreferencesKey(key)] = value }
        }
    }

    companion object {
        const val FILE_NAME = "counting_state.preferences_pb"

        fun create(file: File, scope: CoroutineScope): CountingStore =
            CountingStore(
                PreferenceDataStoreFactory.create(storage = okioStorage(file), scope = scope),
            )
    }
}

/**
 * Okio storage instead of the default FileStorage: its atomic replace (Files.move with
 * REPLACE_EXISTING) also works on a Windows JVM, where FileStorage's File.renameTo fails once the
 * target file exists. On Android both behave the same.
 */
private fun okioStorage(file: File) = OkioStorage(
    fileSystem = FileSystem.SYSTEM,
    serializer = PreferencesSerializer,
    producePath = { file.absolutePath.toPath() },
)

private fun Preferences.toPersisted(): PersistedCounting =
    PersistedCounting.decode(asMap().entries.associate { (key, value) -> key.name to value.toString() })
