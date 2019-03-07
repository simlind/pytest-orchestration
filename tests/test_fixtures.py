from orchestration import plugin
from orchestration import reporter
import time
import pytest

CONFIG_BASE_RELPATH = 'tests/configs/'
TEST_CONFIG_NAME = 'test_config'
SEC_TEST_CONFIG_NAME = 'sec_test_config'


def get_config_under_test():
    test_config = plugin.LOADED_DESCRIPTIONS[TEST_CONFIG_NAME]
    return test_config


def get_sec_config_under_test():
    test_config = plugin.LOADED_DESCRIPTIONS[SEC_TEST_CONFIG_NAME]
    return test_config


@pytest.fixture
def result_reporter_impl(report_queue):

    my_reporter = reporter.ResultReporter(report_queue)

    def do_nothing():
        pass
    my_reporter.on_result = do_nothing
    return my_reporter


def test_orchestrate(request, kill_switch, result_reporter, dummy):
    test_config = get_config_under_test()
    total_time = test_config['total_hours'] * 3600
    all_events = plugin.get_events(request, test_config)
    orchestrator = plugin.Orchestrator(total_time, all_events, kill_switch, result_reporter)
    start_time = time.time()
    orchestrator.run()
    end_time = time.time() - start_time
    assert end_time == pytest.approx(total_time, 3)
    assert 1 == dummy.inc_value
    assert 3 == dummy.dec_value
    assert 3 == result_reporter.results.qsize()


@pytest.mark.parametrize('test_config', [get_config_under_test(), get_sec_config_under_test()])
def test_fixture_creation(request, test_config):
    for event in test_config['events']:
        func = request.getfixturevalue(event['name'])
        assert callable(func)


def test_shared_object(request, dummy):
    test_config = get_config_under_test()
    all_events = plugin.get_events(request, test_config)
    test_funcs_names = ['increament_func_6', 'decreament_func_7']
    test_events = [event for event in all_events if event.name in test_funcs_names]

    expected_value = 1
    for i in range(10):
        for event in test_events:
            event.func()
        assert dummy.inc_value == expected_value
        assert dummy.dec_value == expected_value
        expected_value += 1


def test_param_fixtures(request):
    test_config = get_config_under_test()
    for event in test_config['events']:
        if event['name'].startswith('fixture_and_param_func'):
            param_fixtures = event['params']
            break
    for param_name, value in param_fixtures.items():
        assert request.getfixturevalue(param_name) == value


def test_normal_fix(request, dummy):
    for i in range(10):
        request.getfixturevalue('dummy_adder')
        assert 1 == dummy.inc_value


def test_reused_params(request):
    first_test_config = get_config_under_test()
    sec_test_config = get_sec_config_under_test()
    param_fixtures = list()
    for test_config in [first_test_config, sec_test_config]:
        for event in test_config['events']:
            if event['name'].startswith('fixture_and_param_func'):
                param_fixtures.append(event['params'])
                break
    result_dict = dict()
    for i, event_parms in enumerate(param_fixtures):
        result_dict[str(i)] = list()

        for param_name, value in event_parms.items():
            result_dict[str(i)].append(request.getfixturevalue(param_name))
    for i, result in enumerate(result_dict['0']):
        assert result_dict['1'][i] != result


def test_double_event_in_same_desc(request):
    sec_test_config = get_sec_config_under_test()
    first_event = sec_test_config['events'][0]
    second_event = sec_test_config['events'][1]

    first_event_name = first_event['name']
    second_event_name = second_event['name']
    assert first_event_name != second_event_name
    assert callable(request.getfixturevalue(first_event_name))
    assert callable(request.getfixturevalue(second_event_name))

    first_event_params = first_event['params']
    second_event_params = second_event['params']

    assert first_event_params != second_event_params
    for param_name, param_value in first_event_params.items():
        assert request.getfixturevalue(param_name) == param_value

    for param_name, param_value in second_event_params.items():
        assert request.getfixturevalue(param_name) == param_value


def test_func_copy():

    def my_func(x, y):
        return x + y

    new_func = plugin.copy_func(my_func)
    assert new_func is not my_func
    assert new_func(1, 1) == 2

