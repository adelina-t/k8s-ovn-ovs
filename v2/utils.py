import subprocess
import os
import logging
from threading import Timer
import errno


class CmdTimeoutExceededException(Exception):
    pass

def run_cmd(cmd, timeout=50000, env=None, stdout=False, stderr=False, cwd=None, shell=False):

    def kill_proc_timout(proc):
        proc.kill()
        raise CmdTimeoutExceededException("Timeout of %s exceeded for cmd %s" % (timeout, cmd))

    FNULL = open(os.devnull, "w")
    f_stderr = FNULL
    f_stdout = FNULL
    if stdout == True:
        f_stdout = subprocess.PIPE
    if stderr == True:
        f_stderr = subprocess.PIPE
    logging.info("Calling %s" % " ".join(cmd))
    if shell:
        cmd = " ".join(cmd)
    proc = subprocess.Popen(cmd, env=env, stdout=f_stdout, stderr=f_stderr, cwd=cwd, shell=shell)
    timer=Timer(timeout, kill_proc_timout, [proc])
    try:
        timer.start()
        stdout, stderr = proc.communicate()
        return stdout, stderr, proc.returncode
    finally:
        timer.cancel()

def clone_repo(repo, branch="master", dest_path=None):
    cmd = ["git", "clone", "--single-branch", "--branch", branch, repo]
    if dest_path:
        cmd.append(dest_path)
    logging.info("Cloning git repo %s on branch %s in location %s" % (repo, branch, dest_path if not None else os.getcwd()))
    _, err, ret = run_cmd(cmd, timeout=300, stderr=True)
    if ret != 0:
        raise Exception("Git Clone Failed with error: %s." % err)
    logging.info("Succesfully cloned git repo.")
 
def mkdir_p(dir_path):
    try:
        os.mkdir(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def get_k8s_folder():
    gopath = os.environ.get("GOPATH") if os.environ.get("GOPATH") else "/go"
    return os.path.join(gopath, "src", "k8s.io", "kubernetes")

def build_k8s_binaries(k8s_path=None):
    k8s_path = k8s_path if k8s_path else get_k8s_folder()
    logging.info("Building K8s Binaries:")
    logging.info("Build k8s linux binaries.")
    cmd = ["make", 'WHAT="cmd/kube-apiserver cmd/kube-controller-manager cmd/kubelet cmd/kubectl cmd/kube-scheduler cmd/kube-proxy"']
    
    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)

    if ret != 0:
        logging.error("Failed to build k8s linux binaries with error: %s" % err)
        raise Exception("Failed to build k8s linux binaries with error: %s" % err)
    
    cmd = ["make", 'WHAT="cmd/kubelet cmd/kubectl cmd/kube-proxy"', "KUBE_BUILD_PLATFORMS=windows/amd64"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)
    if ret != 0:
        logging.error("Failed to build k8s windows binaries with error: %s" % err)
        raise Exception("Failed to build k8s windows binaries with error: %s" % err)
    
    logging.info("Succesfully built k8s binaries.")

def get_k8s(repo, branch):
    logging.info("Get Kubernetes.")
    k8s_path = get_k8s_folder()
    clone_repo(repo, branch, k8s_path)
    # Custom cherry-picks
    cmd = "wget https://github.com/kubernetes/kubernetes/pull/74933.diff && git apply 74933.diff"
    cmd = cmd.split()
    _, err, ret = run_cmd(cmd, stderr=True, cwd=k8s_path, shell=True)
    if ret != 0:
        logging.error("Failed to get cherrypick %s" % err)
        raise Exception("Failed to get cherrypick %s" % err)

def download_file(url, dst):
    cmd = ["wget", url, "-O", dst]
    _, err, ret = run_cmd(cmd)

    if ret != 0:
        logging.error("Failed to download file: %s" % url)

def run_ssh_cmd(cmd, user, host,):
    cmd = ["ssh","-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"]
