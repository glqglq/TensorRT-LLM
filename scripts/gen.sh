CUDA_VISIBLE_DEVICES=1 python /home/TensorRT-LLM-luqi/examples/llama/build.py \
	--model_dir /home/weights/llama-2-7b-hf/ \
	--max_batch_size 16 \
        --dtype float32 \
        --enable_context_fmha \
        --output_dir /home/engines/llama-2-7b-hf-tp1-fp32/ \
	--tp_size 1 \
	--world_size 1 \
	--embedding_sharding_dim 0



exit 0
# chinese-alpaca-2-1.3b-hf
# llama-2-7b-hf
python /data/TensorRT-LLM-luqi//examples/llama/build.py \
	--model_dir /data/weights/llama-2-7b-hf/ \
	--max_batch_size 4 \
        --dtype float16 \
        --enable_context_fmha \
        --output_dir /data/engines/engine-llama-2-7b-fp16-tp1/ \
	--use_custom_all_reduce \
	--parallel_build \
        --use_parallel_embedding \
	--embedding_sharding_dim 0
