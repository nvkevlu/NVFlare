package com.nvidia.nvflare.training

enum class MethodType(val displayName: String, val requiredDataset: String) {
    CNN("cnn", "cifar10"),
    XOR("xor", "xor")
} 