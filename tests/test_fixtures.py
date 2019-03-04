from orchestration import plugin
from orchestration import reporter
import time
import pytest

CONFIG_BASE_RELPATH = 'tests/configs/'
TEST_CONFIG_NAME = 'test_config.json'


def get_config_under_test():
    test_config = plugin.get_json_description(CONFIG_BASE_RELPATH, TEST_CONFIG_NAME)
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


def test_fixture_creation(request):
    test_config = get_config_under_test()
    for event in test_config['events']:
        func = request.getfixturevalue(event['name'])
        assert callable(func)


def test_shared_object(request, dummy):
    test_config = get_config_under_test()
    all_events = plugin.get_events(request, test_config)
    test_funcs_names = ['increament_func', 'decreament_func']
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
        if event['name'] == 'fixture_and_param_func':
            param_fixtures = event['params']
            break
    for name, value in param_fixtures.items():
        assert request.getfixturevalue(name) == value


def test_normal_fix(request, dummy):
    for i in range(10):
        request.getfixturevalue('dummy_adder')
        assert 1 == dummy.inc_value
