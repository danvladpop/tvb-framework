# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and 
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2013, Baycrest Centre for Geriatric Care ("Baycrest")
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
Preparation validation and manipulation of adapter input trees
.. moduleauthor:: Mihai Andrei <mihai.andrei@codemart.ro>
"""
from copy import copy
import json
import numpy

from tvb.basic.filters.chain import FilterChain
from tvb.basic.logger.builder import get_logger
from tvb.basic.traits.exceptions import TVBException
from tvb.basic.traits.parameters_factory import collapse_params
from tvb.basic.traits.types_mapped import MappedType
from tvb.core import utils
from tvb.core.adapters import xml_reader
from tvb.core.adapters.exceptions import InvalidParameterException
from tvb.core.entities import model
from tvb.core.entities.load import load_entity_by_gid
from tvb.core.entities.storage import dao
from tvb.core.entities.transient.structure_entities import DataTypeMetaData
from tvb.core.portlets.xml_reader import KEY_DYNAMIC
from tvb.core.utils import string2array

ATT_METHOD = "python_method"
ATT_PARAMETERS = "parameters_prefix"

KEY_EQUATION = "equation"
KEY_FOCAL_POINTS = "focal_points"
KEY_SURFACE_GID = "surface_gid"

TYPE_SELECT = xml_reader.TYPE_SELECT
TYPE_MULTIPLE = xml_reader.TYPE_MULTIPLE
STATIC_ACCEPTED_TYPES = xml_reader.ALL_TYPES
KEY_TYPE = xml_reader.ATT_TYPE
KEY_OPTIONS = xml_reader.ELEM_OPTIONS
KEY_ATTRIBUTES = xml_reader.ATT_ATTRIBUTES
KEY_NAME = xml_reader.ATT_NAME
KEY_DESCRIPTION = xml_reader.ATT_DESCRIPTION
KEY_VALUE = xml_reader.ATT_VALUE
KEY_LABEL = xml_reader.ATT_LABEL
KEY_DEFAULT = "default"
KEY_DATATYPE = 'datatype'
KEY_DTYPE = 'elementType'
KEY_DISABLED = "disabled"
KEY_ALL = "allValue"
KEY_CONDITION = "conditions"
KEY_FILTERABLE = "filterable"
KEY_REQUIRED = "required"
KEY_ID = 'id'
KEY_UI_HIDE = "ui_hidden"

KEYWORD_PARAMS = "_parameters_"
KEYWORD_SEPARATOR = "_"
KEYWORD_OPTION = "option_"

KEY_PARAMETER_CHECKED = model.KEY_PARAMETER_CHECKED

MAXIMUM_DATA_TYPES_DISPLAYED = 50
KEY_WARNING = "warning"
WARNING_OVERFLOW = "Too many entities in storage; some of them were not returned, to avoid overcrowding. " \
                   "Use filters, to make the list small enough to fit in here!"


class InputTreeManager(object):

    def __init__(self):
        self.log = get_logger(self.__class__.__module__)


    def append_required_defaults(self, kwargs, algorithm_inputs):
        """
        Add if necessary any parameters marked as required that have a default value
        in the algorithm interface but were not submitted from the UI. For example in
        operations launched from context-menu or from data structure.
        """
        if algorithm_inputs is None:
            return

        for entry in algorithm_inputs:
            ## First handle this level of the tree, adding defaults where required
            if (entry[KEY_NAME] not in kwargs
                    and entry.get(KEY_REQUIRED) is True
                    and KEY_DEFAULT in entry
                    and entry[KEY_TYPE] != xml_reader.TYPE_DICT):
                kwargs[entry[KEY_NAME]] = entry[KEY_DEFAULT]

        for entry in algorithm_inputs:
            ## Now that first level was handled, go recursively on selected options only
            if entry.get(KEY_REQUIRED) is True and entry.get(KEY_OPTIONS) is not None:
                for option in entry[KEY_OPTIONS]:
                    # Only go recursive on option that was submitted
                    if option[KEY_VALUE] == kwargs[entry[KEY_NAME]] and KEY_ATTRIBUTES in option:
                        self.append_required_defaults(kwargs, option[KEY_ATTRIBUTES])


    def _validate_range_for_value_input(self, value, row):
        if value < row[xml_reader.ATT_MINVALUE] or value > row[xml_reader.ATT_MAXVALUE]:
            warning_message = "Field %s [%s] should be between %s and %s but provided value was %s." % (
                row[KEY_LABEL], row[KEY_NAME], row[xml_reader.ATT_MINVALUE],
                row[xml_reader.ATT_MAXVALUE], value)
            self.log.warning(warning_message)


    def _validate_range_for_array_input(self, array, row):
        min_val = numpy.min(array)
        max_val = numpy.max(array)

        if min_val < row[xml_reader.ATT_MINVALUE] or max_val > row[xml_reader.ATT_MAXVALUE]:
            # As described in TVB-1295, we do no longer raise exception, but only log a warning
            warning_message = "Field %s [%s] should have values between %s and %s but provided array contains min-" \
                              "max:(%s, %s)." % (row[KEY_LABEL], row[KEY_NAME], row[xml_reader.ATT_MINVALUE],
                                                 row[xml_reader.ATT_MAXVALUE], min_val, max_val)
            self.log.warning(warning_message)


    @staticmethod
    def _get_dictionary(row, **kwargs):
        """
        Find all key/value pairs for the dictionary represented by name.
        """
        if InputTreeManager._is_parent_not_submitted(row, kwargs):
            return {}, []
        name = row[KEY_NAME]
        result_dict = {}
        taken_keys = []
        for key in kwargs:
            if name in key and name != key:
                taken_keys.append(key)
                if KEY_DTYPE in row:
                    if row[KEY_DTYPE] == 'array':
                        val = string2array(kwargs[key], " ", "float")
                    else:
                        val = eval(row[KEY_DTYPE] + "('" + kwargs[key] + "')")
                else:
                    val = str(kwargs[key])
                result_dict[key.split(KEYWORD_PARAMS[1:])[-1]] = val
        return result_dict, taken_keys


    def _find_field_submitted_name(self, submited_kwargs, flat_name, perform_clean=False):
        """
        Return key as in submitted dictionary for a given flat_name. Also remove from submitted_kwargs parameters like
        surface_parameters_option_DIFFERENT_GID_vertices.
        This won't work when DataType is in selectMultiple !!!!
        :param submited_kwargs: Flat dictionary with  keys in form surface_parameters_option_GID_vertices
        :param flat_name: Name as retrieved from self.flaten_input_interface
                         (in which we are not aware of existing entities in DB - options in select)
        :returns: key from 'submited_kwargs' which corresponds to 'flat_name'
        """
        if KEYWORD_PARAMS not in flat_name:
            if flat_name in submited_kwargs.keys():
                return flat_name
            else:
                return None
        prefix = flat_name[0: flat_name.find(KEYWORD_PARAMS) + 12]
        sufix = flat_name[flat_name.find(KEYWORD_PARAMS) + 12:]
        parent_name = flat_name[0: flat_name.find(KEYWORD_PARAMS)]
        submitted_options = InputTreeManager._compute_submit_option_select(submited_kwargs[parent_name])

        datatype_like_submit = False

        for submitted_option in submitted_options:
            if sufix.startswith(KEYWORD_OPTION + str(submitted_option)):
                proposed_name = flat_name
            else:
                datatype_like_submit = True
                proposed_name = prefix + KEYWORD_OPTION + str(submitted_option)
                proposed_name = proposed_name + KEYWORD_SEPARATOR + sufix

            if perform_clean:
                ## Remove submitted parameters like surface_parameters_option_GID_vertices when surface != GID
                keys_to_remove = []
                for submit_key in submited_kwargs:
                    if (submit_key.startswith(prefix + KEYWORD_OPTION)
                            and submit_key.endswith(sufix) and submit_key != proposed_name):
                        keys_to_remove.append(submit_key)
                for submit_key in keys_to_remove:
                    del submited_kwargs[submit_key]
                if datatype_like_submit and len(submitted_options) > 1:
                    self.log.warning("DataType attribute in SELECT_MULTIPLE is not supposed to work!!!")
            if proposed_name in submited_kwargs:
                return proposed_name
        return None


    @staticmethod
    def _is_parent_not_submitted(row, kwargs):
        """
        :returns: True when current attributes should not be considered, because parent option was not selected."""
        att_name = row[KEY_NAME]
        parent_name, option = None, None
        if KEYWORD_PARAMS in att_name:
            parent_name = att_name[0: att_name.find(KEYWORD_PARAMS)]
            option = att_name[att_name.find(KEYWORD_OPTION) + 7:]
            option = option[: option.find(KEYWORD_SEPARATOR)]

        if parent_name is None or option is None:
            return False

        submitted_option = InputTreeManager._compute_submit_option_select(kwargs[parent_name])
        if not submitted_option:
            return True
        if option in submitted_option:
            return False
        return True


    @staticmethod
    def _compute_submit_option_select(submitted_option):
        """ """
        if isinstance(submitted_option, basestring):
            submitted_option = submitted_option.replace('[', '').replace(']', '').split(',')
        return submitted_option


    @staticmethod
    def form_prefix(input_param, prefix=None, option_prefix=None):
        """Compute parameter prefix. We need to be able from the flatten
        submitted values in UI, to be able to re-compose the tree of parameters,
        and to make sure all submitted names are uniquely identified."""
        new_prefix = ""
        if prefix is not None and prefix != '':
            new_prefix = prefix
        if prefix is not None and prefix != '' and not new_prefix.endswith(KEYWORD_SEPARATOR):
            new_prefix += KEYWORD_SEPARATOR
        new_prefix += input_param + KEYWORD_PARAMS
        if option_prefix is not None:
            new_prefix += KEYWORD_OPTION + option_prefix + KEYWORD_SEPARATOR
        return new_prefix


    @staticmethod
    def fill_defaults(adapter_interface, data, fill_unselected_branches=False):
        """ Change the default values in the Input Interface Tree."""
        result = []
        for param in adapter_interface:
            # if param[ABCAdapter.KEY_NAME] == 'integrator':
            #     pass
            new_p = copy(param)
            if param[KEY_NAME] in data:
                new_p[KEY_DEFAULT] = data[param[KEY_NAME]]
            if param.get(KEY_ATTRIBUTES) is not None:
                new_p[KEY_ATTRIBUTES] = InputTreeManager.fill_defaults(param[KEY_ATTRIBUTES], data,
                                                                       fill_unselected_branches)
            if param.get(KEY_OPTIONS) is not None:
                new_options = param[KEY_OPTIONS]
                if param[KEY_NAME] in data or fill_unselected_branches:
                    selected_values = []
                    if param[KEY_NAME] in data:
                        if param[KEY_TYPE] == TYPE_MULTIPLE:
                            selected_values = data[param[KEY_NAME]]
                        else:
                            selected_values = [data[param[KEY_NAME]]]
                    for i, option in enumerate(new_options):
                        if option[KEY_VALUE] in selected_values or fill_unselected_branches:
                            new_options[i] = InputTreeManager.fill_defaults([option], data, fill_unselected_branches)[0]
                new_p[KEY_OPTIONS] = new_options
            result.append(new_p)
        return result


    def flatten(self, params_list, prefix=None):
        """ Internal method, to be used recursively, on parameters POST. """
        result = []
        for param in params_list:
            new_param = copy(param)
            new_param[KEY_ATTRIBUTES] = None
            new_param[KEY_OPTIONS] = None

            param_name = param[KEY_NAME]

            if prefix is not None and KEY_TYPE in param:
                new_param[KEY_NAME] = prefix + param_name
            result.append(new_param)

            if param.get(KEY_OPTIONS) is not None:
                for option in param[KEY_OPTIONS]:
                    ### SELECT or SELECT_MULTIPLE attributes
                    if option.get(KEY_ATTRIBUTES) is not None:
                        new_prefix = InputTreeManager.form_prefix(param_name, prefix, option[KEY_VALUE])
                        extra_list = self.flatten(option[KEY_ATTRIBUTES], new_prefix)
                        result.extend(extra_list)

            if param.get(KEY_ATTRIBUTES) is not None:
                ### DATATYPE attributes
                new_prefix = InputTreeManager.form_prefix(param_name, prefix, None)
                extra_list = self.flatten(param[KEY_ATTRIBUTES], new_prefix)
                result.extend(extra_list)
        return result


    @staticmethod
    def prepare_param_names(attributes_list, prefix=None, add_option_prefix=False):
        """
        For a given attribute list, change the name of the attributes where needed.
        Changes refer to adding a prefix, to identify groups.
        Will be used on parameters page GET.
        """
        result = []
        for param in attributes_list:
            prepared_param = copy(param)
            new_name = param[KEY_NAME]
            if prefix is not None and KEY_TYPE in param:
                new_name = prefix + param[KEY_NAME]
                prepared_param[KEY_NAME] = new_name

            if ((KEY_TYPE not in param or param[KEY_TYPE] in STATIC_ACCEPTED_TYPES)
                    and param.get(KEY_OPTIONS) is not None):
                add_prefix_option = param.get(KEY_TYPE) in [xml_reader.TYPE_MULTIPLE, xml_reader.TYPE_SELECT]
                new_prefix = InputTreeManager.form_prefix(param[KEY_NAME], prefix)
                prepared_param[KEY_OPTIONS] = InputTreeManager.prepare_param_names(param[KEY_OPTIONS],
                                                                                   new_prefix, add_prefix_option)

            if param.get(KEY_ATTRIBUTES) is not None:
                new_prefix = prefix
                is_dict = param.get(KEY_TYPE) == 'dict'
                if add_option_prefix:
                    new_prefix = prefix + KEYWORD_OPTION
                    new_prefix = new_prefix + param[KEY_VALUE]
                    new_prefix += KEYWORD_SEPARATOR
                if is_dict:
                    new_prefix = new_name + KEYWORD_PARAMS
                prepared_param[KEY_ATTRIBUTES] = InputTreeManager.prepare_param_names(param[KEY_ATTRIBUTES], new_prefix)
            result.append(prepared_param)
        return result


    # -- Methods that may load entities from the db

    def review_operation_inputs(self, parameters, flat_interface):
        """
        Find out which of the submitted parameters are actually DataTypes and
        return a list holding all the dataTypes in parameters.
        :returns: list of dataTypes and changed parameters.
        """
        inputs_datatypes = []
        changed_parameters = dict()

        for field_dict in flat_interface:
            eq_flat_interface_name = self._find_field_submitted_name(parameters, field_dict[KEY_NAME])

            if eq_flat_interface_name is not None:
                is_datatype = False
                if field_dict.get(KEY_DATATYPE):
                    eq_datatype = load_entity_by_gid(parameters.get(str(eq_flat_interface_name)))
                    if eq_datatype is not None:
                        inputs_datatypes.append(eq_datatype)
                        is_datatype = True
                elif type(field_dict[KEY_TYPE]) in (str, unicode):
                    point_separator = field_dict[KEY_TYPE].rfind('.')
                    if point_separator > 0:
                        module = field_dict[KEY_TYPE][:point_separator]
                        classname = field_dict[KEY_TYPE][(point_separator + 1):]
                        try:
                            module = __import__(module, globals())
                            class_entity = eval("module." + classname)
                            if issubclass(class_entity, MappedType):
                                data_gid = parameters.get(str(field_dict[KEY_NAME]))
                                data_type = load_entity_by_gid(data_gid)
                                if data_type:
                                    inputs_datatypes.append(data_type)
                                    is_datatype = True
                        except ImportError, _:
                            pass

                if is_datatype:
                    changed_parameters[field_dict[KEY_LABEL]] = inputs_datatypes[-1].display_name
                else:
                    if field_dict[KEY_NAME] in parameters and (KEY_DEFAULT not in field_dict
                                    or str(field_dict[KEY_DEFAULT]) != str(parameters[field_dict[KEY_NAME]])):
                        changed_parameters[field_dict[KEY_LABEL]] = str(parameters[field_dict[KEY_NAME]])

        return inputs_datatypes, changed_parameters


    def _convert_to_array(self, input_data, row):
        """
        Method used when the type of an input is array, to parse or read.

        If the user set an equation for computing a model parameter then the
        value of that parameter will be a dictionary which contains all the data
        needed for computing that parameter for each vertex from the used surface.
        """
        if KEY_EQUATION in str(input_data) and KEY_FOCAL_POINTS in str(input_data) and KEY_SURFACE_GID in str(input_data):
            try:
                input_data = eval(str(input_data))
                # TODO move at a different level
                equation_type = input_data.get(KEY_DTYPE)
                if equation_type is None:
                    self.log.warning("Cannot figure out type of equation from input dictionary: %s. "
                                     "Returning []." % input_data)
                    return []
                splitted_class = equation_type.split('.')
                module = '.'.join(splitted_class[:-1])
                classname = splitted_class[-1]
                eq_module = __import__(module, globals(), locals(), [classname])
                eq_class = eval('eq_module.' + classname)
                equation = eq_class.from_json(input_data[KEY_EQUATION])
                focal_points = json.loads(input_data[KEY_FOCAL_POINTS])
                surface_gid = input_data[KEY_SURFACE_GID]
                surface = load_entity_by_gid(surface_gid)
                return surface.compute_equation(focal_points, equation)
            except Exception:
                self.log.exception("The parameter '" + str(row['name']) + "' was ignored. None value was returned.")
                return None

        if xml_reader.ATT_QUATIFIER in row:
            quantifier = row[xml_reader.ATT_QUATIFIER]
            dtype = None
            if KEY_DTYPE in row:
                dtype = row[KEY_DTYPE]
            if quantifier == xml_reader.QUANTIFIER_MANUAL:
                return string2array(str(input_data), ",", dtype)
            elif quantifier == xml_reader.QUANTIFIER_UPLOAD:
                input_str = open(input_data, 'r').read()
                return string2array(input_str, " ", dtype)

        return None


    def _load_entity(self, row, datatype_gid, kwargs, metadata_out):
        """
        Load specific DataType entities, as specified in DATA_TYPE table.
        Check if the GID is for the correct DataType sub-class, otherwise throw an exception.
        Updates metadata_out with the metadata of this entity
        """

        entity = load_entity_by_gid(datatype_gid)
        if entity is None:
            ## Validate required DT one more time, after actual retrieval from DB:
            if row.get(xml_reader.ATT_REQUIRED):
                raise InvalidParameterException("Empty DataType value for required parameter %s [%s]" % (
                    row[KEY_LABEL], row[KEY_NAME]))

            return None

        expected_dt_class = row[KEY_TYPE]
        if isinstance(expected_dt_class, basestring):
            classname = expected_dt_class.split('.')[-1]
            data_class = __import__(expected_dt_class.replace(classname, ''), globals(), locals(), [classname])
            data_class = eval("data_class." + classname)
            expected_dt_class = data_class
        if not isinstance(entity, expected_dt_class):
            raise InvalidParameterException("Expected param %s [%s] of type %s but got type %s." % (
                row[KEY_LABEL], row[KEY_NAME], expected_dt_class.__name__, entity.__class__.__name__))

        result = entity

        ## Step 2 of updating Meta-data from parent DataType.
        if entity.fk_parent_burst:
            ## Link just towards the last Burst identified.
            metadata_out[DataTypeMetaData.KEY_BURST] = entity.fk_parent_burst

        if entity.user_tag_1 and DataTypeMetaData.KEY_TAG_1 not in metadata_out:
            metadata_out[DataTypeMetaData.KEY_TAG_1] = entity.user_tag_1

        current_subject = metadata_out[DataTypeMetaData.KEY_SUBJECT]
        if current_subject == DataTypeMetaData.DEFAULT_SUBJECT:
            metadata_out[DataTypeMetaData.KEY_SUBJECT] = entity.subject
        else:
            if entity.subject != current_subject and entity.subject not in current_subject.split(','):
                metadata_out[DataTypeMetaData.KEY_SUBJECT] = current_subject + ',' + entity.subject
        ##  End Step 2 - Meta-data Updates

        ## Validate current entity to be compliant with specified ROW filters.
        dt_filter = row.get(xml_reader.ELEM_CONDITIONS)
        if dt_filter is not None and entity is not None and not dt_filter.get_python_filter_equivalent(entity):
            ## If a filter is declared, check that the submitted DataType is in compliance to it.
            raise InvalidParameterException("Field %s [%s] did not pass filters." % (row[KEY_LABEL],
                                                                                     row[KEY_NAME]))

        # In case a specific field in entity is to be used, use it
        if xml_reader.ATT_FIELD in row:
            val = eval("entity." + row[xml_reader.ATT_FIELD])
            result = val
        if ATT_METHOD in row:
            param_dict = dict()
            # The 'shape' attribute of an arraywrapper is overridden by us
            # the following check is made only to improve performance
            # (to find data in the dictionary with O(1)) on else the data is found in O(n)
            if hasattr(entity, 'shape'):
                for i in xrange(1, len(entity.shape)):
                    param_key = row[KEY_NAME] + "_" + row[ATT_PARAMETERS] + "_" + str(i - 1)
                    if param_key in kwargs:
                        param_dict[param_key] = kwargs[param_key]
            else:
                param_dict = dict((k, v) for k, v in kwargs.items()
                                  if k.startswith(row[KEY_NAME] + "_" + row[ATT_PARAMETERS]))
            val = eval("entity." + row[ATT_METHOD] + "(param_dict)")
            result = val
        return result


    def convert_ui_inputs(self, flat_input_interface, kwargs, metadata_out, validation_required=True):
        """
        Convert HTTP POST parameters into Python parameters.
        """
        kwa = {}
        simple_select_list, to_skip_dict_subargs = [], []
        for row in flat_input_interface:
            row_attr = row[KEY_NAME]
            row_type = row[KEY_TYPE]
            ## If required attribute was submitted empty no point to continue, so just raise exception
            if validation_required and row.get(xml_reader.ATT_REQUIRED) and kwargs.get(row_attr) == "":
                msg = "Parameter %s [%s] is required for %s but no value was submitted! Please relaunch with valid parameters."
                raise InvalidParameterException(msg % (row[KEY_LABEL], row[KEY_NAME], self.__class__.__name__))

            try:
                if row_type == xml_reader.TYPE_DICT:
                    kwa[row_attr], taken_keys = self._get_dictionary(row, **kwargs)
                    for key in taken_keys:
                        if key in kwa:
                            del kwa[key]
                        to_skip_dict_subargs.append(key)
                    continue
                ## Dictionary subargs that were previously processed should be ignored
                if row_attr in to_skip_dict_subargs:
                    continue

                if row_attr not in kwargs:
                    ## DataType sub-attributes are not submitted with GID in their name...
                    kwa_name = self._find_field_submitted_name(kwargs, row_attr, True)
                    if kwa_name is None:
                        ## Do not populate attributes not submitted
                        continue
                    kwargs[row_attr] = kwargs[kwa_name]
                    ## del kwargs[kwa_name] don't remove the original param, as it is useful for retrieving op.input DTs
                elif self._is_parent_not_submitted(row, kwargs):
                    ## Also do not populate sub-attributes from options not selected
                    del kwargs[row_attr]
                    continue

                if row_type == xml_reader.TYPE_ARRAY:
                    kwa[row_attr] = self._convert_to_array(kwargs[row_attr], row)
                    if xml_reader.ATT_MINVALUE in row and xml_reader.ATT_MAXVALUE in row:
                        self._validate_range_for_array_input(kwa[row_attr], row)
                elif row_type == xml_reader.TYPE_LIST:
                    if not isinstance(kwargs[row_attr], list):
                        kwa[row_attr] = json.loads(kwargs[row_attr])
                elif row_type == xml_reader.TYPE_BOOL:
                    kwa[row_attr] = bool(kwargs[row_attr])
                elif row_type == xml_reader.TYPE_INT:
                    if kwargs[row_attr] in [None, '', 'None']:
                        kwa[row_attr] = None
                    else:
                        kwa[row_attr] = int(kwargs[row_attr])
                        if xml_reader.ATT_MINVALUE in row and xml_reader.ATT_MAXVALUE in row:
                            self._validate_range_for_value_input(kwa[row_attr], row)
                elif row_type == xml_reader.TYPE_FLOAT:
                    if kwargs[row_attr] in ['', 'None']:
                        kwa[row_attr] = None
                    else:
                        kwa[row_attr] = float(kwargs[row_attr])
                        if xml_reader.ATT_MINVALUE in row and xml_reader.ATT_MAXVALUE in row:
                            self._validate_range_for_value_input(kwa[row_attr], row)
                elif row_type == xml_reader.TYPE_STR:
                    kwa[row_attr] = kwargs[row_attr]
                elif row_type in [xml_reader.TYPE_SELECT, xml_reader.TYPE_MULTIPLE]:
                    val = kwargs[row_attr]
                    if row_type == xml_reader.TYPE_MULTIPLE and not isinstance(val, list):
                        val = [val]
                    kwa[row_attr] = val
                    if row_type == xml_reader.TYPE_SELECT:
                        simple_select_list.append(row_attr)
                elif row_type == xml_reader.TYPE_UPLOAD:
                    kwa[row_attr] = kwargs[row_attr]
                else:
                    ## DataType parameter to be processed:
                    simple_select_list.append(row_attr)
                    datatype_gid = kwargs[row_attr]
                    ## Load filtered and trimmed attribute (e.g. field is applied if specified):
                    kwa[row_attr] = self._load_entity(row, datatype_gid, kwargs, metadata_out)
                    if xml_reader.ATT_FIELD in row:
                        # Add entity_GID to the parameters to recognize original input
                        kwa[row_attr + '_gid'] = datatype_gid

            except TVBException:
                raise
            except Exception:
                raise InvalidParameterException("Invalid or missing value in field %s [%s]" % (row[KEY_LABEL],
                                                                                               row[KEY_NAME]))

        return collapse_params(kwa, simple_select_list)


    @staticmethod
    def _populate_values(data_list, type_, category_key, complex_dt_attributes=None):
        """
        Populate meta-data fields for data_list (list of DataTypes).

        Private method, to be called recursively.
        It will receive a list of Attributes, and it will populate 'options'
        entry with data references from DB.
        """
        values = []
        all_field_values = ''
        for value in data_list:
            # Here we only populate with DB data, actual
            # XML check will be done after select and submit.
            entity_gid = value[2]
            actual_entity = dao.get_generic_entity(type_, entity_gid, "gid")
            display_name = ''
            if actual_entity is not None and len(actual_entity) > 0 and isinstance(actual_entity[0], model.DataType):
                display_name = actual_entity[0].display_name
            display_name = display_name + ' - ' + (value[3] or "None ")
            if value[5]:
                display_name = display_name + ' - From: ' + str(value[5])
            else:
                display_name = display_name + utils.date2string(value[4])
            if value[6]:
                display_name = display_name + ' - ' + str(value[6])
            display_name = display_name + ' - ID:' + str(value[0])
            all_field_values = all_field_values + str(entity_gid) + ','
            values.append({KEY_NAME: display_name, KEY_VALUE: entity_gid})
            if complex_dt_attributes is not None:
                ### TODO apply filter on sub-attributes
                values[-1][KEY_ATTRIBUTES] = complex_dt_attributes
        if category_key is not None:
            category = dao.get_category_by_id(category_key)
            if (not category.display) and (not category.rawinput) and len(data_list) > 1:
                values.insert(0, {KEY_NAME: "All", KEY_VALUE: all_field_values[:-1]})
        return values


    def _get_available_datatypes(self, project_id, data_name, filters=None):
        """
        Return all dataTypes that match a given name and some filters.
        """
        data_class = FilterChain._get_class_instance(data_name)
        if data_class is None:
            self.log.warning("Invalid Class specification:" + str(data_name))
            return [], 0
        else:
            self.log.debug('Filtering:' + str(data_class))
            return dao.get_values_of_datatype(project_id, data_class, filters, MAXIMUM_DATA_TYPES_DISPLAYED)


    def fill_input_tree_with_options(self, attributes_list, project_id, category_key):
        """
        For a datatype node in the input tree, load all instances from the db that fit the filters.
        """
        result = []
        for param in attributes_list:
            if param.get(KEY_UI_HIDE):
                continue
            transformed_param = copy(param)

            if (KEY_TYPE in param) and not (param[KEY_TYPE] in STATIC_ACCEPTED_TYPES):

                if KEY_CONDITION in param:
                    filter_condition = param[KEY_CONDITION]
                else:
                    filter_condition = FilterChain('')
                filter_condition.add_condition(FilterChain.datatype + ".visible", "==", True)

                data_list, total_count = self._get_available_datatypes(project_id, param[KEY_TYPE],
                                                                      filter_condition)

                if total_count > MAXIMUM_DATA_TYPES_DISPLAYED:
                    transformed_param[KEY_WARNING] = WARNING_OVERFLOW

                complex_dt_attributes = None
                if param.get(KEY_ATTRIBUTES):
                    complex_dt_attributes = self.fill_input_tree_with_options(param[KEY_ATTRIBUTES],
                                                                    project_id, category_key)
                values = self._populate_values(data_list, param[KEY_TYPE],
                                              category_key, complex_dt_attributes)

                if (transformed_param.get(KEY_REQUIRED) and len(values) > 0 and
                        transformed_param.get(KEY_DEFAULT) in [None, 'None']):
                    transformed_param[KEY_DEFAULT] = str(values[-1][KEY_VALUE])

                transformed_param[KEY_FILTERABLE] = FilterChain.get_filters_for_type(param[KEY_TYPE])
                transformed_param[KEY_TYPE] = TYPE_SELECT
                # If Portlet dynamic parameter, don't add the options instead
                # just add the default value.
                if KEY_DYNAMIC in param:
                    dynamic_param = {KEY_NAME: param[KEY_DEFAULT],
                                     KEY_VALUE: param[KEY_DEFAULT]}
                    transformed_param[KEY_OPTIONS] = [dynamic_param]
                else:
                    transformed_param[KEY_OPTIONS] = values
                if type(param[KEY_TYPE]) == str:
                    transformed_param[KEY_DATATYPE] = param[KEY_TYPE]
                else:
                    data_type = param[KEY_TYPE]
                    transformed_param[KEY_DATATYPE] = data_type.__module__ + '.' + data_type.__name__

                ### DataType-attributes are no longer necessary, they were already copied on each OPTION
                transformed_param[KEY_ATTRIBUTES] = []

            else:
                if param.get(KEY_OPTIONS) is not None:
                    transformed_param[KEY_OPTIONS] = self.fill_input_tree_with_options(param[KEY_OPTIONS],
                                                                                        project_id, category_key)
                    if (transformed_param.get(KEY_REQUIRED) and len(param[KEY_OPTIONS]) > 0 and
                            transformed_param.get(KEY_DEFAULT) in [None, 'None']):
                        def_val = str(param[KEY_OPTIONS][-1][KEY_VALUE])
                        transformed_param[KEY_DEFAULT] = def_val

                if param.get(KEY_ATTRIBUTES) is not None:
                    transformed_param[KEY_ATTRIBUTES] = self.fill_input_tree_with_options(
                        param[KEY_ATTRIBUTES], project_id, category_key)
            result.append(transformed_param)
        return result


    @staticmethod
    def select_simulator_inputs(full_tree, selection_dictionary, prefix=''):
        """
        Cut Simulator input Tree, to display only user-checked inputs.

        :param full_tree: the simulator input tree
        :param selection_dictionary: a dictionary that keeps for each entry a default value and if it is check or not.
        :param prefix: a prefix to be added to the ui_name in case a select with subtrees is not selected

        """
        if full_tree is None:
            return None
        result = []
        for param in full_tree:
            param_name = param[KEY_NAME]
            if KEY_LABEL in param and len(prefix):
                param[KEY_LABEL] = prefix + '_' + param[KEY_LABEL]

            is_checked = param_name in selection_dictionary and selection_dictionary[param_name][KEY_PARAMETER_CHECKED]
            if is_checked:
                param[KEY_DEFAULT] = selection_dictionary[param_name][model.KEY_SAVED_VALUE]
                result.append(param)

            if KEY_OPTIONS in param and param[KEY_OPTIONS] is not None:
                if is_checked:
                    for option in param[KEY_OPTIONS]:
                        if KEY_ATTRIBUTES in option:
                            option[KEY_ATTRIBUTES] = InputTreeManager.select_simulator_inputs(
                                                            option[KEY_ATTRIBUTES], selection_dictionary, prefix)
                            option[KEY_DEFAULT] = selection_dictionary[param_name][model.KEY_SAVED_VALUE]
                else:
                    ## Since entry is not selected, just recurse on the default option and ###
                    ## all it's subtree will come up one level in the input tree         #####
                    for option in param[KEY_OPTIONS]:
                        if (param_name in selection_dictionary and KEY_ATTRIBUTES in option and
                            option[KEY_VALUE] == selection_dictionary[param_name][model.KEY_SAVED_VALUE]):
                            new_prefix = option[KEY_VALUE] + '_' + prefix
                            recursive_results = InputTreeManager.select_simulator_inputs(option[KEY_ATTRIBUTES],
                                                                             selection_dictionary, new_prefix)
                            result.extend(recursive_results)
        return result
