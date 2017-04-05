# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2017, Baycrest Centre for Geriatric Care ("Baycrest") and others
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License version 2 as published by the Free
# Software Foundation. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details. You should have received a copy of the GNU General
# Public License along with this program; if not, you can download it here
# http://www.gnu.org/licenses/old-licenses/gpl-2.0
#
#
#   CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
#   Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
#   Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
#       The Virtual Brain: a simulator of primate brain network dynamics.
#   Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#

"""
.. moduleauthor:: Lia Domide <lia.domide@codemart.ro>
"""

from tvb.core.entities.storage import dao
from tvb.core.adapters.abcremover import ABCRemover
from tvb.core.services.exceptions import RemoveDataTypeException
from tvb.datatypes.time_series import TimeSeriesRegion



class RegionMappingRemover(ABCRemover):
    """
    RegionMapping specific validations at remove time.
    """
    FIELD_NAME = "_region_mapping"
    CLASS_NAME = "RegionMapping"

    def remove_datatype(self, skip_validation=False):
        """
        Called when a Sensor is to be removed.
        """
        if not skip_validation:
            tsr = dao.get_generic_entity(TimeSeriesRegion, self.handled_datatype.gid, self.FIELD_NAME)
            error_msg = "%s cannot be removed because is still used by %d TimeSeries Region entities."
            if tsr:
                raise RemoveDataTypeException(error_msg % (self.CLASS_NAME, len(tsr)))

        ABCRemover.remove_datatype(self, skip_validation)



class RegionVolumeMappingRemover(RegionMappingRemover):
    """
    RegionVolumeMapping specific validations at remove time.
    """

    FIELD_NAME = "_region_mapping_volume"
    CLASS_NAME = "RegionVolumeMapping"

