package com.nvidia.nvflare.models

import com.google.gson.annotations.SerializedName

data class TaskResponse(
    val status: String,
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
    val cookie: JSONValue?
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
            throw NVFlareError.TASK_FETCH_FAILED(message ?: "Task status indicates training should not continue")
        }

        if (taskId == null || taskName == null || taskData == null) {
            throw NVFlareError.TASK_FETCH_FAILED("Missing required task data")
        }

        val trainingConfig = TrainingConfig()

        return TrainingTask(
            id = taskId,
            name = taskName,
            jobId = jobId,
            modelData = taskData.data,
            trainingConfig = trainingConfig
        )
    }
} 