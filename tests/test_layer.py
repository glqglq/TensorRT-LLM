# SPDX-FileCopyrightText: Copyright (c) 2022-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import unittest
from itertools import product

import numpy as np
import pytest

# isort: off
import torch
import tensorrt as trt
# isort: on
from functional.torch_ref import attention_qkvpacked_ref
from parameterized import parameterized
from polygraphy.backend.trt import (CreateConfig, EngineFromNetwork, Profile,
                                    TrtRunner)
from transformers.models.bloom.modeling_bloom import build_alibi_tensor
from transformers.models.llama.modeling_llama import (LlamaConfig, LlamaMLP,
                                                      LlamaRMSNorm)
from utils.util import getSMVersion

import tensorrt_llm
from tensorrt_llm import Tensor
from tensorrt_llm._utils import str_dtype_to_torch, torch_to_numpy
from tensorrt_llm.layers import (AttentionParams, KeyValueCacheParams,
                                 PositionEmbeddingType)
from tensorrt_llm.quantization.mode import QuantMode


class TestLayer(unittest.TestCase):

    def setUp(self):
        tensorrt_llm.logger.set_level('error')

    def test_group_norm_float32(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(2, 6, 3, 3)
        m = torch.nn.GroupNorm(3, 6)

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.GroupNorm(3, 6)

            gm.weight.value = m.weight.detach().cpu().numpy()
            gm.bias.value = m.bias.detach().cpu().numpy()
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    def test_layer_norm_float32(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(2, 5, 10, 10)
        m = torch.nn.LayerNorm([5, 10, 10])

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.LayerNorm([5, 10, 10])

            gm.weight.value = m.weight.detach().cpu().numpy()
            gm.bias.value = m.bias.detach().cpu().numpy()
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    def test_rms_norm_float32(self):
        # test data
        test_shape = [2, 5, 10, 16]
        dtype = 'float32'
        x_data = torch.randn(*test_shape)
        m = LlamaRMSNorm(test_shape[-1])  # LlamaRMSNorm only supports last dim
        with torch.no_grad():
            m.weight.copy_(torch.rand([test_shape[-1]]))

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.RmsNorm(test_shape[-1])

            gm.weight.value = m.weight.detach().cpu().numpy()
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    def _gated_mlp_custom_id(testcase_func, param_num, param):
        return "%s_%s_%s" % (testcase_func.__name__, param.args[0].__name__,
                             param.args[1])

    @parameterized.expand([[tensorrt_llm.layers.GatedMLP, 'float32'],
                           [tensorrt_llm.layers.FusedGatedMLP, 'float32'],
                           [tensorrt_llm.layers.GatedMLP, 'fp8'],
                           [tensorrt_llm.layers.FusedGatedMLP, 'fp8']],
                          name_func=_gated_mlp_custom_id)
    def test_gated_mlp(self, ClsMLP, qformat):
        if getSMVersion() < 89 and qformat == 'fp8':
            pytest.skip("fp8 is not supported in pre-ada architecture")

        # test data
        d_h = 8
        ffn_h = 20
        test_shape = [2, 3, 5, d_h]
        dtype = 'float32'
        torch.random.manual_seed(0)
        # need rand for 'normalized' values
        x_data = torch.randn(*test_shape)
        fc = torch.empty(ffn_h, d_h)
        torch.nn.init.xavier_uniform_(fc)
        gate = torch.empty(ffn_h, d_h)
        torch.nn.init.xavier_uniform_(gate)
        proj = torch.empty(d_h, ffn_h)
        torch.nn.init.xavier_uniform_(proj)
        config = LlamaConfig(hidden_size=d_h,
                             intermediate_size=ffn_h,
                             hidden_act='silu')
        m = LlamaMLP(config)
        # Need torch.no_grad() to update the weights of torch.nn.Linear weights
        with torch.no_grad():
            m.gate_proj.weight.copy_(fc)
            m.up_proj.weight.copy_(gate)
            m.down_proj.weight.copy_(proj)

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            quant_mode = QuantMode(0)
            if qformat == 'fp8':
                quant_mode = quant_mode.set_fp8_qdq()

            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = ClsMLP(d_h,
                        ffn_h,
                        hidden_act='silu',
                        bias=False,
                        dtype=tensorrt_llm.str_dtype_to_trt(dtype),
                        quant_mode=quant_mode)

            # TensorRT-LLM's Linear uses Parameter class which as a 'value' setter
            gm.fc.weight.value = fc.cpu().numpy()
            gm.gate.weight.value = gate.cpu().numpy()
            gm.proj.weight.value = proj.cpu().numpy()
            if quant_mode.has_fp8_qdq():
                gm.fc.weights_scaling_factor.value = np.array([1.42],
                                                              dtype=np.float32)
                gm.gate.weights_scaling_factor.value = np.array(
                    [1.42], dtype=np.float32)
                gm.proj.weights_scaling_factor.value = np.array(
                    [0.42], dtype=np.float32)
                gm.fc.activation_scaling_factor.value = np.array(
                    [0.42], dtype=np.float32)
                gm.gate.activation_scaling_factor.value = np.array(
                    [0.42], dtype=np.float32)
                gm.proj.activation_scaling_factor.value = np.array(
                    [0.42], dtype=np.float32)

            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork(
            (builder.trt_builder, net.trt_network),
            CreateConfig(fp8=(qformat == 'fp8'), precision_constraints="obey"))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        kwargs = {
            'atol': 0.2,
            'rtol': 0.03
        } if qformat == 'fp8' else {
            'atol': 1e-5
        }
        np.testing.assert_allclose(ref.cpu().numpy(), outputs['output'],
                                   **kwargs)

    @parameterized.expand([["float32", False], ["float32", True],
                           ["bfloat16", False], ["bfloat16", True]])
    def test_linear(self, dtype, use_plugin):
        # Skip tests that are not supported on V100
        if getSMVersion() < 80:
            if dtype == 'bfloat16':
                pytest.skip(
                    "bfloat16 is not supported in pre-ampere architecture")

        # test data
        torch.manual_seed(0)
        x_data = torch.randn(128, 20, dtype=str_dtype_to_torch(dtype))
        m = torch.nn.Linear(20, 30, dtype=str_dtype_to_torch(dtype))

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        if use_plugin:
            net.plugin_config.set_gemm_plugin(dtype)
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.Linear(20, 30, dtype=dtype)

            gm.weight.value = torch_to_numpy(m.weight.detach().cpu())
            gm.bias.value = torch_to_numpy(m.bias.detach().cpu())
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork(
            (builder.trt_builder, net.trt_network),
            CreateConfig(bf16=dtype == "bfloat16",
                         precision_constraints="obey"))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # The absolute tolerance for bfloat16 is increased marginally because
        # a single value (out of 4000) breaks tolerance on a 4090 linux/windows.
        atols = {"float32": 1e-6, "bfloat16": 1.03 * 1e-2}

        # compare diff
        np.testing.assert_allclose(ref.to(torch.float32).cpu().numpy(),
                                   outputs['output'].to(torch.float32).numpy(),
                                   atol=atols[dtype])

    @parameterized.expand(list(product([True, False], [True, False])))
    @pytest.mark.skipif(
        getSMVersion() < 80,
        reason="bfloat16 is not supported in pre-ampere architecture"
    )  # Skip tests that are not supported in pre-ampere architecture
    def test_prompt_tuning_embedding(self, enable_lookup_plugin,
                                     remove_padding):
        torch.random.manual_seed(0)
        dtype = "bfloat16"
        trt_dtype = tensorrt_llm.str_dtype_to_trt(dtype)
        torch_dtype = str_dtype_to_torch(dtype)
        embedding_dim = 64
        batch_size = 8
        seq_len = 12
        vocab_size = 100
        num_embeddings = 128
        num_tasks = 3
        task_vocab_size = 30

        embeddings = torch.randn((num_embeddings, embedding_dim),
                                 dtype=torch_dtype)
        prompt_embedding = torch.randn(
            (num_tasks * task_vocab_size, embedding_dim), dtype=torch_dtype)
        ids = torch.randint(0,
                            vocab_size, (batch_size, seq_len),
                            dtype=torch.int32)
        request_tasks = torch.randint(0,
                                      num_tasks, (batch_size, ),
                                      dtype=torch.int32)
        request_tasks = request_tasks.unsqueeze(-1).expand(*ids.shape)
        v_ids = torch.randint(vocab_size,
                              vocab_size + task_vocab_size,
                              (batch_size, seq_len),
                              dtype=torch.int32)
        mask = torch.bernoulli(torch.full((batch_size, seq_len),
                                          0.5)).to(torch.int32)
        ids = ids * mask + v_ids * (1 - mask)

        if remove_padding:
            input_ids = ids.flatten().unsqueeze(0)
            request_tasks = request_tasks.flatten().unsqueeze(0)
        else:
            input_ids = ids

        builder = tensorrt_llm.Builder()
        net = builder.create_network()

        if enable_lookup_plugin:
            net.plugin_config.lookup_plugin = dtype

        with tensorrt_llm.net_guard(net):
            ids_tensor = Tensor(name='ids',
                                shape=[1, -1] if remove_padding else [-1, -1],
                                dtype=trt.int32)
            prompt_embedding_tensor = Tensor(name='prompt_embedding',
                                             shape=[-1, embedding_dim],
                                             dtype=trt_dtype)
            request_tasks_tensor = Tensor(name='request_tasks',
                                          shape=[-1, -1],
                                          dtype=trt.int32)
            task_vocab_size_tensor = Tensor(name='task_vocab_size',
                                            shape=(1, ),
                                            dtype=trt.int32)

            embedding = tensorrt_llm.layers.PromptTuningEmbedding(
                num_embeddings, embedding_dim, vocab_size, trt_dtype)
            embedding.weight.value = torch_to_numpy(embeddings.detach().cpu())

            output = embedding(ids_tensor, prompt_embedding_tensor,
                               request_tasks_tensor, task_vocab_size_tensor)
            net._mark_output(output, "output", dtype=trt_dtype)

        profile = (Profile().add(
            "ids", (1, 1), input_ids.shape, input_ids.shape).add(
                "prompt_embedding", (1, embedding_dim), prompt_embedding.shape,
                prompt_embedding.shape).add("request_tasks", (1, 1),
                                            input_ids.shape, input_ids.shape))

        build_engine = EngineFromNetwork(
            (builder.trt_builder, net.trt_network),
            config=CreateConfig(bf16=(dtype == "bfloat16"),
                                fp16=(dtype == "float16"),
                                precision_constraints="obey",
                                profiles=[profile]))
        assert build_engine is not None
        with TrtRunner(build_engine) as runner:
            output = runner.infer(
                feed_dict={
                    'ids':
                    input_ids,
                    'prompt_embedding':
                    prompt_embedding,
                    'request_tasks':
                    request_tasks,
                    'task_vocab_size':
                    torch.tensor([task_vocab_size], dtype=torch.int32),
                })['output']

        output = output.to(torch.float32)
        embeddings = embeddings.to(torch.float32)
        prompt_embedding = prompt_embedding.view(
            (num_tasks, task_vocab_size, embedding_dim)).to(torch.float32)

        # use loops for clarity, even if it's non-optimal
        for b in range(input_ids.shape[0]):
            for s in range(input_ids.shape[1]):
                token_id = input_ids[b][s]
                if token_id < vocab_size:
                    np.testing.assert_allclose(output[b][s],
                                               embeddings[token_id])
                else:
                    offset_token_id = token_id - vocab_size
                    task = request_tasks[b][s]
                    np.testing.assert_allclose(
                        output[b][s], prompt_embedding[task][offset_token_id])

    def test_conv2d_float32(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(20, 16, 50, 100)
        m = torch.nn.Conv2d(16,
                            33, (3, 5),
                            stride=(2, 1),
                            padding=(4, 2),
                            dilation=(3, 1))

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.Conv2d(16,
                                            33, (3, 5),
                                            stride=(2, 1),
                                            padding=(4, 2),
                                            dilation=(3, 1))

            gm.weight.value = m.weight.detach().cpu().numpy()
            gm.bias.value = m.bias.detach().cpu().numpy()
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-5)

    def test_conv_transpose2d_float32(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(20, 16, 50, 100)
        m = torch.nn.ConvTranspose2d(16,
                                     33, (3, 5),
                                     stride=(2, 1),
                                     padding=(4, 2))
        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            gm = tensorrt_llm.layers.ConvTranspose2d(16,
                                                     33, (3, 5),
                                                     stride=(2, 1),
                                                     padding=(4, 2),
                                                     dilation=(3, 1))

            gm.weight.value = m.weight.detach().cpu().numpy()
            gm.bias.value = m.bias.detach().cpu().numpy()
            output = gm.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-05)

    def test_avg_pooling_2d_float32(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(2, 16, 50, 32)
        m = torch.nn.AvgPool2d((3, 2), stride=(2, 1))
        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            ap2d = tensorrt_llm.layers.AvgPool2d((3, 2), stride=(2, 1))
            output = ap2d.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    @parameterized.expand([("bfloat16", "float32"), ("float32", "bfloat16")])
    def test_cast_bf16(self, from_dtype, to_dtype):
        if getSMVersion() < 80:
            pytest.skip("bfloat16 is not supported in pre-ampere architecture")

        torch_from_dtype = str_dtype_to_torch(from_dtype)
        torch_to_dtype = str_dtype_to_torch(to_dtype)
        x_data = torch.randn(2, 2, 3, 6, dtype=torch_from_dtype)

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()

        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(from_dtype))

            cast = tensorrt_llm.layers.Cast(to_dtype)
            output = cast.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork(
            (builder.trt_builder, net.trt_network),
            config=CreateConfig(bf16=True, precision_constraints="obey"))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data})

        # pytorch run
        ref = x_data.to(torch_to_dtype).to(torch.float32)
        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'].to(torch.float32),
                                   atol=0)

    def test_cast(self):
        dtype = 'float16'
        x_data = torch.randn(2, 2, 3, 6, dtype=torch.float16)

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            cast = tensorrt_llm.layers.Cast('float32')
            output = cast.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        ref = x_data.to(torch.float32)
        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    def test_mish(self):
        # test data
        dtype = 'float32'
        x_data = torch.randn(2, 2, 3, 6)
        m = torch.nn.Mish()
        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        with tensorrt_llm.net_guard(net):
            network = tensorrt_llm.default_trtnet()
            x = Tensor(name='x',
                       shape=x_data.shape,
                       dtype=tensorrt_llm.str_dtype_to_trt(dtype))

            mish = tensorrt_llm.layers.Mish()
            output = mish.forward(x).trt_tensor
            output.name = 'output'
            network.mark_output(output)

        # trt run
        build_engine = EngineFromNetwork((builder.trt_builder, net.trt_network))
        with TrtRunner(build_engine) as runner:
            outputs = runner.infer(feed_dict={'x': x_data.numpy()})

        # pytorch run
        with torch.no_grad():
            ref = m(x_data)

        # compare diff
        np.testing.assert_allclose(ref.cpu().numpy(),
                                   outputs['output'],
                                   atol=1e-6)

    @parameterized.expand([
        (12, 512, 16, 64, 'float16', PositionEmbeddingType.alibi, False),
        (128, 128, 12, 32, 'float16', PositionEmbeddingType.alibi, True),
        (1, 200, 8, 128, 'float32', PositionEmbeddingType.alibi, False),
        (48, 30, 24, 80, 'float32', PositionEmbeddingType.alibi, True),
        (2, 128, 4, 64, 'float16', PositionEmbeddingType.learned_absolute, True,
         True),
        (2, 128, 4, 64, 'float32', PositionEmbeddingType.learned_absolute, True,
         True),
    ])
    def test_attention(self,
                       batch_size,
                       seq_len,
                       head_num,
                       head_size,
                       dtype,
                       pos_emb_type,
                       causal_mask,
                       use_plugin=False):

        hidden_size = head_num * head_size

        torch_dtype = str_dtype_to_torch(dtype)
        mean = 0.0
        std_dev = 0.02 if dtype == "float32" else 0.005

        hidden_states = torch.empty(size=[batch_size, seq_len, hidden_size],
                                    dtype=torch_dtype,
                                    device='cuda')
        hidden_states.normal_(mean, std_dev)

        #TODO: can change to random after torch ref support non padding format
        context_lengths = torch.full([batch_size],
                                     seq_len,
                                     dtype=torch.int32,
                                     device='cuda')

        if use_plugin:
            # Only generate 1 step
            max_seq_len = seq_len + 1

            # zero means "valid" token, one means invalid. Here since torch ref does not support mask, make it all valid.
            host_past_key_value_lengths = torch.tensor([0] * batch_size,
                                                       dtype=torch.int32)

            # the max kv cache length for each layer.
            # single tensor since we only have 1 layer here.
            host_max_attention_window_sizes = torch.tensor([max_seq_len],
                                                           dtype=torch.int32)
            host_sink_token_length = torch.tensor([0], dtype=torch.int32)

            sequence_length = torch.full([batch_size],
                                         seq_len,
                                         dtype=torch.int32,
                                         device='cuda')
            # even in the the context phase, kv cache tensors can not be empty tensor for plugin, the actual shape info
            # otherwise, there will be cublas execution error.
            # are passed to plugin by the `sequence_length` tensor
            kv_shape = (batch_size, 2, head_num, max_seq_len, head_size)
            past_key_value = torch.randn(kv_shape,
                                         dtype=torch_dtype,
                                         device='cuda')
            cache_indirection = torch.full((
                batch_size,
                1,
                max_seq_len,
            ),
                                           0,
                                           dtype=torch.int32,
                                           device='cuda')

            host_request_types = torch.tensor([0] * batch_size,
                                              dtype=torch.int32,
                                              device='cpu')

        q_weight = torch.empty(size=[hidden_size, hidden_size],
                               dtype=torch_dtype)
        torch.nn.init.xavier_uniform_(q_weight)

        # The initialization here is chosen to minimize computation after the
        # QKV BMMs in order to reduce the amount of differences from FP accumulation.
        # We set K and V weights to the identity matrix so that the input is copied
        # without doing any accumulation. Additionally, we set the output projection
        # to the identity for the same reason.
        # The main purpose of these tests is to check the QK^T BMM + Softmax + SV BMM.
        eye_weight = torch.eye(hidden_size, dtype=torch_dtype)
        qkv_weight = torch.cat([q_weight, eye_weight, eye_weight], dim=-1)

        out_weight = eye_weight

        # construct trt network
        builder = tensorrt_llm.Builder()
        net = builder.create_network()
        if use_plugin:
            net.plugin_config.gpt_attention_plugin = dtype
        with tensorrt_llm.net_guard(net):
            trt_hidden_states = Tensor(
                name='hidden_states',
                shape=hidden_states.shape,
                dtype=tensorrt_llm.str_dtype_to_trt(dtype))
            context_lengths_tensor = Tensor(
                name='context_lengths',
                shape=context_lengths.shape,
                dtype=tensorrt_llm.str_dtype_to_trt('int32'))

            if use_plugin:
                host_request_types_tensor = Tensor(
                    name='host_request_types',
                    shape=host_request_types.shape,
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))
                past_key_value_tensor = Tensor(
                    name='past_key_value',
                    shape=tuple(past_key_value.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt(dtype))
                sequence_length_tensor = Tensor(
                    name='sequence_length',
                    shape=tuple(sequence_length.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))
                host_past_key_value_lengths_tensor = Tensor(
                    name='host_past_key_value_lengths',
                    shape=tuple(host_past_key_value_lengths.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))
                host_max_attention_window_sizes_tensor = Tensor(
                    name='host_max_attention_window_sizes',
                    shape=tuple(host_max_attention_window_sizes.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))
                host_sink_token_length_tensor = Tensor(
                    name='host_sink_token_length',
                    shape=tuple(host_sink_token_length.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))
                cache_indirection_tensor = Tensor(
                    name='cache_indirection',
                    shape=tuple(cache_indirection.shape),
                    dtype=tensorrt_llm.str_dtype_to_trt('int32'))

            mask_type = tensorrt_llm.layers.AttentionMaskType.padding
            if causal_mask:
                mask_type = tensorrt_llm.layers.AttentionMaskType.causal

            attn_layer = tensorrt_llm.layers.Attention(
                hidden_size,
                head_num,
                max_position_embeddings=seq_len,
                attention_mask_type=mask_type,
                position_embedding_type=pos_emb_type,
                bias=False)

            attn_layer.qkv.weight.value = np.ascontiguousarray(
                qkv_weight.cpu().numpy().transpose([1, 0]))
            attn_layer.dense.weight.value = np.ascontiguousarray(
                out_weight.cpu().numpy().transpose([1, 0]))
            input_tensor = trt_hidden_states
            if use_plugin:
                output, present_key_value = attn_layer(
                    input_tensor,
                    use_cache=True,
                    kv_cache_params=KeyValueCacheParams(
                        past_key_value=[past_key_value_tensor],
                        host_past_key_value_lengths=
                        host_past_key_value_lengths_tensor,
                        host_max_attention_window_sizes=
                        host_max_attention_window_sizes_tensor,
                        host_sink_token_length=host_sink_token_length_tensor,
                        cache_indirection=cache_indirection_tensor),
                    attention_params=AttentionParams(
                        sequence_length=sequence_length_tensor,
                        context_lengths=context_lengths_tensor,
                        host_request_types=host_request_types_tensor,
                        max_context_length=seq_len))
                assert isinstance(output, Tensor)
                output = output
                present_key_value.mark_output(
                    'present_key_value', tensorrt_llm.str_dtype_to_trt(dtype))
            else:
                output = attn_layer(input_tensor)
            output.mark_output('output', tensorrt_llm.str_dtype_to_trt(dtype))

        builder_config = builder.create_builder_config(name='attention',
                                                       precision=dtype)
        # Build engine
        engine_buffer = builder.build_engine(net, builder_config)
        session = tensorrt_llm.runtime.Session.from_serialized_engine(
            engine_buffer)
        stream = torch.cuda.current_stream().cuda_stream

        if use_plugin:
            inputs = {
                'hidden_states': hidden_states,
                'past_key_value': past_key_value,
                'sequence_length': sequence_length,
                'host_past_key_value_lengths': host_past_key_value_lengths,
                'host_max_attention_window_sizes':
                host_max_attention_window_sizes,
                'host_sink_token_length': host_sink_token_length,
                'context_lengths': context_lengths,
                'host_request_types': host_request_types,
                'cache_indirection': cache_indirection
            }
            outputs = {
                'output':
                torch.empty(hidden_states.shape,
                            dtype=tensorrt_llm._utils.str_dtype_to_torch(dtype),
                            device='cuda'),
                'present_key_value':
                past_key_value,
            }
        else:
            inputs = {
                'hidden_states': hidden_states,
                'context_lengths': context_lengths,
            }
            outputs = {
                'output':
                torch.empty(hidden_states.shape,
                            dtype=tensorrt_llm._utils.str_dtype_to_torch(dtype),
                            device='cuda'),
            }

        session.run(inputs=inputs, outputs=outputs, stream=stream)
        torch.cuda.synchronize()

        packed_torch_qkv = hidden_states.to("cuda") @ qkv_weight.to("cuda")
        packed_torch_qkv = packed_torch_qkv.reshape(
            [batch_size, seq_len, 3, head_num, head_size])

        alibi_bias = None
        if pos_emb_type == PositionEmbeddingType.alibi:
            mask = torch.ones(size=[batch_size, seq_len], device="cuda")
            alibi_bias = build_alibi_tensor(mask, head_num, torch.float32)
            alibi_bias = alibi_bias.reshape([batch_size, head_num, 1, seq_len])

        mha_out, _ = attention_qkvpacked_ref(packed_torch_qkv,
                                             causal=causal_mask,
                                             upcast=False,
                                             bias=alibi_bias)
        torch_out = mha_out.reshape([batch_size, seq_len, hidden_size])

        trt_output = outputs['output']

        a_tol = 5e-5 if (dtype == "float32" and not use_plugin) else 2e-3
        np.testing.assert_allclose(torch_out.cpu().numpy(),
                                   trt_output.cpu().numpy(),
                                   atol=a_tol,
                                   verbose=True)


if __name__ == '__main__':
    unittest.main()
