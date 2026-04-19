from setuptools import setup, Extension
from Cython.Build import cythonize

ext = Extension(
    "_tw_engine",
    sources=["_tw_engine.pyx"],
    extra_compile_args=["-O3", "-march=native"],
)

setup(
    name="twinseed_cython",
    ext_modules=cythonize([ext], compiler_directives={
        "language_level": "3",
        "boundscheck": False,
        "wraparound": False,
        "cdivision": True,
    }),
)
