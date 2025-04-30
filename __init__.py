# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from . import tilemap_to_mesh_panel, load_tilemap, load_ldtk

# submodule
submodules = (
    tilemap_to_mesh_panel,
    load_tilemap,
    load_ldtk
)

def register():
    for submod in submodules:
        submod.register()


def unregister():
    for submod in submodules:
        submod.unregister()

if __name__ == "__main__":
    register()