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
"""
Adapted from examples/quantization/hf_ptq.py
"""

import argparse
import os
import random
import sys

import numpy as np
import torch
from datasets import load_dataset
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer

from tensorrt_llm._utils import str_dtype_to_torch
from tensorrt_llm.logger import logger
from tensorrt_llm.models.quantized.ammo import quantize_and_export

now_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(now_dir)


def get_calib_dataloader(data="ccdv/cnn_dailymail",
                         tokenizer=None,
                         batch_size=1,
                         calib_size=512,
                         block_size=512,
                         cache_dir=None):
    print("Loading calibration dataset")
    if data == "pileval":
        dataset = load_dataset(
            "json",
            data_files="https://the-eye.eu/public/AI/pile/val.jsonl.zst",
            split="train",
            cache_dir=cache_dir)
        dataset = dataset["text"][:calib_size]
    elif data == "ccdv/cnn_dailymail":
        dataset = load_dataset("ccdv/cnn_dailymail",
                               name="3.0.0",
                               split="train",
                               cache_dir=cache_dir)
        dataset = dataset["article"][:calib_size]
    else:
        raise NotImplementedError

    tokenizer.pad_token_id = tokenizer.im_end_id

    for i in range(len(dataset)):
        dataset[i] = dataset[i] + ' TL;DR: '
        dataset[i] = dataset[i].strip()
        dataset[i] = dataset[i].replace(" n't", "n't")

    dataset_input_ids = tokenizer(dataset,
                                  return_tensors="pt",
                                  padding=True,
                                  truncation=True,
                                  max_length=block_size).input_ids.cuda()

    calib_dataloader = DataLoader(dataset_input_ids,
                                  batch_size=batch_size,
                                  shuffle=False)

    return calib_dataloader


def get_tokenizer(ckpt_path, **kwargs):
    logger.info(f"Loading tokenizer from {ckpt_path}")
    tokenizer = AutoTokenizer.from_pretrained(ckpt_path,
                                              padding_side="left",
                                              trust_remote_code=True,
                                              **kwargs)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def get_model(ckpt_path, dtype="float16", cache_dir=None):
    logger.info(f"Loading model from {ckpt_path}")
    torch_dtype = str_dtype_to_torch(dtype)
    model = AutoModelForCausalLM.from_pretrained(
        ckpt_path,
        device_map="auto",
        cache_dir=cache_dir,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
    )
    model.eval()
    model = model.to(memory_format=torch.channels_last)
    return model


def get_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model_dir",
                        type=str,
                        required=False,
                        default=None,
                        help="Directory of a HF model checkpoint")
    parser.add_argument("--dtype", help="Model data type.", default="float16")
    parser.add_argument(
        "--qformat",
        type=str,
        choices=['fp8', 'int4_awq'],
        default='int4_awq',
        help='Quantization format. Currently only fp8 is supported. '
        'For int8 smoothquant, use smoothquant.py instead. ')
    parser.add_argument("--calib_size",
                        type=int,
                        default=32,
                        help="Number of samples for calibration.")
    parser.add_argument("--export_path",
                        default=os.path.join(now_dir,
                                             "qwen_7b_4bit_gs128_awq.pt"))
    parser.add_argument("--cache_dir",
                        type=str,
                        default=None,
                        help="Directory of dataset cache.")
    parser.add_argument('--seed', type=int, default=None, help='Random seed')
    args = parser.parse_args()
    return args


def main():
    if not torch.cuda.is_available():
        raise EnvironmentError("GPU is required for inference.")

    args = get_args()

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)

    tokenizer = get_tokenizer(args.model_dir, cache_dir=args.cache_dir)
    model = get_model(args.model_dir, args.dtype, cache_dir=args.cache_dir)

    calib_dataloader = get_calib_dataloader(tokenizer=tokenizer,
                                            calib_size=args.calib_size,
                                            cache_dir=args.cache_dir)
    model = quantize_and_export(model,
                                qformat=args.qformat,
                                calib_dataloader=calib_dataloader,
                                export_path=args.export_path)


if __name__ == "__main__":
    main()
