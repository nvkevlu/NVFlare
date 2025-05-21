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
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

class Connection(context: Context) {
    private val TAG = "NVFlareConnection"
    private val deviceId = Build.SERIAL ?: "unknown"
    private val appVersion = context.packageManager.getPackageInfo(context.packageName, 0).versionName
    
    private val deviceInfo = mapOf(
        "device_id" to deviceId,
        "platform" to "android",
        "app_version" to appVersion
    )
    
    private val jobEndpoint = "job"
    private val taskEndpoint = "task"
    private val resultEndpoint = "result"
    private val scheme = "http"
    
    var hostname = MutableLiveData("")
    var port = MutableLiveData(0)
    private var capabilities: Map<String, Any> = mapOf("methods" to emptyList<String>())
    
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()
    
    val isValid: Boolean
        get() = !hostname.value.isNullOrEmpty() && port.value?.let { it > 0 && it <= 65535 } ?: false
    
    private val serverURL: String
        get() = "$scheme://${hostname.value}:${port.value}"
    
    fun setCapabilities(capabilities: Map<String, Any>) {
        this.capabilities = capabilities
    }
    
    private fun getURL(endpoint: String): String {
        return "$serverURL/$endpoint"
    }
    
    private fun createRequestBuilder(endpoint: String): Request.Builder {
        val deviceInfoString = deviceInfo.entries.joinToString("&") { 
            "${it.key}=${URLEncoder.encode(it.value, "UTF-8")}"
        }
        
        val builder = Request.Builder()
            .url(getURL(endpoint))
            .addHeader("X-Flare-Device-ID", deviceId)
            .addHeader("X-Flare-Device-Info", deviceInfoString)
            .addHeader("X-Flare-User-Info", "{}")
            
        Log.d(TAG, "Creating request for endpoint: $endpoint")
        Log.d(TAG, "Headers: X-Flare-Device-ID=$deviceId")
        Log.d(TAG, "Headers: X-Flare-Device-Info=$deviceInfoString")
        Log.d(TAG, "Headers: X-Flare-User-Info={}")
        
        return builder
    }
    
    suspend fun fetchJob(): JobResponse {
        if (!isValid) {
            throw NVFlareError.INVALID_METADATA("Invalid server configuration")
        }

        val request = createRequestBuilder(jobEndpoint)
            .post(JSONObject(mapOf("capabilities" to capabilities)).toString()
                .toRequestBody("application/json".toMediaType()))
            .build()
            
        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        Log.d(TAG, "Request body: ${request.body?.toString()}")
        
        val response = client.newCall(request).execute()
        
        Log.d(TAG, "Response code: ${response.code}")
        Log.d(TAG, "Response headers: ${response.headers}")
        
        if (!response.isSuccessful) {
            Log.e(TAG, "Job fetch failed with code: ${response.code}")
            throw when (response.code) {
                400 -> NVFlareError.INVALID_METADATA("Invalid request")
                403 -> NVFlareError.AUTH_ERROR("Authentication error")
                500 -> NVFlareError.SERVER_ERROR("Server error")
                else -> NVFlareError.JOB_FETCH_FAILED
            }
        }
        
        val responseBody = response.body?.string()
        Log.d(TAG, "Response body: $responseBody")
        
        val jobResponse = responseBody?.let { 
            JobResponse.fromJson(it)
        } ?: throw NVFlareError.JOB_FETCH_FAILED
        
        return when (jobResponse.status) {
            "OK" -> jobResponse
            "RETRY" -> {
                jobResponse.retryWait?.let { delay ->
                    Log.d(TAG, "Retrying job fetch after $delay seconds")
                    kotlinx.coroutines.delay(delay * 1000L)
                    fetchJob()
                } ?: throw NVFlareError.JOB_FETCH_FAILED
            }
            else -> throw NVFlareError.JOB_FETCH_FAILED
        }
    }
    
    suspend fun fetchTask(jobId: String): TaskResponse {
        if (!isValid) {
            throw NVFlareError.INVALID_METADATA("Invalid server configuration")
        }

        val request = createRequestBuilder("$taskEndpoint?job_id=$jobId")
            .get()
            .build()
            
        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        
        val response = client.newCall(request).execute()
        
        Log.d(TAG, "Response code: ${response.code}")
        Log.d(TAG, "Response headers: ${response.headers}")
        
        if (!response.isSuccessful) {
            Log.e(TAG, "Task fetch failed with code: ${response.code}")
            throw when (response.code) {
                400 -> NVFlareError.INVALID_METADATA("Invalid request")
                403 -> NVFlareError.AUTH_ERROR("Authentication error")
                500 -> NVFlareError.SERVER_ERROR("Server error")
                else -> NVFlareError.TASK_FETCH_FAILED
            }
        }
        
        val responseBody = response.body?.string()
        Log.d(TAG, "Response body: $responseBody")
        
        val taskResponse = responseBody?.let {
            TaskResponse.fromJson(it)
        } ?: throw NVFlareError.TASK_FETCH_FAILED
        
        return when (taskResponse.status) {
            "OK", "FINISHED" -> taskResponse
            "RETRY", "NO_TASK" -> {
                taskResponse.retryWait?.let { delay ->
                    Log.d(TAG, "Retrying task fetch after $delay seconds")
                    kotlinx.coroutines.delay(delay * 1000L)
                    fetchTask(jobId)
                } ?: throw NVFlareError.TASK_FETCH_FAILED
            }
            else -> throw NVFlareError.TASK_FETCH_FAILED
        }
    }
    
    suspend fun sendResult(jobId: String, taskId: String, taskName: String, weightDiff: FloatArray) {
        if (!isValid) {
            throw NVFlareError.INVALID_METADATA("Invalid server configuration")
        }

        val request = createRequestBuilder("$resultEndpoint?job_id=$jobId&task_id=$taskId&task_name=$taskName")
            .post(JSONObject(mapOf("data" to weightDiff.toList())).toString()
                .toRequestBody("application/json".toMediaType()))
            .build()
            
        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        Log.d(TAG, "Request body: ${request.body?.toString()}")
        
        val response = client.newCall(request).execute()
        
        Log.d(TAG, "Response code: ${response.code}")
        Log.d(TAG, "Response headers: ${response.headers}")
        
        if (!response.isSuccessful) {
            Log.e(TAG, "Result send failed with code: ${response.code}")
            throw when (response.code) {
                400 -> NVFlareError.INVALID_METADATA("Invalid request")
                403 -> NVFlareError.AUTH_ERROR("Authentication error")
                500 -> NVFlareError.SERVER_ERROR("Server error")
                else -> NVFlareError.TRAINING_FAILED("Failed to send results")
            }
        }
        
        val responseBody = response.body?.string()
        Log.d(TAG, "Response body: $responseBody")
    }
}