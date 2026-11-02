import numpy as np

from functions.visualize import style


def test_vector_scale_follows_the_running_params():
    verts = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    style.set_vector_scale({"length_factor": 1.0, "thickness_factor": 1.0})
    base = style.arrow_params(verts)
    style.set_vector_scale({"length_factor": 2.0, "thickness_factor": 1.0})
    assert np.isclose(style.arrow_params(verts)[0], 2 * base[0])
    style.set_vector_scale(None)  # back to the yml values


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
