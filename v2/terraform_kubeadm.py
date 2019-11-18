import deployer
import log
import utils
import os
import configargparse
import subprocess
import stat
import ci
import terraform

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
<<<<<<< HEAD
    
=======


    def up(self):
        self.logging.info("Bringing cluster up.")
        try:
            self.deployer.up()
            import time
            time.sleep(1000000000)
        except Exception as e:
            raise e
>>>>>>> e549a1a... Create user profile and copy ssh public key directly in enableWinServices.

    # These functions are implemented like so to preserve the interface defined by collectlogs functions
    # Those functions should be moved to base CI class and they should be used by all children.
    def _runRemoteCmd(self, command, machines, retries, windows=False, root=False):
        if windows:
            username = self.deployer.get_win_vm_username()
        else:
            username = self.default_linux_username
        for machine in machines:
            out = utils.run_ssh_cmd([command], username, machine, self.opts.ssh_private_key_path)
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
