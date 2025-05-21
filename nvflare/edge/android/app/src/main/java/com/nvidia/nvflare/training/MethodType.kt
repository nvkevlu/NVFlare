package com.nvidia.nvflare.training

enum class MethodType(val displayName: String) {
    CIFAR10("CIFAR-10"),
    XOR("XOR");

    val requiredDataset: String
        get() = name.lowercase() // For now, they match 1:1
} 