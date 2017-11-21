import logging
from enos.provider.provider import Provider
from enos.utils.extra import gen_enoslib_roles
import enoslib.infra.enos_vagrant.provider as enoslib_vagrant

def _build_enoslib_conf(conf):
    resources = conf.get("topology", conf.get("resources"))
    machines = []
    for desc in gen_enoslib_roles(resources):
        # NOTE(msimonin): in the basic definition, we consider only
        # two networks
        machines.append({
            "flavor": desc["flavor"],
            "roles": desc["roles"],
            "number": desc["number"],
            "networks": ["network_interface", "neutron_external_interface"]
        })
    enoslib_conf = conf.get("provider", {})
    if enoslib_conf.get("resources") is None:
        enoslib_conf.update({"resources": {"machines": machines}})
    return enoslib_conf

class Enos_vagrant(Provider):

    def init(self, conf, force_deploy=False):
        logging.info("Vagrant provider")
        resources = conf.get("resources", {})
        enoslib_conf = _build_enoslib_conf(conf)
        vagrant = enoslib_vagrant.Enos_vagrant(enoslib_conf)
        roles, networks = vagrant.init(force_deploy)
        return roles, networks

    def destroy(self, env):
        logging.info("Destroying vagrant deployment")
        enoslib_conf = _build_enoslib_conf(env['config'])
        vagrant = enoslib_vagrant.Enos_vagrant(enoslib_conf)
        vagrant.destroy()

    def default_config(self):
        return {
            'backend': 'virtualbox',
            'box': 'debian/jessie64',
            'user': 'root',
        }
