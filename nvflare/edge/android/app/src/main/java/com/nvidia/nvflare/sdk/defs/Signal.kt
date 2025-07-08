package com.nvidia.nvflare.sdk.defs

/**
 * Signal for handling abort/stop operations in the edge SDK.
 */
class Signal {
    @Volatile
    private var triggered = false
    private var triggerData: Any? = null

    /**
     * Check if the signal has been triggered.
     */
    val isTriggered: Boolean
        get() = triggered

    /**
     * Get the data associated with the trigger.
     */
    fun getTriggerData(): Any? = triggerData

    /**
     * Trigger the signal with optional data.
     */
    fun trigger(data: Any? = null) {
        triggered = true
        triggerData = data
    }

    /**
     * Reset the signal.
     */
    fun reset() {
        triggered = false
        triggerData = null
    }
} 