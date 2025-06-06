package com.nvidia.nvflare.models

import com.google.gson.annotations.SerializedName

data class ResultResponse(
    @SerializedName("status")
    val status: String,
    
    @SerializedName("task_id")
    val taskId: String?,
    
    @SerializedName("task_name")
    val taskName: String?,
    
    @SerializedName("job_id")
    val jobId: String?,
    
    @SerializedName("message")
    val message: String?,
    
    @SerializedName("details")
    val details: Map<String, String>?
) 