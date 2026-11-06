"""Projection regressions for result framing across browser shapes."""
from itertools import product

import numpy as np
import pytest

from viewer import fitted_camera


@pytest.mark.parametrize("aspect", [0.4, 1.0, 2.5])
@pytest.mark.parametrize("fov", [0.4, 1.2])
def test_fitted_camera_keeps_all_display_corners_inside_frustum(aspect, fov):
    # Off-origin, deep bounds include the caption area above the geometry.
    bounds = np.array([[-3., -2., -4.], [5., 6., 7.]])
    target, position, distance = fitted_camera(bounds, fov, aspect)
    corners = np.array(list(product(*zip(*bounds))))
    depth = position[2] - corners[:, 2]
    assert (depth > 0).all()
    ndc_x = (corners[:, 0] - target[0]) / (depth * np.tan(fov / 2) * aspect)
    ndc_y = (corners[:, 1] - target[1]) / (depth * np.tan(fov / 2))
    assert np.abs(ndc_x).max() < 1
    assert np.abs(ndc_y).max() < 1
    assert np.linalg.norm(position - target) == pytest.approx(distance)


def test_concurrent_next_clicks_do_not_lose_a_step():
    # Widget updates can yield while Viser dispatches another button callback.
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from viewer import ExperimentViewer

    class SlowSelection:
        def __init__(self):
            self.selected = 'a'

        @property
        def value(self):
            return self.selected

        @value.setter
        def value(self, value):
            time.sleep(0.03)
            self.selected = value

    browser = SimpleNamespace(samples={'a': {}, 'b': {}, 'c': {}},
                              sample=SlowSelection(), lock=threading.RLock())
    ready = threading.Barrier(2)

    def next_sample():
        ready.wait(timeout=5)
        ExperimentViewer.move(browser, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(next_sample) for _ in range(2)]
        for task in tasks:
            task.result(timeout=5)
    assert browser.sample.value == 'c'
