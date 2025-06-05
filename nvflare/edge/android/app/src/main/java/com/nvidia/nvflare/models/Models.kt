package com.nvidia.nvflare.models

import org.json.JSONObject
import org.json.JSONArray
import java.util.Base64
import com.google.gson.annotations.SerializedName

// Dataset Types
object DatasetType {
    const val CIFAR10 = "cifar10"
    const val XOR = "xor"
}

// Meta Keys
object MetaKey {
    const val DATASET_TYPE = "dataset_type"
    const val BATCH_SIZE = "batch_size"
    const val LEARNING_RATE = "learning_rate"
    const val TOTAL_EPOCHS = "total_epochs"
    const val DATASET_SHUFFLE = "dataset_shuffle"
}

// Model Exchange Format Constants
object ModelExchangeFormat {
    const val MODEL_BUFFER = "model_buffer"
    const val MODEL_BUFFER_TYPE = "model_buffer_type"
    const val MODEL_BUFFER_NATIVE_FORMAT = "model_buffer_native_format"
    const val MODEL_BUFFER_ENCODING = "model_buffer_encoding"
}

// Model Buffer Types
enum class ModelBufferType {
    EXECUTORCH,
    PYTORCH,
    TENSORFLOW,
    UNKNOWN;

    companion object {
        fun fromString(value: String): ModelBufferType {
            return try {
                valueOf(value.uppercase())
            } catch (e: IllegalArgumentException) {
                UNKNOWN
            }
        }
    }
}

// Model Native Formats
enum class ModelNativeFormat {
    BINARY,
    JSON,
    UNKNOWN;

    companion object {
        fun fromString(value: String): ModelNativeFormat {
            return try {
                valueOf(value.uppercase())
            } catch (e: IllegalArgumentException) {
                UNKNOWN
            }
        }
    }
}

// Model Encodings
enum class ModelEncoding {
    BASE64,
    RAW,
    UNKNOWN;

    companion object {
        fun fromString(value: String): ModelEncoding {
            return try {
                valueOf(value.uppercase())
            } catch (e: IllegalArgumentException) {
                UNKNOWN
            }
        }
    }
}

// JSON Value Types
sealed class JSONValue {
    data class StringValue(val value: String) : JSONValue()
    data class IntValue(val value: Int) : JSONValue()
    data class DoubleValue(val value: Double) : JSONValue()
    data class BooleanValue(val value: Boolean) : JSONValue()
    data class ArrayValue(val value: List<JSONValue>) : JSONValue()
    data class ObjectValue(val value: Map<String, JSONValue>) : JSONValue()
    object NullValue : JSONValue()

    companion object {
        fun fromJSONObject(json: JSONObject): ObjectValue {
            val map = mutableMapOf<String, JSONValue>()
            json.keys().forEach { key ->
                map[key] = fromAny(json.get(key))
            }
            return ObjectValue(map)
        }

        fun fromJSONArray(json: JSONArray): ArrayValue {
            val list = mutableListOf<JSONValue>()
            for (i in 0 until json.length()) {
                list.add(fromAny(json.get(i)))
            }
            return ArrayValue(list)
        }

        private fun fromAny(value: Any): JSONValue {
            return when (value) {
                is String -> StringValue(value)
                is Int -> IntValue(value)
                is Double -> DoubleValue(value)
                is Boolean -> BooleanValue(value)
                is JSONObject -> fromJSONObject(value)
                is JSONArray -> fromJSONArray(value)
                JSONObject.NULL -> NullValue
                else -> NullValue
            }
        }
    }
}

// Task Headers
object TaskHeaderKey {
    const val TASK_SEQ = "task_seq"
    const val UPDATE_INTERVAL = "update_interval"
    const val CURRENT_ROUND = "current_round"
    const val NUM_ROUNDS = "num_rounds"
    const val CONTRIBUTION_ROUND = "contribution_round"
}

// Task Response
data class TaskResponse(
    val status: String,
    val message: String?,
    val jobId: String?,
    val taskId: String?,
    val taskName: String?,
    val retryWait: Int?,
    val taskData: TaskData?,
    val cookie: JSONValue?,
    val headers: Map<String, Any> = emptyMap()
) {
    data class TaskData(
        val data: String,
        val meta: JSONValue,
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

        val currentRound = headers[TaskHeaderKey.CURRENT_ROUND] as? Int ?: 0
        val numRounds = headers[TaskHeaderKey.NUM_ROUNDS] as? Int ?: 1
        val updateInterval = headers[TaskHeaderKey.UPDATE_INTERVAL] as? Float ?: 1.0f

        return TrainingTask(
            id = taskId,
            name = taskName,
            jobId = jobId,
            modelData = taskData.data,
            trainingConfig = TrainingConfig(),
            currentRound = currentRound,
            numRounds = numRounds,
            updateInterval = updateInterval
        )
    }
}

// Job Response
data class JobResponse(
    val status: String,
    val jobId: String?,
    val jobName: String?,
    val jobData: Map<String, Any>?,
    val method: String?,
    val retryWait: Int?,
    val message: String?,
    val details: Map<String, String>?
) {
    fun toJob(): Job {
        if (jobId == null) {
            throw NVFlareError.InvalidRequest("Can't convert JobResponse to Job")
        }
        return Job(id = jobId, status = "running")
    }
}

// Job
data class Job(
    val id: String,
    val status: String
)

// Training Config
data class TrainingConfig(
    val totalEpochs: Int = 1,
    val batchSize: Int = 4,
    val learningRate: Float = 0.1f,
    val method: String = "cnn",
    val dataSetType: String = DatasetType.CIFAR10
) {
    companion object {
        fun fromMap(data: Map<String, Any>): TrainingConfig {
            return TrainingConfig(
                totalEpochs = (data[MetaKey.TOTAL_EPOCHS] as? Number)?.toInt() ?: 1,
                batchSize = (data[MetaKey.BATCH_SIZE] as? Number)?.toInt() ?: 4,
                learningRate = (data[MetaKey.LEARNING_RATE] as? Number)?.toFloat() ?: 0.1f,
                method = data["method"] as? String ?: "xor",
                dataSetType = data[MetaKey.DATASET_TYPE] as? String ?: DatasetType.XOR
            )
        }
    }

    fun toMap(): Map<String, Any> = mapOf(
        MetaKey.TOTAL_EPOCHS to totalEpochs,
        MetaKey.BATCH_SIZE to batchSize,
        MetaKey.LEARNING_RATE to learningRate,
        "method" to method,
        MetaKey.DATASET_TYPE to dataSetType
    )
}

// Training Task
data class TrainingTask(
    val id: String,
    val name: String,
    val jobId: String,
    val modelData: String,
    val trainingConfig: TrainingConfig,
    val currentRound: Int = 0,
    val numRounds: Int = 1,
    val updateInterval: Float = 1.0f
)

// Result Response
data class ResultResponse(
    val status: String,
    val taskId: String?,
    val taskName: String?,
    val jobId: String?,
    val message: String?,
    val details: Map<String, String>?
) {
    companion object {
        fun fromJSON(json: JSONObject): ResultResponse {
            return ResultResponse(
                status = json.getString("status"),
                taskId = json.optString("task_id"),
                taskName = json.optString("task_name"),
                jobId = json.optString("job_id"),
                message = json.optString("message"),
                details = json.optJSONObject("details")?.let { details ->
                    val map = mutableMapOf<String, String>()
                    details.keys().forEach { key ->
                        map[key] = details.getString(key)
                    }
                    map
                }
            )
        }
    }
}

// NVFlare Error
sealed class NVFlareError : Exception() {
    // Network related
    data class JobFetchFailed(override val message: String = "Failed to fetch job") : NVFlareError()
    data class TaskFetchFailed(override val message: String) : NVFlareError()
    data class InvalidRequest(override val message: String) : NVFlareError()
    data class AuthError(override val message: String) : NVFlareError()
    data class ServerError(override val message: String) : NVFlareError()

    // Training related
    data class InvalidMetadata(override val message: String) : NVFlareError()
    data class InvalidModelData(override val message: String) : NVFlareError()
    data class TrainingFailed(override val message: String) : NVFlareError()
    object ServerRequestedStop : NVFlareError() {
        override val message: String = "Server requested stop"
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