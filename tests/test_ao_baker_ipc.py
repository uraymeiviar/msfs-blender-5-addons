"""Step (a) of the OptiX AO Baker (journal 20261114.optix-baker.md; Glider plan PLAN-20261114.optix-ao-baker.md): the
channel, the protocol's first messages and the two hosts, measured from a Python client (ao_baker_client.py).

    python -I tests/test_ao_baker_ipc.py --exe <aobaker.exe> [--glider <glider2.exe>] [--out result.json]
    blender -b --factory-startup --python tests/test_ao_baker_ipc.py -- --exe <aobaker.exe> --quick

Checks (each prints PASS or FAIL with its numbers; the exit code is the number of failures):
  ready-headless, ready-window, ready-module: Hello answered with Ready, protocol 1, device Ok, the probe's value
  echo-1gib: a 1 GiB block written by numpy, its checksum equal on both sides; times and bandwidth
  round-trip: 2000 Echo messages without a block, median and 99th percentile
  cancel, unknown-message: Cancelled; an Error for a type the server does not know
  bye-exit: Bye ends the app with code 0
  client-killed-app: a client killed ends the app with code 3; client-killed-module: the module frees the channel and
    answers the next client; server-killed: the client's wait reports the server's end; starter-gone: the process
    named by --client-pid ends before connecting, the app ends with code 3
  no-driver: FSS_AO_BAKER_NO_CUDA set: Ready says NoDriver, the app ends with code 2
--quick runs ready-headless, round-trip and a 64 MiB echo only (for Blender's Python, which has no second Python to
kill). Run under the CPU cap (AGENTS.md): cpucap.exe 50 python ...
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ao_baker_client as client  # noqa: E402

import numpy as np  # noqa: E402

RESULTS = []
WORK = tempfile.mkdtemp(prefix='ao-baker-ipc-')


def check(name, ok, **measured):
    RESULTS.append(dict(name=name, ok=bool(ok), **measured))
    print(f"{'PASS' if ok else 'FAIL'} {name}: " + ', '.join(f'{k}={v}' for k, v in measured.items()), flush=True)


def start_app(exe, channel, headless=True, client_pid=None, env=None):
    args = [exe, '--channel', channel] + (['--headless'] if headless else [])
    if client_pid is not None:
        args += ['--client-pid', str(client_pid)]
    log = open(os.path.join(WORK, f'{channel}.log'), 'w')
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=WORK, env=env)


def ready_ok(r):
    return (r['protocol'] == client.PROTOCOL and r['device_state'] == 'Ok'
            and r['probe_value'] == client.PROBE_INPUT * 3 + 1 and r['optix_version'] >= 90100)


def ready_fields(r, seconds):
    return dict(seconds=round(seconds, 3), device=r['device'], state=r['device_state'], compute='%d.%d' % r['compute'],
                optix=r['optix_version'], driver=r['driver_version'], probe=r['probe_value'],
                memory_mib=r['device_memory'] >> 20, detail=r['detail'] or '-')


def round_trips(ch, n=2000):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        ch.echo()
        times.append((time.perf_counter() - t) * 1e6)
    times.sort()
    check('round-trip', True, messages=n, median_us=round(statistics.median(times), 1),
          p99_us=round(times[int(n * 0.99) - 1], 1), max_us=round(times[-1], 1))


def echo_block(ch, nbytes):
    name = f'fss-ao-baker-test.{os.getpid()}.{nbytes}'
    t0 = time.perf_counter()
    block = client.make_block(name, nbytes)
    words = np.frombuffer(block, dtype=np.uint64)
    rng = np.random.default_rng(20261114)
    step = 1 << 24
    for i in range(0, len(words), step):
        words[i:i + step] = rng.integers(0, 2 ** 63, size=min(step, len(words) - i), dtype=np.uint64)
    t1 = time.perf_counter()
    mine = int(words.sum(dtype=np.uint64))
    t2 = time.perf_counter()
    got = ch.echo(name, nbytes, timeout=60.0)
    t3 = time.perf_counter()
    del words
    block.close()
    gib = nbytes / 2 ** 30
    check(f'echo-{nbytes >> 20}mib', got['error'] == 0 and got['bytes'] == nbytes and got['checksum'] == mine,
          checksum=hex(mine), server_checksum=hex(got['checksum']), fill_s=round(t1 - t0, 3), client_sum_s=round(t2 - t1, 3),
          server_sum_s=round(got['microseconds'] / 1e6, 3), server_gib_s=round(gib / max(got['microseconds'] / 1e6, 1e-9), 2),
          round_trip_s=round(t3 - t2, 3))


def child_client(channel):
    """A second Python that connects, says Hello and waits to be killed."""
    code = ('import sys,time; sys.path.insert(0, %r); import ao_baker_client as c; ch = c.connect(%r); ch.hello(); '
            'print("connected", flush=True); time.sleep(120)') % (HERE, channel)
    p = subprocess.Popen([sys.executable, '-I', '-c', code], stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    return p, line == 'connected'


def test_headless(exe, quick):
    t = time.perf_counter()
    app = start_app(exe, f'h{os.getpid()}', client_pid=os.getpid())
    ch = client.connect(f'h{os.getpid()}')
    r = ch.hello()
    check('ready-headless', ready_ok(r), **ready_fields(r, time.perf_counter() - t))
    round_trips(ch)
    echo_block(ch, (64 if quick else 1024) << 20)
    if not quick:
        ch.job_info(1, 10, 'TEST_MASTER')
        ch.cancel()
        check('cancel', True)
        ch.send(99)
        got = ch.receive(5.0)
        check('unknown-message', got is not None and got[0] == client.ERROR, answer=got[0] if got else None)
    t = time.perf_counter()
    ch.bye()
    ch.close()
    code = app.wait(10)
    check('bye-exit', code == 0, exit_code=code, seconds=round(time.perf_counter() - t, 3))


def test_window(exe):
    t = time.perf_counter()
    app = start_app(exe, f'w{os.getpid()}', headless=False, client_pid=os.getpid())
    ch = client.connect(f'w{os.getpid()}', wait=30.0)
    r = ch.hello()
    seconds = time.perf_counter() - t
    ch.job_info(3, 10, 'WINDOW_TEST')
    time.sleep(1.0)  # the window shows the client and its master for a moment
    ch.bye()
    ch.close()
    code = app.wait(15)
    check('ready-window', ready_ok(r) and code == 0, exit_code=code, **ready_fields(r, seconds))


def test_client_killed_app(exe):
    channel = f'k{os.getpid()}'
    app = start_app(exe, channel)
    child, connected = child_client(channel)
    t = time.perf_counter()
    child.kill()
    child.wait()
    code = app.wait(10)
    check('client-killed-app', connected and code == 3, exit_code=code, seconds=round(time.perf_counter() - t, 3))


def test_server_killed(exe):
    channel = f's{os.getpid()}'
    app = start_app(exe, channel, client_pid=os.getpid())
    ch = client.connect(channel)
    ch.hello()
    t = time.perf_counter()
    app.kill()
    gone = False
    try:
        ch.receive(10.0)
    except client.PeerGone:
        gone = True
    seconds = time.perf_counter() - t
    ch.close()
    check('server-killed', gone, seconds=round(seconds, 4))


def test_starter_gone(exe):
    starter = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(0.5)'])
    app = start_app(exe, f'g{os.getpid()}', client_pid=starter.pid)
    starter.wait()
    t = time.perf_counter()
    code = app.wait(10)
    check('starter-gone', code == 3, exit_code=code, seconds_after_its_end=round(time.perf_counter() - t, 3))


def test_no_driver(exe):
    env = dict(os.environ, FSS_AO_BAKER_NO_CUDA='1')
    app = start_app(exe, f'n{os.getpid()}', client_pid=os.getpid(), env=env)
    ch = client.connect(f'n{os.getpid()}')
    r = ch.hello()
    ch.bye()
    ch.close()
    code = app.wait(10)
    check('no-driver', r['device_state'] == 'NoDriver' and code == 2, state=r['device_state'], exit_code=code,
          detail=r['detail'])


def test_module(glider):
    t = time.perf_counter()
    host = subprocess.Popen([glider], cwd=WORK, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ch = client.connect('default', wait=60.0)
        r = ch.hello()
        check('ready-module', ready_ok(r), **ready_fields(r, time.perf_counter() - t))
        echo_block(ch, 256 << 20)
        ch.bye()
        ch.close()
        child, connected = child_client('default')
        t = time.perf_counter()
        child.kill()
        child.wait()
        ch = client.connect('default', timeout=5.0)
        r2 = ch.hello()
        seconds = time.perf_counter() - t
        ch.bye()
        ch.close()
        check('client-killed-module', connected and r2['device_state'] == 'Ok', next_client_after_s=round(seconds, 3))
    finally:
        host.kill()
        host.wait()


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', required=True)
    ap.add_argument('--glider')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    print(f'Python {sys.version.split()[0]} ({sys.executable}), numpy {np.__version__}, work folder {WORK}', flush=True)
    test_headless(a.exe, a.quick)
    if not a.quick:
        test_window(a.exe)
        test_client_killed_app(a.exe)
        test_server_killed(a.exe)
        test_starter_gone(a.exe)
        test_no_driver(a.exe)
        if a.glider:
            test_module(a.glider)
    failed = [r['name'] for r in RESULTS if not r['ok']]
    print(f'{len(RESULTS) - len(failed)} passed, {len(failed)} failed' + (f': {", ".join(failed)}' if failed else ''))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(dict(python=sys.version, results=RESULTS), f, indent=1)
    return len(failed)


if __name__ == '__main__':
    code = main()
    if 'bpy' in sys.modules:
        sys.stdout.flush()
        os._exit(code)
    sys.exit(code)
