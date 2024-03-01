import json
import os
from pathlib import Path

import numpy as np
import torch

from .._utils import (_str_to_np_dict, fromfile, numpy_to_torch,
                      str_dtype_to_torch)


class LoraConfig(object):

    def __init__(self,
                 hf_lora_dir: str = None,
                 adapter_config: dict = {},
                 tokenizer_config: dict = {},
                 lora_target_modules: list = [],
                 is_valid: bool = False,
                 lm_head_weight=None,
                 embedding_weight=None,
                 hf_modules_to_trtllm_modules: dict = {}):
        self.hf_lora_dir = hf_lora_dir
        self.adapter_config = adapter_config
        self.tokenizer_config = tokenizer_config
        self.hf_lora_target_modules = lora_target_modules
        self.lora_target_modules = [
            hf_modules_to_trtllm_modules[m] for m in lora_target_modules
        ]
        self.is_valid = is_valid
        self.lm_head_weight = lm_head_weight
        self.embedding_weight = embedding_weight
        self.vocab_size, self.hidden_size = self.lm_head_weight.shape if self.lm_head_weight is not None else (
            0, 0)

    @classmethod
    def from_hf(cls, hf_lora_dir, hf_modules_to_trtllm_modules):
        lora_target_modules = {}
        adapter_config = None
        tokenizer_config = None
        hf_lora_dir = hf_lora_dir
        is_valid = True

        if os.path.exists(f"{hf_lora_dir}/adapter_config.json"):
            with open(f"{hf_lora_dir}/adapter_config.json") as f:
                adapter_config = json.load(f)
            lora_target_modules = adapter_config["target_modules"]
        else:
            is_valid = False

        if os.path.exists(f"{hf_lora_dir}/tokenizer_config.json"):
            with open(f"{hf_lora_dir}/tokenizer_config.json") as f:
                tokenizer_config = json.load(f)
        else:
            is_valid = False

        lm_head_weight = None
        embedding_weight = None
        if os.path.exists(f"{hf_lora_dir}/adapter_model.bin"):
            lora_weight = torch.load(f"{hf_lora_dir}/adapter_model.bin")

            if adapter_config["modules_to_save"] is not None:
                if "lm_head" in adapter_config["modules_to_save"]:
                    lm_head_weight = lora_weight[
                        "base_model.model.lm_head.weight"]

                if "embed_tokens" in adapter_config["modules_to_save"]:
                    embedding_weight = lora_weight[
                        "base_model.model.model.embed_tokens.weight"]

        return cls(hf_lora_dir, adapter_config, tokenizer_config,
                   lora_target_modules, is_valid, lm_head_weight,
                   embedding_weight, hf_modules_to_trtllm_modules)


class LoraManager(object):

    def __init__(self):
        self._lora_uid_to_key = {}
        '''
        _lora_uid_to_low_ranks: dict[str -> List[dict[str -> int]]]
        {
            uid:
            [
                {
                    lora_module: int
                }, # layer_0_rank,
                {
                    lora_module: int
                }, # layer_1_rank,
                ...
            ]
        }

        _lora_weights_pointers_list:
        [
            {
               uid:
               {
                   lora_module_1: [t_in, t_out]
                   lora_module_2: [t_in, t_out]
               }
            }, # layer_0
            {

            }, # layer_1
            ...
        ]

        '''
        self._lora_uid_to_low_ranks = {}
        self._lora_weights = []
        self._lora_weights_pointers_list = []

    def load_from_ckpt(self, model_dir, model_config, runtime_mapping,
                       ckpt_source):
        if ckpt_source == "hf":
            self.load_from_hf(model_dir, model_config, runtime_mapping)
        elif ckpt_source == "nemo":
            self.load_from_nemo(model_dir, model_config, runtime_mapping)
        else:
            assert False, f"LoraManager does not support source {ckpt_source}"

    def load_from_nemo(self, model_dir, model_config, runtime_mapping):
        '''
        Load lora modules, could be move to client side
        '''
        self._model_config = model_config
        model_dir = Path(model_dir)

        with open(model_dir / "lora_weights.json", 'r') as f:
            config = json.load(f)
        lora_config = config['lora_config']
        for key in lora_config['lora_kqv_adapter']:
            self._lora_uid_to_key[lora_config['lora_kqv_adapter'][key]
                                  ['key']] = key

        lora_target_modules = model_config.lora_target_modules
        dtype = model_config.dtype

        for layer_idx in range(model_config.num_layers):
            self._lora_weights_pointers_list.append({})

            for uid, key in self._lora_uid_to_key.items():
                self._lora_weights_pointers_list[layer_idx].update({uid: {}})
                low_rank = int(lora_config['lora_kqv_adapter'][key]['low_rank'])

                for lora_module in lora_target_modules:
                    if uid not in self._lora_uid_to_low_ranks:
                        self._lora_uid_to_low_ranks.update(
                            {uid: [{} for _ in range(model_config.num_layers)]})
                    self._lora_uid_to_low_ranks[uid][layer_idx][
                        lora_module] = low_rank

                    prefix = f"model.model.language_model.encoder.layers.{layer_idx}.self_attention.adapter_layer.lora_kqv_adapter.{key}"
                    t_in = numpy_to_torch(
                        np.ascontiguousarray(
                            fromfile(
                                model_dir, f'{prefix}.linear_in.weight.bin',
                                [model_config.hidden_size, low_rank],
                                _str_to_np_dict['bfloat16']).transpose(
                                    1,
                                    0))).cuda()  # t_in: [low_rank, hidden_size]

                    t_out = numpy_to_torch(
                        np.ascontiguousarray(
                            fromfile(model_dir,
                                     f'{prefix}.linear_out.weight.bin',
                                     [low_rank, model_config.hidden_size * 3],
                                     _str_to_np_dict['bfloat16']).transpose(
                                         1, 0))).cuda(
                                         )  # t_in: [hidden_size * 3, low_rank]
                    t_in = t_in.float().to(str_dtype_to_torch(dtype))
                    t_out = t_out.float().to(str_dtype_to_torch(dtype))

                    self._lora_weights_pointers_list[layer_idx][uid].update({
                        lora_module: [
                            t_in.contiguous().data_ptr(),
                            t_out.contiguous().data_ptr()
                        ]
                    })

                    self._lora_weights.append(t_in)
                    self._lora_weights.append(t_out)

            if "-1" not in self._lora_uid_to_low_ranks:
                self._lora_uid_to_low_ranks.update(
                    {"-1": [{} for _ in range(model_config.num_layers)]})
            self._lora_uid_to_low_ranks["-1"][layer_idx][lora_module] = 0

    def load_from_hf(self, model_dir, model_config, runtime_mapping):
        '''
        lora config of https://huggingface.co/hfl/chinese-alpaca-2-lora-7b
        {
            "base_model_name_or_path": "/Llama-2-7b-hf",
            "bias": "none",
            "enable_lora": null,
            "fan_in_fan_out": false,
            "inference_mode": true,
            "lora_alpha": 128.0,
            "lora_dropout": 0.05,
            "merge_weights": false,
            "modules_to_save": [
                "embed_tokens",
                "lm_head"
            ],
            "peft_type": "LORA",
            "r": 64,
            "target_modules": [
                "q_proj",
                "v_proj",
                "k_proj",
                "o_proj",
                "gate_proj",
                "down_proj",
                "up_proj"
            ],
            "task_type": "CAUSAL_LM"

        }

        keys in adapter_model.bin:
            base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.self_attn.q_proj.lora_B.weight torch.Size([4096, 64])
            base_model.model.model.layers.0.self_attn.k_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.self_attn.k_proj.lora_B.weight torch.Size([4096, 64])
            base_model.model.model.layers.0.self_attn.v_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.self_attn.v_proj.lora_B.weight torch.Size([4096, 64])
            base_model.model.model.layers.0.self_attn.o_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.self_attn.o_proj.lora_B.weight torch.Size([4096, 64])
            base_model.model.model.layers.0.mlp.gate_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.mlp.gate_proj.lora_B.weight torch.Size([11008, 64])
            base_model.model.model.layers.0.mlp.up_proj.lora_A.weight torch.Size([64, 4096])
            base_model.model.model.layers.0.mlp.up_proj.lora_B.weight torch.Size([11008, 64])
            base_model.model.model.layers.0.mlp.down_proj.lora_A.weight torch.Size([64, 11008])
            base_model.model.model.layers.0.mlp.down_proj.lora_B.weight torch.Size([4096, 64])
            ...

        '''
        tp_size = runtime_mapping.tp_size
        tp_rank = runtime_mapping.tp_rank
        lora_model = torch.load(f"{model_dir}/adapter_model.bin")

        with open(f"{model_dir}/adapter_config.json", 'r') as f:
            hf_config = json.load(f)

        lora_target_modules = model_config.lora_target_modules
        dtype = model_config.dtype

        ranks = [0, hf_config["r"]]
        uids = ["-1", "0"]  # TODO should be lora from some config

        for uid, rank in zip(uids, ranks):
            self._lora_uid_to_low_ranks[uid] = []
            for layer_idx in range(model_config.num_layers):
                self._lora_weights_pointers_list.append({})
                self._lora_weights_pointers_list[layer_idx].update({uid: {}})

                self._lora_uid_to_low_ranks[uid].append({})

                prefix = "base_model.model.model.layers"
                for lora_module in lora_target_modules:
                    if uid == "-1":
                        self._lora_uid_to_low_ranks[uid][layer_idx][
                            lora_module] = 0
                        continue

                    if lora_module == "attn_q" or lora_module == "attn_k" or lora_module == "attn_v":
                        name = f"{prefix}.{layer_idx}.{lora_module.replace('attn_', 'self_attn.')}_proj"
                        # not split
                        t_in = lora_model[f"{name}.lora_A.weight"]
                        # split by column
                        t_out = lora_model[f"{name}.lora_B.weight"]
                        assert t_out.shape[0] % tp_size == 0
                        t_out = torch.split(t_out,
                                            t_out.shape[0] // tp_size,
                                            dim=0)[tp_rank].contiguous()

                    elif lora_module == "attn_dense":
                        # split by row
                        t_in = lora_model[
                            f"{prefix}.{layer_idx}.self_attn.o_proj.lora_A.weight"]
                        assert t_in.shape[1] % tp_size == 0
                        t_in = torch.split(t_in,
                                           t_in.shape[1] // tp_size,
                                           dim=1)[tp_rank].contiguous()
                        # not split
                        t_out = lora_model[
                            f"{prefix}.{layer_idx}.self_attn.o_proj.lora_B.weight"]

                    elif lora_module == "mlp_h_to_4h":
                        # not split
                        t_in = lora_model[
                            f"{prefix}.{layer_idx}.mlp.gate_proj.lora_A.weight"]
                        # split by column
                        t_out = lora_model[
                            f"{prefix}.{layer_idx}.mlp.gate_proj.lora_B.weight"]
                        assert t_out.shape[0] % tp_size == 0
                        t_out = torch.split(t_out,
                                            t_out.shape[0] // tp_size,
                                            dim=0)[tp_rank].contiguous()

                    elif lora_module == "mlp_gate":
                        # not split
                        t_in = lora_model[
                            f"{prefix}.{layer_idx}.mlp.up_proj.lora_A.weight"]
                        # split by column
                        t_out = lora_model[
                            f"{prefix}.{layer_idx}.mlp.up_proj.lora_B.weight"]
                        assert t_out.shape[0] % tp_size == 0
                        t_out = torch.split(t_out,
                                            t_out.shape[0] // tp_size,
                                            dim=0)[tp_rank].contiguous()

                    elif lora_module == "mlp_4h_to_h":
                        # split by row
                        t_in = lora_model[
                            f"{prefix}.{layer_idx}.mlp.down_proj.lora_A.weight"]
                        assert t_in.shape[0] % tp_size == 0
                        t_in = torch.split(t_in,
                                           t_in.shape[1] // tp_size,
                                           dim=1)[tp_rank].contiguous()
                        # not split
                        t_out = lora_model[
                            f"{prefix}.{layer_idx}.mlp.down_proj.lora_B.weight"]

                    t_in = t_in.cuda().contiguous()
                    t_out = t_out.cuda().contiguous()
                    t_in = t_in.float().to(str_dtype_to_torch(dtype))
                    t_out = t_out.float().to(str_dtype_to_torch(dtype))
                    self._lora_weights_pointers_list[layer_idx][uid].update(
                        {lora_module: [t_in.data_ptr(),
                                       t_out.data_ptr()]})

                    assert t_in.shape[0] == int(hf_config["r"])
                    self._lora_uid_to_low_ranks[uid][layer_idx][
                        lora_module] = int(hf_config["r"])

                    # prevent torch free this buffer
                    self._lora_weights.append(t_in)
                    self._lora_weights.append(t_out)
        del lora_model

    def uid_to_key(self, uid: str):
        assert isinstance(uid, str)
        return self._lora_uid_to_key[uid]

    def uid_to_low_ranks(self, uid: str):
        assert isinstance(uid, str)
        return self._lora_uid_to_low_ranks[uid]

    @property
    def lora_weights(self):
        return self._lora_weights

    @property
    def lora_weights_pointers_list(self):
        return self._lora_weights_pointers_list
