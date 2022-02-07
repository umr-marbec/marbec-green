# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.11.5
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

import numpy as np
red = np.array([228,55,77,152,255,255,166,247,153]) / 255.
green = np.array([26,126,175,78,127,255,86,129,153]) / 255.
blue = np.array([28,184,74,163,0,51,40,191,153]) / 255.
colors = [(r, g, b) for r, g, b in zip(red, green, blue)]
