MODEL_FILE_NAME=llama-2-7b-hf
TP_COUNT=2


#nvidia-smi -mig 1
#nvidia-smi mig -i 1 -lgip
#nvidia-smi mig -i 1 -lcip
#nvidia-smi mig -i 1 -cgi 9
#nvidia-smi mig -i 1 -cci 0,1 -gi 1:wq



CUDA_VISIBLE_DEVICES="MIG-26554dc5-3986-5fce-8cef-5e7c89b5790c" python /home/TensorRT-LLM-luqi/examples/llama/build.py \
	--model_dir /home/weights/${MODEL_FILE_NAME}/ \
	--max_batch_size 1 \
        --dtype float16 \
        --enable_context_fmha \
        --output_dir /home/engines/${MODEL_FILE_NAME}-tp${TP_COUNT}-halftuning/ \
	--tp_size ${TP_COUNT} \
	--world_size ${TP_COUNT} \
	--embedding_sharding_dim 0
#nvidia-smi mig -i 1 -dgi

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
