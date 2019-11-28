import subprocess
import os
import log
from threading import Timer
import errno
import random
import shutil
import string
import glob
import constants
import paramiko
#from Crypto.PublicKey import RSA
#from Crypto.Cipher import PKCS1_v1_5 as Cipher_PKCS1_v1_5
from base64 import b64encode
from azure.storage.blob import BlockBlobService

logging = log.getLogger(__name__)


class CmdTimeoutExceededException(Exception):
    pass


def run_cmd(cmd, timeout=50000, env=None, stdout=False,
            stderr=False, cwd=None, shell=False, sensitive=False):

    def kill_proc_timout(proc):
        proc.kill()
        raise CmdTimeoutExceededException("Timeout of %s exceeded for cmd %s" % (timeout, cmd))
    print cmd

    FNULL = open(os.devnull, "w")
    f_stderr = FNULL
    f_stdout = FNULL
    if stdout is True:
        f_stdout = subprocess.PIPE
    if stderr is True:
        f_stderr = subprocess.PIPE
    if not sensitive:
        logging.info("Calling %s" % " ".join(cmd))
    if shell:
        cmd = " ".join(cmd)
    proc = subprocess.Popen(cmd, env=env, stdout=f_stdout, stderr=f_stderr, cwd=cwd, shell=shell)
    timer = Timer(timeout, kill_proc_timout, [proc])
    try:
        timer.start()
        stdout, stderr = proc.communicate()
        return stdout, stderr, proc.returncode
    finally:
        timer.cancel()

def get_clone_command(repo, branch="master", dest_path=None):
    cmd = ["git", "clone", "--single-branch", "--branch", branch, repo]
    if dest_path:
        cmd.append(dest_path)
    return cmd

def clone_repo(repo, branch="master", dest_path=None):
    cmd = get_clone_command(repo, branch, dest_path)
    logging.info("Cloning git repo %s on branch %s in location %s" % (repo, branch, dest_path if not None else os.getcwd()))
    _, err, ret = run_cmd(cmd, timeout=900, stderr=True)
    if ret != 0:
        raise Exception("Git Clone Failed with error: %s." % err)
    logging.info("Succesfully cloned git repo.")


def rm_dir(dir_path):
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)


def mkdir_p(dir_path):
    try:
        os.mkdir(dir_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def generate_random_password(key, length=20):
    passw = ''.join(random.choice(string.ascii_lowercase) for i in range(length // 4))
    passw += ''.join(random.choice(string.ascii_uppercase) for i in range(length // 4))
    passw += ''.join(random.choice(string.digits) for i in range(length // 4))
    passw += ''.join(random.choice("!?.,@#$%^&=") for i in range(length - 3 * (length // 4)))
    passw = ''.join(random.sample(passw, len(passw)))

    pubKeyObj = RSA.importKey(key)
    cipher = Cipher_PKCS1_v1_5.new(pubKeyObj)
    cipher_text = cipher.encrypt(passw.encode())
    enc_pwd = b64encode(cipher_text)
    logging.info("Encrypted pass: %s" % enc_pwd)

    return passw


def get_go_path():
    return os.environ.get("GOPATH") if os.environ.get("GOPATH") else "/go"


def get_bins_path():
    # returns location where all built bins should be stored
    path = os.path.join("/tmp/bins")
    mkdir_p(path)
    return path


def get_k8s_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "k8s.io", "kubernetes")


def get_containerd_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "containerd", "cri")


def get_containerd_shim_folder(fromVendor=False):
    gopath = get_go_path()

    if fromVendor:
        containerd_path = get_containerd_folder()
        path_prefix = os.path.join(containerd_path, "vendor")
    else:
        path_prefix = os.path.join(gopath, "src")

    return os.path.join(path_prefix, "github.com", "Microsoft", "hcsshim")


def get_ctr_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "containerd", "containerd")


def get_sdn_folder():
    gopath = get_go_path()
    return os.path.join(gopath, "src", "github.com", "Microsoft", "windows-container-networking")


def build_containerd_binaries(containerd_path=None, ctr_path=None):
    containerd_path = containerd_path if containerd_path else get_containerd_folder()
    ctr_path = ctr_path if ctr_path else get_ctr_folder()
    logging.info("Building containerd binaries")
    cmd = ["GOOS=windows", "make"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=containerd_path, shell=True)

    if ret != 0:
        logging.error("Failed to build containerd windows binaries with error: %s" % err)
        raise Exception("Failed to build containerd windows binaries with error: %s" % err)

    logging.info("Succesfully built containerd binaries.")

    logging.info("Building ctr")
    cmd = ["GOOS=windows", "make bin/ctr.exe"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=ctr_path, shell=True)

    if ret != 0:
        logging.error("Failed to build ctr windows binary with error: %s" % err)
        raise Exception("Failed to build ctr windows binary with error: %s" % err)

    logging.info("Succesfully built ctr binary.")
    logging.info("Copying built bins to central location")

    containerd_bins_location = os.path.join(containerd_path, constants.CONTAINERD_BINS_LOCATION)
    for path in glob.glob("%s/*" % containerd_bins_location):
        shutil.copy(path, get_bins_path())

    shutil.copy(os.path.join(ctr_path, constants.CONTAINERD_CTR_LOCATION), get_bins_path())


def build_containerd_shim(containerd_shim_path=None, fromVendor=False):
    containerd_shim_path = containerd_shim_path if containerd_shim_path else get_containerd_shim_folder()
    logging.info("Building containerd shim")

    if fromVendor:
        vendoring_path = get_containerd_folder()
        cmd = ["go", "get", "github.com/LK4D4/vndr"]
        _, err, ret = run_cmd(cmd, stderr=True, shell=True)
        if ret != 0:
            logging.error("Failed to install vndr with error: %s" % err)
            raise Exception("Failed to install vndr with error: %s" % err)

        cmd = ["vndr", "-whitelist", "hcsshim", "github.com/Microsoft/hcsshim"]
        _, err, ret = run_cmd(cmd, stderr=True, cwd=vendoring_path, shell=True)
        if ret != 0:
            logging.error("Failed to install vndr with error: %s" % err)
            raise Exception("Failed to install vndr with error: %s" % err)

    cmd = ["GOOS=windows", "go", "build", "-o", constants.CONTAINERD_SHIM_BIN, constants.CONTAINERD_SHIM_DIR]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=containerd_shim_path, shell=True)

    if ret != 0:
        logging.error("Failed to build containerd shim with error: %s" % err)
        raise Exception("Failed to build containerd shim with error: %s" % err)

    logging.info("Succesfully built containerd shim.")
    logging.info("Copying built shim to central location")
    containerd_shim_bin = os.path.join(containerd_shim_path, constants.CONTAINERD_SHIM_BIN)
    shutil.copy(containerd_shim_bin, get_bins_path())


def build_sdn_binaries(sdn_path=None):
    sdn_path = sdn_path if sdn_path else get_sdn_folder()
    logging.info("Build sdn binaries")
    cmd = ["GOOS=windows", "make", "all"]

    _, err, ret = run_cmd(cmd, stderr=True, cwd=sdn_path, shell=True)

    if ret != 0:
        logging.error("Failed to build sdn windows binaries with error: %s" % err)
        raise Exception("Failed to build sdn windows binaries with error: %s" % err)

    logging.info("Successfuly built sdn binaries.")
    logging.info("Copying built bins to central location")
    sdn_bins_location = os.path.join(sdn_path, constants.SDN_BINS_LOCATION)
    for path in glob.glob("%s/*" % sdn_bins_location):
        shutil.copy(path, get_bins_path())


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
    logging.info("Copying built bins to central location.")
    k8s_linux_bins_location = os.path.join(k8s_path, constants.KUBERNETES_LINUX_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_linux_bins_location):
        shutil.copy(path, get_bins_path())
    k8s_windows_bins_location = os.path.join(k8s_path, constants.KUBERNETES_WINDOWS_BINS_LOCATION)
    for path in glob.glob("%s/*" % k8s_windows_bins_location):
        shutil.copy(path, get_bins_path())


def get_k8s(repo, branch):
    logging.info("Get Kubernetes.")
    k8s_path = get_k8s_folder()
    clone_repo(repo, branch, k8s_path)


def download_file(url, dst):
    cmd = ["wget", "-q", url, "-O", dst]
    _, err, ret = run_cmd(cmd, stderr=True)

    if ret != 0:
        logging.error("Failed to download file: %s" % url)

def _get_ssh_client(user, host, key):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, key_filename=key)
    return ssh

def run_ssh_cmd(cmd, user, host, key_file):
    ssh_client = _get_ssh_client(user, host, key_file)
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    std_out = stdout.read().decode()
    std_err = stderr.read().decode()
    logging.info(std_out)
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        logging.error("Failed to run ssh cmd %s with error %s" % (cmd, std_err))
        raise Exception("Failed to run ssh cmd %s with error %s" % (cmd, std_err))
    return std_out

def scp_put(src, dst, user, host, key_file):
    scp_cmd = ["scp", "-o","StrictHostKeyChecking=no","-o","UserKnownHostsFile=/dev/null", "-i", key_file, src, "%s@%s:%s" % (user, host, dst)]

    out, err, ret = run_cmd(scp_cmd, stdout=True, stderr=True, shell=True)
    if ret != 0:
        logging.error("Failed to run scp put cmd %s with error %s" % (scp_cmd, err))
        raise Exception("Failed to run scp put cmd %s with error %s" % (scp_cmd, err))
    return out


def scp_get(src, dst, user, host, key_file):
    scp_cmd = ["scp", "-o","StrictHostKeyChecking=no","-o","UserKnownHostsFile=/dev/null", "-i", key_file, "%s@%s:%s" % (user, host, src), dst]

    out, err, ret = run_cmd(scp_cmd, stdout=True, stderr=True, shell=True)
    if ret != 0:
        logging.error("Failed to run scp get cmd %s with error %s" % (scp_cmd, err))
        raise Exception("Failed to run scp get cmd %s with error %s" % (scp_cmd, err))
    return out

def upload_blob(blob_name, blob_file):
    try:
        container_name = os.environ['AZURE_STORAGE_CONTAINER'].strip()
        storage_account = os.environ['AZURE_STORAGE_ACCOUNT'].strip()
        storage_key = os.environ['AZURE_STORAGE_ACCOUNT_KEY'].strip()

        blob_client = BlockBlobService(account_name=storage_account, account_key=storage_key)
        content = blob_client.list_blobs(container_name)

        
        blob_client.create_blob_from_path(container_name, blob_name, blob_file)
    except Exception as e:
         logging.error("Failed to upload release with error: %s", e)
         raise Exception("Failed to upload release with error: %s" % e)
