import pytest
import logging

logger = logging.getLogger(__name__)

def assert_func():
    assert True


def increament_func(dummy):
    logger.warning('increasing!')
    dummy.inc_value += 1


def decreament_func(dummy, result_reporter):
    logger.warning('decreasing!')
    dummy.dec_value += 1
    result_reporter.add_result('dummy_res')


def fixture_and_param_func(str_value, int_value, list_value, dict_value, request):
    assert str_value == 'test_string'
    assert int_value == 5
    assert list_value == [1, 2, 3, 4, 5]
    assert dict_value == {'key': 'value'}
