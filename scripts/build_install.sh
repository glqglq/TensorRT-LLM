cd /home/TensorRT-LLM-luqi/
# python3 ./scripts/build_wheel.py --clean  --trt_root /usr/local/tensorrt
python3 ./scripts/build_wheel.py --trt_root /usr/local/tensorrt --build_dir=/home/TensorRT-LLM-luqi/cpp/build --benchmarks
pip install ./build/tensorrt_llm*.whl  --target=./  --no-deps --upgrade
