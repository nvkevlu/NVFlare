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
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.nvidia.nvflare.models.*
import okhttp3.RequestBody
import okhttp3.MediaType
import java.util.*
import okhttp3.HttpUrl

class Connection(private val context: Context) {
    private val TAG = "Connection"
    private var currentCookie: JsonObject? = null
    private var capabilities: Map<String, Any> = mapOf("methods" to emptyList<String>())
    private val gson = Gson()
    private val httpClient = OkHttpClient()

    // Add hostname and port properties to match iOS
    var hostname: String = ""
    var port: Int = 0

    val isValid: Boolean
        get() = hostname.isNotEmpty() && port > 0 && port <= 65535

    // Device info matching iOS exactly
    private val deviceId: String = context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode.toString()
    private val deviceInfo: Map<String, String> = mapOf(
        "device_id" to deviceId,
        "platform" to "android",
        "app_version" to context.packageManager.getPackageInfo(context.packageName, 0).versionName
    )

    enum class TaskStatus(val value: String) {
        OK("OK"),
        DONE("DONE"),
        ERROR("ERROR"),
        RETRY("RETRY"),
        UNKNOWN("UNKNOWN");

        companion object {
            fun fromString(value: String): TaskStatus {
                return values().find { it.value == value } ?: UNKNOWN
            }
        }

        val isSuccess: Boolean
            get() = this == OK || this == DONE

        val shouldContinueTraining: Boolean
            get() = this == OK
    }

    fun setCapabilities(capabilities: Map<String, Any>) {
        this.capabilities = capabilities
    }

    fun resetCookie() {
        currentCookie = null
    }

    private fun infoToQueryString(info: Map<String, String>): String {
        return info.map { (key, value) -> "$key=$value" }.joinToString("&")
    }

    suspend fun fetchJob(): JobResponse = withContext(Dispatchers.IO) {
        val url = HttpUrl.Builder()
            .scheme("http")
            .host(hostname)
            .port(port)
            .addPathSegment("job")
            .build()

        // Prepare request body
        val requestBody = JSONObject().apply {
            put("capabilities", JSONObject(capabilities))
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", deviceId)
            .header("X-Flare-Device-Info", infoToQueryString(deviceInfo))
            .header("X-Flare-User-Info", "")
            .build()

        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        Log.d(TAG, "Headers: ${request.headers}")
        Log.d(TAG, "Request body: $requestBody")

        try {
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string()
            Log.d(TAG, "Response Status Code: ${response.code}")
            Log.d(TAG, "Response Headers: ${response.headers}")
            Log.d(TAG, "Response body: $responseBody")

            if (!response.isSuccessful) {
                when (response.code) {
                    400 -> throw NVFlareError.INVALID_REQUEST("Invalid request")
                    403 -> throw NVFlareError.AUTH_ERROR("Authentication error")
                    500 -> throw NVFlareError.SERVER_ERROR("Server error")
                    else -> throw NVFlareError.JOB_FETCH_FAILED
                }
            }

            val jobResponse = gson.fromJson(responseBody, JobResponse::class.java)
            when (jobResponse.status) {
                "OK" -> jobResponse
                "RETRY" -> {
                    val retryWait = jobResponse.retryWait ?: 5000
                    Log.d(TAG, "Retrying job fetch after $retryWait ms")
                    kotlinx.coroutines.delay(retryWait.toLong())
                    fetchJob()
                }
                else -> throw NVFlareError.JOB_FETCH_FAILED
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error fetching job", e)
            throw NVFlareError.JOB_FETCH_FAILED
        }
    }

    suspend fun fetchTask(jobId: String): TaskResponse = withContext(Dispatchers.IO) {
        val url = HttpUrl.Builder()
            .scheme("http")
            .host(hostname)
            .port(port)
            .addPathSegment("task")
            .addQueryParameter("job_id", jobId)
            .build()

        // Prepare request body with cookie
        val requestBody = if (currentCookie != null) {
            JSONObject().apply {
                put("cookie", JSONObject(currentCookie.toString()))
            }
        } else {
            JSONObject() // Empty JSON object like iOS
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", deviceId)
            .header("X-Flare-Device-Info", infoToQueryString(deviceInfo))
            .header("X-Flare-User-Info", "{}")
            .build()

        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        Log.d(TAG, "Headers: ${request.headers}")
        Log.d(TAG, "Request body: $requestBody")

        try {
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string()
            Log.d(TAG, "Response Status Code: ${response.code}")
            Log.d(TAG, "Response Headers: ${response.headers}")
            Log.d(TAG, "Response body: $responseBody")

            if (!response.isSuccessful) {
                when (response.code) {
                    400 -> throw NVFlareError.INVALID_REQUEST("Invalid request")
                    403 -> throw NVFlareError.AUTH_ERROR("Authentication error")
                    500 -> throw NVFlareError.SERVER_ERROR("Server error")
                    else -> throw NVFlareError.TASK_FETCH_FAILED("Task fetch failed")
                }
            }

            val taskResponse = gson.fromJson(responseBody, TaskResponse::class.java)
            
            // Update cookie if present
            taskResponse.cookie?.let { currentCookie = it }

            // Check task status using enum
            val taskStatus = TaskStatus.fromString(taskResponse.status)
            if (!taskStatus.shouldContinueTraining) {
                throw NVFlareError.TASK_FETCH_FAILED(taskResponse.message ?: "Task status indicates training should not continue")
            }

            when (taskStatus) {
                TaskStatus.OK -> taskResponse
                TaskStatus.RETRY -> {
                    val retryWait = taskResponse.retryWait ?: 5000
                    Log.d(TAG, "Retrying task fetch after $retryWait ms")
                    kotlinx.coroutines.delay(retryWait.toLong())
                    fetchTask(jobId)
                }
                else -> throw NVFlareError.TASK_FETCH_FAILED(taskResponse.message ?: "Task fetch failed")
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error fetching task", e)
            throw NVFlareError.TASK_FETCH_FAILED("Network error")
        }
    }

    suspend fun sendResult(jobId: String, taskId: String, taskName: String, weightDiff: String): ResultResponse = withContext(Dispatchers.IO) {
        val url = HttpUrl.Builder()
            .scheme("http")
            .host(hostname)
            .port(port)
            .addPathSegment("result")
            .build()

        // Prepare request body
        val requestBody = JSONObject().apply {
            put("job_id", jobId)
            put("task_id", taskId)
            put("task_name", taskName)
            put("result", weightDiff)
            if (currentCookie != null) {
                put("cookie", JSONObject(currentCookie.toString()))
            }
        }

        val request = Request.Builder()
            .url(url)
            .post(requestBody.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Flare-Device-ID", deviceId)
            .header("X-Flare-Device-Info", infoToQueryString(deviceInfo))
            .header("X-Flare-User-Info", "{}")
            .build()

        Log.d(TAG, "Sending request: ${request.method} ${request.url}")
        Log.d(TAG, "Headers: ${request.headers}")
        Log.d(TAG, "Request body: $requestBody")

        try {
            val response = httpClient.newCall(request).execute()
            val responseBody = response.body?.string()
            Log.d(TAG, "Response Status Code: ${response.code}")
            Log.d(TAG, "Response Headers: ${response.headers}")
            Log.d(TAG, "Response body: $responseBody")

            if (!response.isSuccessful) {
                when (response.code) {
                    400 -> throw NVFlareError.INVALID_REQUEST("Invalid request")
                    403 -> throw NVFlareError.AUTH_ERROR("Authentication error")
                    500 -> throw NVFlareError.SERVER_ERROR("Server error")
                    else -> throw NVFlareError.RESULT_SEND_FAILED("Result send failed")
                }
            }

            val resultResponse = gson.fromJson(responseBody, ResultResponse::class.java)
            when (resultResponse.status) {
                "OK" -> resultResponse
                else -> throw NVFlareError.RESULT_SEND_FAILED(resultResponse.message ?: "Unknown error")
            }
        } catch (e: IOException) {
            Log.e(TAG, "Network error sending result", e)
            throw NVFlareError.RESULT_SEND_FAILED("Network error")
        }
    }

    suspend fun getCapabilities(): Map<String, Any> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/capabilities")
            .addHeader("X-Client-ID", clientId)
            .addHeader("X-Client-Name", clientName)
            .addHeader("X-Client-Token", clientToken)
            .build()

        try {
            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) {
                throw NVFlareError.NETWORK_ERROR
            }

            val responseBody = response.body?.string() ?: throw NVFlareError.NETWORK_ERROR
            val jsonObject = gson.fromJson(responseBody, JsonObject::class.java)
            jsonObject.asMap()
        } catch (e: IOException) {
            throw NVFlareError.NETWORK_ERROR
        }
    }

    private fun JsonObject.asMap(): Map<String, Any> {
        val map = mutableMapOf<String, Any>()
        entrySet().forEach { (key, value) ->
            map[key] = when {
                value.isJsonPrimitive -> value.asJsonPrimitive.asString
                value.isJsonObject -> value.asJsonObject.asMap()
                value.isJsonArray -> value.asJsonArray.map { it.asString }
                else -> value.toString()
            }
        }
        return map
    }

    private fun JSONObject.toMap(): Map<String, Any> {
        val map = mutableMapOf<String, Any>()
        keys().forEach { key ->
            map[key] = get(key)
        }
        return map
    }
}