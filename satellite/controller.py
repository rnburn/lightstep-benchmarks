import subprocess
import time
import requests
import os
from os import path

# top level directory
SATELLITE_DIR = path.dirname(path.realpath(__file__))
PROJECT_DIR = path.join(SATELLITE_DIR, "..")
DEFAULT_PORTS = list(range(8360, 8368))

class MockSatelliteHandler:
    def __init__(self, port, mode):
        os.makedirs(path.join(PROJECT_DIR, "logs/temp"), exist_ok=True)
        self.logfile = open(path.join(PROJECT_DIR, f'logs/temp/mock_satellite_{str(port)}.log'), 'w+')
        self.port = port

        # we will subtract this number from how many received spans satellites report
        # this will give us the ability to reset spans_received without even communicating
        # with satellites
        self._spans_received_baseline = 0

        mock_satellite_path = path.join(SATELLITE_DIR, 'mock_satellite.py')

        self._handler = subprocess.Popen(
            ["python3", mock_satellite_path, str(port), mode],
            stdout=self.logfile, stderr=self.logfile)

    def is_running(self):
        return self._handler.poll() == None

    def get_spans_received(self):
        host = "http://localhost:" + str(self.port)
        res = requests.get(host + "/spans_received")

        if res.status_code != 200:
            raise Exception("Bad status code -- not able to GET /spans_received from " + host)

        try:
            return int(res.text) - self._spans_received_baseline
        except ValueError:
            raise Exception("Bad response -- expected an integer from " + host)

    def reset_spans_received(self):
        self._spans_received_baseline += self.get_spans_received()

    """ Shutdown this satellite and return its logs in string format. """
    def terminate(self):
        # cross-platform way to terminate a program
        # on Windows calls TerminateProcess, on Posix sends SIGTERM
        self._handler.terminate()

        # wait for an exit code
        while self._handler.poll() == None:
            pass

        # read & close the logfile
        self.logfile.seek(0) # seek to beginning of file
        logs = self.logfile.read()
        self.logfile.close()
        return logs


class MockSatelliteGroup:
    def __init__(self, mode, ports=DEFAULT_PORTS):
        os.makedirs(path.join(PROJECT_DIR, "logs"), exist_ok=True)

        self._ports = ports
        self._satellites = \
            [MockSatelliteHandler(port, mode) for port in ports]

        time.sleep(1)

        if not self.all_running():
            raise Exception("Couldn't start all satellites.")

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.shutdown()
        return False

    def get_spans_received(self):
        # before trying to communicate with the mock, check if its running
        if not self.all_running():
            raise Exception("Can't get spans received since not all satellites are running.")

        return sum([s.get_spans_received() for s in self._satellites])

    def all_running(self):
        # if the satellites are shutdown, they aren't running
        if not self._satellites:
            return False

        for s in self._satellites:
            if not s.is_running():
                return False
        return True

    def reset_spans_received(self):
        if not self._satellites:
            raise Exception("Can't reset spans received since no satellites are running.")

        for s in self._satellites:
            s.reset_spans_received()

    def start(self, mode, ports=DEFAULT_PORTS):
        if not self._satellites:
            self.__init__(mode, ports=ports)
        else:
            raise Exception("Can't call startup since satellites are running.")

    """ Shutdown all satellites and save their logs into a single file """
    def shutdown(self):
        if not self._satellites:
            raise Exception("Can't call terminate since there are no satellites running")

        with open(path.join(PROJECT_DIR, 'logs/mock_satellites.log'), 'a+') as logfile:
            logfile.write('**********\n')
            for s in self._satellites:
                logs = s.terminate()
                logfile.write(f'*** logs from satellite {s.port} ***\n')
                logfile.write(logs)
            logfile.write('\n')

        self._satellites = None
