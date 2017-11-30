# -*- coding: utf-8 -*-
"""Enos: Monitor and test your OpenStack.

usage: enos <command> [<args> ...] [-e ENV|--env=ENV]
            [-h|--help] [-v|--version] [-s|--silent|--vv]

General options:
  -e ENV --env=ENV  Path to the environment directory. You should
                    use this option when you want to link to a specific
                    experiment. Not specifying this value will
                    discard the loading of the environment (it
                    makes sense for `up`).
  -h --help         Show this help message.
  -s --silent       Quiet mode.
  -v --version      Show version number.
  -vv               Verbose mode.

Commands:
  new            Print a reservation.yaml example
  up             Get resources and install the docker registry.
  os             Run kolla and install OpenStack.
  init           Initialise OpenStack with the bare necessities.
  bench          Run rally on this OpenStack.
  backup         Backup the environment
  ssh-tunnel     Print configuration for port forwarding with horizon.
  tc             Enforce network constraints
  info           Show information of the actual deployment.
  destroy        Destroy the deployment and optionally the related resources.
  deploy         Shortcut for enos up, then enos os and enos config.


See 'enos <command> --help' for more information on a specific
command.

"""

from docopt import docopt
from enoslib.task import enostask as task
from enoslib.api import run_ansible, emulate_network, validate_network
import json
import logging
import operator
import os
import pickle
import pprint
from subprocess import check_call
from utils.errors import EnosFilePathError
from utils.extra import (make_provider, generate_inventory,
seekpath, get_vip_pool, pop_ip, bootstrap_kolla, lookup_network)
from utils.constants import (ANSIBLE_DIR, INVENTORY_DIR, VERSION, TEMPLATE_DIR)
import yaml

def deploy(**kwargs):
    """
usage: enos deploy [-e ENV|--env=ENV] [-f CONFIG_PATH] [--force-deploy]
                   [-s|--silent|-vv]

Shortcut for enos up, then enos os, and finally enos config.

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment.
  -f CONFIG_PATH       Path to the configuration file describing the
                       deployment [default: ./reservation.yaml].
  --force-deploy       Force deployment [default: False].
  -s --silent          Quiet mode.
  -vv                  Verbose mode.
    """
    # --reconfigure and --tags can not be provided in 'deploy'
    # but they are required for 'up' and 'install_os'
    kwargs['--reconfigure'] = False
    kwargs['--tags'] = None

    up(**kwargs)

    install(**kwargs)
    # TODO
    #init_os(**kwargs)


@task()
def destroy(env=None, **kwargs):
    """
usage: enos destroy [-e ENV|--env=ENV] [-s|--silent|-vv] [--hard]
                    [--include-images]

Destroy the deployment.

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment.
  -h --help            Show this help message.
  --hard               Destroy the underlying resources as well.
  --include-images     Remove also all the docker images.
  -s --silent          Quiet mode.
  -vv                  Verbose mode.
"""

    hard = kwargs['--hard']
    if hard:
        logging.info('Destroying all the resources')
        provider = make_provider(env)
        provider.destroy(env)
    else:
        command = ['destroy', '--yes-i-really-really-mean-it']
        if kwargs['--include-images']:
            command.append('--include-images')
        kolla_kwargs = {'--': True,
                  '-v': kwargs['-v'],
                  '<command>': command,
                  '--silent': kwargs['--silent'],
                  'kolla': True}
        kolla(env=env['resultdir'], **kolla_kwargs)


@task()
def kolla(env=None, **kwargs):
    """
usage: enos kolla [-e ENV|--env=ENV] [-s|--silent|-vv] -- <command>...

Run arbitrary Kolla command.

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment.
  -h --help            Show this help message.
  -s --silent          Quiet mode.
  -vv                  Verbose mode.
  command              Kolla command (e.g prechecks, checks, pull)
    """
    logging.info('Kolla command')
    logging.info(kwargs)
    kolla_path = os.path.join(env['resultdir'], 'kolla')
    kolla_cmd = [os.path.join(kolla_path, "tools", "kolla-ansible")]
    kolla_cmd.extend(kwargs['<command>'])
    kolla_cmd.extend(["-i", "%s/multinode" % env['resultdir'],
                      "--passwords", "%s/passwords.yml" % env['resultdir'],
                      "--configdir", "%s" % env['resultdir']])
    logging.info(kolla_cmd)
    check_call(kolla_cmd)


@task()
def install(env=None, **kwargs):
    """
usage: enos os [-e ENV|--env=ENV] [--reconfigure] [-t TAGS|--tags=TAGS]
               [-s|--silent|-vv]

Run kolla and install OpenStack.

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment [default: %s].
  -h --help            Show this help message.
  --reconfigure        Reconfigure the services after a deployment.
  -s --silent          Quiet mode.
  -t TAGS --tags=TAGS  Only run ansible tasks tagged with these values.
  -vv                  Verbose mode.
    """
    # Clone or pull Kolla
    kolla_path = os.path.join(env['resultdir'], 'kolla')
    if os.path.isdir(kolla_path):
        logging.info("Remove previous Kolla installation")
        check_call("rm -rf %s" % kolla_path, shell=True)

    logging.info("Cloning Kolla repository...")
    check_call("git clone %s --branch %s --single-branch --quiet %s" %
                   (env['config']['kolla_repo'],
                    env['config']['kolla_ref'],
                    kolla_path),
               shell=True)

    # Bootstrap kolla running by patching kolla sources (if any) and
    # generating admin-openrc, globals.yml, passwords.yml
    bootstrap_kolla(env)

    # Construct kolla-ansible command...
    kolla_cmd = [os.path.join(kolla_path, "tools", "kolla-ansible")]

    if kwargs['--reconfigure']:
        kolla_cmd.append('reconfigure')
    else:
        kolla_cmd.append('deploy')

    kolla_cmd.extend(["-i", "%s/multinode" % env['resultdir'],
                      "--passwords", "%s/passwords.yml" % env['resultdir'],
                      "--configdir", "%s" % env['resultdir']])

    if kwargs['--tags']:
        kolla_cmd.extend(['--tags', kwargs['--tags']])

    logging.info("Calling Kolla...")
    check_call(kolla_cmd)


@task()
def info(env=None, **kwargs):
    """
usage: enos info [-e ENV|--env=ENV] [--out={json,pickle,yaml}]

Show information of the `ENV` deployment.

Options:

  -e ENV --env=ENV         Path to the environment directory. You should use
                           this option when you want to link a
                           specific experiment.

  --out {json,pickle,yaml} Output the result in either json, pickle or
                           yaml format.
    """

    if not kwargs['--out']:
        pprint.pprint(env)
    elif kwargs['--out'] == 'json':
        print json.dumps(env, default=operator.attrgetter('__dict__'))
    elif kwargs['--out'] == 'pickle':
        print pickle.dumps(env)
    elif kwargs['--out'] == 'yaml':
        print yaml.dump(env)
    else:
        print("--out doesn't suppport %s output format" % kwargs['--out'])
        print(info.__doc__)


@task()
def init(env=None, **kwargs):
    """
usage: enos init [-e ENV|--env=ENV] [-s|--silent|-vv]

Initialise OpenStack with the bare necessities:
- Install a 'member' role
- Download and install a cirros image
- Install default flavor (m1.tiny, ..., m1.xlarge)
- Install default network

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment.
  -h --help            Show this help message.
  -s --silent          Quiet mode.
  -vv                  Verbose mode.
    """
    logging.debug('phase[init]: args=%s' % kwargs)

    cmd = []
    cmd.append('. %s' % os.path.join(env['resultdir'], 'admin-openrc'))
    # add cirros image
    url = 'http://download.cirros-cloud.net/0.3.4/cirros-0.3.4-x86_64-disk.img'
    images = [{'name': 'cirros.uec',
               'url': url}]
    for image in images:
        cmd.append("wget -q -O /tmp/%s %s" % (image['name'], image['url']))
        cmd.append("openstack image list "
                   "--property name=%(image_name)s -c Name -f value "
                   "| grep %(image_name)s"
                   "|| openstack image create"
                   " --disk-format=qcow2"
                   " --container-format=bare"
                   " --property architecture=x86_64"
                   " --public"
                   " --file /tmp/%(image_name)s"
                   " %(image_name)s" % {'image_name': image['name'], })

    # flavors name, ram, disk, vcpus

    flavors = [('m1.tiny', 512, 1, 1),
               ('m1.small', 2048, 20, 1),
               ('m1.medium', 4096, 40, 2),
               ('m1.large', 8192, 80, 4),
               ('m1.xlarge', 16384, 160, 8)]
    for flavor in flavors:
        cmd.append("openstack flavor create %s"
                   " --id auto"
                   " --ram %s"
                   " --disk %s"
                   " --vcpus %s"
                   " --public" % (flavor[0], flavor[1], flavor[2], flavor[3]))

    # security groups - allow everything
    protos = ['icmp', 'tcp', 'udp']
    for proto in protos:
        cmd.append("openstack security group rule create default"
                   " --protocol %s"
                   " --dst-port 1:65535"
                   " --src-ip 0.0.0.0/0" % proto)

    # quotas - set some unlimited for admin project
    quotas = ['cores', 'ram', 'instances']
    for quota in quotas:
        cmd.append('nova quota-class-update --%s -1 default' % quota)

    quotas = ['fixed-ips', 'floating-ips']
    for quota in quotas:
        cmd.append('openstack quota set --%s -1 admin' % quota)

    # default network (one public/one private)
    cmd.append("openstack network create public"
               " --share"
               " --provider-physical-network physnet1"
               " --provider-network-type flat"
               " --external")

    provider_net = lookup_network(env['networks'],
                                  'neutron_external_interface')

    cmd.append("openstack subnet create public-subnet"
               " --network public"
               " --subnet-range %s"
               " --no-dhcp"
               " --allocation-pool start=%s,end=%s"
               " --gateway %s"
               " --dns-nameserver %s"
               " --ip-version 4" % (
                   provider_net['cidr'],
                   provider_net['start'],
                   provider_net['end'],
                   provider_net['gateway'],
                   provider_net['dns']))

    cmd.append("openstack network create private"
               " --provider-network-type vxlan")

    cmd.append("openstack subnet create private-subnet"
               " --network private"
               " --subnet-range 192.168.0.0/18"
               " --gateway 192.168.0.1"
               " --dns-nameserver %s"
               " --ip-version 4" % (provider_net['dns']))

    # create a router between this two networks
    cmd.append('openstack router create router')
    # NOTE(msimonin): not sure how to handle these 2 with openstack cli
    cmd.append('neutron router-gateway-set router public')
    cmd.append('neutron router-interface-add router private-subnet')

    cmd = '\n'.join(cmd)

    logging.info(cmd)
    check_call(cmd, shell=True)


@task()
def new(env=None, **kwargs):
    """
usage: enos new [-e ENV|--env=ENV] [-s|--silent|-vv]

Print reservation example, to be manually edited and customized:

  enos new > reservation.yaml

Options:
  -h --help            Show this help message.
  -s --silent          Quiet mode.
  -vv                  Verbose mode.
    """
    logging.debug('phase[new]: args=%s' % kwargs)
    with open(os.path.join(TEMPLATE_DIR, 'reservation.yaml.sample'),
              mode='r') as content:
        print content.read()

@task()
def tc(env=None, **kwargs):
    """
usage: enos tc [-e ENV|--env=ENV] [--test] [-s|--silent|-vv]

Enforce network constraints

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link a specific
                       experiment.
  -h --help            Show this help message.
  -s --silent          Quiet mode.
  --test               Test the rules by generating various reports.
  -vv                  Verbose mode.
    """
    roles = env["rsc"]
    inventory = env["inventory"]
    test = kwargs['--test']
    if test:
        validate_network(roles, inventory)
    else:
        network_constraints = env["config"]["network_constraints"]
        emulate_network(roles, inventory, network_constraints)


@task(new=True)
def up(env=None, **kwargs):
    """
usage: enos up  [-e ENV|--env=ENV][-f CONFIG_PATH] [--force-deploy]
                [-t TAGS|--tags=TAGS] [-s|--silent|-vv]

Get resources and install the docker registry.

Options:
  -e ENV --env=ENV     Path to the environment directory. You should
                       use this option when you want to link to a specific
                       experiment. Do not specify it in other cases.
  -f CONFIG_PATH       Path to the configuration file describing the
                       deployment [default: ./reservation.yaml].
  -h --help            Show this help message.
  --force-deploy       Force deployment [default: False].
  -s --silent          Quiet mode.
  -t TAGS --tags=TAGS  Only run ansible tasks tagged with these values.
  -vv                  Verbose mode.

    """
    # Loads the configuration file
    config_file = os.path.abspath(kwargs['-f'])
    if os.path.isfile(config_file):
        env['config_file'] = config_file
        with open(config_file, 'r') as f:
            env['config'].update(yaml.load(f))
            logging.info("Reloaded configuration file %s", env['config_file'])
            logging.debug("Configuration is %s", env['config'])
    else:
        raise EnosFilePathError(
            config_file, "Configuration file %s does not exist" % config_file)

    # TODO: Check json schema for enos (not provider)

    # Calls the provider and initialise resources
    provider = make_provider(env)
    # TODO: remove the following
    #config = load_config(env['config'],
    #                     provider.topology_to_resources,
                         # Done by enos-lib at init +provider.default_config()+
    #                     )
    # TODO: Directly pass env['config'], 3 cases:
    # - rsc is a simple description :: transform it to a enos-lib one
    # - rsc is a topos description :: transform it to a enos-lib one
    # - rsc is a enos-lib description (under provider key) :: pass it to enos-lib
    rsc, networks = \
        provider.init(env['config'], kwargs['--force-deploy'])

    env['rsc'] = rsc
    env['networks'] = networks

    logging.debug("Provider ressources: %s", env['rsc'])
    logging.debug("Provider network information: %s", env['networks'])

    # Generates inventory for ansible/kolla
    inventory = os.path.join(env['resultdir'], 'multinode')
    inventory_conf = env['config'].get('inventory')
    if not inventory_conf:
        logging.debug("No inventory specified, using the sample.")
        base_inventory = os.path.join(INVENTORY_DIR, 'inventory.sample')
    else:
        base_inventory = seekpath(inventory_conf)

    generate_inventory(env['rsc'], env['networks'], base_inventory, inventory)
    logging.info('Generates inventory %s' % inventory)

    env['inventory'] = inventory

    # Set variables required by playbooks of the application
    # TODO: https://github.com/BeyondTheClouds/enos/pull/159/files#diff-15a7159acfc2c0c18193258af93ad086R135
    vip_pool = get_vip_pool(networks)
    env['config'].update({
       'vip':               pop_ip(vip_pool),
       'registry_vip':      pop_ip(vip_pool),
       'influx_vip':        pop_ip(vip_pool),
       'grafana_vip':       pop_ip(vip_pool),
       'resultdir':         env['resultdir'],
       'rabbitmq_password': "demo",
       'database_password': "demo",
    })

    # Runs playbook that initializes resources (eg,
    # installs the registry, install monitoring tools, ...)
    up_playbook = os.path.join(ANSIBLE_DIR, 'up.yml')
    # TODO: use enoslib.run_ansible
    run_ansible([up_playbook], inventory, extra_vars=env['config'],
        tags=kwargs['--tags'])



def pushtask(ts, f):
    ts.update({f.__name__: f})


def main():
    args = docopt(__doc__,
                  version=VERSION,
                  options_first=True)

    #_configure_logging(args)
    argv = [args['<command>']] + args['<args>']

    enostasks = {}
    # pushtask(enostasks, backup)
    # pushtask(enostasks, bench)
    pushtask(enostasks, deploy)
    pushtask(enostasks, destroy)
    pushtask(enostasks, kolla)
    pushtask(enostasks, info)
    pushtask(enostasks, init)
    pushtask(enostasks, install)
    pushtask(enostasks, new)
    pushtask(enostasks, tc)
    pushtask(enostasks, up)

    task = enostasks[args['<command>']]
    task(**docopt(task.__doc__, argv=argv))


if __name__ == '__main__':
    main()
