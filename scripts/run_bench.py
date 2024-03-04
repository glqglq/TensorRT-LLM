python /code/tensorrt_llm/benchmarks/python/benchmark.py \
        --batch_size 4 \
        --input_output_len 128,2 \
        --warm_up 0 \
        --duration 3 \
        --engine_dir ../models/engine-llama-2-7b-fp16/
