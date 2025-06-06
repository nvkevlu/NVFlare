package com.nvidia.nvflare.models

import com.google.gson.annotations.SerializedName
import com.google.gson.JsonElement

data class JobResponse(
    @SerializedName("status")
    val status: String,
    
    @SerializedName("job_id")
    val jobId: String?,
    
    @SerializedName("job_name")
    val jobName: String?,
    
    @SerializedName("job_data")
    val jobData: Map<String, JsonElement>?,
    
    @SerializedName("method")
    val method: String?,
    
    @SerializedName("retry_wait")
    val retryWait: Int?,
    
    @SerializedName("message")
    val message: String?,
    
    @SerializedName("details")
    val details: Map<String, String>?
) {
    fun toJob(): Job {
        if (jobId == null) {
            throw NVFlareError.INVALID_REQUEST("Can't convert JobResponse to Job")
        }
        return Job(id = jobId, status = "running")
    }
} 