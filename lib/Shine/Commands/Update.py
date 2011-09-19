# Update.py -- Update a file system with a new model file
# Copyright (C) 2011 CEA
#
# This file is part of shine
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
# $Id$

"""
Shine 'update' command class.
"""

from Shine.Commands.Status import Status

from Shine.Configuration.Globals import Globals

from Shine.Commands.Exceptions import CommandHelpException
from Shine.Commands.Base.Command import Command
from Shine.Commands.Base.CommandRCDefs import RC_OK, RC_FAILURE
from Shine.Commands.Base.Support.LMF import LMF
from Shine.Commands.Base.Support.Yes import Yes
from Shine.Commands.Base.Support.Nodes import Nodes
from Shine.Commands.Base.Support.Verbose import Verbose

from Shine.FSUtils import open_model, open_lustrefs, create_lustrefs, \
                          convert_comparison, instantiate_lustrefs

from Shine.Commands.Base.FSEventHandler import FSGlobalEventHandler

from Shine.Lustre.FileSystem import FSRemoteError, ComponentGroup, OFFLINE, \
                                    MOUNTED, TARGET_ERROR, CLIENT_ERROR, \
                                    RUNTIME_ERROR, RECOVERING

class GlobalUpdateEventHandler(FSGlobalEventHandler):

    ACTION = 'update'
    ACTIONING = 'updating'

    def __init__(self, verbose=1, fs_conf=None):
        FSGlobalEventHandler.__init__(self, verbose, fs_conf)

        for event in ('start', 'done', 'failed'):
            # Journal
            funcname = "ev_formatjournal_%s" % event
            currname = "ev_actionjournal_%s" % event
            setattr(self, funcname, getattr(self, currname))
            # Target
            for action in ('start', 'format', 'fsck', 
                           'status', 'stop', 'tunefs'):
                funcname = "ev_%starget_%s" % (action, event)
                currname = "ev_actiontarget_%s" % event
                setattr(self, funcname, getattr(self, currname))
            # Router
            for action in ('start', 'status', 'stop'):
                funcname = "ev_%srouter_%s" % (action, event)
                currname = "ev_actionrouter_%s" % event
                setattr(self, funcname, getattr(self, currname))
            # Client
            for action in ('mount', 'status', 'umount'):
                funcname = "ev_%sclient_%s" % (action, event)
                currname = "ev_actionclient_%s" % event
                setattr(self, funcname, getattr(self, currname))

    def handle_post(self, fs):
        if self.verbose > 0:
            Status.status_view_fs(fs, show_clients=False)

    def ev_actionjournal_start(self, node, comp):
        self.action_start(node, comp, 'journal')
    def ev_actionjournal_done(self, node, comp):
        self.action_done(node, comp, 'journal')
    def ev_actionjournal_failed(self, node, comp, rc, message):
        self.action_failed(node, comp, rc, message, 'journal')

    def ev_actiontarget_start(self, node, comp):
        self.action_start(node, comp)
    def ev_actiontarget_done(self, node, comp):
        self.action_done(node, comp)
    def ev_actiontarget_failed(self, node, comp, rc, message):
        self.action_failed(node, comp, rc, message)

    def ev_actionrouter_start(self, node, comp):
        self.action_start(node, comp)
    def ev_actionrouter_done(self, node, comp):
        self.action_done(node, comp)
    def ev_actionrouter_failed(self, node, comp, rc, message):
        self.action_failed(node, comp, rc, message)

    def ev_actionclient_start(self, node, comp):
        self.action_start(node, comp)
    def ev_actionclient_done(self, node, comp):
        self.action_done(node, comp)
    def ev_actionclient_failed(self, node, comp, rc, message):
        self.action_failed(node, comp, rc, message)

class CannotApplyError(Exception):
    """Filesystem cannot be uninstall for update."""
    def __init__(self, action, elements):
        Exception.__init__(self, "Cannot %s where needed" % action)
        self.elements = elements

class Update(Command):
    """Update an installed filesystem with a updated model file."""
 
    NAME = "update"
    DESCRIPTION = "Update an installed filesystem with a new model"

    GLOBAL_EH = GlobalUpdateEventHandler

    def __init__(self):
        Command.__init__(self)

        self.verbose_support = Verbose(self)

        self.lmf_support = LMF(self)
        self.nodes_support = Nodes(self)

        self.yes_support = Yes(self)

    def lmfpath(self):
        """Check LMF value and return a full LMF path"""

        if not self.opt_m:
            raise CommandHelpException("Lustre model file path "
                                       "(-m <model_file>) "
                                       "argument required.", self)

        lmf = self.lmf_support.get_lmf_path()
        if lmf:
            print "Using Lustre model file %s" % lmf
        else:
            raise CommandHelpException("Lustre model file for ``%s'' not " \
                    "found: please use filename or full LMF path.\n" \
                    "Your default model files directory (lmf_dir) " \
                    "is: %s" % (self.opt_m, Globals().get_lmf_dir()), self)
        return lmf

    def ask_confirm(self, prompt):
        """
        Ask user for confirmation if -y not specified.

        Return True when the user confirms the action, False otherwise.
        """
        return self.yes_support.has_yes() or Command.ask_confirm(self, prompt)


    def __warning(self, message):
        """Helper to display a warning message."""
        print "WARNING: %s" % message

    def __verbose(self, message):
        """Helper to display a verbose message, if enabled."""
        if self.verbose_support.has_verbose():
            print message

    def __debug(self, message):
        """Helper to display a debug message, if enabled."""
        if self.debug_support.has_debug():
            print "DEBUG ", message

    @classmethod
    def display_changes(cls, changes):
        """Display changes detected in a filesystem comparison."""
        
        txt = []
        for action in ('unmount', 'stop'):
            if action in changes:
                comps = changes[action]
                txt.append(" %10s: %d component(s) on %s" % 
                           (action.capitalize(), len(comps), comps.servers()))
                if action == 'stop':
                    txt.append("Warning: A target should be empty before" \
                               " being removed.")
        for action in ('tunefs', 'writeconf', 'reformat', 'remount', 'restart'):
            if action in changes:
                txt.append(" %10s: Yes" % action.capitalize())
        for action in ('format', 'start', 'mount'):
            if action in changes:
                comps = changes[action]
                txt.append(" %10s: %d component(s) on %s" % 
                           (action.capitalize(), len(comps), comps.servers()))
        if txt:
            print "FILESYSTEM CHANGES\n%s\n" % "\n".join(txt)

    @classmethod
    def __show_proxy_errors(cls, fs):
        """Display proxy error messages for the specified filesystem."""
        for nodes, message in fs.proxy_errors:
            print "%s: %s" % (nodes, message)

    def _apply(self, fs, action, actiontxt, comps, expected):
        """Apply an action on the provided filesystem and check for errors."""

        # TODO: Comps should be set disabled by arguments.
        filter_states = [expected, TARGET_ERROR, CLIENT_ERROR, RUNTIME_ERROR]
        comps = comps.filter(key=lambda c: c.state not in filter_states)
        if len(comps):
            self.__verbose("%s components on %s ..." % (actiontxt.capitalize(),
                                                        comps.servers()))
            fs.event_handler.ACTION = actiontxt
            fs.event_handler.ACTIONING = actiontxt + 'ing'
            result = action(comps=comps)

            # Got an error if state is not the expected one. 
            # Proxy errors set result to RUNTIME_ERROR
            if result != expected:
                self.__show_proxy_errors(fs)
                raise CannotApplyError(actiontxt, "this component")

    # XXX: Could be merged with _apply() method?
    def _precheck(self, fs, action, actiontxt, comps):
        """Check status on provided components."""

        if len(comps):
            self.__verbose("%s components on %s ..." % (actiontxt.capitalize(),
                                                        comps.servers()))
            fs.event_handler.ACTION = actiontxt
            fs.event_handler.ACTIONING = actiontxt + 'ing'
            result = action(comps=comps)

            # Got an error if state is not the expected one. 
            # Proxy errors set result to RUNTIME_ERROR
            if result not in [OFFLINE, RECOVERING, MOUNTED]:
                self.__show_proxy_errors(fs)
                raise CannotApplyError(actiontxt, "this component")


    def _remove(self, fs, action, actiontxt, servers):
        """Uninstall configuration for provided servers for provided
        filesystem."""

        # TODO: Comps should be set disabled by arguments.
        if len(servers):
            self.__verbose("%s configuration from %s ..." %
                            (actiontxt.capitalize(), servers))
            fs.event_handler.ACTION = actiontxt
            fs.event_handler.ACTIONING = actiontxt + 'ing'
            result = action(servers)

            # Got an error if state is not the expected one. 
            # Proxy errors set result to RUNTIME_ERROR
            if result != 0:
                self.__show_proxy_errors(fs)
                raise CannotApplyError(actiontxt, "those servers")


    def _copy(self, fs, conf_file):
        """Install a configuration on needed nodes."""
        
        try:
            self.__verbose("Update configuration file: %s" % conf_file)
            fs.install(conf_file)
        except FSRemoteError, error:
            self.__warning("Due to error, configuration update skipped on %s" \
               % error.nodes)
            return RC_FAILURE
        else:
            self.__verbose("Configuration file successfully updated.")

    @classmethod
    def _next_action_cmd(cls, action, fs, options=''):
        """
        Helper to build the shine command line to run the specified action.
        """
        return '  shine %s -f %s %s' % (action, fs.fs_name, options)


    def execute(self):

        rc = RC_OK

        # Check
        lmf = self.lmfpath()

        # Load next model
        newconf = open_model(lmf)
        newfsconf = newconf._fs
        newfsconf.setup_target_devices(update_mode=True)
        neweh = self.GLOBAL_EH(self.verbose_support.get_verbose_level())
        newfs = instantiate_lustrefs(newconf, 
                                   nodes=self.nodes_support.get_nodeset(),
                                   excluded=self.nodes_support.get_excludes(),
                                   event_handler=neweh)
        newfs.set_debug(self.debug_support.has_debug())

        # Load current registered FS
        oldeh = self.GLOBAL_EH(self.verbose_support.get_verbose_level())
        oldconf, oldfs = open_lustrefs(newfsconf.fs_name, 
                                     nodes=self.nodes_support.get_nodeset(),
                                     excluded=self.nodes_support.get_excludes(),
                                     event_handler=oldeh)
        oldfs.set_debug(self.debug_support.has_debug())

        # Compare them
        actions = oldconf._fs.compare(newfsconf)

        # Convert Configuration objects to ComponentGroup
        # for old filesystem
        oldcomps = ComponentGroup()
        for action in ('unmount', 'stop'):
            if action in actions:
                actions[action] = convert_comparison(oldconf, oldfs,
                                                     actions[action]).managed()
                if len(actions[action]) == 0:
                    del actions[action]
                else:
                    oldcomps.update(actions[action])
        # for new filesystem
        for action in ('format', 'start', 'mount'):
            if action in actions:
                # XXX: Do we need to add .managed() here?
                actions[action] = convert_comparison(newconf, newfs, 
                                                     actions[action])

        self.display_changes(actions)

        # XXX: Update message with node list
        if not self.ask_confirm("Update `%s': do you want to continue?" %
                                oldfs.fs_name):
            return RC_FAILURE

        # Will call the handle_pre() method defined by the event handler.
        if hasattr(oldeh, 'pre'):
            oldeh.pre(oldfs)

        #
        # UNINSTALL unused component for old filesystem version.
        #

        try:

            # Check status of removed components
            if len(oldcomps):
                self._precheck(oldfs, oldfs.status, 'verify', comps=oldcomps)

            # Unmount what's will be removed
            if 'unmount' in actions:
                comps = actions['unmount']
                self._apply(oldfs, oldfs.umount, 'unmount', comps, OFFLINE)

            # Stop what's will be removed
            if 'stop' in actions:
                self._apply(oldfs, oldfs.stop, 'stop', actions['stop'], OFFLINE)

            # Remove conf on now unused nodes
            # XXX: This does not take _precheck() status into account.
            oldservers = oldcomps.managed().allservers()
            newservers = newfs.components.managed().allservers()
            removedsrvs = oldservers.difference(newservers)
            if len(removedsrvs) > 0:
                self.__verbose("Remove configuration from %s" % removedsrvs)
                self._remove(oldfs, oldfs.remove, "uninstall", removedsrvs)

        except CannotApplyError, exp:
            self.__warning(str(exp))
            print "Please fix the error or disable %s and restart the update" \
                  % exp.elements + " command"
            return 1
            

        # Unregister from backend
        if 'unmount' in actions:
            servers = actions['unmount'].servers()
            self.__verbose("Remove client(s) %s from backend." % servers)
            oldconf.unregister_clients(servers)
        if 'stop' in actions:
            self.__verbose("Remove target(s) %s from backend." % 
                           actions['stop'].labels())
            for comp in actions['stop'].filter(supports='dev'):
                tgtlist = [oldconf.get_target_from_tag_and_type(
                                 comp.tag, comp.TYPE.upper())]
                oldconf.set_status_targets_available(tgtlist)

        #
        # NewFS
        #

        # Register the new conf
        self.__debug("Create new filesystem version")

        # XXX: Replace that with a simple fs save.
        newconf, newfs = create_lustrefs(lmf, 
                                    nodes=self.nodes_support.get_nodeset(),
                                    excluded=self.nodes_support.get_excludes(),
                                    event_handler=neweh,
                                    update_mode=True)
        newfs.set_debug(self.debug_support.has_debug())

        # Will call the handle_pre() method defined by the event handler.
        if hasattr(neweh, 'pre'):
            neweh.pre(newfs)

        # Update with new conf
        # Note: For user convenience, we always copy configuration, this could
        # help when nodes are misinstalled.
        self._copy(newfs, newconf.get_cfg_filename())
        if Globals().get_tuning_file():
            self._copy(newfs, Globals().get_tuning_file())


        next_actions = []

        # Tunefs if needed
        if 'tunefs' in actions or 'writeconf' in actions:
            next_actions.append("Need to run `tunefs' on some components.")
            next_actions.append(self._next_action_cmd('tunefs', newfs)) 

        # Reformat if needed
        if 'reformat' in actions:
            next_actions.append("Need to `reformat' all targets.")
            next_actions.append(self._next_action_cmd('format', newfs)) 

        # Format if needed
        if 'format' in actions:
            # XXX: Check if everything is already stopped?
            next_actions.append("You can now `format' %d new target(s)" % \
                                len(actions['format']))
            next_actions.append(self._next_action_cmd('format', newfs, 
                                '-l %s' % actions['format'].labels()))
        # Start if needed
        if 'start' in actions:
            next_actions.append("You can now `start' %d new component(s)" % \
                                len(actions['start']))
            next_actions.append(self._next_action_cmd('start', newfs, 
                                '-l %s' % actions['start'].labels()))

        # Remount need unmount first
        if 'remount' in actions:
            next_actions.append("Need to `remount' all clients.")
            next_actions.append(self._next_action_cmd('umount', newfs)) 
            next_actions.append(self._next_action_cmd('mount', newfs)) 

        # Mount if needed
        if 'mount' in actions:
            next_actions.append("You can now `mount' the needed %d client(s)" %
                                len(actions['mount']))
            next_actions.append(self._next_action_cmd('mount', newfs, 
                                '-n %s' % actions['mount'].servers()))

        # Print this line only if there is other actions to be performed
        if next_actions:
            print
            print "NEXT ACTIONS (should be done manually)"
            for txt in next_actions:
                print ">%s" % txt

        print "Update is finished."

        return rc