import deployer
import log
import utils
import os
import configargparse
import subprocess
import stat
import ci
import terraform
import constants

TESTINFRA_REPO_URL = "https://github.com/kubernetes/test-infra"

p = configargparse.get_argument_parser()

p.add("--flannelMode", default="overlay", help="Option: overlay or host-gw")
p.add("--kubeadmRepo", help="Kueadm repo for windows")
p.add("--kubeadmBranch")


class Terraform_Kubeadm(ci.CI):

    def __init__(self):
        super(Terraform_Kubeadm, self).__init__()

        self.deployer = terraform.TerraformProvisioner()

        self.opts = p.parse_known_args()[0]
        self.logging = log.getLogger(__name__)
        self.default_linux_username = "ubuntu" # Oversight in terraform. This should be configurable


    def up(self):
        self.logging.info("Bringing cluster up.")
        try:
            self.deployer.up()
            self._real_build()
            self._prepare_for_kubeadm_deploy()
        except Exception as e:
            raise e

    def build(self, binsToBuild):
        # Since in this scenario we need the master created in order to be able to build binaries
        # This method will act as a dummy builder, passing along the bins to build to the actual
        # build method that will be invoked after terraform creates the machines
        self.binsToBuild = binsToBuild

    def _real_build(self):
        builder_mapping = {
            "k8sbins": self._build_k8s_bins
        }

        def noop_func():
            pass

        for bins in self.binsToBuild:
            self.logging.info("Building %s binaries." % bins)
            builder_mapping.get(bins, noop_func)()


    def _build_k8s_bins(self):
        build_host = self.deployer.get_cluster_master_public_ip()
        remote_k8s_path = "/home/ubuntu/kubernetes"
        # For this scenario, we need docker to build k8s, thus all building should happen on remote master host
        
        k8s_linux_bins = ["kubectl", "kubelet", "kubeadm"]
        k8s_windows_bins = ["kubectl", "kubelet", "kube-proxy", "kubeadm"]

        def _install_prereqs():
            self._runRemoteCmd("sudo apt-get install make", [build_host])

        def _build_k8s_linux_binaries():
            #Binaries built here are to be installed dirrectly on the master, and are not built by the _build_k8s_release_images function
            for binary in k8s_linux_bins:
                self.logging.info("Building %s for linux/amd64" % binary)
                cmd = "cd kubernetes ; build/run.sh make %s KUBE_BUILD_PLATFORMS=linux/amd64 KUBE_VERBOSE=0" % binary
                self._runRemoteCmd(cmd, [build_host])

        def _build_k8s_windows_binaries():
            for binary in k8s_windows_bins:
                self.logging.info("Building %s for windows/amd64" % binary)
                cmd = "cd kubernetes ; build/run.sh make %s KUBE_BUILD_PLATFORMS=windows/amd64 KUBE_VERBOSE=0" % binary
                self._runRemoteCmd(cmd, [build_host])

        def _package_k8s_windows_binaries():
            self.logging.info("Packaging windows binaries.")
            cmd = "cd kubernetes ; mkdir _output/release-tars ; KUBE_BUILD_PLATFORMS=windows/amd64 && TAR=/bin/tar && source build/common.sh && source build/lib/release.sh && kube::release::package_src_tarball && kube::release::package_node_tarballs "
            self._runRemoteCmd(cmd, [build_host])
            
            # remote_path = os.path.join('/home/ubuntu/kubernetes', constants.KUBERNETES_TARBALL_LOCATION, constants.KUBERNETES_WINDOWS_RELEASE_TARBALLS)
            # cmd = "mkdir -p %s" % ( os.path.join('/home/ubuntu/kubernetes', constants.KUBERNETES_TARBALL_LOCATION))
            # self._runRemoteCmd(cmd, [build_host])
            # cmd = "echo 'whatever random' > %s" % remote_path
            # self._runRemoteCmd(cmd, [build_host])

        def _build_k8s_release_images():
            self.logging.info("Building linux release images.")
            cmd = "cd kubernetes ; export KUBE_VERBOSE=0 ; export KUBE_BUILD_CONFORMANCE=n ; export KUBE_BUILD_PLATFORMS=linux/amd64; export KUBE_BUILD_HYPERKUBE=n ;  make quick-release-images"
            self._runRemoteCmd(cmd, [build_host])

        def _get_k8s_version():
            cmd = "cd kubernetes; ./hack/print-workspace-status.sh | grep \"^gitVersion\" | awk '{print $2}' > /tmp/k8s_version.txt"
            self._runRemoteCmd(cmd, [build_host])
            self._copyFrom('/tmp/k8s_version.txt','/tmp/k8s_version.txt', build_host)
            with open('/tmp/k8s_version.txt') as f:
                content = f.read()
            return content.strip().replace('+','_')

        self._clone_k8s_repo(build_host, remote_k8s_path)
        _install_prereqs()
        self.k8s_version = _get_k8s_version()
        _build_k8s_linux_binaries()
        _build_k8s_release_images()
        _build_k8s_windows_binaries()
        _package_k8s_windows_binaries()

    def _prepare_for_kubeadm_deploy(self):
        self._stage_k8s_windows_release()
        self._import_k8s_linux_images()
        self._prepare_configs()

    def _prepare_configs(self):
        self.logging.info("Preapare binaries and configs for master")
        master_bins = ["kubectl", "kubelet", "kubeadm"]
        for binary in master_bins:
            self.logging.info("Installing %s." % binary)
            bin_path = os.path.join("/home/ubuntu/kubernetes", constants.KUBERNETES_DOCKERIZEB_BINS_LINUX_LOCATION, binary)
            bin_install_path = os.path.join("/usr/bin", binary)
            cmd = "sudo install %s %s" % (bin_path, bin_install_path)
            self._runRemoteCmd(cmd, [self.deployer.get_cluster_master_public_ip()])
            
        service_d_path = "/etc/systemd/system/kubelet.service.d/"
        configs = {"kubelet.service": "/lib/systemd/system", 
                   "10-kubeadm.conf": "/etc/systemd/system/kubelet.service.d" }

        self.logging.info("Creating remote kubelet service path")
        cmd = "mkdir -p %s" % service_d_path
        self._runRemoteCmd(cmd, [self.deployer.get_cluster_master_public_ip()])
        for config, install_path in configs.items():
            self.logging.info("Installing config file %s." % config)
            config_path = os.path.join("/home/ubuntu/kubernetes/debs", config)
            config_install_path = os.path.join(install_path, config)
            cmd = "sudo install %s %s" % (config_path, config_install_path)
            self._runRemoteCmd(cmd, [self.deployer.get_cluster_master_public_ip()])

    def _import_k8s_linux_images(self):
        self.logging.info("Importing docker images on master.")
        for image in ['kube-apiserver.tar', 'kube-controller-manager.tar', 'kube-proxy.tar', 'kube-scheduler.tar']:
            image_path = os.path.join("/home/ubuntu/kubernetes", constants.KUBERNETES_IMAGES_LOCATION, image)
            cmd = "docker load -i %s" % image_path
            self.logging.info("Importing %s from %s." % (image, image_path))
            self._runRemoteCmd(cmd, [self.deployer.get_cluster_master_public_ip()])

    def _stage_k8s_windows_release(self):
        self.logging.info("Uploading kubernetes release to Azure blob.")
        tarball_remote_src = os.path.join('/home/ubuntu/kubernetes', constants.KUBERNETES_TARBALL_LOCATION, constants.KUBERNETES_WINDOWS_RELEASE_TARBALLS)
        tarball_local_dst = os.path.join('/tmp/', constants.KUBERNETES_WINDOWS_RELEASE_TARBALLS)
        self._copyFrom(tarball_remote_src, tarball_local_dst, self.deployer.get_cluster_master_public_ip())

        self.windows_k8s_release_blob_name = "%s_%s.tar.gz" % ("kubernetes-node-windows-amd64", self.k8s_version)
        utils.upload_blob(self.windows_k8s_release_blob_name, tarball_local_dst)


    def _clone_k8s_repo(self, remote_host, remote_path):
        cmd = utils.get_clone_command(self.opts.k8s_repo, self.opts.k8s_branch, remote_path)
        self._runRemoteCmd(" ".join(cmd), [remote_host])

    # These functions are implemented like so to preserve the interface defined by collectlogs functions
    # Those functions should be moved to base CI class and they should be used by all children.
    def _runRemoteCmd(self, command, machines, retries=0, windows=False, root=False):
        if windows:
            username = self.deployer.get_win_vm_username()
        else:
            username = self.default_linux_username
        for machine in machines:
            out = utils.run_ssh_cmd(command, username, machine, self.opts.ssh_private_key_path)

    def _copyTo(self, src, dest, machines, windows=False, root=False):
        if windows:
            username = self.deployer.get_win_vm_username()
        else:
            username = self.default_linux_username
        for machine in machines:
            out = utils.scp_put(src, dest, username, machine, self.opts.ssh_private_key_path)

    def _copyFrom(self, src, dest, machine, windows=False, root=False):
        if windows:
            username = self.deployer.get_win_vm_username()
        else:
            username = self.default_linux_username
        out = utils.scp_get(src, dest, username, machine, self.opts.ssh_private_key_path)
