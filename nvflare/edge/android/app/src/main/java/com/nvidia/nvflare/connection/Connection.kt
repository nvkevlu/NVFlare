package com.nvidia.nvflare.connection

import android.content.Context
import android.os.Build
import android.util.Log
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import com.nvidia.nvflare.models.JobResponse
import com.nvidia.nvflare.models.TaskResponse
import com.nvidia.nvflare.models.ResultResponse
import com.nvidia.nvflare.models.NVFlareError
import com.nvidia.nvflare.models.JSONValue
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.IOException

class Connection(
    private val baseUrl: String,
    private val clientId: String,
    private val clientName: String
) {
    private val TAG = "Connection"
    private var currentCookie: String? = null
    private var capabilities: Map<String, Any> = mapOf("methods" to emptyList<String>())
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    fun setCapabilities(capabilities: Map<String, Any>) {
        this.capabilities = capabilities
    }

    suspend fun fetchJob(): JobResponse = withContext(Dispatchers.IO) {
        val url = "$baseUrl/job"
        
        // Prepare request body with capabilities
        val requestBody = JSONObject().apply {
            put("capabilities", JSONObject(capabilities))
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", clientId)
            .header("X-Flare-Device-Info", "{}")
            .header("X-Flare-User-Info", "{}")
            .build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                throw NVFlareError.NETWORK_ERROR("Failed to fetch job: ${response.code}")
            }

            val responseBody = response.body?.string()
                ?: throw NVFlareError.NETWORK_ERROR("Empty response body")
            Log.d(TAG, "Job response: $responseBody")

            // Parse response
            val json = JSONObject(responseBody)
            val jobResponse = JobResponse(
                jobId = json.optString("job_id").takeIf { it.isNotEmpty() },
                status = json.getString("status"),
                method = json.optString("method").takeIf { it.isNotEmpty() }
            )

            // Handle retry logic
            when (jobResponse.status) {
                "OK" -> jobResponse
                "RETRY" -> {
                    val retryWait = json.optInt("retry_wait")
                    if (retryWait > 0) {
                        delay(retryWait.toLong())
                        fetchJob()
                    } else {
                        throw NVFlareError.NETWORK_ERROR("Retry failed")
                    }
                }
                else -> throw NVFlareError.NETWORK_ERROR("Invalid job status: ${jobResponse.status}")
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error fetching job", e)
            throw NVFlareError.NETWORK_ERROR("Failed to fetch job: ${e.message}")
        }
    }

    suspend fun fetchTask(jobId: String): TaskResponse = withContext(Dispatchers.IO) {
        val url = "$baseUrl/task"
        
        // Create request body with cookie
        val requestBody = JSONObject().apply {
            if (currentCookie != null) {
                put("cookie", currentCookie)
            }
            // Empty JSON object if no cookie
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", clientId)
            .header("X-Flare-Device-Info", "{}")
            .header("X-Flare-User-Info", "{}")
            .build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                throw NVFlareError.NETWORK_ERROR("Failed to fetch task: ${response.code}")
            }

            val responseBody = response.body?.string()
                ?: throw NVFlareError.NETWORK_ERROR("Empty response body")
            Log.d(TAG, "Task response: $responseBody")

            // Parse response
            val json = JSONObject(responseBody)
            val taskResponse = TaskResponse(
                taskId = json.getString("task_id"),
                name = json.getString("name"),
                status = json.getString("status"),
                modelData = json.getString("model_data"),
                trainingConfig = parseTrainingConfig(json.getJSONObject("training_config"))
            )

            // Update cookie if present
            json.optString("cookie").takeIf { it.isNotEmpty() }?.let {
                currentCookie = it
            }

            // Handle retry logic
            when (taskResponse.status) {
                "OK", "DONE" -> taskResponse
                "RETRY", "NO_TASK" -> {
                    val retryWait = json.optInt("retry_wait")
                    if (retryWait > 0) {
                        delay(retryWait.toLong())
                        fetchTask(jobId)
                    } else {
                        throw NVFlareError.NETWORK_ERROR("Retry failed")
                    }
                }
                else -> throw NVFlareError.NETWORK_ERROR("Invalid task status: ${taskResponse.status}")
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error fetching task", e)
            throw NVFlareError.NETWORK_ERROR("Failed to fetch task: ${e.message}")
        }
    }

    suspend fun sendResult(jobId: String, taskId: String, taskName: String, weightDiff: Map<String, FloatArray>) = withContext(Dispatchers.IO) {
        val url = "$baseUrl/result"
        
        // Create request body with cookie and result
        val requestBody = JSONObject().apply {
            put("result", JSONObject(weightDiff.mapValues { it.value.toList() }))
            if (currentCookie != null) {
                put("cookie", currentCookie)
            }
            // Empty JSON object if no cookie
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", clientId)
            .header("X-Flare-Device-Info", "{}")
            .header("X-Flare-User-Info", "{}")
            .build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                throw NVFlareError.NETWORK_ERROR("Failed to send result: ${response.code}")
            }

            val responseBody = response.body?.string()
                ?: throw NVFlareError.NETWORK_ERROR("Empty response body")
            Log.d(TAG, "Result response: $responseBody")

            // Parse response
            val json = JSONObject(responseBody)
            val resultResponse = ResultResponse(
                status = json.getString("status"),
                message = json.optString("message").takeIf { it.isNotEmpty() }
            )

            // Handle response status
            when (resultResponse.status) {
                "OK" -> Unit // Success
                "INVALID" -> throw NVFlareError.TRAINING_FAILED(resultResponse.message ?: "Invalid result")
                else -> throw NVFlareError.TRAINING_FAILED("Unknown status")
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error sending result", e)
            throw NVFlareError.NETWORK_ERROR("Failed to send result: ${e.message}")
        }
    }

    fun resetCookie() {
        currentCookie = null
    }

    private fun parseTrainingConfig(json: JSONObject): TrainingConfig {
        return TrainingConfig(
            method = json.getString("method"),
            epochs = json.getInt("epochs"),
            batchSize = json.getInt("batch_size"),
            learningRate = json.getDouble("learning_rate").toFloat(),
            momentum = json.getDouble("momentum").toFloat(),
            weightDecay = json.getDouble("weight_decay").toFloat()
        )
    }
}