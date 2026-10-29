import numpy as np

from functions.math.axis_estimation import train_multi_plane


def test_convex_em_converges():
    # Convex wedge = AND of two half-spaces. A converged EM gives the same planes whatever max_iter is;
    # an oscillating one (negatives assigned by argmax) swaps the two planes on every iteration.
    rng = np.random.default_rng(3)
    X = rng.normal(0, 1, (2000, 3)) * [1, 1, 0.2]
    a = 0.6
    s = np.minimum(X @ [np.cos(a), np.sin(a), 0], X @ [np.cos(a), -np.sin(a), 0])
    pos, neg = np.nonzero(s > 0)[0], np.nonzero(s < 0)[0]
    fits = [train_multi_plane(X, pos, neg, boundary="convex", max_iter=it) for it in (19, 20)]
    for (n1, _), (n2, _) in zip(fits[0]["planes"], fits[1]["planes"]):
        assert np.allclose(n1, n2)
    assert fits[0]["score"] > 0.99
