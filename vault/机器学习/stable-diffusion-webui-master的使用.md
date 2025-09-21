

git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git

不好用的时候  要在cmd 里面 用v2rayn的命令


![[Pasted image 20250904160824.png]]




E:\stable-diffusion-webui-master>git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git .
Cloning into '.'...
error: RPC failed; HTTP 408 curl 22 The requested URL returned error: 408
fatal: expected 'packfile'

E:\stable-diffusion-webui-master>set http_proxy=http://127.0.0.1:10808

E:\stable-diffusion-webui-master>set https_proxy=http://127.0.0.1:10808

E:\stable-diffusion-webui-master>set all_proxy=socks5://127.0.0.1:10808

E:\stable-diffusion-webui-master>
E:\stable-diffusion-webui-master>set HTTP_PROXY=http://127.0.0.1:10808

E:\stable-diffusion-webui-master>set HTTPS_PROXY=http://127.0.0.1:10808

E:\stable-diffusion-webui-master>set ALL_PROXY=socks5://127.0.0.1:10808

E:\stable-diffusion-webui-master>git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git
Cloning into 'stable-diffusion-webui'...
remote: Enumerating objects: 34968, done.
remote: Total 34968 (delta 0), reused 0 (delta 0), pack-reused 34968 (from 1)
Receiving objects: 100% (34968/34968), 35.57 MiB | 4.13 MiB/s, done.
Resolving deltas: 100% (24420/24420), done.


这样就可以