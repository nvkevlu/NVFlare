package com.nvidia.nvflare.models

import com.google.gson.annotations.SerializedName
import com.google.gson.JsonObject
import com.google.gson.JsonPrimitive
import com.google.gson.JsonArray

data class TaskResponse(
    @SerializedName("status")
    val status: String,
    
    @SerializedName("message")
    val message: String?,
    
    @SerializedName("job_id")
    val jobId: String?,
    
    @SerializedName("task_id")
    val taskId: String?,
    
    @SerializedName("task_name")
    val taskName: String?,
    
    @SerializedName("retry_wait")
    val retryWait: Int?,
    
    @SerializedName("task_data")
    val taskData: TaskData?,
    
    @SerializedName("cookie")
    val cookie: JsonObject?
) {
    data class TaskData(
        @SerializedName("data")
        val data: String,
        
        @SerializedName("meta")
        val meta: JsonObject?,
        
        @SerializedName("kind")
        val kind: String
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

    val taskStatus: TaskStatus
        get() = TaskStatus.fromString(status)

    fun toTrainingTask(jobId: String): TrainingTask {
        if (!taskStatus.shouldContinueTraining) {
            throw NVFlareError.TaskFetchFailed(message ?: "Task status indicates training should not continue")
        }

        if (taskId == null || taskName == null || taskData == null) {
            throw NVFlareError.TaskFetchFailed("Missing required task data")
        }

        // Convert meta JsonObject to Map<String, Any>
        val metaMap = taskData.meta?.let { meta ->
            meta.entrySet().associate { (key, value) ->
                key to when (value) {
                    is JsonPrimitive -> when {
                        value.isString -> value.asString
                        value.isNumber -> value.asNumber
                        value.isBoolean -> value.asBoolean
                        else -> null
                    }
                    is JsonObject -> value.asMap()
                    is JsonArray -> value.asList()
                    else -> null
                }
            }
        } ?: emptyMap()

        return TrainingTask(
            id = taskId,
            name = taskName,
            jobId = jobId,
            modelData = taskData.data,
            trainingConfig = TrainingConfig.fromMap(metaMap)
        )
    }
} 