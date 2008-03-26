# Exceptions.py -- Configuration exception classes
# Copyright (C) 2008 CEA
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


class CommandException(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message

class CommandSyntaxError(CommandException):
    def __init__(self, file, line_nbr, line):
        self.file = file
        self.lineNbr = line_nbr
        self.line = line
        self.message = "Syntax error in %s at line %d: \"%s\"" % \
                       (self.file, self.lineNbr, self.line)

class CommandNotFoundError(CommandException):
    def __init__(self, cmd_name):
        self.cmd = cmd_name
        self.message = "Command \"%s\" not found" % cmd_name

class CommandXMFNotFoundError(CommandException):
    def __init__(self, fsname):
        self.fsname = fsname
        self.message = "File system \"%s\" is not installed" % fsname
