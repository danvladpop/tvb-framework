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
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this
# program.  If not, see <http://www.gnu.org/licenses/>.
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
.. moduleauthor:: bogdan.neacsa <bogdan.neacsa@codemart.ro>
"""

import json
import pytest
from tvb.tests.framework.core.base_testcase import TransactionalTestCase
from tvb.core.entities import model
from tvb.core.entities.storage import dao
from tvb.core.adapters.exceptions import NoMemoryAvailableException
from tvb.core.services.operation_service import OperationService
from tvb.tests.framework.core.factory import TestFactory


class TestAdapterMemoryUsage(TransactionalTestCase):
    """
    Test class for the module handling methods computing required memory for an adapter to run.
    """
    
    def setUp(self):
        """
        Reset the database before each test.
        """
        self.test_user = TestFactory.create_user()
        self.test_project = TestFactory.create_project(admin=self.test_user)
    
    
    def test_adapter_memory(self):
        """
        Test that a method not implemented exception is raised in case the
        get_required_memory_size method is not implemented.
        """
        adapter = TestFactory.create_adapter("tvb.tests.framework.adapters.testadapter3", "TestAdapterHDDRequired")
        assert 42 == adapter.get_required_memory_size()
        
        
    def test_adapter_huge_memory_requirement(self):
        """
        Test that an MemoryException is raised in case adapter cant launch due to lack of memory.
        """
        adapter = TestFactory.create_adapter("tvb.tests.framework.adapters.testadapter3",
                                             "TestAdapterHugeMemoryRequired")
        data = {"test": 5}

        operation = model.Operation(self.test_user.id, self.test_project.id, adapter.stored_adapter.id,
                                    json.dumps(data), json.dumps({}), status=model.STATUS_STARTED)
        operation = dao.store_entity(operation)
        with pytest.raises(NoMemoryAvailableException):
            OperationService().initiate_prelaunch(operation, adapter, {})


