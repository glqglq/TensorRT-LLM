/*
 * Copyright (c) 2019-2023, NVIDIA CORPORATION.  All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#pragma once

#include "cutlass/gemm_coord.h"
#include <NvInferRuntime.h>

namespace tensorrt_llm
{
namespace kernels
{

void gropuedGemm(std::vector<cutlass::gemm::GemmCoord> problem_sizes, std::vector<void*> ptrA, std::vector<void*> ptrB,
    std::vector<void*> ptrC, std::vector<void*> ptrD, void* workspace, int64_t workSpaceSize, void* cublasWorkSpace,
    int64_t cublasWorkspaceSize, bool isLoraIn, nvinfer1::DataType dataType, cudaStream_t stream);

} // namespace kernels

} // namespace tensorrt_llm
