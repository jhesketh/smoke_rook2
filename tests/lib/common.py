# Copyright (c) 2019 SUSE LINUX GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple


logger = logging.getLogger(__name__)


def simple_matcher(result):
    def compare(testee):
        return testee == result
    return compare


def regex_matcher(regex_pattern):
    def compare(testee):
        return len(regex_pattern.findall(testee)) > 0
    return compare


def regex_count_matcher(regex_pattern, matches):
    def compare(testee):
        return len(regex_pattern.findall(testee)) == matches
    return compare


def decode_wrapper(i):
    return i.stdout


def wait_for_result(func, *args, matcher=simple_matcher(True), attempts=20,
                    interval=5, decode=decode_wrapper):
    """Runs `func` with `args` until `matcher(out)` returns true or timesout

    Returns the matching result, or raises an exception.
    """

    for i in range(attempts):
        out = func(*args)
        if decode:
            out = decode(out)
        if matcher(out):
            return out
        time.sleep(interval)

    logger.error("Timed out waiting for result %s in %s(%s)" %
                 (matcher, func, args))

    logger.error("The last output of the function:")
    logger.error(out)

    raise Exception("Timed out waiting for result")


def execute(command: str, capture=False, check=True, log_stdout=True,
            log_stderr=True, env: Optional[Dict[str, str]] = None) -> Tuple[
                int, Optional[str], Optional[str]]:
    """A helper util to excute `command`.

    If `log_stdout` or `log_stderr` are True, the stdout and stderr
    (respectfully) are redirected to the logging module. You can optionally
    catpure it by setting `capture` to True. stderr is logged as a warning as
    it is up to the caller to raise any actual errors from the RC code (or to
    use the `check` param).

    If `check` is true, subprocess.CalledProcessError is raised when the RC is
    non-zero. Note, however, that due to the way we're buffering the output
    into memory, stdout and stderr are only available on the exception if
    `capture` was True.

    `env` is a dictionary of environment vars passed into Popen.

    Returns a tuple of (rc code, stdout, stdin), where stdout and stdin are
    None if `capture` is False, or are a string.
    """
    stdout_pipe = subprocess.PIPE \
        if log_stdout or capture else subprocess.DEVNULL

    stderr_pipe = subprocess.PIPE \
        if log_stderr or capture else subprocess.DEVNULL

    process = subprocess.Popen(
        command,
        shell=True,
        stdout=stdout_pipe, stderr=stderr_pipe,
        universal_newlines=True,
        env=env,
    )

    # Use a dictionary to capture the output as it is a mutable object that
    # we can access outside of the threads.
    output: Dict[str, Optional[str]] = {}
    output['stdout'] = None
    output['stderr'] = None
    if capture:
        output['stdout'] = ""
        output['stderr'] = ""

    def read_stdout_from_process(process, capture_dict):
        log = logging.getLogger(process.args)
        while True:
            output = process.stdout.readline()
            if output:
                log.info(output.rstrip())
                if capture_dict['stdout'] is not None:
                    capture_dict['stdout'] += output
            elif output == '' and process.poll() is not None:
                break

    def read_stderr_from_process(process, capture_dict):
        log = logging.getLogger(process.args)
        while True:
            output = process.stderr.readline()
            if output:
                log.warning(output.rstrip())
                if capture_dict['stderr'] is not None:
                    capture_dict['stderr'] += output
            elif output == '' and process.poll() is not None:
                break

    if log_stdout:
        stdout_thread = threading.Thread(
            target=read_stdout_from_process, args=(process, output))
        stdout_thread.start()
    if log_stderr:
        stderr_thread = threading.Thread(
            target=read_stderr_from_process, args=(process, output))
        stderr_thread.start()

    if log_stdout:
        stdout_thread.join()
    if log_stderr:
        stderr_thread.join()

    if not log_stdout and capture:
        output['stdout'] = process.stdout.read()  # type: ignore
    if not log_stderr and capture:
        output['stderr'] = process.stderr.read()  # type: ignore

    rc = process.wait()
    logger.debug(f"Command {command} finished with RC {rc}")

    if check and rc != 0:
        if capture:
            raise subprocess.CalledProcessError(
                rc, command, output['stdout'], output['stderr'])
        else:
            raise subprocess.CalledProcessError(rc, command)

    return (rc, output['stdout'], output['stderr'])
