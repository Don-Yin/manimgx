"""Manim's authoring API, backed by ManimGX's scene, object and animation models.

Each module lists the names it gives in `__all__`, and each package, this one too, takes in
its children's names with a star import and gathers their lists in its own.
"""

from manimgx import (
    animation,
    audio,
    constants,
    drawing,
    mobject,
    mobjects,
    rendering,
    scene,
    settings,
)
from manimgx.animation import *
from manimgx.audio import *
from manimgx.constants import *
from manimgx.drawing import *
from manimgx.mobject import *
from manimgx.mobjects import *
from manimgx.rendering import *
from manimgx.scene import *
from manimgx.settings import *

__all__ = []
__all__ += animation.__all__
__all__ += audio.__all__
__all__ += constants.__all__
__all__ += drawing.__all__
__all__ += mobject.__all__
__all__ += mobjects.__all__
__all__ += rendering.__all__
__all__ += scene.__all__
__all__ += settings.__all__
