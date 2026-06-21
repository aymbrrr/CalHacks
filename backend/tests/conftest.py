"""Test session setup.

Force the deterministic local-fallback embedding so the suite never makes real
(paid, slow, flaky) OpenAI embedding calls, regardless of whether an
``OPENAI_API_KEY`` is present in the environment. This must run before
``redundant.config`` constructs its ``SETTINGS`` singleton, which is why it lives
at module import time in conftest (loaded by pytest before any test module).
"""

import os

os.environ["REDUNDANT_EMBEDDINGS_OFFLINE"] = "1"
