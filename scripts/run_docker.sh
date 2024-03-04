#!/bin/bash
MY_CONTAINER="TensorRT_LLM_Luqi_Run"
num=`sudo docker ps -a|grep "$MY_CONTAINER"|wc -l`
echo $num,$MY_CONTAINER
if [ 0 -eq $num ];then
  docker run  -itd \
		-p 2239:22 \
		--privileged=true \
		--cap-add=SYS_ADMIN \
		--security-opt seccomp=default_with_perf.json \
    		--gpus=all \
    		--volume /home/tj/luckygong/:/home/ \
    		--workdir /home \
    		--name $MY_CONTAINER \
		--tmpfs /tmp:exec \
    	        trt_luqi:240302 
  #docker start $MY_CONTAINER
  #docker exec -w /home/ -it $MY_CONTAINER /bin/bash
fi
#else
sudo docker start $MY_CONTAINER
  # sudo docker attach $MY_CONTAINER
sudo docker exec -w /home/ -ti $MY_CONTAINER /bin/bash
