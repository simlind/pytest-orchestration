from orchestration import plugin

ESSENTIAL_FIXTURES = ['all_events', 'kill_switch', 'result_reporter']


def get_path():
    return __file__


def generate_test(name, test_time_sec, setup_fixtures):

    def generated_test(*args):
        orchestrator = plugin.Orchestrator(test_time_sec, *args)
        orchestrator.run()

    fixture_signature_list = ESSENTIAL_FIXTURES + setup_fixtures
    fixture_signature_str = ', '.join(fixture_signature_list)

    func_def = 'lambda {fixtures}: generated_test({fixtures})'.format(fixtures=fixture_signature_str)
    eval_test = eval(func_def, {'generated_test': generated_test})

    globals()[name] = eval_test
    globals()[name].__name__ = name
