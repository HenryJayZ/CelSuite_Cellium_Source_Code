package com.henny.cellium.shizuku;

interface IShizukuShellService {
    String execCommand(String command, int timeoutSec);
    int getServerUid();
    void destroy();
}
