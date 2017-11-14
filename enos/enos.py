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
from enoslib.task import enostask as task
import logging
import pprint

from docopt import docopt

VERSION="test"


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
    config_file = path.abspath(kwargs['-f'])
    if path.isfile(config_file):
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
    config = load_config(env['config'],
                         provider.topology_to_resources,
                         # Done by enos-lib at init +provider.default_config()+
                         )
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
    inventory = path.join(env['resultdir'], 'multinode')
    # TODO: use enoslib.generate_inventory
    generate_inventory(env['rsc'], env['networks'], inventory, check_networks=True)
    # TODO: Concat inventory_conf + inventory (cf upper)
    inventory_conf = env['config'].get('inventory')
    if not inventory_conf:
        logging.debug("No inventory specified, using the sample.")
        base_inventory = path.join(INVENTORY_DIR, 'inventory.sample')
    else:
        base_inventory = seekpath(inventory_conf)

    logging.info('Generates inventory %s' % inventory)

    env['inventory'] = inventory

    # Set variables required by playbooks of the application
    # TODO: https://github.com/BeyondTheClouds/enos/pull/159/files#diff-15a7159acfc2c0c18193258af93ad086R135
    env['config'].update({
       'vip':               pop_ip(env),
       'registry_vip':      pop_ip(env),
       'influx_vip':        pop_ip(env),
       'grafana_vip':       pop_ip(env),
       'network_interface': eths[NETWORK_IFACE],
       'resultdir':         env['resultdir'],
       'rabbitmq_password': "demo",
       'database_password': "demo",
       # TODO +'external_vip':      pop_ip(env)+
    })

    # Runs playbook that initializes resources (eg,
    # installs the registry, install monitoring tools, ...)
    up_playbook = path.join(ANSIBLE_DIR, 'up.yml')
    # TODO: use enoslib.run_ansible
    run_ansible([up_playbook], inventory, extra_vars=env['config'],
        tags=kwargs['--tags'])


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


def pushtask(ts, f):
    ts.update({f.__name__: f})


def main():
    args = docopt(__doc__,
                  version=VERSION,
                  options_first=True)

    #_configure_logging(args)
    argv = [args['<command>']] + args['<args>']

    enostasks = {}
    pushtask(enostasks, backup)
    pushtask(enostasks, bench)
    pushtask(enostasks, deploy)
    pushtask(enostasks, destroy)
    pushtask(enostasks, info)
    pushtask(enostasks, init)
    pushtask(enostasks, kolla)
    pushtask(enostasks, new)
    pushtask(enostasks, os)
    pushtask(enostasks, tc)
    pushtask(enostasks, up)

    task = enostasks[args['<command>']]
    task(**docopt(task.__doc__, argv=argv))


if __name__ == '__main__':
    main()
