# Cython hot-path for twinseed_fast. Build with:
#   cd tools/solver/games/twinseed_cython && python setup.py build_ext --inplace
try:
    from ._tw_engine import apply_cy, heuristic_and_prune_cy
    CYTHON_AVAILABLE = True
except ImportError:
    apply_cy = None
    heuristic_and_prune_cy = None
    CYTHON_AVAILABLE = False
