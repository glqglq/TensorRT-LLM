#!/bin/bash

CONTAINER_NAME="TensorRT_LLM_Luqi2"

docker run -itd \
    -p 2241:22 \
    --volume /home/tj/luckygong/:/home/ \
    --gpus=all \
    --workdir /home \
    --name $CONTAINER_NAME \
    --tmpfs /tmp:exec \
    --privileged=true \
    --cap-add=SYS_ADMIN \
    --security-opt seccomp=default_with_perf.json \
    trt_luqi:240302

docker ps -f "name=$CONTAINER_NAME"
docker exec -it $CONTAINER_NAME /bin/bash
