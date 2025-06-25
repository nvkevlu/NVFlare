package com.nvidia.nvflare.models

import com.google.gson.annotations.SerializedName
import com.google.gson.JsonObject
import com.google.gson.JsonPrimitive
import com.google.gson.JsonArray
import com.google.gson.JsonElement

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
        @SerializedName("kind")
        val kind: String,
        
        @SerializedName("data")
        val data: JsonElement,
        
        @SerializedName("meta")
        val meta: JsonObject?
    ) {
        fun toDXO(): DXO {
            // Convert data JsonElement to Map<String, Any>
            val dataMap = when (data) {
                is JsonObject -> data.asMap()
                is JsonPrimitive -> mapOf("value" to when {
                    data.isString -> data.asString
                    data.isNumber -> data.asNumber
                    data.isBoolean -> data.asBoolean
                    else -> null
                })
                is JsonArray -> mapOf("array" to data.asList())
                else -> emptyMap()
            }
            
            // Convert meta JsonObject to Map<String, Any>
            val metaMap = meta?.asMap() ?: emptyMap()
            
            return DXO(
                kind = kind,
                data = dataMap,
                meta = metaMap
            )
        }
    }

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

        // Convert task data to DXO format
        val dxo = taskData.toDXO()
        
        // Extract model data from DXO based on kind
        val modelData = when (dxo.kind) {
            DataKind.EXECUTORCH_PTE -> {
                // For Executorch models, data should contain the model buffer
                when (val modelBuffer = dxo.data["model_buffer"]) {
                    is String -> modelBuffer
                    else -> throw NVFlareError.TaskFetchFailed("Invalid model buffer format for Executorch PTE")
                }
            }
            DataKind.MODEL -> {
                // For regular models, convert data to JSON string
                com.google.gson.Gson().toJson(dxo.data)
            }
            DataKind.WEIGHTS, DataKind.WEIGHT_DIFF -> {
                // For weight data, convert to JSON string
                com.google.gson.Gson().toJson(dxo.data)
            }
            else -> {
                // Default case, convert data to JSON string
                com.google.gson.Gson().toJson(dxo.data)
            }
        }

        // Use meta from DXO for training config
        val trainingConfig = TrainingConfig.fromMap(dxo.meta)

        return TrainingTask(
            id = taskId,
            name = taskName,
            jobId = jobId,
            modelData = modelData,
            trainingConfig = trainingConfig
        )
    }
} 