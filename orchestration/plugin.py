import functools
import importlib
import inspect
import json
import logging
import multiprocessing
import os
import copy
import time
import types
from concurrent.futures import ThreadPoolExecutor
from os import path

import pytest
from orchestration import orch_run
from orchestration import reporter


logger = logging.getLogger(__name__)
UNIQUE_ID = list(range(100))
LOADED_DESCRIPTIONS = dict()


@pytest.fixture
def kill_switch(request):
    """
    Event that will be set when test is ended so we know when subprocess should be killed
    """
    kill_event = multiprocessing.Event()

    def fin():
        kill_event.set()

    request.addfinalizer(fin)
    return kill_event


@pytest.fixture
def report_queue():
    result_queue = multiprocessing.Manager().Queue()
    return result_queue


@pytest.fixture
def result_reporter(report_queue):
    result_reporter = reporter.ResultReporter(report_queue)
    return result_reporter


@pytest.fixture
def target_description(request):
    orchestration_name = request.config.getoption('--run-orch')
    orchestration_config = LOADED_DESCRIPTIONS[orchestration_name]
    return orchestration_config


@pytest.fixture
def all_events(request, target_description):
    event_objects = get_events(request, target_description)
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


def generate_factory_fixture(func, new_params):

    def generated_fixture(*args, **kwargs):

        def factory_func():
            func(*args, **kwargs)

        return factory_func

    args_str = adjust_parameters(func, new_params)
    func_def = 'lambda {args}: generated_fixture({args})'.format(args=args_str)
    eval_func = eval(func_def, {'generated_fixture': generated_fixture})
    return pytest.fixture(functools.wraps(func)(eval_func))


def adjust_parameters(func, params):
    arg_spec = inspect.getargspec(func)
    formatted_args = inspect.formatargspec(*arg_spec)
    sig = inspect.signature(func)
    param_sig_list = list(sig.parameters.values())

    for param in params:
        param_name = param.rsplit('_', 1)[0]
        formatted_args = formatted_args.replace(param_name, param)
        for i, old_param in enumerate(param_sig_list):
            if old_param.name == param_name:
                param_sig_list[i] = old_param.replace(name=param)
    func.__signature__ = sig.replace(parameters=param_sig_list)
    clean_args_str = formatted_args.lstrip('(').rstrip(')')
    return clean_args_str


def setup_value_fixtures(orchestration_description):
    desc_working_copy = copy.deepcopy(orchestration_description)
    for i, event in enumerate(desc_working_copy['events']):
        if 'params' not in event:
            continue
        for param_name, param_value in event['params'].items():
            unique_name = '{}_{}'.format(param_name, UNIQUE_ID.pop(0))
            globals()[unique_name] = generate_value_fixture(param_value)
            orchestration_description['events'][i]['params'][unique_name] = orchestration_description['events'][i]['params'].pop(param_name)


def setup_factory_fixtures(sources, orchestration_description):
    module_sources = list()
    for source in sources:
        if not path.exists(source):
            logger.warning('Specified orchestration_source: {} do not exist!'.format(source))
            continue
        event_module = filepath_to_modulepath(source)
        module_sources.append(event_module)

    for i, event in enumerate(orchestration_description['events']):
        event_name = event['name']
        for module in module_sources:
            tmp_module = importlib.import_module(module)
            try:
                event_fun = copy_func(getattr(tmp_module, event_name))
                generated_event_name = '{}_{}'.format(event_name, UNIQUE_ID.pop(0))
                event_params = event.get('params', list())
                globals()[generated_event_name] = generate_factory_fixture(event_fun, event_params)
                orchestration_description['events'][i]['name'] = generated_event_name
                break
            except Exception as e:
                logger.debug('Caught exception {}'.format(e))
                pass


def copy_func(func):
    new_func = types.FunctionType(
        func.__code__,
        func.__globals__,
        name=func.__name__,
        argdefs=func.__defaults__,
        closure=func.__closure__
    )
    new_func = functools.update_wrapper(new_func, func)
    new_func.__kwdefaults__ = func.__kwdefaults__
    return new_func


def _setup_fixtures(orch_source, orchestration_description):
    setup_value_fixtures(orchestration_description)
    setup_factory_fixtures(orch_source, orchestration_description)
    LOADED_DESCRIPTIONS[orchestration_description['test_name']] = orchestration_description


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
        orchestration_sources = config.sections['pytest']['orchestration_sources'].split(',')
    except KeyError:
        raise Exception('No "orchestration_sources" entry found in .ini config')
    try:
        orchestration_descriptions_folder = config.sections['pytest']['orchestration_descriptions']
    except KeyError:
        raise Exception('No "orchestration_descriptions" entry found in .ini config file')
    return orchestration_sources, orchestration_descriptions_folder


def pytest_configure(config):
    config_to_run = config.getoption('--run-orch')
    if config.getoption('--load-orch') or config_to_run:
        orchestration_sources, orchestration_descriptions_folder = get_source_and_desc_folder(config.inicfg.config)
        for root, dirs, files in os.walk(orchestration_descriptions_folder, topdown=False):
            for name in files:
                orchestration_description = get_json_description(root, name)
                if orchestration_description is None:
                    continue
                # If --run-orch not specified we setup all fixtures
                if config_to_run is None:
                    _setup_fixtures(orchestration_sources, orchestration_description)
                # If --run-orch is specified we only setup its related fixtures
                elif config_to_run == orchestration_description['test_name']:
                    _setup_fixtures(orchestration_sources, orchestration_description)
                    _setup_test(config, orchestration_description)
                    return
        pytest.exit('Failed to setup orchestration!')


def _setup_test(config, orch_desc):
    test_name = 'test_{}'.format(orch_desc['test_name'])
    timeout = config.inicfg.config.sections['pytest'].get('orchestration_timeout', 60*60)

    if config.getoption('--runtime-orch'):
        orch_desc['total_hours'] = float(config.getoption('--runtime-orch'))

    test_time_sec = orch_desc['total_hours'] * 3600
    setup_fixtures = orch_desc.get('unref_setup_fixtures', list())
    orch_run.generate_test(test_name, test_time_sec, setup_fixtures)
    config.args.append(orch_run.get_path())
    config.option.timeout = float(test_time_sec + timeout)
    config.option.keyword = test_name


def pytest_addoption(parser):
    group = parser.getgroup("orchestration", "orchestrating tests")
    group.addoption('--load-orch', action='store_true', default=False, help='orchestration events will be loaded')
    group.addoption('--run-orch', action='store', help='orchestration description name')
    group.addoption('--runtime-orch', action='store', help='Optional, runtime for orch test, will override description value')


def create_event_from_json(json_config, func):
    name = json_config['name']
    if json_config.get('interval_sec'):
        interval_sec = json_config.get('interval_sec')
    elif json_config.get('interval_min'):
        interval_sec = json_config.get('interval_min') * 60
    elif json_config.get('interval_hour'):
        interval_sec = json_config.get('interval_hour') * 60 * 60
    else:
        interval_sec = None
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
    TIC_TIME = 60

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
            logger.info('No interval events left to run, {} sec until end of test'.format(timeout_sec))
            time.sleep(self.TIC_TIME)
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
        test_failure = False
        while time.time() <= end_time:
            time_left = end_time - time.time()
            if time_left <= 0:
                time_left = 0
            if self.kill_event.is_set():
                logger.info('Kill switch triggered, stopping test!')
                test_failure = True
                break
            self.next_event(time_left)
        self.run_teardown_events()
        self.kill_all_events()
        if test_failure:
            pytest.fail('Test failed', False)
        logger.info('Orchestration test finished!')
