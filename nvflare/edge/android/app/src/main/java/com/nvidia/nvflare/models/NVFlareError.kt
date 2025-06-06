package com.nvidia.nvflare.models

sealed class NVFlareError(message: String) : Exception(message) {
    object JOB_FETCH_FAILED : NVFlareError("Failed to fetch job")
    object TASK_FETCH_FAILED : NVFlareError("Failed to fetch task")
    object SERVER_REQUESTED_STOP : NVFlareError("Server requested stop")
    object NETWORK_ERROR : NVFlareError("Network error occurred")
    data class TRAINING_FAILED(override val message: String) : NVFlareError(message)
    data class INVALID_METADATA(override val message: String) : NVFlareError(message)
    data class INVALID_MODEL_DATA(override val message: String) : NVFlareError(message)
    data class AUTH_ERROR(override val message: String) : NVFlareError(message)
    data class SERVER_ERROR(override val message: String) : NVFlareError(message)
} 