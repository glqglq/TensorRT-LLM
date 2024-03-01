CUDA_VISIBLE_DEVICES=6,7 /usr/local/NVIDIA-Nsight-Compute-2023.3/ncu \
	--target-processes all \
	--replay-mode application \
	--app-replay-match grid \
	--app-replay-mode relaxed \
	--kernel-name-base function \
	--launch-skip-before-match 0 \
	--filter-mode global \
	--section PmSampling \
	--profile-from-start 1 \
	--cache-control all \
	--clock-control base \
	--import-source no \
	--check-exit-code yes \
	-o llama27b_in128_out1_rank1-2-pm \
	mpirun  -n 1 --allow-run-as-root \
    /data/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
    --model llama \
    --engine_dir /data/engines/engine-llama-2-7b-fp16-tp1/ \
    --log_level info \
    --duration 1 \
    --num_runs 1 \
    --batch_size 4 \
    --input_output_len 128,1
exit 0
	--section MemoryWorkloadAnalysis \
	--section SchedulerStats \
	--section ComputeWorkloadAnalysis \
	--section WarpStateStats\
CUDA_VISIBLE_DEVICES=0,1 ncu \
	--target-processes all \
	--replay-mode application \
	--app-replay-match grid \
	--app-replay-mode relaxed \
	--kernel-name-base function \
	--launch-skip-before-match 0 \
	--filter-mode global \
	--section LaunchStats \
	--section Occupancy \
	--section SpeedOfLight \
	--sampling-interval auto \
	--sampling-max-passes 5 \
	--sampling-buffer-size 33554432 \
	--profile-from-start 1 \
	--cache-control all \
	--clock-control base \
	--rule LaunchConfiguration \
	--rule Occupancy \
	--rule SOLBottleneck \
	--import-source no \
	--check-exit-code yes \
	-o llama27b_in128_out1_rank2 \
	mpirun  -n 2 --allow-run-as-root \
    /data/TensorRT-LLM-luqi/cpp/build/benchmarks/gptSessionBenchmark \
    --model llama \
    --engine_dir /data/engines/engine-llama-2-7b-fp16-tp2/ \
    --log_level info \
    --duration 1 \
    --num_runs 1 \
    --batch_size 4 \
    --input_output_len 128,1
exit 0
