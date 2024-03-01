#/bin/bash
#--device=/dev/video0
export MY_CONTAINER="TensorRT_LLM_Luqi"
num=`sudo docker ps -a|grep "$MY_CONTAINER"|wc -l`
echo $num,$MY_CONTAINER
if [ 0 -eq $num ];then
  sudo xhost +
  docker run  -it \
		-p 2239:22 \
		--privileged=true \
		--cap-add=SYS_ADMIN \
		--security-opt seccomp=default_with_perf.json \
    		--gpus=all \
    		--volume /home/tj/luckygong/:/home/ \
    		--workdir /home \
    		--name $MY_CONTAINER \
		--tmpfs /tmp:exec \
    		registry.cn-hangzhou.aliyuncs.com/kristonai/tensorrt_llm:23.11 
                /bin/bash
else
  sudo docker start $MY_CONTAINER
  #sudo docker attach $MY_CONTAINER
  sudo docker exec -w /home/ -ti $MY_CONTAINER /bin/bash
fi

