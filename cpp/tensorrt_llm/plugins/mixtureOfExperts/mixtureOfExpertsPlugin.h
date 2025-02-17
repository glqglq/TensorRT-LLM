/*
 * SPDX-FileCopyrightText: Copyright (c) 1993-2023 NVIDIA CORPORATION &
 * AFFILIATES. All rights reserved. SPDX-License-Identifier: Apache-2.0
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
#ifndef TRT_MIXTURE_OF_EXPERTS_PLUGIN_H
#define TRT_MIXTURE_OF_EXPERTS_PLUGIN_H

#include "NvInferPlugin.h"
#include "tensorrt_llm/common/quantization.h"
#include "tensorrt_llm/kernels/mixtureOfExperts/moe_kernels.h"
#include "tensorrt_llm/plugins/common/plugin.h"
#include <cassert>
#include <mpi.h>
#include <set>
#include <string>
#include <vector>

namespace tensorrt_llm::plugins
{
class MixtureOfExpertsGemmProfiler;
using MixtureOfExpertsPluginProfilerPtr = std::shared_ptr<MixtureOfExpertsGemmProfiler>;

struct GemmIDMoe
{
    int num_experts{};
    int moe_k{};
    int hidden{};
    int inter{};
    tensorrt_llm::ActivationType actfn{};
    nvinfer1::DataType dtype{};
    nvinfer1::DataType wdtype{};
    tensorrt_llm::common::QuantMode quant_mode;
    tensorrt_llm::kernels::MOEParallelismMode parallelism_mode{};

    bool operator==(const GemmIDMoe& id) const
    {
        return id.num_experts == num_experts && id.moe_k == moe_k && id.hidden == hidden && id.inter == inter
            && id.actfn == actfn && id.dtype == dtype && id.wdtype == wdtype && id.quant_mode == quant_mode
            && id.parallelism_mode == parallelism_mode;
    }

    friend std::ostream& operator<<(std::ostream& out, const GemmIDMoe& id)
    {
        out << "experts, k, hidden, inter, actfn, dtype, weight type, parallelism mode=" << id.num_experts << ","
            << id.moe_k << "," << id.hidden << "," << id.inter << "," << static_cast<int>(id.actfn) << ","
            << static_cast<int>(id.dtype) << "," << static_cast<int>(id.wdtype) << "," << id.quant_mode.value() << ","
            << static_cast<int>(id.parallelism_mode);
        return out;
    }
};

// Hash of GemmIDMoe
struct GemmIDMoeHash
{
    std::size_t operator()(const GemmIDMoe& id) const
    {
        size_t hash = std::hash<int>{}(id.num_experts);
        hash ^= std::hash<int>{}(id.moe_k);
        hash ^= std::hash<int>{}(id.hidden);
        hash ^= std::hash<int>{}(id.inter);
        hash ^= std::hash<int>{}(static_cast<int>(id.actfn));
        hash ^= std::hash<int>{}(static_cast<int>(id.dtype));
        hash ^= std::hash<int>{}(static_cast<int>(id.wdtype));
        hash ^= std::hash<int>{}(static_cast<int>(id.quant_mode.value()));
        hash ^= std::hash<int>{}(static_cast<int>(id.parallelism_mode));
        return hash;
    }
};

class MixtureOfExpertsPlugin : public nvinfer1::IPluginV2DynamicExt
{
public:
    using MOEParallelismMode = tensorrt_llm::kernels::MOEParallelismMode;
    using MOEExpertScaleNormalizationMode = tensorrt_llm::kernels::MOEExpertScaleNormalizationMode;

    MixtureOfExpertsPlugin() = delete;
    MixtureOfExpertsPlugin(int number_of_experts, int top_k, int expert_hidden_size, int expert_inter_size,
        tensorrt_llm::ActivationType activation_type, nvinfer1::DataType type, nvinfer1::DataType weight_type,
        tensorrt_llm::common::QuantMode quant_mode, bool use_finished, bool use_bias, int tp_size, int tp_rank,
        MOEParallelismMode parallelism_mode, MOEExpertScaleNormalizationMode normalization_mode,
        MixtureOfExpertsPluginProfilerPtr plugin_profiler_ptr);
    MixtureOfExpertsPlugin(const void* data, size_t length, MixtureOfExpertsPluginProfilerPtr plugin_profiler_ptr);
    MixtureOfExpertsPlugin(const MixtureOfExpertsPlugin&);

    void init();

    ~MixtureOfExpertsPlugin() override = default;

    // IPluginV2DynamicExt Methods
    nvinfer1::IPluginV2DynamicExt* clone() const noexcept override;
    nvinfer1::DimsExprs getOutputDimensions(int outputIndex, const nvinfer1::DimsExprs* inputs, int nbInputs,
        nvinfer1::IExprBuilder& exprBuilder) noexcept override;
    bool supportsFormatCombination(
        int pos, const nvinfer1::PluginTensorDesc* inOut, int nbInputs, int nbOutputs) noexcept override;
    void configurePlugin(const nvinfer1::DynamicPluginTensorDesc* in, int nbInputs,
        const nvinfer1::DynamicPluginTensorDesc* out, int nbOutputs) noexcept override;
    size_t getWorkspaceSize(const nvinfer1::PluginTensorDesc* inputs, int nbInputs,
        const nvinfer1::PluginTensorDesc* outputs, int nbOutputs) const noexcept override;
    int enqueue(const nvinfer1::PluginTensorDesc* inputDesc, const nvinfer1::PluginTensorDesc* outputDesc,
        const void* const* inputs, void* const* outputs, void* workspace, cudaStream_t stream) noexcept override;

    // IPluginV2Ext Methods
    nvinfer1::DataType getOutputDataType(
        int index, const nvinfer1::DataType* inputTypes, int nbInputs) const noexcept override;

    // IPluginV2 Methods
    const char* getPluginType() const noexcept override;
    const char* getPluginVersion() const noexcept override;

    int getNbOutputs() const noexcept override
    {
        return 1;
    }

    int initialize() noexcept override;
    void terminate() noexcept override;
    size_t getSerializationSize() const noexcept override;
    void serialize(void* buffer) const noexcept override;
    void destroy() noexcept override;
    void setPluginNamespace(const char* pluginNamespace) noexcept override;
    const char* getPluginNamespace() const noexcept override;

private:
    friend class MixtureOfExpertsGemmProfiler;
    std::unique_ptr<kernels::CutlassMoeFCRunnerInterface> mMOERunner{};
    int mNumExperts{};
    int mK{};
    int mExpertHiddenSize{};
    int mExpertInterSize{};
    tensorrt_llm::ActivationType mActivationType;
    nvinfer1::DataType mType{};
    nvinfer1::DataType mWeightType{};
    tensorrt_llm::common::QuantMode mQuantMode;
    bool mUseFinished{};
    bool mUseBias{};
    int mTPSize{};
    int mTPRank{};
    MOEParallelismMode mParallelismMode{};
    MOEExpertScaleNormalizationMode mNormalizationMode{};

    GemmDims mDims{};

    // The below are not serialised
    GemmIDMoe mGemmId{};

    MixtureOfExpertsPluginProfilerPtr mPluginProfiler;

    const std::string mLayerName{};
    std::string mNamespace{};

    struct WorkspaceInfo
    {
        void* workspace{};
        void* scale_probs{};
        void* fc2_output{};
        void* src_to_dest_map{};
        void* selected_experts{};
        size_t size{};
    };

    int getNumTokens(const nvinfer1::PluginTensorDesc* input_tensor) const;
    WorkspaceInfo setupWorkspace(void* base_ptr, int num_tokens) const;

    kernels::MOEParallelismConfig getParallelismConfig() const;

    using IndexType = std::int32_t;

    // Inputs
    constexpr static IndexType getInputTensorIndex()
    {
        return 0;
    }

    constexpr static IndexType getRoutingTensorIndex()
    {
        return getInputTensorIndex() + 1;
    }

    constexpr static IndexType getExpertWeights1Index()
    {
        return getRoutingTensorIndex() + 1;
    }

    constexpr static IndexType getExpertWeights2Index()
    {
        return getExpertWeights1Index() + 1;
    }

    // Conditional inputs, we only allocate a new index if actually used
    bool hasBias() const
    {
        return mUseBias;
    }

    bool hasFinishedTensor() const
    {
        return mUseFinished;
    }

    bool hasExpertQuantScales() const
    {
        return mQuantMode.hasInt4Weights() || mQuantMode.hasInt8Weights();
    }

    IndexType getExpertBias1Index() const
    {
        return getExpertWeights2Index() + hasBias();
    }

    IndexType getExpertBias2Index() const
    {
        return getExpertBias1Index() + hasBias();
    }

    IndexType getFinishedTensorIndex() const
    {
        return getExpertBias2Index() + hasFinishedTensor();
    }

    IndexType getExpertQuantScale1Index() const
    {
        return getFinishedTensorIndex() + hasExpertQuantScales();
    }

    IndexType getExpertQuantScale2Index() const
    {
        return getExpertQuantScale1Index() + hasExpertQuantScales();
    }

    IndexType getNbInputs() const
    {
        return getExpertQuantScale2Index() + 1;
    }

    // Outputs
    constexpr static IndexType getOutputTensorIndex()
    {
        return 0;
    }

    /**
     * Get the index of the expert shape tuple that represents the inner dimension
     */
    int getGemmShapeInnerDimIndex() const
    {
        // In weight only mode the shape is transposed
        return hasExpertQuantScales() ? 1 : 2;
    }

    /**
     * Get the index of the expert shape tuple that represents the outer dimension
     */
    int getGemmShapeOuterDimIndex() const
    {
        // In weight only mode the shape is transposed
        return hasExpertQuantScales() ? 2 : 1;
    }

    /**
     * Get quantization dimension scaling factor
     */
    int getWeightPackedElements() const
    {
        return mQuantMode.hasInt4Weights() ? 2 : 1;
    }
};

class MixtureOfExpertsGemmProfiler
    : public tensorrt_llm::plugins::GemmPluginProfiler<tensorrt_llm::cutlass_extensions::CutlassGemmConfig,
          MixtureOfExpertsPlugin*, GemmIDMoe, GemmIDMoeHash>
{
public:
    MixtureOfExpertsGemmProfiler()
    {
        // NOTE: Do not access mPlugin here, since we are called from the constructor before all fields are init
    }

protected:
    using Config = tensorrt_llm::cutlass_extensions::CutlassGemmConfig;
    void runTactic(int m, int n, int k, const Config& tactic, char* workspace, const cudaStream_t& stream) override;
    void computeTmpSize(int maxM, int n, int k) override;
    std::vector<Config> getTactics(int m, int n, int k) const override;
    void initTmpData(int maxM, int n, int k, char* workspace, size_t size, cudaStream_t stream) override;

    std::vector<size_t> getProfilerWorkspaces(int maxM);
};

class MixtureOfExpertsPluginCreator : public nvinfer1::IPluginCreator
{
public:
    MixtureOfExpertsPluginCreator();

    const char* getPluginName() const noexcept override;

    const char* getPluginVersion() const noexcept override;

    const nvinfer1::PluginFieldCollection* getFieldNames() noexcept override;

    nvinfer1::IPluginV2* createPlugin(const char* name, const nvinfer1::PluginFieldCollection* fc) noexcept override;

    nvinfer1::IPluginV2* deserializePlugin(
        const char* name, const void* serialData, size_t serialLength) noexcept override;

    void setPluginNamespace(const char* pluginNamespace) noexcept override;

    const char* getPluginNamespace() const noexcept override;

private:
    GemmPluginProfilerManager<MixtureOfExpertsGemmProfiler> moePluginProfiler;
    static nvinfer1::PluginFieldCollection mFC;
    static std::vector<nvinfer1::PluginField> mPluginAttributes;
    std::string mNamespace;
};

} // namespace tensorrt_llm::plugins

#endif // TRT_MIXTURE_OF_EXPERTS_PLUGIN_H
