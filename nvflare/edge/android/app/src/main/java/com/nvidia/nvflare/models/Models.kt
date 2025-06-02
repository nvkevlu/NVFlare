package com.nvidia.nvflare.models

import org.json.JSONObject
import org.json.JSONArray

data class JobResponse(
    val status: String,
    val message: String?,
    val retryWait: Int?,
    val jobId: String?,
    val jobName: String?,
    val jobMeta: Map<String, Any>?,
    val method: String?,
    val details: Map<String, String>?
) {
    companion object {
        fun fromJson(json: String): JobResponse {
            val obj = JSONObject(json)
            return JobResponse(
                status = obj.getString("status"),
                message = obj.optString("message"),
                retryWait = obj.optInt("retry_wait").takeIf { it > 0 },
                jobId = obj.optString("job_id").takeIf { it.isNotEmpty() },
                jobName = obj.optString("job_name").takeIf { it.isNotEmpty() },
                jobMeta = obj.optJSONObject("job_meta")?.toMap(),
                method = obj.optString("method").takeIf { it.isNotEmpty() },
                details = obj.optJSONObject("details")?.toMap()?.mapValues { it.value.toString() }
            )
        }
    }
}

// Extension function to convert JSONObject to Map
private fun JSONObject.toMap(): Map<String, Any> {
    val map = mutableMapOf<String, Any>()
    val keys = this.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        val value = this.get(key)
        map[key] = when (value) {
            is JSONObject -> value.toMap()
            is JSONArray -> value.toList()
            else -> value
        }
    }
    return map
}

// Extension function to convert JSONArray to List
private fun JSONArray.toList(): List<Any> {
    val list = mutableListOf<Any>()
    for (i in 0 until this.length()) {
        val value = this.get(i)
        list.add(when (value) {
            is JSONObject -> value.toMap()
            is JSONArray -> value.toList()
            else -> value
        })
    }
    return list
}

fun JobResponse.toJob(): Job {
    if (jobId == null) {
        throw NVFlareError.INVALID_METADATA("Missing job_id in response")
    }
    if (jobMeta == null) {
        throw NVFlareError.INVALID_METADATA("Missing job_meta in response")
    }
    
    // Extract method from either direct method field or job_meta
    val methodString = method ?: jobMeta["edge_method"] as? String
        ?: throw NVFlareError.INVALID_METADATA("Missing method in job metadata")
    
    return Job(
        id = jobId,
        status = status,
        meta = JobMeta(
            method = methodString,
            modelType = jobMeta["model_type"] as? String
        )
    )
}

data class TaskStatus(
    val shouldContinueTraining: Boolean
)

data class TaskResponse(
    val status: String,
    val message: String?,
    val retryWait: Int?,
    val taskId: String?,
    val taskName: String?,
    val data: Map<String, Any>?,
    val taskStatus: TaskStatus
) {
    companion object {
        fun fromJson(json: String): TaskResponse {
            val obj = JSONObject(json)
            val taskStatusObj = obj.optJSONObject("task_status") ?: JSONObject()
            return TaskResponse(
                status = obj.getString("status"),
                message = obj.optString("message"),
                retryWait = obj.optInt("retry_wait").takeIf { it > 0 },
                taskId = obj.optString("task_id").takeIf { it.isNotEmpty() },
                taskName = obj.optString("task_name").takeIf { it.isNotEmpty() },
                data = obj.optJSONObject("data")?.toMap(),
                taskStatus = TaskStatus(
                    shouldContinueTraining = taskStatusObj.optBoolean("should_continue_training", true)
                )
            )
        }
    }
}

data class ResultResponse(
    val status: String,
    val message: String?
) {
    companion object {
        fun fromJson(json: String): ResultResponse {
            val obj = JSONObject(json)
            return ResultResponse(
                status = obj.getString("status"),
                message = obj.optString("message")
            )
        }
    }
}

data class TrainingTask(
    val id: String,
    val name: String,
    val modelData: Map<String, String>
)

fun TaskResponse.toTrainingTask(jobId: String): TrainingTask {
    if (taskId == null) {
        throw NVFlareError.INVALID_METADATA("Missing task_id in response")
    }
    if (taskName == null) {
        throw NVFlareError.INVALID_METADATA("Missing task_name in response")
    }
    if (data == null) {
        throw NVFlareError.INVALID_METADATA("Missing data in response")
    }
    
    return TrainingTask(
        id = taskId,
        name = taskName,
        modelData = data.mapValues { it.value.toString() }
    )
} 