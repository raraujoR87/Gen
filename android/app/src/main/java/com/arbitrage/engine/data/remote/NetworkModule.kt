package com.arbitrage.engine.data.remote

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit

/**
 * Minimal Retrofit wiring for [ArbitrageApiService]. Not a full DI graph
 * (Hilt/Koin module) — presentation-layer units are free to wrap this in
 * whichever DI framework they adopt; this just keeps the data layer usable
 * and compilable on its own.
 */
object NetworkModule {

    private val json = Json { ignoreUnknownKeys = true }

    fun createArbitrageApiService(
        baseUrl: String,
        loggingEnabled: Boolean = false
    ): ArbitrageApiService {
        val okHttpClient = OkHttpClient.Builder()
            .apply {
                if (loggingEnabled) {
                    addInterceptor(
                        HttpLoggingInterceptor().apply {
                            level = HttpLoggingInterceptor.Level.BASIC
                        }
                    )
                }
            }
            .build()

        val contentType = "application/json".toMediaType()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
            .create(ArbitrageApiService::class.java)
    }
}
