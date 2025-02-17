/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#include "tensorrt_llm/common/memoryUtils.h"
#include "tensorrt_llm/plugins/api/tllmPlugin.h"
#include "tensorrt_llm/runtime/iTensor.h"
#include "tensorrt_llm/runtime/tllmLogger.h"
#include "tensorrt_llm/runtime/tllmRuntime.h"
#include "tensorrt_llm/runtime/worldConfig.h"

#include <NvInfer.h>
#include <chrono>
#include <cxxopts.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <sstream>
#include <string>

using namespace tensorrt_llm::runtime;

namespace tc = tensorrt_llm::common;
namespace trt = nvinfer1;

namespace
{
// follows https://github.com/NVIDIA/TensorRT/blob/release/8.6/samples/common/sampleEngines.cpp
std::vector<uint8_t> loadEngine(std::string const& enginePath)
{
    std::ifstream engineFile(enginePath, std::ios::binary);
    TLLM_CHECK_WITH_INFO(engineFile.good(), std::string("Error opening engine file: " + enginePath));
    engineFile.seekg(0, std::ifstream::end);
    auto const size = engineFile.tellg();
    engineFile.seekg(0, std::ifstream::beg);

    std::vector<uint8_t> engineBlob(size);
    engineFile.read(reinterpret_cast<char*>(engineBlob.data()), size);
    TLLM_CHECK_WITH_INFO(engineFile.good(), std::string("Error loading engine file: " + enginePath));
    return engineBlob;
}

std::string engineFilename(
    std::filesystem::path const& dataPath, WorldConfig const& worldConfig, std::string const& model)
{
    auto constexpr allowExceptions = true;
    auto constexpr ingoreComments = true;
    auto const jsonFilePath = dataPath / "config.json";
    TLLM_CHECK_WITH_INFO(
        std::filesystem::exists(jsonFilePath), std::string("File does not exist: ") + jsonFilePath.string());
    std::ifstream jsonStream(jsonFilePath);
    auto const json = nlohmann::json::parse(jsonStream, nullptr, allowExceptions, ingoreComments);
    auto const& builderConfig = json.at("builder_config");
    auto const precision = builderConfig.at("precision").template get<std::string>();
    auto const worldSize = builderConfig.at("tensor_parallel").template get<SizeType>();

    TLLM_CHECK_WITH_INFO(worldSize == worldConfig.getSize(), "world size mismatch");
    return model + "_" + precision + "_tp" + std::to_string(worldConfig.getSize()) + "_rank"
        + std::to_string(worldConfig.getRank()) + ".engine";
}

void benchmarkBert(std::string const& modelName, std::filesystem::path const& dataPath,
    std::vector<int> const& batchSizes, std::vector<int> const& inLens,
    std::shared_ptr<nvinfer1::ILogger> const& logger, int warmUp, int numRuns, int duration)
{
    auto const worldConfig = WorldConfig::mpi();
    auto const enginePath = dataPath / engineFilename(dataPath, worldConfig, modelName);
    auto engineBlob = loadEngine(enginePath.string());

    auto rt = std::make_shared<TllmRuntime>(engineBlob.data(), engineBlob.size(), *logger);
    rt->addContext(0);

    for (auto inLen : inLens)
    {
        for (auto const batchSize : batchSizes)
        {
            auto& allocator = rt->getBufferManager();
            TllmRuntime::TensorMap tensorMap{};

            // input_ids
            std::vector<SizeType> inputIdsHost(batchSize * inLen, inLen);
            auto inputIdsBuffer = std::shared_ptr<ITensor>{
                allocator.copyFrom(inputIdsHost, ITensor::makeShape({batchSize, inLen}), MemoryType::kGPU)};
            allocator.setZero(*inputIdsBuffer);
            tensorMap.insert(std::make_pair("input_ids", inputIdsBuffer));
            // input_lengths
            std::vector<SizeType> inputLenghtsHost(batchSize);
            auto inLensBuffer = std::shared_ptr<ITensor>{
                allocator.copyFrom(inputLenghtsHost, ITensor::makeShape({batchSize}), MemoryType::kGPU)};
            allocator.setZero(*inLensBuffer);
            tensorMap.insert(std::make_pair("input_lengths", inLensBuffer));

            rt->setInputTensors(0, tensorMap);
            rt->setOutputTensors(0, tensorMap);
            cudaDeviceSynchronize();

            for (auto r = 0; r < warmUp; ++r)
            {
                rt->executeContext(0);
                rt->getStream().synchronize();
            }
            cudaDeviceSynchronize();

            int iterIdx = 0;
            float curDuration = 0;
            while (iterIdx < numRuns || curDuration / 1000 < duration)
            {
                auto const start = std::chrono::steady_clock::now();
                rt->executeContext(0);
                rt->getStream().synchronize();
                auto const end = std::chrono::steady_clock::now();

                iterIdx += 1;
                curDuration
                    += (static_cast<float>(std::chrono::duration_cast<std::chrono::microseconds>(end - start).count())
                        / 1000);
            }
            printf("Benchmarking done. Iteration: %d, duration: %.2f sec.\n", iterIdx, curDuration / 1000);

            auto averageLatency = curDuration / iterIdx;

            if (worldConfig.getRank() == 0)
            {
                printf(
                    "[BENCHMARK] batch_size %d input_length %d latency(ms) %.2f\n", batchSize, inLen, averageLatency);
            }
        }
    }
}

} // namespace

// int main(int argc, char* argv[])
// {
//     cxxopts::Options options("TensorRT-LLM C++ Runtime Benchmark", "TensorRT-LLM C++ Runtime Benchmark for BERT.");
//     options.add_options()("h,help", "Print usage");
//     options.add_options()(
//         "m,model", "Model name specified for engines.", cxxopts::value<std::string>()->default_value("bert_base"));
//     options.add_options()("engine_dir", "Directory that store the engines.", cxxopts::value<std::string>());
//     options.add_options()("batch_size",
//         "Specify batch size(s) you want to benchmark. Multiple batch sizes can be separated by \";\", example: "
//         "\"1;8;64\".",
//         cxxopts::value<std::string>()->default_value("8"));
//     options.add_options()("input_len",
//         "Specify input length(s) you want to benchmark. Multiple input lengths can be "
//         "separated by \";\", example: \"60;128\".",
//         cxxopts::value<std::string>()->default_value("128"));

//     options.add_options()("log_level", "Choose log level between verbose/info/warning/error/internal_error.",
//         cxxopts::value<std::string>()->default_value("error"));
//     options.add_options()(
//         "warm_up", "Specify warm up iterations before benchmark starts.", cxxopts::value<int>()->default_value("2"));
//     options.add_options()("num_runs", "Minimal number of iterations to run during benchmarking.",
//         cxxopts::value<int>()->default_value("10"));
//     options.add_options()("duration", "Minimal duration of iterations to measure in seconds.",
//         cxxopts::value<int>()->default_value("60"));

//     auto result = options.parse(argc, argv);

//     if (result.count("help"))
//     {
//         std::cout << options.help() << std::endl;
//         exit(0);
//     }

//     // Argument: Engine directory
//     if (!result.count("engine_dir"))
//     {
//         std::cout << options.help() << std::endl;
//         TLLM_LOG_ERROR("Please specify engine directory.");
//         return 1;
//     }

//     // Argument: Batch sizes
//     std::istringstream ssBatchSizesArg;
//     ssBatchSizesArg.str(result["batch_size"].as<std::string>());
//     std::vector<int> batchSizes;
//     for (std::string token; std::getline(ssBatchSizesArg, token, ';');)
//     {
//         batchSizes.push_back(std::stoi(token));
//     }

//     // Argument : Input lengths
//     std::istringstream ssInLenArg;
//     ssInLenArg.str(result["input_len"].as<std::string>());
//     std::vector<int> inLens;
//     for (std::string token; std::getline(ssInLenArg, token, ';');)
//     {
//         inLens.push_back(std::stoi(token));
//     }

//     // Argument: Log level
//     auto logger = std::make_shared<TllmLogger>();
//     auto const logLevel = result["log_level"].as<std::string>();
//     if (logLevel == "verbose")
//     {
//         logger->setLevel(trt::ILogger::Severity::kVERBOSE);
//     }
//     else if (logLevel == "info")
//     {
//         logger->setLevel(trt::ILogger::Severity::kINFO);
//     }
//     else if (logLevel == "warning")
//     {
//         logger->setLevel(trt::ILogger::Severity::kWARNING);
//     }
//     else if (logLevel == "error")
//     {
//         logger->setLevel(trt::ILogger::Severity::kERROR);
//     }
//     else if (logLevel == "internal_error")
//     {
//         logger->setLevel(trt::ILogger::Severity::kINTERNAL_ERROR);
//     }
//     else
//     {
//         TLLM_LOG_ERROR("Unexpected log level: " + logLevel);
//         return 1;
//     }
//     initTrtLlmPlugins(logger.get());

//     try
//     {
//         benchmarkBert(result["model"].as<std::string>(), result["engine_dir"].as<std::string>(), batchSizes, inLens,
//             logger, result["warm_up"].as<int>(), result["num_runs"].as<int>(), result["duration"].as<int>());
//     }
//     catch (const std::exception& e)
//     {
//         TLLM_LOG_ERROR(e.what());
//         return 1;
//     }
//     return 0;
// }

int main(int argc, char* argv[]){
    std::string enginePath = "/workspace/models/trt_engines/llama-2-7b/fp16/test-gpu/llama_float16_tp2_rank0.engine";
    auto engineBlob = loadEngine(enginePath);
    auto logger = std::make_shared<TllmLogger>();
    logger->setLevel(trt::ILogger::Severity::kINFO);
    initTrtLlmPlugins(logger.get());
    std::cout << engineBlob.size() <<std::endl;
    auto rt = std::make_shared<TllmRuntime>(engineBlob.data(), engineBlob.size(), *logger);
    rt->addContext(0);
    std::vector<int> inLens;
    inLens.push_back(13);
    std::vector<int> batchSizes;
    batchSizes.push_back(1);
    TllmRuntime::TensorMap tensorMap{};
    
    auto const inputName = rt->getEngine().getIOTensorName(0);
    std::cout << inputName << std::endl;
    auto const inputDims = rt->getEngine().getTensorShape(inputName);
    std::cout << inputDims.d[0] << std::endl;
    auto const outputName = rt->getEngine().getIOTensorName(2);
    std::cout << outputName << std::endl;
    auto dataType = rt->getEngine().getTensorDataType(inputName);

    auto& allocator = rt->getBufferManager();
    nvinfer1::Dims dim;
    dim.nbDims = 1;
    dim.d[0] = 13;
    auto inputBuffer = std::shared_ptr<ITensor>{allocator.gpu(dim, dataType)};
    
    allocator.setZero(*inputBuffer);
    tensorMap.insert(std::make_pair(inputName, inputBuffer));
    rt->setInputTensors(0, tensorMap);
    rt->setOutputTensors(0, tensorMap);

    // auto outputBuffer = tensorMap.at(outputName);
    // allocator.setZero(*outputBuffer);
    rt->executeContext(0);

}
