CUDA_VISIBLE_DEVICES=0,1 mpirun -n 2  --allow-run-as-root nsys profile \
	--trace=mpi,cuda,nvtx,cublas,cublas-verbose,cusparse,cudnn \
	--mpi-impl=openmpi \
	--cudabacktrace=all \
	--cuda-graph-trace=graph \
	--cuda-memory-usage=true \
	--cuda-um-cpu-page-faults=true \
	--cuda-um-gpu-page-faults=true \
	--gpuctxsw=true \
	--force-overwrite=true \
	--stats=true \
	--gpu-metrics-device=0 \
	--gpu-metrics-frequency=100 \
	/data/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
	--model llama \
	--engine_dir /data/engines/engine-llama-2-7b-fp16-tp2/ \
	--log_level info \
	--duration 1 \
	--batch_size 4 \
	--input_output_len 128,1

exit 0

CUDA_VISIBLE_DEVICES=0,1 mpirun -n 1 --allow-run-as-root nsys profile \
	--trace=mpi,cuda,nvtx,cublas,cublas-verbose,cusparse,cudnn \
	--mpi-impl=openmpi \
	--cudabacktrace=all \
	--cuda-graph-trace=graph \
	--cuda-memory-usage=true \
	--cuda-um-cpu-page-faults=true \
	--cuda-um-gpu-page-faults=true \
	--gpuctxsw=true \
	--force-overwrite=true \
	--stats=true \
	--gpu-metrics-device=0 \
	--gpu-metrics-frequency=100 \
	/data/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
	--model llama \
	--engine_dir /data/engines/engine-llama-2-7b-fp16-tp1/ \
	--log_level info \
	--duration 1 \
	--batch_size 4 \
	--input_output_len 128,1
