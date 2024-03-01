CUDA_VISIBLE_DEVICES=1 nsys profile \
	--trace=cuda,nvtx,cublas,cublas-verbose,cusparse,cudnn \
	--cudabacktrace=all \
	--cuda-graph-trace=graph \
	--cuda-memory-usage=true \
	--cuda-um-cpu-page-faults=true \
	--cuda-um-gpu-page-faults=true \
	--gpuctxsw=true \
	--force-overwrite=true \
	--gpu-metrics-device=1 \
	--stats=true \
	--gpu-metrics-frequency=100 \
        python3 /code/tensorrt_llm/examples/llama/run.py \
	--max_output_len=1 \
        --tokenizer_dir /code/tensorrt_llm/models/llama-2-13b-hf/ \
        --engine_dir=/code/tensorrt_llm/models/
