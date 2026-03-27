cd ..

scp -r .\app root@h2978645.stratoserver.net:~/esports-calendar-sync/
@REM scp -r .\config root@h2978645.stratoserver.net:~/esports-calendar-sync/
scp .\requirements.txt root@h2978645.stratoserver.net:~/esports-calendar-sync/

ssh root@h2978645.stratoserver.net "pip install -r esports-calendar-sync/requirements.txt"
ssh root@h2978645.stratoserver.net "systemctl stop ecf-admin-panel"
ssh root@h2978645.stratoserver.net "systemctl start ecf-admin-panel"