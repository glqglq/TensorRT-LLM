CUDA_VISIBLE_DEVICES=0 nsys profile \
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
	/home/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
	--model llama \
	--engine_dir /home/engines/llama-2-7b-hf-tp1/ \
	--log_level info \
	--duration 60 \
	--num_runs 3 \
	--batch_size 1 \
	--input_output_len 128,20
