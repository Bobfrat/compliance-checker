#!/usr/bin/env python
# -*- coding: utf-8 -*-

from compliance_checker.suite import CheckSuite
from compliance_checker.cf import CFBaseCheck, dimless_vertical_coordinates
from compliance_checker.cf.util import is_vertical_coordinate, is_time_variable, units_convertible, units_temporal, StandardNameTable, create_cached_data_dir, download_cf_standard_name_table
from compliance_checker import cfutil
from netCDF4 import Dataset
from tempfile import gettempdir
from compliance_checker.tests.resources import STATIC_FILES
from compliance_checker.tests import BaseTestCase
from compliance_checker.tests.helpers import MockTimeSeries, MockVariable
from compliance_checker.cf.appendix_d import no_missing_terms
from itertools import chain

import os
import re
import sys
import pytest

from operator import sub

class TestCF(BaseTestCase):

    def setUp(self):
        '''
        Initialize the dataset
        '''
        self.cf = CFBaseCheck()

    # --------------------------------------------------------------------------------
    # Helper Methods
    # --------------------------------------------------------------------------------

    def new_nc_file(self):
        '''
        Make a new temporary netCDF file for the scope of the test
        '''
        nc_file_path = os.path.join(gettempdir(), 'example.nc')
        if os.path.exists(nc_file_path):
            raise IOError('File Exists: %s' % nc_file_path)
        nc = Dataset(nc_file_path, 'w')
        self.addCleanup(os.remove, nc_file_path)
        self.addCleanup(nc.close)
        return nc

    def load_dataset(self, nc_dataset):
        '''
        Return a loaded NC Dataset for the given path
        '''
        if not isinstance(nc_dataset, str):
            raise ValueError("nc_dataset should be a string")

        nc_dataset = Dataset(nc_dataset, 'r')
        self.addCleanup(nc_dataset.close)
        return nc_dataset

    def get_results(self, results):
        '''
        Returns a tuple of the value scored, possible, and a list of messages
        in the result set.
        '''
        out_of = 0
        scored = 0
        for r in results:
            if isinstance(r.value, tuple):
                out_of += r.value[1]
                scored += r.value[0]
            else:
                out_of += 1
                scored += int(r.value)

        # Store the messages
        messages = []
        for r in results:
            messages.extend(r.msgs)

        return scored, out_of, messages

    # --------------------------------------------------------------------------------
    # Compliance Tests
    # --------------------------------------------------------------------------------

    def test_check_data_types(self):
        """
        Invoke check_data_types() and loop through all variables to check data
        types. Pertains to 2.2 The netCDF data types char, byte, short, int,
        float or real, and double are all acceptable.
        """

        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_data_types(dataset)
        assert result.value[0] == result.value[1]

        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_data_types(dataset)
        assert result.msgs[0] == u'The variable temp failed because the datatype is int64'
        assert result.value == (6, 7)

    def test_naming_conventions(self):
        '''
        Section 2.3 Naming Conventions

        Variable, dimension and attr names should begin with a letter and be composed of letters, digits, and underscores.
        '''

        # compliant dataset
        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        results = self.cf.check_naming_conventions(dataset)
        scored, out_of, messages = self.get_results(results)
        assert scored == out_of

        # non-compliant dataset
        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_naming_conventions(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 3
        assert scored < out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u'§2.3 Naming Conventions' for r in results)

        # another non-compliant dataset
        dataset = self.load_dataset(STATIC_FILES['chap2'])
        results = self.cf.check_naming_conventions(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 3
        assert scored < out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u'§2.3 Naming Conventions' for r in results)


    def test_check_names_unique(self):
        """
        2.3 names should not be distinguished purely by case, i.e., if case is disregarded, no two names should be the same.
        """
        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_names_unique(dataset)

        num_var = len(dataset.variables)
        expected = (num_var,) * 2

        self.assertEqual(result.value, expected)

        dataset = self.load_dataset(STATIC_FILES['chap2'])
        result = self.cf.check_names_unique(dataset)
        assert result.value == (6, 7)
        assert result.msgs[0] == u'Variables are not case sensitive. Duplicate variables named: not_unique'

    def test_check_dimension_names(self):
        """
        2.4 A variable may have any number of dimensions, including zero, and the dimensions must all have different names.
        """

        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_dimension_names(dataset)
        assert result.value == (6, 7)

        dataset = self.load_dataset(STATIC_FILES['chap2'])
        result = self.cf.check_dimension_names(dataset)
        assert result.msgs[0] == u'no_reason has two or more dimensions named time'

    def test_check_dimension_order(self):
        """
        2.4 If any or all of the dimensions of a variable have the interpretations of "date or time" (T), "height or depth" (Z),
        "latitude" (Y), or "longitude" (X) then we recommend, those dimensions to appear in the relative order T, then Z, then Y,
        then X in the CDL definition corresponding to the file. All other dimensions should, whenever possible, be placed to the
        left of the spatiotemporal dimensions.
        """
        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_dimension_order(dataset)
        assert result.value == (5, 6)
        assert result.msgs[0] == (u"really_bad's dimensions are not in the recommended order "
                                  "T, Z, Y, X. They are latitude, power")

        dataset = self.load_dataset(STATIC_FILES['dimension_order'])
        result = self.cf.check_dimension_order(dataset)
        self.assertEqual((3, 3), result.value)
        self.assertEqual([], result.msgs)

    def test_check_fill_value_outside_valid_range(self):
        """
        2.5.1 The _FillValue should be outside the range specified by valid_range (if used) for a variable.
        """

        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_fill_value_outside_valid_range(dataset)
        assert result.msgs[0] == (u'salinity:_FillValue (1.0) should be outside the '
                                  'range specified by valid_min/valid_max (-10, 10)')

        dataset = self.load_dataset(STATIC_FILES['chap2'])
        result = self.cf.check_fill_value_outside_valid_range(dataset)
        assert result.value == (1, 2)
        assert result.msgs[0] == (u'wind_speed:_FillValue (12.0) should be outside the '
                                  'range specified by valid_min/valid_max (0.0, 20.0)')

    def test_check_conventions_are_cf_16(self):
        """
        §2.6.1 the NUG defined global attribute Conventions to the string value
        "CF-1.6"
        """
        # :Conventions = "CF-1.6"
        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_conventions_are_cf_16(dataset)
        self.assertTrue(result.value)

        # :Conventions = "CF-1.6 ,ACDD" ;
        dataset = self.load_dataset(STATIC_FILES['conv_multi'])
        result = self.cf.check_conventions_are_cf_16(dataset)
        self.assertTrue(result.value)

        # :Conventions = "NoConvention"
        dataset = self.load_dataset(STATIC_FILES['conv_bad'])
        result = self.cf.check_conventions_are_cf_16(dataset)
        self.assertFalse(result.value)
        assert result.msgs[0] == (u'§2.6.1 Conventions global attribute does not contain '
                                  '"CF-1.6". The CF Checker only supports CF-1.6 '
                                  'at this time.')

    def test_check_convention_globals(self):
        """
        Load up a dataset and ensure title and history global attrs are checked
        properly (§2.6.2).
        """

        # check for pass
        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_convention_globals(dataset)
        assert result.value[0] == result.value[1]

        # check if it doesn't exist that we pass
        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_convention_globals(dataset)
        assert result.value[0] != result.value[1]
        assert result.msgs[0] == u'§2.6.2 global attribute title should exist and be a non-empty string'

    def test_check_convention_possibly_var_attrs(self):
        """
        §2.6.2 The units attribute is required for all variables that represent dimensional quantities
        (except for boundary variables defined in Section 7.1, "Cell Boundaries" and climatology variables
        defined in Section 7.4, "Climatological Statistics").

        Units are not required for dimensionless quantities. A variable with no units attribute is assumed
        to be dimensionless. However, a units attribute specifying a dimensionless unit may optionally be
        included.

        - units required
        - type must be recognized by udunits
        - if std name specified, must be consistent with standard name table, must also be consistent with a
          specified cell_methods attribute if present
        """

        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_convention_possibly_var_attrs(dataset)
        # 10x comment attrs
        # 1x institution
        # 1x source
        # 1x EMPTY references
        assert result.value[0] != result.value[1]
        assert result.msgs[0] == u"§2.6.2 references global attribute should be a non-empty string"

        # load bad_data_type.nc
        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        result = self.cf.check_convention_possibly_var_attrs(dataset)
        # no references
        # institution is a 10L
        # no source

        # comments don't matter unless they're empty

        assert result.value[0] != result.value[1]
        assert result.msgs[0] == u'§2.6.2 salinity:institution should be a non-empty string'

    def test_check_standard_name(self):
        """
        3.3 A standard name is associated with a variable via the attribute standard_name which takes a
        string value comprised of a standard name optionally followed by one or more blanks and a
        standard name modifier
        """
        dataset = self.load_dataset(STATIC_FILES['2dim'])
        results = self.cf.check_standard_name(dataset)
        for each in results:
            self.assertTrue(each.value)

        # load failing ds
        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        results = self.cf.check_standard_name(dataset)
        score, out_of, messages = self.get_results(results)

        # 9 vars checked, 8 fail
        assert len(results) == 9
        assert score < out_of
        assert all(r.name == u"§3.3 Standard Name" for r in results)

        #load different ds --  ll vars pass this check
        dataset = self.load_dataset(STATIC_FILES['reduced_horizontal_grid'])
        results = self.cf.check_standard_name(dataset)
        score, out_of, messages = self.get_results(results)
        assert score ==  out_of

    def test_cell_bounds(self):
        dataset = self.load_dataset(STATIC_FILES['grid-boundaries'])
        results = self.cf.check_cell_boundaries(dataset)
        score, out_of, messages = self.get_results(results)
        assert (score, out_of) == (2, 2)

        dataset = self.load_dataset(STATIC_FILES['cf_example_cell_measures'])
        results = self.cf.check_cell_boundaries(dataset)

        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        results = self.cf.check_cell_boundaries(dataset)

        dataset = self.load_dataset(STATIC_FILES['bounds_bad_order'])
        results = self.cf.check_cell_boundaries(dataset)
        score, out_of, messages = self.get_results(results)
        # Make sure that the rgrid coordinate variable isn't checked for standard_name
        assert (score, out_of) == (0, 2)

        dataset = self.load_dataset(STATIC_FILES['bounds_bad_num_coords'])
        results = self.cf.check_cell_boundaries(dataset)
        score, out_of, messages = self.get_results(results)
        assert (score, out_of) == (0, 2)

        dataset = self.load_dataset(STATIC_FILES['1d_bound_bad'])
        results = self.cf.check_cell_boundaries(dataset)
        score, out_of, messages = self.get_results(results)

    def test_cell_measures(self):
        dataset = self.load_dataset(STATIC_FILES['cell_measure'])
        results = self.cf.check_cell_measures(dataset)
        score, out_of, messages = self.get_results(results)
        assert score == out_of
        assert score > 0

        dataset = self.load_dataset(STATIC_FILES['bad_cell_measure1'])
        results = self.cf.check_cell_measures(dataset)
        score, out_of, messages = self.get_results(results)
        message = ("The cell_measures attribute for variable PS is formatted incorrectly.  "
                   "It should take the form of either 'area: cell_var' or 'volume: cell_var' "
                   "where cell_var is the variable describing the cell measures")
        assert message in messages

        dataset = self.load_dataset(STATIC_FILES['bad_cell_measure2'])
        results = self.cf.check_cell_measures(dataset)
        score, out_of, messages = self.get_results(results)
        message = u'Cell measure variable PS referred to by box_area is not present in dataset variables'
        assert message in messages

    def test_climatology_cell_methods(self):
        """
        Checks that climatology cell_methods strings are properly validated
        """
        dataset = self.load_dataset(STATIC_FILES['climatology'])
        results = self.cf.check_climatological_statistics(dataset)
        # cell methods in this file is
        # "time: mean within days time: mean over days"
        score, out_of, messages = self.get_results(results)
        self.assertEqual(score, out_of)
        temp_var = dataset.variables['temperature'] = \
                   MockVariable(dataset.variables['temperature'])
        temp_var.cell_methods = 'INVALID'
        results = self.cf.check_climatological_statistics(dataset)
        score, out_of, messages = self.get_results(results)
        self.assertNotEqual(score, out_of)
        # incorrect time units
        temp_var.cell_methods = "time: mean within years time: mean over days"
        results = self.cf.check_climatological_statistics(dataset)
        score, out_of, messages = self.get_results(results)
        self.assertNotEqual(score, out_of)
        # can only have third method over years if first two are within and
        # over days, respectively
        temp_var.cell_methods = "time: mean within years time: mean over years time: sum over years"
        results = self.cf.check_climatological_statistics(dataset)
        score, out_of, messages = self.get_results(results)
        self.assertNotEqual(score, out_of)
        # this, on the other hand, should work.
        temp_var.cell_methods = "time: mean within days time: mean over days time: sum over years"
        results = self.cf.check_climatological_statistics(dataset)
        score, out_of, messages = self.get_results(results)
        self.assertEqual(score, out_of)
        # parenthesized comment to describe climatology
        temp_var.cell_methods = "time: sum within days time: maximum over days (ENSO years)"
        results = self.cf.check_climatological_statistics(dataset)
        score, out_of, messages = self.get_results(results)
        self.assertEqual(score, out_of)

    def test_check_ancillary_variables(self):
        '''
        Test to ensure that ancillary variables are properly checked
        '''

        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        results = self.cf.check_ancillary_variables(dataset)
        result_dict = {result.name: result for result in results}
        result = result_dict[u'§3.4 Ancillary Data']
        assert result.value == (2, 2)

        dataset = self.load_dataset(STATIC_FILES['bad_reference'])
        results = self.cf.check_ancillary_variables(dataset)
        result_dict = {result.name: result for result in results}
        result = result_dict[u'§3.4 Ancillary Data']
        assert result.value == (1, 2)
        assert u"temp_qc is not a variable in this dataset" == result.msgs[0]

    def test_download_standard_name_table(self):
        """
        Test that a user can download a specific standard name table
        """
        version = '35'

        data_directory = create_cached_data_dir()
        location = os.path.join(data_directory, 'cf-standard-name-table-test-{0}.xml'.format(version))
        download_cf_standard_name_table(version, location)

        # Test that the file now exists in location and is the right version
        self.assertTrue(os.path.isfile(location))
        std_names = StandardNameTable(location)
        self.assertEqual(std_names._version, version)
        self.addCleanup(os.remove, location)

    def test_bad_standard_name_table(self):
        """
        Test that failure in case a bad standard name table is passed.
        """
        with pytest.raises(IOError):
            StandardNameTable('dummy_non_existent_file.ext')

    def test_check_flags(self):
        """Test that the check for flags works as expected."""

        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        results = self.cf.check_flags(dataset)
        scored, out_of, messages = self.get_results(results)

        # only 4 variables in this dataset do not have perfect scores
        imperfect = [r.value for r in results if r.value[0] < r.value[1]]
        assert len(imperfect) == 4

    def test_check_flag_masks(self):
        dataset = self.load_dataset(STATIC_FILES['ghrsst'])
        results = self.cf.check_flags(dataset)
        scored, out_of, messages = self.get_results(results)
        # This is an example of a perfect dataset for flags
        assert scored > 0
        assert scored == out_of

    def test_check_bad_units(self):
        """Load a dataset with units that are expected to fail (bad_units.nc).
        There are 6 variables in this dataset, three of which should give
        an error: 
            - time, with units "s" (should be <units> since <epoch>)
            - lat, with units "degrees_E" (should be degrees)
            - lev, with units "level" (deprecated)"""

        dataset = self.load_dataset(STATIC_FILES['2dim'])
        results = self.cf.check_units(dataset)
        for result in results:
            self.assert_result_is_good(result)

        # Not sure why bad_data_type was being used, we have a dataset specifically for bad units
        # dataset = self.load_dataset(STATIC_FILES['bad_data_type'])

        dataset = self.load_dataset(STATIC_FILES['bad_units'])
        all_results = self.cf.check_units(dataset) 

        # use itertools.chain() to unpack the lists of messages
        results_list = list(chain(*(r.msgs for r in all_results if r.msgs)))

        # check the results only have '§3.1 Units' as the header
        assert all(r.name == u'§3.1 Units' for r in all_results)

        # check that all the expected variables have been hit
        assert all(any(s in msg for msg in results_list) for s in ["time", "lat", "lev"])


    def test_latitude(self):
        '''
        Section 4.1 Latitude Coordinate
        '''
        # Check compliance
        dataset = self.load_dataset(STATIC_FILES['example-grid'])
        results = self.cf.check_latitude(dataset)
        score, out_of, messages = self.get_results(results)
        assert score == out_of

        # Verify non-compliance -- 9/12 pass
        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_latitude(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 12
        assert scored < out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 3
        assert (r.name == u'§4.1 Latitude Coordinates' for r in results)
        
        # check with another ds -- all 6 vars checked pass
        dataset = self.load_dataset(STATIC_FILES['rotated_pole_grid'])
        results = self.cf.check_latitude(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 6
        assert scored == out_of
        assert (r.name == u'§4.1 Latitude Coordinates' for r in results)

        # hack to avoid writing to read-only file
        dataset.variables['rlat'] = MockVariable(dataset.variables['rlat'])
        rlat = dataset.variables['rlat']
        rlat.name = 'rlat'
        # test with a bad value
        rlat.units = 'degrees_north'
        results = self.cf.check_latitude(dataset)
        scored, out_of, messages = self.get_results(results)
        wrong_format = u"Grid latitude variable '{}' should use degree equivalent units without east or north components. Current units are {}"
        self.assertTrue(wrong_format.format(rlat.name, rlat.units) in messages)
        rlat.units = 'radians'
        results = self.cf.check_latitude(dataset)
        scored, out_of, messages = self.get_results(results)
        self.assertTrue(wrong_format.format(rlat.name, rlat.units) in messages)


    def test_longitude(self):
        '''
        Section 4.2 Longitude Coordinate
        '''
        # Check compliance
        dataset = self.load_dataset(STATIC_FILES['example-grid'])
        results = self.cf.check_longitude(dataset)
        score, out_of, messages = self.get_results(results)
        assert score ==  out_of

        # Verify non-compliance -- 12 checked, 3 fail
        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_longitude(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 12
        assert scored < out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 3
        assert all(r.name == u'§4.1 Latitude Coordinates' for r in results)

        # check different dataset # TODO can be improved for check_latitude too
        dataset = self.load_dataset(STATIC_FILES['rotated_pole_grid'])
        results = self.cf.check_latitude(dataset)
        scored, out_of, messages = self.get_results(results)
        assert (scored, out_of) == (6, 6)
        # hack to avoid writing to read-only file
        dataset.variables['rlon'] = MockVariable(dataset.variables['rlon'])
        rlon = dataset.variables['rlon']
        rlon.name = 'rlon'
        # test with a bad value
        rlon.units = 'degrees_east'
        results = self.cf.check_longitude(dataset)
        scored, out_of, messages = self.get_results(results)
        wrong_format = u"Grid longitude variable '{}' should use degree equivalent units without east or north components. Current units are {}"
        self.assertTrue(wrong_format.format(rlon.name, rlon.units) in messages)
        rlon.units = 'radians'
        results = self.cf.check_longitude(dataset)
        scored, out_of, messages = self.get_results(results)
        self.assertTrue(wrong_format.format(rlon.name, rlon.units) in messages)


    def test_is_vertical_coordinate(self):
        '''
        Section 4.3 Qualifiers for Vertical Coordinate

        NOTE: The standard doesn't explicitly say that vertical coordinates must be a
        coordinate type.
        '''
        # Make something that I can attach attrs to
        mock_variable = MockVariable

        # Proper name/standard_name
        known_name = mock_variable()
        known_name.standard_name = 'depth'
        self.assertTrue(is_vertical_coordinate('not_known', known_name))

        # Proper Axis
        axis_set = mock_variable()
        axis_set.axis = 'Z'
        self.assertTrue(is_vertical_coordinate('not_known', axis_set))

        # Proper units
        units_set = mock_variable()
        units_set.units = 'dbar'
        self.assertTrue(is_vertical_coordinate('not_known', units_set))

        # Proper units/positive
        positive = mock_variable()
        positive.units = 'm'
        positive.positive = 'up'
        self.assertTrue(is_vertical_coordinate('not_known', positive))

    def test_vertical_dimension(self):
        '''
        Section 4.3.1 Dimensional Vertical Coordinate
        '''
        # Check for compliance
        dataset = self.load_dataset(STATIC_FILES['example-grid'])
        results = self.cf.check_dimensional_vertical_coordinate(dataset)
        assert len(results) == 1
        assert all(r.name  == u'§4.3 Vertical Coordinate' for r in results)

        # non-compliance -- one check fails
        dataset = self.load_dataset(STATIC_FILES['illegal-vertical'])
        results = self.cf.check_dimensional_vertical_coordinate(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 1
        assert all(r.name  == u'§4.3 Vertical Coordinate' for r in results)
        assert scored < out_of


    def test_appendix_d(self):
        '''
        CF 1.6
        Appendix D
        The definitions given here allow an application to compute dimensional
        coordinate values from the dimensionless ones and associated variables.
        The formulas are expressed for a gridpoint (n,k,j,i) where i and j are
        the horizontal indices, k is the vertical index and n is the time index.
        A coordinate variable is associated with its definition by the value of
        the standard_name attribute. The terms in the definition are associated
        with file variables by the formula_terms attribute. The formula_terms
        attribute takes a string value, the string being comprised of
        blank-separated elements of the form "term: variable", where term is a
        keyword that represents one of the terms in the definition, and variable
        is the name of the variable in a netCDF file that contains the values
        for that term. The order of elements is not significant.
        '''

        # For each of the listed dimensionless vertical coordinates,
        # verify that the formula_terms match the provided set of terms
        self.assertTrue(no_missing_terms('atmosphere_ln_pressure_coordinate',
                                         {"p0", "lev"}))
        self.assertTrue(no_missing_terms('atmosphere_sigma_coordinate',
                                         {"sigma", "ps", "ptop"}))
        self.assertTrue(no_missing_terms('atmosphere_hybrid_sigma_pressure_coordinate',
                                         {'a', 'b', 'ps'}))
        # test alternative terms for
        # 'atmosphere_hybrid_sigma_pressure_coordinate'
        self.assertTrue(no_missing_terms('atmosphere_hybrid_sigma_pressure_coordinate',
                                         {'ap', 'b', 'ps'}))
        # check that an invalid set of terms fails
        self.assertFalse(no_missing_terms('atmosphere_hybrid_sigma_pressure_coordinate',
                                          {'a', 'b', 'p'}))
        self.assertTrue(no_missing_terms('atmosphere_hybrid_height_coordinate',
                                          {"a", "b", "orog"}))
        # missing terms should cause failure
        self.assertFalse(no_missing_terms('atmosphere_hybrid_height_coordinate',
                                          {"a", "b"}))
        # excess terms should cause failure
        self.assertFalse(no_missing_terms('atmosphere_hybrid_height_coordinate',
                                         {"a", "b", "c", "orog"}))
        self.assertTrue(no_missing_terms('atmosphere_sleve_coordinate',
                                         {"a", "b1", "b2", "ztop", "zsurf1",
                                          "zsurf2"}))
        self.assertTrue(no_missing_terms('ocean_sigma_coordinate',
                                         {"sigma", "eta", "depth"}))
        self.assertTrue(no_missing_terms('ocean_s_coordinate',
                                         {"s", "eta", "depth", "a", "b",
                                          "depth_c"}))
        self.assertTrue(no_missing_terms('ocean_sigma_z_coordinate',
                                         {"sigma", "eta", "depth", "depth_c",
                                          "nsigma", "zlev"}))
        self.assertTrue(no_missing_terms('ocean_double_sigma_coordinate',
                                         {"sigma", "depth", "z1", "z2", "a",
                                          "href", "k_c"}))

    def test_dimensionless_vertical(self):
        '''
        Section 4.3.2
        '''
        # Check affirmative compliance
        dataset = self.load_dataset(STATIC_FILES['dimensionless'])
        results = self.cf.check_dimensionless_vertical_coordinate(dataset)
        scored, out_of, messages = self.get_results(results)

        # all variables checked (2) pass
        assert len(results) == 2
        assert scored == out_of
        assert all(r.name == u"§4.3 Vertical Coordinate" for r in results)

        # Check negative compliance -- 3 out of 4 pass

        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_dimensionless_vertical_coordinate(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 4 
        assert scored <= out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u"§4.3 Vertical Coordinate" for r in results)

        # test with an invalid formula_terms
        dataset.variables['lev2'] = MockVariable(dataset.variables['lev2'])
        lev2 = dataset.variables['lev2']
        lev2.formula_terms = 'a: var1 b:var2 orog:'

        # create a malformed formula_terms attribute and check that it fails
        # 2/4 still pass
        results = self.cf.check_dimensionless_vertical_coordinate(dataset)
        scored, out_of, messages = self.get_results(results)

        assert len(results) == 4 
        assert scored <= out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u"§4.3 Vertical Coordinate" for r in results)


    def test_is_time_variable(self):
        var1 = MockVariable()
        var1.standard_name = 'time'
        self.assertTrue(is_time_variable('not_time', var1))

        var2 = MockVariable()
        self.assertTrue(is_time_variable('time', var2))

        self.assertFalse(is_time_variable('not_time', var2))

        var3 = MockVariable()
        var3.axis = 'T'
        self.assertTrue(is_time_variable('maybe_time', var3))

        var4 = MockVariable()
        var4.units = 'seconds since 1900-01-01'
        self.assertTrue(is_time_variable('maybe_time', var4))

    def test_dimensionless_standard_names(self):
        """Check that dimensionless standard names are properly detected"""
        std_names_xml_root = self.cf._std_names._root
        # canonical_units are K, should be False
        self.assertFalse(cfutil.is_dimensionless_standard_name(std_names_xml_root,
                                                             'sea_water_temperature'))
        # canonical_units are 1, should be True
        self.assertTrue(cfutil.is_dimensionless_standard_name(std_names_xml_root,
                                                             'sea_water_practical_salinity'))
        # canonical_units are 1e-3, should be True
        self.assertTrue(cfutil.is_dimensionless_standard_name(std_names_xml_root,
                                                             'sea_water_salinity'))

    def test_check_time_coordinate(self):
        dataset = self.load_dataset(STATIC_FILES['example-grid'])
        results = self.cf.check_time_coordinate(dataset)
        for r in results:
            self.assertTrue(r.value)

        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_time_coordinate(dataset)

        scored, out_of, messages = self.get_results(results)

        assert u'time does not have correct time units' in messages
        assert (scored, out_of) == (1, 2)

    def test_check_calendar(self):
        """Load a dataset with an invalid calendar attribute (non-comp/bad.nc).
        This dataset has a variable, "time" with  calendar attribute "nope"."""

        dataset = self.load_dataset(STATIC_FILES['example-grid'])
        results = self.cf.check_calendar(dataset)
        for r in results:
            self.assertTrue(r.value)

        dataset = self.load_dataset(STATIC_FILES['bad'])
        results = self.cf.check_calendar(dataset)
        scored, out_of, messages = self.get_results(results)

        assert u"§4.4.1 Variable time should have a valid calendar: 'nope' is not a valid calendar" in messages

    def test_check_aux_coordinates(self):
        dataset = self.load_dataset(STATIC_FILES['illegal-aux-coords'])
        results = self.cf.check_aux_coordinates(dataset)
        result_dict = {result.name: result for result in results}
        result = result_dict[u"§5 Coordinate Systems"]
        assert result.msgs == [] # shouldn't have any messages
        assert result.value == (4, 4)

    def test_check_grid_coordinates(self):
        dataset = self.load_dataset(STATIC_FILES['2dim'])
        results = self.cf.check_grid_coordinates(dataset)
        scored, out_of, messages = self.get_results(results)

        result_dict = {result.name: result for result in results}
        result = result_dict[u'§5.6 Horizontal Coorindate Reference Systems, Grid Mappings, Projections']
        assert result.value == (2, 2)
        assert (scored, out_of) == (2, 2)

    def test_check_two_dimensional(self):
        dataset = self.load_dataset(STATIC_FILES['2dim'])
        results = self.cf.check_grid_coordinates(dataset)
        for r in results:
            self.assertTrue(r.value)
        # Need the bad testing
        dataset = self.load_dataset(STATIC_FILES['bad2dim'])
        results = self.cf.check_grid_coordinates(dataset)
        scored, out_of, messages = self.get_results(results)

        # all variables checked fail (2)
        assert len(results) == 2
        assert scored < out_of
        assert all(r.name == u'§5.6 Horizontal Coorindate Reference Systems, Grid Mappings, Projections' for r in results)


    def test_check_reduced_horizontal_grid(self):
        dataset = self.load_dataset(STATIC_FILES['rhgrid'])
        results = self.cf.check_reduced_horizontal_grid(dataset)
        scored, out_of, messages = self.get_results(results)
        assert scored == out_of
        assert len(results) == 1
        assert all(r.name == u'§5.3 Reduced Horizontal Grid' for r in results)

        # load failing ds -- one variable has failing check
        dataset = self.load_dataset(STATIC_FILES['bad-rhgrid'])
        results = self.cf.check_reduced_horizontal_grid(dataset)
        scored, out_of, messages = self.get_results(results)
        assert scored != out_of
        assert len(results) == 2
        assert len([r for r in results if r.value[0] < r.value[1]]) == 1
        assert all(r.name == u'§5.3 Reduced Horizontal Grid' for r in results)


    def test_check_grid_mapping(self):
        dataset = self.load_dataset(STATIC_FILES['mapping'])
        results = self.cf.check_grid_mapping(dataset)

        # there are 8 results, 2 of which did not have perfect scores
        assert len(results) == 8
        assert len([r.value for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u'§5.6 Horizontal Coorindate Reference Systems, Grid Mappings, Projections' for r in results)


    def test_check_geographic_region(self):
        dataset = self.load_dataset(STATIC_FILES['bad_region'])
        results = self.cf.check_geographic_region(dataset)
        scored, out_of, messages = self.get_results(results)

        # only one variable failed this check in this ds out of 2
        assert len(results) == 2
        assert scored < out_of
        assert u"6.1.1 'Neverland' specified by 'neverland' is not a valid region" in messages


    def test_check_packed_data(self):
        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        results = self.cf.check_packed_data(dataset)
        self.assertEqual(len(results), 4)
        self.assertFalse(results[0].value)
        self.assertFalse(results[1].value)
        self.assertTrue(results[2].value)
        self.assertFalse(results[3].value)

    def test_compress_packed(self):
        """Tests compressed indexed coordinates"""
        dataset = self.load_dataset(STATIC_FILES['reduced_horizontal_grid'])
        results = self.cf.check_compression_gathering(dataset)
        self.assertTrue(results[0].value)

        dataset = self.load_dataset(STATIC_FILES['bad_data_type'])
        results = self.cf.check_compression_gathering(dataset)
        self.assertFalse(results[0].value)
        self.assertFalse(results[1].value)

    def test_check_all_features_are_same_type(self):
        dataset = self.load_dataset(STATIC_FILES['rutgers'])
        result = self.cf.check_all_features_are_same_type(dataset)
        assert result

        dataset = self.load_dataset(STATIC_FILES['featureType'])
        result = self.cf.check_all_features_are_same_type(dataset)
        assert result

    def test_featureType_is_case_insensitive(self):
        '''
        Tests that the featureType attribute is case insensitive
        '''
        nc = self.new_nc_file()
        nc.featureType = 'timeseriesprofile'
        result = self.cf.check_feature_type(nc)
        self.assertTrue(result.value == (1, 1))

        nc.featureType = 'timeSeriesProfile'
        result = self.cf.check_feature_type(nc)
        self.assertTrue(result.value == (1, 1))

        nc.featureType = 'traJectorYpRofile'
        result = self.cf.check_feature_type(nc)
        self.assertTrue(result.value == (1, 1))

        # This one should fail
        nc.featureType = 'timeseriesprofilebad'
        result = self.cf.check_feature_type(nc)
        self.assertTrue(result.value == (0, 1))

    def test_check_units(self):
        '''
        Ensure that container variables are not checked for units but geophysical variables are
        '''
        dataset = self.load_dataset(STATIC_FILES['units_check'])
        results = self.cf.check_units(dataset)

        # We don't keep track of the variables names for checks that passed, so
        # we can make a strict assertion about how many checks were performed
        # and if there were errors, which there shouldn't be.
        # FIXME (badams): find a better way of grouping together results by
        #                 variable checked instead of checking the number of
        #                 points scored, which should be deprecated, and
        #                 furthermore is fragile and breaks tests when check
        #                 definitions change
        scored, out_of, messages = self.get_results(results)
        assert scored == 24
        assert out_of == 24
        assert messages == []

    def test_check_duplicates(self):
        '''
        Test to verify that the check identifies duplicate axes. Load the
        duplicate_axis.nc dataset and verify the duplicate axes are accounted
        for.
        '''

        dataset = self.load_dataset(STATIC_FILES['duplicate_axis'])
        results = self.cf.check_duplicate_axis(dataset)
        scored, out_of, messages = self.get_results(results)

        # only one check run here, so we can directly compare all the values
        assert scored != out_of
        assert messages[0] == u"'temp' has duplicate axis X defined by lon_rho"

    def test_check_multi_dimensional_coords(self):
        '''
        Test to verify that multi dimensional coordinates are checked for
        sharing names with dimensions
        '''
        dataset = self.load_dataset(STATIC_FILES['multi-dim-coordinates'])
        results = self.cf.check_multi_dimensional_coords(dataset)
        scored, out_of, messages = self.get_results(results)

        # 4 variables were checked in this ds, 2 of which passed
        assert len(results) == 4
        assert len([r for r in results if r.value[0] < r.value[1]]) == 2
        assert all(r.name == u"§5 Coordinate Systems" for r in results)


    def test_64bit(self):
        dataset = self.load_dataset(STATIC_FILES['ints64'])
        suite = CheckSuite()
        suite.checkers = {
            'cf'        : CFBaseCheck
        }
        suite.run(dataset, 'cf')

    def test_variable_feature_check(self):

        # non-compliant dataset -- 1/1 fail
        dataset = self.load_dataset(STATIC_FILES['bad-trajectory'])
        results = self.cf.check_variable_features(dataset)
        scored, out_of, messages = self.get_results(results)
        assert len(results) == 1
        assert scored < out_of
        assert len([r for r in results if r.value[0] < r.value[1]]) == 1
        assert all(r.name == u'§9.1 Features and feature types' for r in results)

        # compliant dataset
        dataset = self.load_dataset(STATIC_FILES['trajectory-complete'])
        results = self.cf.check_variable_features(dataset)
        scored, out_of, messages = self.get_results(results)
        assert scored == out_of

        # compliant(?) dataset
        dataset = self.load_dataset(STATIC_FILES['trajectory-implied'])
        results = self.cf.check_variable_features(dataset)
        scored, out_of, messages = self.get_results(results)
        assert scored == out_of


    def test_check_cell_methods(self):
        """Load a dataset (climatology.nc) and check the cell methods.
        This dataset has variable "temperature" which has valid cell_methods
        format, cell_methods attribute, and valid names within the
        cell_methods attribute."""

        dataset = self.load_dataset(STATIC_FILES['climatology'])
        results = self.cf.check_cell_methods(dataset)
        scored, out_of, messages = self.get_results(results)

        # use itertools.chain() to unpack the lists of messages
        results_list = list(chain(*(r.msgs for r in results if r.msgs)))

        # check the results only have expected headers
        assert set([r.name for r in results]).issubset(set([u'§7.1 Cell Boundaries', u'§7.3 Cell Methods']))

        # check that all the expected variables have been hit
        assert all("temperature" in msg for msg in results_list)

        # check that all the results have come back passing
        assert all(r.value[0] == r.value[1] for r in results)

        # create a temporary variable and test this only
        nc_obj = MockTimeSeries()
        nc_obj.createVariable('temperature', 'd', ('time',))

        temp = nc_obj.variables['temperature']
        temp.cell_methods = 'lat: lon: mean depth: mean (interval: 20 meters)'
        results = self.cf.check_cell_methods(nc_obj)
        # invalid components lat, lon, and depth -- expect score == (6, 9)
        scored, out_of, messages = self.get_results(results)
        assert scored != out_of

        temp.cell_methods = 'lat: lon: mean depth: mean (interval: x whizbangs)'
        results = self.cf.check_cell_methods(nc_obj)
        scored, out_of, messages = self.get_results(results)

        # check non-standard comments are gauged correctly
        temp.cell_methods = 'lat: lon: mean depth: mean (comment: should not go here interval: 2.5 m)'
        results = self.cf.check_cell_methods(nc_obj)
        scored, out_of, messages = self.get_results(results)

        self.assertTrue(u'§7.3.3 The non-standard "comment:" element must come after any standard elements in cell_methods for variable temperature' in messages)

        # standalone comments require no keyword
        temp.cell_methods = 'lon: mean (This is a standalone comment)'
        results = self.cf.check_cell_methods(nc_obj)
        scored, out_of, messages = self.get_results(results)
        assert "standalone" not in messages

        # check that invalid keywords dealt with
        temp.cell_methods = 'lat: lon: mean depth: mean (invalid_keyword: this is invalid)'
        results = self.cf.check_cell_methods(nc_obj)
        scored, out_of, messages = self.get_results(results)
        self.assertTrue(u'§7.3.3 Invalid cell_methods keyword "invalid_keyword:" for variable temperature. Must be one of [interval, comment]' in messages)

        # check that "parenthetical elements" are well-formed (they should not be)
        temp.cell_methods = 'lat: lon: mean depth: mean (interval 0.2 m interval: 0.01 degrees)'
        results = self.cf.check_cell_methods(nc_obj)
        scored, out_of, messages = self.get_results(results)
        assert u'§7.3.3 Parenthetical content inside temperature:cell_methods is not well formed: interval 0.2 m interval: 0.01 degrees' in messages



    # --------------------------------------------------------------------------------
    # Utility Method Tests
    # --------------------------------------------------------------------------------

    def test_temporal_unit_conversion(self):
        self.assertTrue(units_convertible('hours', 'seconds'))
        self.assertFalse(units_convertible('hours', 'hours since 2000-01-01'))

    def test_units_temporal(self):
        self.assertTrue(units_temporal('hours since 2000-01-01'))
        self.assertFalse(units_temporal('hours'))
        self.assertFalse(units_temporal('days since the big bang'))
