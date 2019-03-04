import functools
import importlib
import inspect
import json
import logging
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from os import path

import pytest
from orchestration import orch_run
from orchestration import reporter


logger = logging.getLogger(__name__)


@pytest.fixture
def kill_switch():
    """
    Event that will be set when test is ended so we know when subprocess should be killed
    """
    kill_event = multiprocessing.Event()
    return kill_event


@pytest.fixture
def report_queue():
    result_queue = multiprocessing.Manager().Queue()
    return result_queue


@pytest.fixture
def result_reporter_impl(report_queue):
    return reporter.ResultReporter(report_queue)


@pytest.fixture
def result_reporter(result_reporter_impl):
    return result_reporter_impl


@pytest.fixture
def orchestration_description(request):
    orchestration_name = request.config.getoption('--run-orch')
    orchestration_descriptions_folder = request.config.inicfg.config.sections['pytest']['orchestration_descriptions']
    # Todo: fix config getting, shouldnt have to be same as file name
    orchestration_config = get_json_description(orchestration_descriptions_folder, orchestration_name)
    return orchestration_config


@pytest.fixture
def all_events(request, orchestration_description):
    event_objects = get_events(request, orchestration_description)
    return event_objects


def get_events(request, orch_config):
    event_list = orch_config['events']
    event_objects = list()
    for event_dict in event_list:
        func = request.getfixturevalue(event_dict['name'])
        event = create_event_from_json(event_dict, func)
        event_objects.append(event)
    return event_objects


def generate_value_fixture(value):

    def generated_fixture():
        return value

    return pytest.fixture(generated_fixture)


def generate_factory_fixture(func):

    def generated_fixture(*args, **kwargs):

        def factory_func():
            func(*args, **kwargs)

        return factory_func

    arg_spec = inspect.getargspec(func)
    formatted_args = inspect.formatargspec(*arg_spec)
    stripped_args = formatted_args.lstrip('(').rstrip(')')
    func_def = 'lambda {}: generated_fixture{}'.format(stripped_args, formatted_args)
    eval_func = eval(func_def, {'generated_fixture': generated_fixture})
    return pytest.fixture(functools.wraps(func)(eval_func))


def setup_value_fixtures(events):
    for event in events:
        if 'params' not in event:
            continue
        for param_name, param_value in event['params'].items():
            globals()[param_name] = generate_value_fixture(param_value)


def setup_factory_fixtures(sources, events):
    module_sources = list()
    for source in sources:
        if not path.exists(source):
            logger.warning('Specified orchestration_source: {} do not exist!'.format(source))
            continue
        event_module = filepath_to_modulepath(source)
        module_sources.append(event_module)

    for event in events:
        event_name = event['name']
        for module in module_sources:
            tmp_module = importlib.import_module(module)
            try:
                event_fun = getattr(tmp_module, event_name)
                globals()[event_name] = generate_factory_fixture(event_fun)
                break
            except Exception:
                logger.debug('Event do not exist in {}'.format(module))
                pass


def filepath_to_modulepath(file_path):
    module_path = file_path.replace('/', '.').replace('.py', '')
    return module_path


def get_json_description(base_folder, name):
    if not name.endswith('.json'):
        name += '.json'
    description_path = path.join(base_folder, name)
    with open(description_path) as f:
        try:
            description_config = json.load(f, strict=False)
        except Exception as e:
            logger.error('Failed to load config file: "{}", error: {}'.format(name, e))
            return None
    return description_config


def get_source_and_desc_folder(config):
    try:
        orchestration_sources = config.inicfg.config.sections['pytest']['orchestration_sources'].split(',')
    except KeyError:
        raise Exception('No "orchestration_sources" entry found in .ini config')
    try:
        orchestration_descriptions_folder = config.inicfg.config.sections['pytest']['orchestration_descriptions']
    except KeyError:
        raise Exception('No "orchestration_descriptions" entry found in .ini config file')
    return orchestration_sources, orchestration_descriptions_folder


def pytest_configure(config):
    logger.warning('setting up our conifgs')
    config_to_run = config.getoption('--run-orch')
    if config.getoption('--load-orch') or config_to_run:
        orchestration_sources, orchestration_descriptions_folder = get_source_and_desc_folder(config)
        for root, dirs, files in os.walk(orchestration_descriptions_folder, topdown=False):
            for name in files:
                orchestration_description = get_json_description(root, name)
                if orchestration_description is None:
                    continue
                # Todo: make it smarter, dont have to set up all if config_to_run is set
                _setup_fixtures(orchestration_sources, orchestration_description['events'])
                if config_to_run is not None and config_to_run == orchestration_description['test_name']:
                    _setup_test(config, orchestration_description)


def _setup_fixtures(orch_source, event_list):
    setup_value_fixtures(event_list)
    setup_factory_fixtures(orch_source, event_list)


def _setup_test(config, orch_desc):
    test_name = 'test_{}'.format(orch_desc['test_name'])
    test_time_sec = orch_desc['total_hours'] * 3600
    setup_fixtures = orch_desc.get('unref_setup_fixtures', list())
    orch_run.generate_test(test_name, test_time_sec, setup_fixtures)
    config.args.append(orch_run.get_path())
    config.option.timeout = float(test_time_sec + 60)
    config.option.keyword = test_name


def pytest_addoption(parser):
    group = parser.getgroup("orchestration", "orchestrating tests")
    group.addoption('--load-orch', action='store_true', default=False, help='orchestration events will be loaded')
    group.addoption('--run-orch', action='store', help='orchestration description name')


def create_event_from_json(json_config, func):
    name = json_config['name']
    interval_sec = json_config.get('interval_sec')
    at_startup = json_config.get('at_startup', True)
    at_teardown = json_config.get('at_teardown', False)
    event = Event(name, func, interval_sec, at_startup, at_teardown)
    return event


class Event:
    """
    A class representing the event being used in a orchestration test.
    Holds configurations, result and a reference to the callable function
    """

    def __init__(
            self,
            name,
            func,
            interval_sec,
            at_startup,
            at_teardown):
        self.name = name
        self.func = func
        self.interval_sec = interval_sec
        self._time_left = interval_sec
        self.at_startup = at_startup
        self.at_teardown = at_teardown

    @property
    def time_left(self):
        return self._time_left

    @time_left.setter
    def time_left(self, time):
        if time >= 0:
            self._time_left = time
        else:
            self._time_left = 0

    def reset(self):
        """
        Resets the wait time for the event
        """
        self.time_left = self.interval_sec


class Orchestrator:
    """
    Class that takes a list of events and schedules them according to their
    interval_sec parameter.
    """

    def __init__(self, total_time_sec, events, kill_event, reporter, *args):
        self.total_time_sec = total_time_sec
        self.all_events = events
        self.kill_event = kill_event
        self.interval_events = [event for event in events if event.interval_sec is not None]
        self._executor_workers = dict()
        self.reporter = reporter
        self.start_reporter()

    @property
    def executor_workers(self):
        if not self._executor_workers:
            return self._executor_workers
        for event in self.all_events:
            self._executor_workers[event.name] = ThreadPoolExecutor(max_workers=1)
        return self._executor_workers

    def start_reporter(self):
        self.executor_workers['reporter'] = ThreadPoolExecutor(max_workers=1)
        self.executor_workers['reporter'].submit(self.reporter.monitor, self.kill_event)

    def run_startup_events(self):
        for event in self.all_events:
            if event.at_startup:
                self.execute(event)

    def run_teardown_events(self):
        for event in self.all_events:
            if event.at_teardown:
                self.execute(event)

    def execute(self, event):
        try:
            self.executor_workers[event.name].shutdown()
        except Exception:
            pass
        logger.info('Executing event: {}'.format(event.name))
        try:
            self.executor_workers[event.name].submit(event.func)
        except Exception:
            pass

    def next_event(self, timeout_sec):
        """
        Sleeps until its time for next event and executes it
        """
        logger.info('next_event timeout: {}'.format(timeout_sec))
        if not self.interval_events:
            logger.info('No interval events left to run, waiting {} sec until end of test'.format(timeout_sec))
            time.sleep(timeout_sec)
            return None
        upcoming_event = self.interval_events.pop(0)
        if upcoming_event.time_left > timeout_sec:
            logger.warning('Next event: "{}" is scheduled after test end.'.format(upcoming_event.name))
            return None
        logger.info('Waiting {} sec for next event: "{}"'.format(upcoming_event.time_left, upcoming_event.name))
        time.sleep(upcoming_event.time_left)
        self.execute(upcoming_event)
        self.update_events(upcoming_event)

    def update_events(self, last_event):
        """
        Updates the scheduled list of events
        """
        for event in self.interval_events:
            event.time_left = event.time_left - last_event.time_left
        last_event.reset()
        self.interval_events.append(last_event)
        self.interval_events = sorted(self.interval_events, key=lambda x: x.time_left)

    def kill_all_events(self):
        self.kill_event.set()
        for name, executor in self.executor_workers.items():
            logger.info('Shutting down: {}'.format(name))
            executor.shutdown(10)

    def run(self):
        logger.info('Test orchestration started!')
        end_time = time.time() + self.total_time_sec
        self.run_startup_events()
        while time.time() <= end_time:
            time_left = end_time - time.time()
            if time_left <= 0:
                time_left = 0
            self.next_event(time_left)
        self.run_teardown_events()
        self.kill_all_events()
        logger.info('Orchestration test finished!')
