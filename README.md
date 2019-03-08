# Pytest-Orchestration

Pytest-Orchestration is configuration driven test orchestration plugin, designed with the intention of being used for performance tests, however it might fit other purposes as well.

## Installation
```
pip install pytest-orchestration
```

## Configuration/Description

The configuration describing the orchestrated tests has the form of a .json file.
Where these files live is defined in the pytest.ini under "orchestration_descriptions". Note that the name of the file should match the `test_name` key in the file as well.
```
[pytest]
orchestration_descriptions = orchestration/descriptions/
```
Below is an example config with comments:
```
{
  "test_name": "my_orchestration_test",                 // Name of the test (no need to have a "test" prefix or suffix)
  "total_hours": 3,                                     // Total number of hours for the test to run
  "unref_setup_fixtures": ["device_with_collectd"],     // A list of setup fixtures that won't be references in actual test events
  "events": [                                           // A list of all "events" making up the test
    {
      "name": "start_playback",                         // Mandatory: The name of the event as it is implemented, see Events section below
      "interval_sec": 300,                              // Optional: The number of seconds between eache execution of this event. If it is not set, then the event will only be triggerd according to "at_startup" and "at_teardown"
      "at_startup": true,                               // Optional(Defaults to true): Specifies if the event should be executed once on startup, if false it will wait interval_sec befor being executed.
      "at_teardown": false,                              // Optional(Defaults to false): Specifies if a event should be executed on teardown, one last time after the time "total_hours" have been reached.
      "params":{                                        // Optional: Params is a dict of simple key: values that would be used in the implemented events
        "video_path": "/home/orch-tests/video-files/high_res_clip.mp4"
      }
    },
    {
      "name": "start_streamer",
      "at_startup": true
    },
    {
      "name": "collect_system_report",
      "at_startup": false,
      "at_teardown": true
    }
  ]
}
```

## Events
Events are what make up the orchestrated test. From the configuration example above we have 3 event; `start_playback`, `start_streamer` and `collect_system_report`. Each of these events needs to have an corresponding function. Where these functions live is specified in pytest.ini under `orchestration_sources` and can be a comma(',') separated list of files.
```
[pytest]
orchestration_sources = tests/event_plugin.py, somethingelse.py
```

These events implementations can use any existing pytest fixture as parameter, as well as any parameter defined in the configuration/description, see "video_path" in configuration example above.

See an actual event implementation of `start_playback` from configuration example above.
It's input parameters are:
* "video_player" - An already existing fixture we are reusing in our event
* "video_path" - An input defined from our configuration/description file
* "kill_switch" - The provided kill_switch fixture, we send it in you play method since it will start a subprocess which orchestration can not stop on it's own, so through the kill_switch we signal it and it has to take care of stopping itself.
* "result_reporter" - We pass in the result_reporter so the play method can add its info/error whatever that orchestration then will monitor and execute on_result() when there is something new reported
```
def start_playback(video_player, video_path, kill_switch, result_reporter):
    video_player.play(video_path, kill_switch, result_reporter)
```

## Reporter
Reporter is a class provided that the orchestration is using to collect reports/result/info from all its orchestrated events. An implemented event can use the `result_reporter()` fixture to get the instance. The reporter has 2 main methods worth noticing; ``monitor()`` and ``on_result()``. The monitor method will be running in the background of the ``orchestration`` and monitor the Queue object it contains for new info, if it finds something then ``on_result()`` will be called which will pop the info and log it. It is possible to implement your own Reporter class by inheriting from provided ResultReporter class and implementing your own ``on_result()`` method. If you implement this you also need to override the ``result_reporter(report_queue)`` fixture and make it return your reporter instead.

## Fixtures
The plugin comes with a few fixture helpers, these are:
* kill_switch() - Gives you a `multiprocessing.Event()` which will be set when tests finishes, so your event can know when test has ended and tear itself down properly.
* result_reporter() - Facilitates a way to collect and report what is important from your events, see Reporter section.
* report_queue() - Fixture which returns a thread safe `multiprocessing.Manager().Queue()` object which is injected into result_reporter, could be overridden as well.


## Usage

To run a orchestration test you just need to specify --run-orch=<orch_name> where orch_name should be the name of the description configuration file excluding its extension.
```
pytest --test-orch=my_orchestration_test
```

The option `--load-orch` is also available, specifying this will load all events. This is mostly meant for testing.