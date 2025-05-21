package com.nvidia.nvflare.models

import org.json.JSONObject

data class JobResponse(
    val status: String,
    val message: String?,
    val retryWait: Int?,
    val jobId: String?,
    val meta: Map<String, Any>?
) {
    companion object {
        fun fromJson(json: String): JobResponse {
            val obj = JSONObject(json)
            return JobResponse(
                status = obj.getString("status"),
                message = obj.optString("message"),
                retryWait = obj.optInt("retry_wait").takeIf { it > 0 },
                jobId = obj.optString("job_id").takeIf { it.isNotEmpty() },
                meta = obj.optJSONObject("meta")?.toMap()
            )
        }
    }
}

fun JobResponse.toJob(): Job {
    if (jobId == null) {
        throw NVFlareError.INVALID_METADATA("Missing job_id in response")
    }
    if (meta == null) {
        throw NVFlareError.INVALID_METADATA("Missing meta in response")
    }
    return Job(
        id = jobId,
        status = status,
        meta = JobMeta(
            method = meta["method"] as? String,
            modelType = meta["model_type"] as? String
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

private fun JSONObject.toMap(): Map<String, Any> {
    val map = mutableMapOf<String, Any>()
    val keys = this.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        val value = this.get(key)
        map[key] = when (value) {
            is JSONObject -> value.toMap()
            is org.json.JSONArray -> value.toList()
            else -> value
        }
    }
    return map
}

private fun org.json.JSONArray.toList(): List<Any> {
    val list = mutableListOf<Any>()
    for (i in 0 until this.length()) {
        val value = this.get(i)
        list.add(when (value) {
            is JSONObject -> value.toMap()
            is org.json.JSONArray -> value.toList()
            else -> value
        })
    }
    return list
} 