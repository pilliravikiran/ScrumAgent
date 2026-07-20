"""Background execution must be independent from a Streamlit script run."""

from threading import Event

from background import start_background_run


def test_background_run_finishes_after_caller_continues():
    started = Event()
    release = Event()

    def work(*, event_log):
        event_log({"type": "text", "text": "started"})
        started.set()
        release.wait(timeout=2)
        event_log({"type": "text", "text": "finished"})
        return "complete"

    run = start_background_run("Meeting agent", work)
    assert started.wait(timeout=2)
    assert not run.done
    assert run.events() == [{"type": "text", "text": "started"}]

    release.set()
    assert run.future.result(timeout=2) == "complete"
    assert run.done
    assert run.events()[-1] == {"type": "text", "text": "finished"}
