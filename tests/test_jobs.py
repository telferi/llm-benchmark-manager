import time
from llmbench.jobs import LocalJobManager

def test_job_manager_cancel_signal_is_visible():
    jobs=LocalJobManager(max_workers=1)
    def work(cancelled):
        while not cancelled(): time.sleep(0.005)
        return 'cancelled'
    jobs.submit('run_x',work)
    time.sleep(0.02)
    assert jobs.cancel('run_x') is True
    assert jobs.wait('run_x',1)=='cancelled'
