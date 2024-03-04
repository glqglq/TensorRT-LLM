CUDA_VISIBLE_DEVICES=0	/home/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmarkTwoThread  \
	--model llama \
	--engine_dir /home/engines/llama-2-7b-hf-tp2-halftuning/ \
	--log_level info \
	--duration 60 \
	--num_runs 10000 \
	--batch_size 1 \
	--input_output_len 128,20  > ../../log/llama-2-7b-hf-bs1-tp2-two-halftuning
exit 0

CUDA_VISIBLE_DEVICES=1 mpirun -n 2 --allow-run-as-root \
	/home/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
	--model llama \
	--engine_dir /home/engines/llama-2-7b-hf-tp2/ \
	--log_level info \
	--duration 60 \
	--num_runs 10000 \
	--batch_size 1 \
	--input_output_len 128,20  > ../../log/llama-2-7b-hf-bs1-tp2-mpi
CUDA_VISIBLE_DEVICES=1 mpirun -n 1 --allow-run-as-root \
	/home/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmarkTwoThread \
	--model llama \
	--engine_dir /home/engines/llama-2-7b-hf-tp2/ \
	--log_level info \
	--duration 60 \
	--num_runs 10000 \
	--batch_size 1 \
	--input_output_len 128,20  > ../../log/llama-2-7b-hf-bs1-tp2-two
CUDA_VISIBLE_DEVICES=1 mpirun -n 1 --allow-run-as-root \
	/home/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
	--model llama \
	--engine_dir /home/engines/llama-2-7b-hf-tp1/ \
	--log_level info \
	--duration 60 \
	--num_runs 10000 \
	--batch_size 1 \
	--input_output_len 128,20  > ../../log/llama-2-7b-hf-bs1-tp1
exit 0

