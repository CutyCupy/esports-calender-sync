cd ..

scp .\*.py root@h2978645.stratoserver.net:~/scripts/
@REM scp .\config.yaml root@h2978645.stratoserver.net:~/scripts/
scp .\requirements.txt root@h2978645.stratoserver.net:~/scripts/
scp -r .\templates root@h2978645.stratoserver.net:~/scripts/
scp -r .\static root@h2978645.stratoserver.net:~/scripts/

ssh root@h2978645.stratoserver.net "pip install -r scripts/requirements.txt"
ssh root@h2978645.stratoserver.net "systemctl stop ecf-admin-panel"
ssh root@h2978645.stratoserver.net "systemctl start ecf-admin-panel"