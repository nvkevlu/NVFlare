package com.nvidia.nvflare.models

sealed class NVFlareError : Exception() {
    // Network related
    object JOB_FETCH_FAILED : NVFlareError()
    data class TASK_FETCH_FAILED(val message: String) : NVFlareError()
    data class INVALID_REQUEST(val message: String) : NVFlareError()
    data class AUTH_ERROR(val message: String) : NVFlareError()
    data class SERVER_ERROR(val message: String) : NVFlareError()
    
    // Training related
    data class INVALID_METADATA(val message: String) : NVFlareError()
    data class INVALID_MODEL_DATA(val message: String) : NVFlareError()
    data class TRAINING_FAILED(val message: String) : NVFlareError()
    object SERVER_REQUESTED_STOP : NVFlareError()
} 